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
| Workspace-level OAuth secrets for them | verified 29 Oct 2026, a secret created and deleted again |
| Serverless access to `api.energy-charts.info` and `api.open-meteo.com` | to check before the ingest Action is built |
| Files API upload to a Volume from a GitHub runner | to check with the ingest Action |
| Asset Bundle deploy, Unity Catalog model aliases, a serving endpoint | to check when each is first used |
| Whether "one active pipeline per type" counts deployed or running pipelines | to check with the first pipeline |

## 3. Ingestion runs outside Databricks

Because serverless compute can only reach trusted domains, the external APIs are called from a scheduled GitHub
Action, which uploads the raw JSON into a Unity Catalog Volume through the Files API. If the check in section 2 shows
both hosts are reachable from serverless, this decision is revisited rather than kept out of habit.

- The Action authenticates as its own service principal, which may write to the raw Volume and nothing else. The
  credentials live in a GitHub Environment limited to `main`.
- The day-ahead auction closes at 12:00 Berlin time and results follow shortly after. GitHub cron runs in UTC and is
  best-effort, so the Action runs twice, at 12:40 and 15:40 UTC, which is after publication in both summer and winter
  time. Each run fetches a rolling three-day window and overwrites one file per delivery day, so a missed run heals
  itself and a repeated run changes nothing.
- The Energy-Charts API answers bursts with HTTP 429 and a `Retry-After` header; the Action waits as told.
- A delivery day that should be published but comes back empty fails the run instead of looking green.
- GitHub disables scheduled workflows in public repositories after 60 days without activity, so a monthly keepalive
  commit is part of the workflow.

## 4. Hours, not quarter-hours

The DE-LU day-ahead market moved to 15-minute products with delivery day 1 October 2025. Two years of history mix
hourly and quarter-hourly prices. The tariff is hourly, so quarter-hours are averaged into the hour they start in.

- Each hour records how many points it had and how many the market had for that hour (one before the switch, four
  after), so an incomplete hour is recognisable. Silver keeps incomplete hours with their flag; gold uses complete
  hours only.
- Hours are stored in UTC and shown in Europe/Berlin. A local delivery day has 23 or 25 hours when the clocks change.
- Duplicate or misaligned timestamps, non-numeric or infinite prices, and empty or deprecated responses are rejected,
  not averaged in.

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
covers the hours of D, a horizon of 14 to 38 hours (39 on the day the clocks go back).

Features may only use what was known at 10:00 on D-1: day-ahead prices up to and including D-1, calendar features, and
weather forecasts issued before the cutoff. Training uses Open-Meteo's archived historical forecasts rather than
observed weather, so the model trains on the same kind of input it is scored on. Weather comes from several sites
across Germany rather than one city, since the price follows national wind, solar and load.

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
Python 3.12, matching `requires-python`.
