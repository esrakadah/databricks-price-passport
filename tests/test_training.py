import re
import tomllib
from datetime import date, timedelta
from importlib.resources import files
from pathlib import Path

import mlflow.pyfunc
import numpy as np
import pandas as pd
import pytest

from price_passport.models import (
    FEATURE_COLUMNS,
    TARGET,
    WEEK_BEFORE,
    SeasonalNaive,
    feature_frame,
    gradient_boosting,
)
from price_passport.training import (
    HOLDOUT_FIRST_DAY,
    HOLDOUT_LAST_DAY,
    RUNTIME_REQUIREMENTS,
    evaluate,
    model_name,
    split,
)

HOURS_PER_DAY = 24
PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def gold_rows(first_day: date, days: int) -> pd.DataFrame:
    """Rows shaped like gold_features, with a price that follows the week-before price plus an evening premium."""
    generator = np.random.default_rng(0)
    rows = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        for hour in range(HOURS_PER_DAY):
            week_before = 80 + 20 * np.sin(hour / 4) + generator.normal(0, 5)
            row = dict.fromkeys(FEATURE_COLUMNS, 1.0)
            row.update(
                delivery_day=day,
                local_hour=hour,
                day_of_week=day.isoweekday() % 7 + 1,
                month=day.month,
                is_weekend=day.isoweekday() >= 6,
                quarter_hour_market=True,
                **{WEEK_BEFORE: week_before, TARGET: week_before + (30.0 if 17 <= hour < 21 else 0.0)},
            )
            rows.append(row)
    return pd.DataFrame(rows)


def test_training_ends_before_the_holdout_and_the_holdout_is_fixed():
    frame = gold_rows(HOLDOUT_FIRST_DAY - timedelta(days=10), 120)

    data = split(frame)

    assert data.train["delivery_day"].max() < HOLDOUT_FIRST_DAY
    assert data.holdout["delivery_day"].min() == HOLDOUT_FIRST_DAY
    assert data.holdout["delivery_day"].max() == HOLDOUT_LAST_DAY


def test_hours_without_a_price_are_neither_trained_on_nor_scored():
    frame = gold_rows(HOLDOUT_FIRST_DAY - timedelta(days=2), 4)
    frame.loc[frame.index[:5], TARGET] = None

    data = split(frame)

    assert len(data.train) + len(data.holdout) == len(frame) - 5


def test_features_without_holdout_hours_are_refused():
    with pytest.raises(ValueError, match="holdout"):
        split(gold_rows(HOLDOUT_FIRST_DAY - timedelta(days=30), 5))


def test_the_baseline_has_no_skill_against_itself_and_the_evening_is_measured_apart():
    holdout = gold_rows(HOLDOUT_FIRST_DAY, 7)

    metrics = evaluate(holdout, holdout[WEEK_BEFORE])

    assert metrics["mae"] == pytest.approx(30 * 4 / 24)
    assert metrics["mae_evening"] == pytest.approx(30)
    assert metrics["skill_vs_baseline"] == pytest.approx(0)
    assert metrics["holdout_hours"] == 7 * HOURS_PER_DAY


def test_a_perfect_forecast_has_full_skill():
    holdout = gold_rows(HOLDOUT_FIRST_DAY, 2)

    metrics = evaluate(holdout, holdout[TARGET])

    assert metrics["mae"] == pytest.approx(0)
    assert metrics["skill_vs_baseline"] == pytest.approx(1)


def test_the_learned_model_beats_the_baseline_where_the_baseline_is_wrong():
    data = split(gold_rows(HOLDOUT_FIRST_DAY - timedelta(days=60), 90))

    estimator = gradient_boosting().fit(feature_frame(data.train), data.train[TARGET])
    metrics = evaluate(data.holdout, estimator.predict(feature_frame(data.holdout)))

    assert metrics["skill_vs_baseline"] > 0.5


def test_the_model_input_has_the_feature_columns_in_order_with_booleans_as_numbers():
    features = feature_frame(gold_rows(HOLDOUT_FIRST_DAY, 1))

    assert tuple(features.columns) == FEATURE_COLUMNS
    assert features["is_weekend"].dtype == "int64"


def test_every_feature_is_a_column_of_the_gold_table():
    sql = files("price_passport").joinpath("sql", "gold_features.sql").read_text(encoding="utf-8")

    missing = [column for column in FEATURE_COLUMNS if not re.search(rf"\b{column}\b", sql)]

    assert not missing


def test_the_seasonal_naive_model_survives_saving_and_loading(tmp_path):
    features = feature_frame(gold_rows(HOLDOUT_FIRST_DAY, 1))
    package = Path(files("price_passport").joinpath("__init__.py")).parent

    mlflow.pyfunc.save_model(tmp_path / "model", python_model=SeasonalNaive(), code_paths=[str(package)])
    predicted = mlflow.pyfunc.load_model(str(tmp_path / "model")).predict(features)

    assert np.allclose(np.asarray(predicted), features[WEEK_BEFORE])


def test_the_logged_requirements_match_the_pinned_dev_dependencies():
    dev = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["dependency-groups"]["dev"]

    assert set(RUNTIME_REQUIREMENTS) <= set(dev)


def test_the_model_lives_next_to_the_features():
    assert model_name("workspace", "price_passport") == "workspace.price_passport.price_model"
    with pytest.raises(ValueError, match="plain SQL identifier"):
        model_name("workspace", "a.b")
