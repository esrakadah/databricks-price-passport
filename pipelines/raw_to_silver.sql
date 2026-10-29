-- Bronze and silver for Price Passport (decisions sections 3 and 4).
--
-- Bronze reads the files the ingest job writes, as they are, and every refresh re-reads them, so a file the job
-- overwrote is always seen at its latest content. Silver is the hourly price and weather series. The price logic
-- mirrors `price_passport.energy_charts.parse_day_ahead_prices`, which is the tested reference: quarter-hours averaged
-- into the UTC hour they start in, one expected point per hour before the 15-minute switch and four after it.

CREATE OR REFRESH MATERIALIZED VIEW bronze_price_files
COMMENT "Energy-Charts day-ahead price responses as written by the ingest job, one row per local delivery day."
AS SELECT
  to_date(regexp_extract(_metadata.file_path, 'dt=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1)) AS delivery_day,
  _metadata.file_path AS source_file,
  _metadata.file_modification_time AS file_modified_at,
  unit,
  deprecated,
  license_info,
  unix_seconds,
  price
FROM read_files(
  '${raw_root}/energy_charts/price/',
  format => 'json',
  recursiveFileLookup => true,
  schema => 'unit STRING, deprecated BOOLEAN, license_info STRING, unix_seconds ARRAY<BIGINT>, price ARRAY<DOUBLE>'
);

CREATE OR REFRESH MATERIALIZED VIEW silver_price_hourly (
  CONSTRAINT unit_is_eur_per_mwh EXPECT (unit = 'EUR / MWh') ON VIOLATION FAIL UPDATE,
  CONSTRAINT not_more_points_than_products EXPECT (source_points <= expected_points) ON VIOLATION FAIL UPDATE,
  CONSTRAINT price_is_finite EXPECT (price_eur_mwh IS NOT NULL AND NOT isnan(price_eur_mwh)) ON VIOLATION FAIL UPDATE
)
COMMENT "Day-ahead price per UTC hour with completeness flags. Gold uses complete hours only."
AS WITH points AS (
  SELECT
    delivery_day,
    unit,
    point.unix_seconds - point.unix_seconds % 3600 AS hour_epoch,
    point.price AS price
  FROM bronze_price_files
  LATERAL VIEW explode(arrays_zip(unix_seconds, price)) AS point
  WHERE point.price IS NOT NULL
),
hours AS (
  SELECT
    hour_epoch,
    max(delivery_day) AS delivery_day,
    max(unit) AS unit,
    avg(price) AS price_eur_mwh,
    count(*) AS source_points,
    -- 1759269600 is 2025-09-30T22:00Z, the first hour of delivery day 1 October 2025 and of the 15-minute products.
    CASE WHEN hour_epoch >= 1759269600 THEN 4 ELSE 1 END AS expected_points
  FROM points
  GROUP BY hour_epoch
)
SELECT
  timestamp_seconds(hour_epoch) AS hour_start,
  from_utc_timestamp(timestamp_seconds(hour_epoch), 'Europe/Berlin') AS local_hour_start,
  delivery_day,
  unit,
  price_eur_mwh,
  source_points,
  expected_points,
  source_points = expected_points AS is_complete
FROM hours;

CREATE OR REFRESH MATERIALIZED VIEW bronze_weather_files
COMMENT "Open-Meteo archived hourly forecasts as written by the ingest job, one row per site and UTC day."
AS SELECT
  regexp_extract(_metadata.file_path, 'site=([a-z]+)', 1) AS site,
  to_date(regexp_extract(_metadata.file_path, 'dt=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1)) AS utc_day,
  _metadata.file_path AS source_file,
  _metadata.file_modification_time AS file_modified_at,
  latitude,
  longitude,
  hourly
FROM read_files(
  '${raw_root}/open_meteo/historical_forecast/',
  format => 'json',
  recursiveFileLookup => true,
  schema => 'latitude DOUBLE, longitude DOUBLE, hourly STRUCT<time: ARRAY<STRING>, temperature_2m: ARRAY<DOUBLE>, wind_speed_100m: ARRAY<DOUBLE>, shortwave_radiation: ARRAY<DOUBLE>, cloud_cover: ARRAY<DOUBLE>>'
);

CREATE OR REFRESH MATERIALIZED VIEW silver_weather_hourly (
  CONSTRAINT hour_is_parsed EXPECT (hour_start IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT site_is_known EXPECT (site IN ('hamburg', 'berlin', 'cologne', 'frankfurt', 'munich')) ON VIOLATION FAIL UPDATE,
  CONSTRAINT weather_is_present EXPECT (
    temperature_2m IS NOT NULL AND wind_speed_100m IS NOT NULL AND shortwave_radiation IS NOT NULL
    AND cloud_cover IS NOT NULL
  )
)
COMMENT "Archived hourly weather forecasts per site and UTC hour."
AS SELECT
  site,
  to_timestamp(reading.time, "yyyy-MM-dd'T'HH:mm") AS hour_start,
  reading.temperature_2m,
  reading.wind_speed_100m,
  reading.shortwave_radiation,
  reading.cloud_cover
FROM bronze_weather_files
LATERAL VIEW explode(
  arrays_zip(
    hourly.time, hourly.temperature_2m, hourly.wind_speed_100m, hourly.shortwave_radiation, hourly.cloud_cover
  )
) AS reading;
