# Price Passport API

A small Dart service for the Flutter web app. It reads prices from Databricks through the SQL Statement Execution
API as the read-only service principal `price-passport-reader`, and keeps each day for an hour so most requests never
wake the warehouse (decisions section 5).

| Route | Answer |
|---|---|
| `GET /prices?day=YYYY-MM-DD` | the hours of one local delivery day, with `source` and `fetched_at` |
| `GET /health` | `ok` |

With `SNAPSHOT_BUCKET` set, every live answer is also stored in that private bucket, and a failed live read is
answered from it with `source: snapshot` and the original `fetched_at`. Not built yet: the passport route, which needs
the scored prices table.

## Configuration

| Variable | Value |
|---|---|
| `DATABRICKS_HOST` | the workspace URL |
| `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` | OAuth machine-to-machine credentials of `price-passport-reader`; on Cloud Run the secret comes from Secret Manager |
| `DATABRICKS_WAREHOUSE_ID` | the SQL warehouse |
| `PRICE_PASSPORT_CATALOG`, `PRICE_PASSPORT_SCHEMA` | where silver lives |
| `SNAPSHOT_BUCKET` | optional; the private bucket for snapshots, read and written with the service account's own token |
| `PORT` | set by Cloud Run, 8080 locally |

The principal needs the `databricks-sql-access` entitlement, `CAN USE` on the warehouse, `USE CATALOG`, and
`USE SCHEMA` plus `SELECT` on the schema. Table grants alone give HTTP 403 on every statement.

## Deploy

`./deploy.sh` deploys to Cloud Run in `devfest-backyard-barista-2026` (europe-west3) as the service account
`price-passport-api`, which may read only the secret `price-passport-reader-secret`. At most two instances, scaled to
zero when idle. The script refuses to run on 10 to 16 November and 10 to 11 December, when the Backyard Barista talk
demo in the same project is live.

Before the first deploy:

1. Create the secret `price-passport-reader-secret` with a fresh OAuth secret of `price-passport-reader`.
2. Point the service at a schema the reader can read: `PRICE_PASSPORT_SCHEMA` defaults to the prod schema
   `price_passport`, which exists after the first prod deploy from CI and needs the same grants as dev (`USE SCHEMA`,
   `SELECT`). Until then, deploy with `PRICE_PASSPORT_SCHEMA=dev_kdh_esra_price_passport_dev`.

## Run the checks

```bash
dart pub get
dart analyze
dart test
```
