# Decisions

Why the project is shaped the way it is. Newest decisions are added at the end.

## 1. Every price row carries its own lineage

A price is only explainable if the row itself says where it came from. Each scored price stores the model version and
alias at scoring time, the MLflow run ID, the Delta version of the feature table it was scored from, and the version of
the tariff rule that turned the forecast into a price. A lineage column that is null is treated as a failed run, not a
missing detail.

## 2. Databricks Free Edition

The project runs on Free Edition, which costs nothing and does not expire, so the demo stays reachable. Its limits shape
several of the decisions below: serverless compute only, one 2X-Small SQL warehouse, outbound internet restricted to a
set of trusted domains, compute shut down for the day when the fair-use quota is exceeded, and no commercial use. This
is a non-commercial learning project.

## 3. Ingestion runs outside Databricks

Because serverless compute can only reach trusted domains, the external APIs are called from a scheduled GitHub Action,
which uploads the raw JSON into a Unity Catalog Volume through the Files API. Databricks then reads files it owns. This
also keeps the boundary between "fetching someone else's data" and "processing our own" explicit.

## 4. Hours, not quarter-hours

The DE-LU day-ahead market moved to 15-minute products on 1 October 2025. Two years of history therefore mix hourly and
quarter-hourly prices. The tariff is hourly, so quarter-hours are averaged into the hour they start in, and the number
of source points per hour is kept so a partial hour can be recognised.

## 5. The demo reads live data, with a snapshot behind it

The Cloud Run service queries Databricks with a read-only identity and caches results for an hour. When Databricks is
unreachable or over its quota, it serves the last nightly snapshot instead, and the app says which source it shows.
A demo that shows an error whenever the free quota runs out would be worse than one that is a few hours old.

## 6. Overrides are new versions, never edits

A person can override a price through the agent, but only after approving it, and the override is written as a new
record next to the original. The original price and its lineage stay untouched, so the history of a price is complete.
Overrides made through the public demo go to a sandbox table that is reset nightly.
