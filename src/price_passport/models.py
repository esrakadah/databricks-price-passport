"""The price models and the features they read (decisions section 8).

Kept apart from the training job, so that a registered model loads without the training code and scoring reads the
same feature list the models were trained on.
"""

from typing import Any

import pandas as pd
from mlflow.pyfunc.model import PythonModel
from sklearn.ensemble import HistGradientBoostingRegressor

TARGET = "price_eur_mwh"
WEEK_BEFORE = "price_same_hour_week_before"
FEATURE_COLUMNS = (
    "local_hour",
    "day_of_week",
    "month",
    "is_weekend",
    "quarter_hour_market",
    "price_same_hour_day_before",
    WEEK_BEFORE,
    "price_day_before_mean",
    "price_day_before_min",
    "price_day_before_max",
    "temperature_mean",
    "cloud_cover_mean",
    "wind_hamburg",
    "wind_berlin",
    "wind_cologne",
    "wind_frankfurt",
    "wind_munich",
    "solar_hamburg",
    "solar_berlin",
    "solar_cologne",
    "solar_frankfurt",
    "solar_munich",
)
SEASONAL_NAIVE = "seasonal_naive"
GRADIENT_BOOSTING = "gradient_boosting"
MODEL_KINDS = (SEASONAL_NAIVE, GRADIENT_BOOSTING)

# Fixed so that two runs on the same feature version train the same model. Absolute error, because the model is
# judged on MAE; no early stopping, because its validation split would be drawn at random across time.
GRADIENT_BOOSTING_PARAMETERS: dict[str, Any] = {
    "loss": "absolute_error",
    "learning_rate": 0.05,
    "max_iter": 400,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 40,
    "early_stopping": False,
    "random_state": 0,
}


def feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """The model input: the feature columns in a fixed order, booleans as 0 and 1."""
    features = frame.loc[:, list(FEATURE_COLUMNS)].copy()
    for column in ("is_weekend", "quarter_hour_market"):
        features[column] = features[column].astype("int64")
    return features


def seasonal_naive_forecast(features: pd.DataFrame) -> pd.Series:
    return features[WEEK_BEFORE].astype("float64")


class SeasonalNaive(PythonModel):
    """Version 1: the price of the same hour one week earlier, the baseline every later model is measured against."""

    def predict(self, context: Any, model_input: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.Series:
        return seasonal_naive_forecast(model_input)


def gradient_boosting() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(**GRADIENT_BOOSTING_PARAMETERS)
