-- Gold features: one row per delivery hour, built only from what was known at 10:00 Berlin time on the day before
-- (decisions section 7). A plain Delta table rather than a materialized view, so every version stays readable with
-- VERSION AS OF for the retention set below (section 9). Placeholders in braces are filled in by `features.py`.
CREATE OR REPLACE TABLE {catalog}.{schema}.gold_features
COMMENT 'One row per delivery hour with features known at 10:00 Berlin time on the day before. price_eur_mwh is the target and is null for hours not yet published.'
TBLPROPERTIES (
  'delta.logRetentionDuration' = 'interval 365 days',
  'delta.deletedFileRetentionDuration' = 'interval 365 days'
)
AS WITH prices AS (
  SELECT hour_start, delivery_day, price_eur_mwh, is_complete
  FROM {catalog}.{schema}.silver_price_hourly
),
daily AS (
  SELECT delivery_day, avg(price_eur_mwh) AS day_mean, min(price_eur_mwh) AS day_min, max(price_eur_mwh) AS day_max,
    count_if(is_complete) = count(*) AS day_complete
  FROM prices
  GROUP BY delivery_day
),
weather AS (
  SELECT
    hour_start,
    avg(temperature_2m) AS temperature_mean,
    avg(cloud_cover) AS cloud_cover_mean,
    max(CASE WHEN site = 'hamburg' THEN wind_speed_100m END) AS wind_hamburg,
    max(CASE WHEN site = 'berlin' THEN wind_speed_100m END) AS wind_berlin,
    max(CASE WHEN site = 'cologne' THEN wind_speed_100m END) AS wind_cologne,
    max(CASE WHEN site = 'frankfurt' THEN wind_speed_100m END) AS wind_frankfurt,
    max(CASE WHEN site = 'munich' THEN wind_speed_100m END) AS wind_munich,
    max(CASE WHEN site = 'hamburg' THEN shortwave_radiation END) AS solar_hamburg,
    max(CASE WHEN site = 'berlin' THEN shortwave_radiation END) AS solar_berlin,
    max(CASE WHEN site = 'cologne' THEN shortwave_radiation END) AS solar_cologne,
    max(CASE WHEN site = 'frankfurt' THEN shortwave_radiation END) AS solar_frankfurt,
    max(CASE WHEN site = 'munich' THEN shortwave_radiation END) AS solar_munich,
    count(*) AS weather_sites
  FROM {catalog}.{schema}.silver_weather_hourly
  GROUP BY hour_start
),
hours AS (
  SELECT
    weather.*,
    to_date(from_utc_timestamp(weather.hour_start, 'Europe/Berlin')) AS delivery_day,
    from_utc_timestamp(weather.hour_start, 'Europe/Berlin') AS local_hour_start
  FROM weather
)
SELECT
  hours.hour_start,
  hours.delivery_day,
  to_utc_timestamp(CAST(date_sub(hours.delivery_day, 1) AS TIMESTAMP) + INTERVAL 10 HOURS, 'Europe/Berlin')
    AS forecast_issued_at,
  CAST(
    (
      unix_timestamp(hours.hour_start)
      - unix_timestamp(to_utc_timestamp(CAST(date_sub(hours.delivery_day, 1) AS TIMESTAMP) + INTERVAL 10 HOURS, 'Europe/Berlin'))
    ) / 3600 AS INT
  ) AS horizon_hours,
  hour(hours.local_hour_start) AS local_hour,
  dayofweek(hours.delivery_day) AS day_of_week,
  month(hours.delivery_day) AS month,
  dayofweek(hours.delivery_day) IN (1, 7) AS is_weekend,
  -- 2025-09-30T22:00Z starts delivery day 1 October 2025, the first day of 15-minute products.
  hours.hour_start >= TIMESTAMP '2025-09-30 22:00:00' AS quarter_hour_market,
  day_before.price_eur_mwh AS price_same_hour_day_before,
  week_before.price_eur_mwh AS price_same_hour_week_before,
  previous_day.day_mean AS price_day_before_mean,
  previous_day.day_min AS price_day_before_min,
  previous_day.day_max AS price_day_before_max,
  hours.temperature_mean,
  hours.cloud_cover_mean,
  hours.wind_hamburg,
  hours.wind_berlin,
  hours.wind_cologne,
  hours.wind_frankfurt,
  hours.wind_munich,
  hours.solar_hamburg,
  hours.solar_berlin,
  hours.solar_cologne,
  hours.solar_frankfurt,
  hours.solar_munich,
  CASE WHEN target.is_complete THEN target.price_eur_mwh END AS price_eur_mwh
FROM hours
LEFT JOIN prices AS target ON target.hour_start = hours.hour_start
JOIN prices AS day_before
  ON day_before.hour_start = hours.hour_start - INTERVAL 24 HOURS AND day_before.is_complete
JOIN prices AS week_before
  ON week_before.hour_start = hours.hour_start - INTERVAL 168 HOURS AND week_before.is_complete
JOIN daily AS previous_day
  ON previous_day.delivery_day = date_sub(hours.delivery_day, 1) AND previous_day.day_complete
WHERE hours.weather_sites = 5
