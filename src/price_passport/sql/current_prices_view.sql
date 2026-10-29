-- The latest scored price of every hour: the price the tariff serves until an override exists (decisions section 6).
CREATE OR REPLACE VIEW {catalog}.{schema}.current_prices
COMMENT 'Latest scored price per hour from prices, with its lineage.'
AS SELECT *
FROM {catalog}.{schema}.prices
QUALIFY row_number() OVER (PARTITION BY hour_start ORDER BY scored_at DESC, model_version DESC) = 1
