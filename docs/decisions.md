# Decisions

Why the project is shaped the way it is. Newest decisions are added at the end; a decision that changes is rewritten
in place, with the date of the change.

## 1. Every price row carries its own lineage

A price is only explainable if the row itself says where it came from. Each scored price stores:

| Column | What it is |
|---|---|
| `model_version` | the Unity Catalog model version that scored it, resolved once from `@champion` before loading |
| `mlflow_run_id` | the run of that exact model version, read from the same `ModelVersion` object |
| `model_alias` | the alias used to find it; informational only, because aliases move |
| `training_data_version` | the Delta version of the feature table the model was trained on, logged on the run |
| `scoring_feature_version` | the Delta version of the feature table the price was scored from |
| `tariff_rule_version`, `tariff_rule_hash` | which rule turned the forecast into a price, and a hash of its parameters |
| `forecast_issued_at`, `horizon_hours` | when the forecast was made and how far ahead it looked |
| `scored_at` | when the row was written |

The scoring job resolves the alias with `get_model_version_by_alias` and then loads `models:/<name>/<version>`, so
the version stored is the one that ran even if the gate moves the alias in between. Lineage is checked for
consistency, not only presence: for every `(model_version, mlflow_run_id)` pair in the prices table, the registry must
report that run for that version, and every rule version must exist in code. A failed check fails the run.

## 2. Databricks Free Edition

The project runs on Free Edition, which costs nothing. Its terms shape the rest of this document:

- Serverless compute only, one 2X-Small SQL warehouse, five concurrent job tasks, one active pipeline per type.
- Outbound internet from serverless compute is restricted to a set of trusted domains.
- Exceeding the fair-use quota shuts compute down for the rest of the day, in extreme cases for the rest of the month.
- Inactive accounts may be deleted, so the scheduled runs also keep the workspace in use.
- No commercial use. This is a personal, non-commercial learning project and is not used for client work.

What has been verified on this workspace so far, and how:

| Capability | Status |
|---|---|
| Workspace service principals | verified 29 Oct 2026, created with `databricks service-principals create` |
| Workspace-level OAuth secrets for them | verified 29 Oct 2026 with `databricks service-principal-secrets-proxy create`, deleted again with `delete`; none remain |
| Grants for `price-passport-reader` | not applied yet; applied with the Cloud Run service |
| Serverless environment version with Python 3.12 | verified 29 Oct 2026: environment version 4 runs Python 3.12.3 |
| Serverless access to `api.energy-charts.info` and `historical-forecast-api.open-meteo.com` | verified 29 Oct 2026 with a one-off serverless job, HTTP 200 from both |
| Files API upload to a Volume from a GitHub runner | not needed while ingestion runs in Databricks (section 3) |
| Asset Bundle deploy, Unity Catalog model aliases, a serving endpoint | to check when each is first used |
| A serverless SQL pipeline next to a job on Free Edition | verified 29 Oct 2026: `silver` deployed and refreshed while a backfill job ran |

## 3. Ingestion runs as a Databricks job (changed 29 Oct 2026)

The first version of this decision moved ingestion out of Databricks, into a GitHub Action, because Free Edition
restricts outbound internet to trusted domains. A serverless test job on 29 October reached both
`api.energy-charts.info` and `historical-forecast-api.open-meteo.com`, so ingestion runs where the rest of the data
work runs: a scheduled job on serverless compute that writes the unchanged responses into the `raw` Volume.

- The job is part of the Asset Bundle (`databricks.yml`) and runs the packaged `price-passport-ingest` entry point.
- Databricks schedules take a time zone, so it runs at 13:40 and 16:40 Berlin time, after the 12:00 auction results
  are out, in summer and winter alike. The 13:40 run is best-effort and stays green if tomorrow is not published yet;
  from 15:00 local time a run requires tomorrow, so the 16:40 run fails if tomorrow is missing.
- Each run fetches yesterday, today and tomorrow and overwrites one file per delivery day, so a missed run heals itself
  and a repeated run changes nothing (checked on the first run: the same checksum twice). A day that is not published
  yet is reported, never written as an empty file. Energy-Charts answers such a day with HTTP 404 and "No content
  available", which the first run on Databricks found at 12:01; both a 404 and an empty list count as not published.
- Every API call becomes one file named after the days it covers (`range=<first>_<last>.json`). A daily run writes
  one file per day; a backfill one file per calendar month, because Energy-Charts rate-limits single-day calls to
  about one every 25 seconds (26 days in 11 minutes on the first attempt), while a month is one call. The two-year
  backfill took 7 minutes. Silver keeps each timestamp from the most recently written file, so overlapping files
  never count twice.
- Weather is Open-Meteo's forecast for five sites across Germany as it stood two days before each hour
  (`*_previous_day2` from the Previous Runs API), fetched up to tomorrow (section 7).
- The Energy-Charts API answers bursts with HTTP 429 and a `Retry-After` header (22 seconds when first seen on
  29 Oct 2026); the job waits as told, and pauses between requests anyway.
- If Databricks narrows the trusted domains, the fallback is the original design: a scheduled GitHub Action that
  fetches the same files and uploads them through the Files API as a service principal limited to the Volume.

Bundle deploys from CI use the service principal `price-passport-ci` with an OAuth machine-to-machine secret kept in
a GitHub Environment limited to `main`. Federated GitHub OIDC tokens would avoid a stored secret, but Databricks
creates federation policies at account level, and Free Edition has no account console.

## 4. Hours, not quarter-hours

Bronze and silver are materialized views in a SQL pipeline (`pipelines/raw_to_silver.sql`) that re-read the raw
files on every refresh, so an overwritten file is always seen at its latest content. The SQL mirrors the Python parser,
which stays the tested reference; `sql/checks/` holds the queries that compare silver with the calendar.


The DE-LU day-ahead market moved to 15-minute products with delivery day 1 October 2025. Two years of history mix
hourly and quarter-hourly prices. The tariff is hourly, so quarter-hours are averaged into the hour they start in.

- Each hour records how many points it had and how many the market had for that hour (one before the switch, four
  after), so an incomplete hour is recognisable. Silver keeps incomplete hours with their flag; gold uses complete
  hours only.
- Hours are stored in UTC and shown in Europe/Berlin. A local delivery day has 23 or 25 hours when the clocks change.
- Duplicate or misaligned timestamps, non-numeric or infinite prices, responses marked deprecated, and responses
  without a single price (unless the caller passes `allow_empty`) are rejected, not averaged in.

## 5. The demo reads live data, with a snapshot behind it

The Cloud Run service queries Databricks through the SQL Statement API as the service principal
`price-passport-reader` and caches results for an hour. It holds `USE CATALOG`, `USE SCHEMA` and `SELECT` on the
published schema and `CAN USE` on the warehouse, nothing else. The warehouse may be cold, so the service waits with a
timeout and retries before falling back.

The fallback is a snapshot that a nightly job writes to Cloud Storage. Reading it does not need Databricks, so it still
works when the quota has shut compute down. Every served record carries `exported_at` and its source, and the app shows
the snapshot's age, because a quota shutdown can last more than a day.

## 6. Overrides are new versions, never edits

A person can override a price through the agent, but only after approving it. The override is written as a new record
next to the original, with `override_id`, `approved_by`, `approved_at` and `reason`. The original price and its lineage
stay untouched.

The price that is shown and used is the effective price: the latest approved override for that hour if there is one,
otherwise the model price. The effective prices view carries `price_origin` (`model` or `override`), and the passport
shows both prices and says which one was served, so "which model version produced this price" is never answered with
a model version when a person set the price. Overrides made through the public demo go to a sandbox table that is
reset nightly.

## 7. What the model forecasts, and when

After the day-ahead auction, tomorrow's prices are public, and forecasting them would be pointless. The tariff for
delivery day D is therefore committed at 10:00 Berlin time on D-1, before the auction closes at 12:00. The forecast
covers the hours of D. `horizon_hours` is the start of the priced hour minus `forecast_issued_at`: 14 to 37 hours,
38 on the day the clocks go back and 36 on the day they go forward.

Features may only use what was known at 10:00 on D-1: day-ahead prices up to and including D-1, calendar features, and
weather forecasts issued before the cutoff. Weather is the forecast each hour had two days earlier (Open-Meteo's
`previous_day2`): for any hour of D that forecast run started no later than 23:00 on D-2, so it existed by the cutoff.
The one-day-old forecast would leak for the late hours of D, and the stitched "historical forecast" series is only a few
hours old for every hour. The same `previous_day2` series is available for tomorrow, so training and scoring use exactly
the same feature. Weather comes from five sites across Germany rather than one city, since the price follows national
wind, solar and load.

## 8. Baseline and promotion gate

- Version 1 is a seasonal naive baseline: the same hour one week earlier. Every run logs its skill against it.
- Models are compared on a fixed, time-ordered holdout that lies after every candidate's training window.
- A challenger becomes `@champion` only if its MAE on that holdout is at least 2 percent lower than the champion's. A
  tie keeps the champion. Runs also log MAE on the evening hours 17:00 to 21:00, where errors cost most.
- The 15-minute switch changes how hourly prices are formed, so the market regime is a feature.

## 9. Feature versions that can be read again

A version number in a passport is only useful if that version can be read again. Materialized views do not support
time travel, so the gold feature table is a plain Delta table written by a job. Its log and deleted-file retention are
set to a year, so a version named in a passport stays readable for at least that long. The job reads the current
version from the table history once and then reads with `VERSION AS OF` that number, so the stored version and the
data read cannot drift apart.

## 10. Versioned tariff rule

The rule that turns a forecast into a price is a small function with a `RULE_VERSION` constant and a hash of its
parameters. A test pins the hash, so changing a parameter without raising the version fails CI.

## 11. One workspace, two targets

Free Edition has one workspace, so dev and prod are schemas in one catalog, selected by the Asset Bundle target, and
one pipeline is parameterised by target rather than duplicated. Jobs pin a serverless environment version with
Python 3.12, matching `requires-python`: environment version 4 (Python 3.12.3, checked 29 Oct 2026).
