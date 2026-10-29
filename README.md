# Price Passport

> Work in progress, started in October 2026 and built in the open.

An hourly energy tariff priced by a versioned model, where every price carries a passport: which model version
produced it, from which MLflow run, trained on which version of the data, scored from which version of the features,
under which tariff rule, and whether a person overrode it. If someone asks "why does 18:00 tomorrow cost this much?",
the answer is a query, not a guess.

## What it will be

```text
Databricks (Free Edition, deployed as an Asset Bundle from CI)
  ingest job, 13:40 and 16:40 Berlin: Energy-Charts + Open-Meteo -> raw Volume, one file per source, site and day
  declarative pipeline: bronze -> silver (typed, hourly, completeness flags, expectations)
  feature job: gold features as a plain Delta table with long version retention
  MLflow training -> Unity Catalog model; training-data version logged on every run
  promotion gate: a challenger becomes @champion only if it beats it by a margin on a fixed holdout
  scoring at 10:00 the day before delivery: every price row carries its lineage
  nightly export: prices and passports as a snapshot in Cloud Storage
Cloud Run (Dart): prices and passports, live through a read-only service principal, snapshot as fallback
  Genkit Dart agent over MCP: explains a price, proposes overrides that wait for a person's approval
Flutter web: price chart -> tap an hour -> its passport
```

The design decisions, their reasons, and which Free Edition capabilities are verified so far are in
[docs/decisions.md](docs/decisions.md).

## Status

- [x] Day-ahead price parser: hourly and 15-minute responses, clock-change days, negative prices, partial hours
  flagged, malformed responses rejected (34 tests, 7 of them on 5 real API responses)
- [x] Ingestion into a Unity Catalog Volume: Databricks job twice a day, deployed and running; two-year backfill
  (1 Nov 2024 to 29 Oct 2026) in monthly files
- [x] Silver pipeline in SQL: 728 delivery days, every one with the hours of its local day (23, 24 or 25), and
  17,472 hours of two-day-ahead weather forecasts for each of five sites
- [x] Gold features: one row per delivery hour with only what was known at 10:00 the day before, a plain Delta
  table kept readable for a year; tomorrow's 24 hours are ready for scoring before their prices exist
- [x] MLflow training and registry: the seasonal naive baseline is version 1, a gradient-boosted model version 2
  (31 percent lower MAE on a fixed holdout), each tagged with the feature version it was trained on
- [x] Promotion gate: `@champion` moves only on a 2 percent lower holdout MAE, and every judged version records why
- [x] Scoring with lineage: `prices` stores every price with its model version, run, training and scoring feature
  versions and tariff rule, checked against the registry on every run; `current_prices` serves the latest per hour
- [ ] Asset Bundle deployment from CI
- [ ] Dart API on Cloud Run: service written and tested against live Databricks (`api/`); passport route, snapshot
  fallback and deployment still to come
- [ ] Flutter web passport
- [ ] Genkit Dart agent with approval-gated overrides

## Run the checks

```bash
uv sync
uv run ruff check
uv run mypy
uv run pytest
```

## How this is built

Esra Kadah designs the project and makes the decisions recorded in [docs/decisions.md](docs/decisions.md). Much of
the code is written with Claude Code as a pair programmer, and commits it worked on carry a `Co-Authored-By` line. The
design and the code also go through review rounds by independent AI reviewers whose findings are fixed in the open;
every change still has to pass the tests, type checks and CI before it lands.

## Data and attribution

- Day-ahead prices for the DE-LU bidding zone: Bundesnetzagentur | SMARD.de, via the
  [Energy-Charts API](https://api.energy-charts.info/) of Fraunhofer ISE, licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Weather forecasts: [Open-Meteo](https://open-meteo.com/), licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), used through its free non-commercial API.

Changes made to the data: 15-minute prices are averaged into hourly prices, and the tariff prices this project
publishes are model output derived from them. They are a demonstration, not an offer or a forecast to rely on.

## Licence

The code is [MIT](LICENSE). The files in [tests/fixtures](tests/fixtures) are unmodified Energy-Charts responses and
stay under CC BY 4.0; see the README there.
