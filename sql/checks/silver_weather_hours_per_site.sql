-- Every site must have 24 hourly readings per UTC day. Expected result: no rows.
SELECT site, CAST(hour_start AS DATE) AS utc_day, count(*) AS readings
FROM workspace.price_passport.silver_weather_hourly
GROUP BY site, CAST(hour_start AS DATE)
HAVING count(*) <> 24;
