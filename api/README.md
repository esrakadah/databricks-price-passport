# Price Passport API

A small Dart service for the Flutter web app. It reads prices from Databricks through the SQL Statement Execution
API as the read-only service principal `price-passport-reader`, and keeps each day for an hour so most requests never
wake the warehouse (decisions section 5).

| Route | Answer |
|---|---|
| `GET /prices?day=YYYY-MM-DD` | the hours of one local delivery day, with `source` and `fetched_at` |
| `GET /health` | `ok` |

Not built yet: the passport route, which needs the scored prices table, and the snapshot fallback, which needs the
nightly export.

## Configuration

| Variable | Value |
|---|---|
| `DATABRICKS_HOST` | the workspace URL |
| `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` | OAuth machine-to-machine credentials of `price-passport-reader`; on Cloud Run the secret comes from Secret Manager |
| `DATABRICKS_WAREHOUSE_ID` | the SQL warehouse |
| `PRICE_PASSPORT_CATALOG`, `PRICE_PASSPORT_SCHEMA` | where silver lives |
| `PORT` | set by Cloud Run, 8080 locally |

The principal needs the `databricks-sql-access` entitlement, `CAN USE` on the warehouse, `USE CATALOG`, and
`USE SCHEMA` plus `SELECT` on the schema. Table grants alone give HTTP 403 on every statement.

## Run the checks

```bash
dart pub get
dart analyze
dart test
```
