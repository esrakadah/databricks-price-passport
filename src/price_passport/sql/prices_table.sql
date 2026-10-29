-- Scored prices, one row per hour and scoring, never updated (decisions sections 1 and 9). A new champion, a new
-- feature version or a new tariff rule adds rows next to the old ones; current_prices picks the latest per hour.
-- Placeholders in braces are filled in by `scoring.py`.
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.prices (
  hour_start TIMESTAMP NOT NULL COMMENT 'Start of the priced hour, UTC.',
  delivery_day DATE NOT NULL COMMENT 'Local delivery day in Europe/Berlin.',
  forecast_eur_mwh DOUBLE NOT NULL COMMENT 'Model forecast of the day-ahead price.',
  price_ct_kwh DOUBLE NOT NULL COMMENT 'Tariff price from the forecast under tariff_rule_version, VAT included.',
  model_name STRING NOT NULL,
  model_version INT NOT NULL COMMENT 'Unity Catalog model version that scored the row, resolved from the alias once.',
  mlflow_run_id STRING NOT NULL COMMENT 'Run of that model version, read from the same model version.',
  model_alias STRING NOT NULL COMMENT 'Alias used to find the version; informational, aliases move.',
  training_data_version BIGINT NOT NULL COMMENT 'Delta version of gold_features the model was trained on.',
  scoring_feature_version BIGINT NOT NULL COMMENT 'Delta version of gold_features the row was scored from.',
  tariff_rule_version INT NOT NULL,
  tariff_rule_hash STRING NOT NULL,
  forecast_issued_at TIMESTAMP NOT NULL COMMENT 'Information cutoff, 10:00 Berlin time on the day before delivery.',
  horizon_hours INT NOT NULL,
  scored_at TIMESTAMP NOT NULL
)
COMMENT 'Scored tariff prices with the lineage of every row. Append-only.'
TBLPROPERTIES (
  'delta.logRetentionDuration' = 'interval 365 days',
  'delta.deletedFileRetentionDuration' = 'interval 365 days'
)
