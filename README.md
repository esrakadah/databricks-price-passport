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
- [ ] Ingestion into a Unity Catalog Volume: job, bundle and 22 tests written, first deploy pending
- [ ] Pipeline and features
- [ ] MLflow training, registry and promotion gate
- [ ] Scoring with lineage, traceability query
- [ ] Asset Bundle deployment from CI
- [ ] Dart API on Cloud Run
- [ ] Flutter web passport
- [ ] Genkit Dart agent with approval-gated overrides

## Run the checks

```bash
uv sync
uv run ruff check
uv run mypy
uv run pytest
```

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
