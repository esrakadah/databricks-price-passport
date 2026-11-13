#!/usr/bin/env bash
# Deploys the Price Passport API to Cloud Run (decisions section 5 and plan day 9).
#
# Shares the project with the Backyard Barista talk demo, so it never deploys while the talks run, caps its instances,
# and runs as its own service account that may read nothing but its one secret. The secret itself is created by hand:
#   gcloud secrets create price-passport-reader-secret --project devfest-backyard-barista-2026 --data-file=-
set -euo pipefail

PROJECT="devfest-backyard-barista-2026"
REGION="europe-west3"
SERVICE="price-passport-api"
SERVICE_ACCOUNT="price-passport-api@${PROJECT}.iam.gserviceaccount.com"
SECRET="price-passport-reader-secret"
SNAPSHOT_BUCKET="${PROJECT}-price-passport-snapshots"
MAX_INSTANCES=2
CONCURRENCY=40
MEMORY="256Mi"

DATABRICKS_HOST="https://dbc-7669358a-2975.cloud.databricks.com"
DATABRICKS_CLIENT_ID="${DATABRICKS_CLIENT_ID:?set it to the application ID of price-passport-reader}"
DATABRICKS_WAREHOUSE_ID="fe5eb9c53b8169e5"
PRICE_PASSPORT_CATALOG="workspace"
PRICE_PASSPORT_SCHEMA="${PRICE_PASSPORT_SCHEMA:-price_passport}"

# The DevFest talks use this project on these days; a broken deploy then would hit the live demo.
today="$(TZ=Europe/Berlin date +%Y-%m-%d)"
case "${today}" in
  2026-11-1[0-6] | 2026-12-1[01])
    echo "No deploys on ${today}: the Backyard Barista demo in this project is in use for a talk." >&2
    exit 1
    ;;
esac

if ! gcloud secrets describe "${SECRET}" --project "${PROJECT}" >/dev/null 2>&1; then
  echo "Secret ${SECRET} does not exist yet; create it first (see the comment at the top)." >&2
  exit 1
fi

# The API serves the Flutter web app from public/, so the image carries the current build of app/.
api_dir="$(cd "$(dirname "$0")" && pwd)"
(cd "${api_dir}/../app" && flutter build web --release)
rm -rf "${api_dir}/public"
cp -R "${api_dir}/../app/build/web" "${api_dir}/public"

gcloud secrets add-iam-policy-binding "${SECRET}" \
  --project "${PROJECT}" \
  --member "serviceAccount:${SERVICE_ACCOUNT}" \
  --role roles/secretmanager.secretAccessor \
  --condition None >/dev/null

gcloud run deploy "${SERVICE}" \
  --project "${PROJECT}" \
  --region "${REGION}" \
  --source "${api_dir}" \
  --service-account "${SERVICE_ACCOUNT}" \
  --max-instances "${MAX_INSTANCES}" \
  --min-instances 0 \
  --concurrency "${CONCURRENCY}" \
  --memory "${MEMORY}" \
  --allow-unauthenticated \
  --set-env-vars "DATABRICKS_HOST=${DATABRICKS_HOST},DATABRICKS_CLIENT_ID=${DATABRICKS_CLIENT_ID},DATABRICKS_WAREHOUSE_ID=${DATABRICKS_WAREHOUSE_ID},PRICE_PASSPORT_CATALOG=${PRICE_PASSPORT_CATALOG},PRICE_PASSPORT_SCHEMA=${PRICE_PASSPORT_SCHEMA},SNAPSHOT_BUCKET=${SNAPSHOT_BUCKET}" \
  --set-secrets "DATABRICKS_CLIENT_SECRET=${SECRET}:latest"

url="$(gcloud run services describe "${SERVICE}" --project "${PROJECT}" --region "${REGION}" --format 'value(status.url)')"
echo "Deployed ${url}"
curl --fail --silent "${url}/health" && echo " (health ok)"
