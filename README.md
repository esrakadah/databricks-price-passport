# Price Passport

> Work in progress, built in the open from 30 October to 1 December 2026.

An hourly energy tariff priced by a versioned model, where every price carries a passport: which model version
produced it, from which MLflow run, trained on which version of the data, under which tariff rule. If someone asks
"why does 18:00 tomorrow cost this much?", the answer is a query, not a guess.

## What it will be

```text
GitHub Action (daily) ── Energy-Charts + Open-Meteo ──> Unity Catalog Volume
Databricks
  Lakeflow pipeline: bronze -> silver (typed, hourly, expectations) -> gold features (SQL)
  MLflow training -> Unity Catalog model, versions and a @champion alias
  champion/challenger gate, run from CI
  batch scoring: every price stamped with model version, run ID, feature-table version, tariff-rule version
Cloud Run (Dart): prices and passports, live with a nightly snapshot as fallback
  Genkit Dart agent over MCP: explains a price, proposes overrides that wait for a person's approval
Flutter web: price chart -> tap an hour -> its passport
```

Built on Databricks Free Edition. The design decisions and their reasons are in [docs/decisions.md](docs/decisions.md).

## Status

- [x] Day-ahead price parser, hourly and 15-minute responses
- [ ] Ingestion into a Unity Catalog Volume
- [ ] Lakeflow pipeline and features
- [ ] MLflow training, registry and champion/challenger gate
- [ ] Batch scoring with lineage, traceability query
- [ ] Asset Bundle deployment from CI
- [ ] Dart API on Cloud Run
- [ ] Flutter web passport
- [ ] Genkit Dart agent with approval-gated overrides

## Run the tests

```bash
uv sync
uv run pytest
```

## Data and attribution

- Day-ahead prices for the DE-LU bidding zone: Bundesnetzagentur | SMARD.de, via the
  [Energy-Charts API](https://api.energy-charts.info/) of Fraunhofer ISE, licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Weather: [Open-Meteo](https://open-meteo.com/), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The prices this project produces are a demonstration, not an offer or a forecast to rely on.

## Licence

[MIT](LICENSE)
