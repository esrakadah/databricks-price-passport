from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from price_passport.models import FEATURE_COLUMNS
from price_passport.scoring import (
    PRICE_COLUMNS,
    SPARK_SCHEMA,
    Champion,
    Lineage,
    days_to_score,
    hours_in_local_day,
    lineage_problems,
    optional_day,
    priced_rows,
    require_complete_days,
    tomorrow,
)
from price_passport.tariff import RULES

CHAMPION = Champion(
    name="workspace.price_passport.price_model",
    version=2,
    run_id="run-2",
    training_data_version=0,
    training_last_day=date(2026, 7, 31),
)
SCORED_AT = datetime(2026, 10, 29, 9, 5, tzinfo=UTC)


def feature_rows(day: date) -> pd.DataFrame:
    hours = hours_in_local_day(day)
    midnight_utc = datetime(day.year, day.month, day.day, tzinfo=UTC).replace(tzinfo=None)
    first_hour = pd.Timestamp(midnight_utc - timedelta(hours=1))
    rows = pd.DataFrame({column: [1.0] * hours for column in FEATURE_COLUMNS})
    rows["hour_start"] = [first_hour + pd.Timedelta(hours=hour) for hour in range(hours)]
    rows["delivery_day"] = day
    rows["forecast_issued_at"] = pd.Timestamp(midnight_utc - timedelta(hours=15))
    rows["horizon_hours"] = range(14, 14 + hours)
    return rows


def test_the_default_day_is_tomorrow_in_berlin_even_late_in_the_utc_evening():
    assert tomorrow(datetime(2026, 10, 29, 23, 30, tzinfo=UTC)) == date(2026, 10, 31)


@pytest.mark.parametrize(
    ("day", "hours"),
    [(date(2026, 10, 25), 25), (date(2026, 3, 29), 23), (date(2026, 10, 30), 24)],
)
def test_local_days_have_23_24_or_25_hours(day, hours):
    assert hours_in_local_day(day) == hours


def test_days_inside_the_training_window_are_never_scored():
    with pytest.raises(ValueError, match="has seen"):
        days_to_score(date(2026, 7, 31), date(2026, 8, 2), CHAMPION)


def test_a_range_lists_every_day_once():
    assert days_to_score(date(2026, 8, 1), date(2026, 8, 3), CHAMPION) == [
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 8, 3),
    ]


def test_a_reversed_range_is_refused():
    with pytest.raises(ValueError, match="before"):
        days_to_score(date(2026, 8, 3), date(2026, 8, 1), CHAMPION)


def test_a_day_with_missing_hours_stops_the_run():
    day = date(2026, 10, 30)
    features = feature_rows(day).iloc[:-1]

    with pytest.raises(ValueError, match="23 of 24 hours"):
        require_complete_days(features, [day])


def test_a_day_without_any_features_stops_the_run():
    with pytest.raises(ValueError, match="0 of 24 hours"):
        require_complete_days(feature_rows(date(2026, 10, 30)), [date(2026, 10, 30), date(2026, 10, 31)])


def test_every_price_row_carries_the_full_lineage():
    day = date(2026, 10, 25)
    features = feature_rows(day)

    rows = priced_rows(
        features,
        [100.0] * len(features),
        champion=CHAMPION,
        scoring_feature_version=3,
        rule=RULES[1],
        scored_at=SCORED_AT,
    )

    assert tuple(rows.columns) == PRICE_COLUMNS
    assert len(rows) == 25
    first = rows.iloc[0]
    assert first["model_version"] == 2
    assert first["mlflow_run_id"] == "run-2"
    assert first["model_alias"] == "champion"
    assert first["training_data_version"] == 0
    assert first["scoring_feature_version"] == 3
    assert first["tariff_rule_version"] == 1
    assert first["tariff_rule_hash"] == RULES[1].parameter_hash
    assert first["price_ct_kwh"] == pytest.approx(RULES[1].price_ct_kwh(100.0))
    assert first["scored_at"] == pd.Timestamp(2026, 10, 29, 9, 5)


def test_the_spark_schema_lists_the_price_columns_in_order():
    assert tuple(field.split()[0] for field in SPARK_SCHEMA.split(", ")) == PRICE_COLUMNS


def test_consistent_lineage_has_no_problems():
    rule = RULES[1]
    stored = [Lineage(2, "run-2", rule.version, rule.parameter_hash)]

    assert lineage_problems(stored, lambda version: f"run-{version}") == []


def test_a_run_the_registry_does_not_report_is_a_problem():
    rule = RULES[1]
    problems = lineage_problems([Lineage(2, "run-x", rule.version, rule.parameter_hash)], lambda version: "run-2")

    assert problems == ["model version 2 names run run-x, the registry says run-2"]


def test_a_rule_missing_from_code_or_with_another_hash_is_a_problem():
    problems = lineage_problems(
        [Lineage(2, "run-2", 99, "abc"), Lineage(2, "run-2", 1, "abc")],
        lambda version: "run-2",
    )

    assert problems[0] == "tariff rule 99 does not exist in code"
    assert problems[1].startswith("tariff rule 1 has hash")


def test_an_empty_job_parameter_means_the_default_day():
    assert optional_day("") is None
    assert optional_day("2026-10-30") == date(2026, 10, 30)
