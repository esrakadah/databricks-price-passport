import re

import pytest

from price_passport.features import feature_sql

PRICE_LAGS = re.compile(r"-\s*INTERVAL\s+(\d+)\s+HOURS", re.IGNORECASE)
SHORTEST_SAFE_LAG_HOURS = 24


def test_the_statement_targets_the_given_catalog_and_schema():
    sql = feature_sql("workspace", "price_passport")

    assert "CREATE OR REPLACE TABLE workspace.price_passport.gold_features" in sql
    assert "{" not in sql


def test_the_feature_table_keeps_versions_for_a_year():
    sql = feature_sql("workspace", "price_passport")

    assert "'delta.logRetentionDuration' = 'interval 365 days'" in sql
    assert "'delta.deletedFileRetentionDuration' = 'interval 365 days'" in sql


def test_no_price_lag_is_shorter_than_a_day():
    """A lag under 24 hours would read a price of the delivery day itself, which is unknown at the cutoff."""
    sql = feature_sql("workspace", "price_passport")
    lags = [int(hours) for hours in PRICE_LAGS.findall(sql)]

    assert lags
    assert min(lags) >= SHORTEST_SAFE_LAG_HOURS


@pytest.mark.parametrize("name", ["price_passport; DROP TABLE x", "a.b", "", "1schema"])
def test_names_that_are_not_plain_identifiers_are_refused(name):
    with pytest.raises(ValueError, match="plain SQL identifier"):
        feature_sql("workspace", name)
