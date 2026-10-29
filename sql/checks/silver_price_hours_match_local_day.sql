-- Every delivery day in silver must have exactly as many hours as its local day: 23 when the clocks go forward,
-- 25 when they go back, 24 otherwise. Expected result: wrong_days = 0. Replace the schema for the target you check.
SELECT
  count(*) AS days,
  count_if(hours <> local_day_hours) AS wrong_days,
  count_if(complete_hours <> hours) AS days_with_incomplete_hours
FROM (
  SELECT
    delivery_day,
    count(*) AS hours,
    count_if(is_complete) AS complete_hours,
    CAST(
      (
        unix_timestamp(to_utc_timestamp(CAST(date_add(delivery_day, 1) AS TIMESTAMP), 'Europe/Berlin'))
        - unix_timestamp(to_utc_timestamp(CAST(delivery_day AS TIMESTAMP), 'Europe/Berlin'))
      ) / 3600 AS INT
    ) AS local_day_hours
  FROM workspace.price_passport.silver_price_hourly
  GROUP BY delivery_day
);
