"""Trains a price model on one version of the gold features and registers it in Unity Catalog (decisions 1, 8 and 9).

Runs as a Databricks job task on serverless compute. The job reads the current version of the feature table once and
then reads exactly that version, so the `training_data_version` logged on the run is the data the model saw. Every run
is scored on the same fixed holdout and logs its MAE next to the seasonal naive baseline's on those hours, so runs can
be compared by the promotion gate without retraining anything.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from price_passport import __version__
from price_passport.features import latest_version, require_identifiers
from price_passport.models import (
    FEATURE_COLUMNS,
    GRADIENT_BOOSTING,
    GRADIENT_BOOSTING_PARAMETERS,
    MODEL_KINDS,
    SEASONAL_NAIVE,
    TARGET,
    WEEK_BEFORE,
    SeasonalNaive,
    feature_frame,
    gradient_boosting,
    seasonal_naive_forecast,
)

MODEL_NAME = "price_model"
FEATURE_TABLE = "gold_features"
# The holdout lies after every candidate's training window and does not move as new days arrive, so MAEs logged weeks
# apart are measured on the same hours. Moving it starts a new series: the gate only compares runs with the same id.
HOLDOUT_FIRST_DAY = date(2026, 8, 1)
HOLDOUT_LAST_DAY = date(2026, 10, 28)
HOLDOUT_ID = f"{HOLDOUT_FIRST_DAY.isoformat()}_{HOLDOUT_LAST_DAY.isoformat()}"
EVENING_FIRST_HOUR = 17
EVENING_END_HOUR = 21
# The packages of serverless environment version 4, read from a probe run on 29 Oct 2026. Training and scoring run
# there, the model is logged with the same pins, and the dev dependency group in pyproject.toml matches them.
RUNTIME_REQUIREMENTS = ("mlflow-skinny==2.22.0", "scikit-learn==1.6.1", "pandas==2.2.3", "numpy==2.1.3")
INPUT_EXAMPLE_ROWS = 3


@dataclass(frozen=True)
class Split:
    train: pd.DataFrame
    holdout: pd.DataFrame


def split(frame: pd.DataFrame) -> Split:
    """Hours with a known price, divided at the fixed holdout; hours after the holdout are not used at all."""
    labelled = frame[frame[TARGET].notna()]
    train = labelled[labelled["delivery_day"] < HOLDOUT_FIRST_DAY]
    holdout = labelled[(labelled["delivery_day"] >= HOLDOUT_FIRST_DAY) & (labelled["delivery_day"] <= HOLDOUT_LAST_DAY)]
    if train.empty or holdout.empty:
        raise ValueError(f"the features need hours before {HOLDOUT_FIRST_DAY} and in the holdout {HOLDOUT_ID}")
    return Split(train=train, holdout=holdout)


def mean_absolute_error(actual: pd.Series, predicted: pd.Series) -> float:
    return float(np.mean(np.abs(actual.to_numpy(dtype="float64") - predicted.to_numpy(dtype="float64"))))


def evaluate(holdout: pd.DataFrame, predictions: Any) -> dict[str, float]:
    """MAE over the holdout and over its evening hours 17:00 to 21:00, next to the baseline's on the same hours.

    `predictions` holds one value per holdout row, in row order.
    """
    predicted = pd.Series(np.asarray(predictions, dtype="float64"), index=holdout.index)
    evening = holdout["local_hour"].between(EVENING_FIRST_HOUR, EVENING_END_HOUR - 1)
    mae = mean_absolute_error(holdout[TARGET], predicted)
    baseline_mae = mean_absolute_error(holdout[TARGET], holdout[WEEK_BEFORE])
    return {
        "mae": mae,
        "mae_evening": mean_absolute_error(holdout.loc[evening, TARGET], predicted[evening]),
        "baseline_mae": baseline_mae,
        "baseline_mae_evening": mean_absolute_error(holdout.loc[evening, TARGET], holdout.loc[evening, WEEK_BEFORE]),
        "skill_vs_baseline": 1 - mae / baseline_mae,
        "holdout_hours": float(len(holdout)),
    }


def model_name(catalog: str, schema: str) -> str:
    require_identifiers(catalog, schema)
    return f"{catalog}.{schema}.{MODEL_NAME}"


def train_and_register(
    spark: Any, *, catalog: str, schema: str, kind: str, experiment_id: str, git_commit: str
) -> tuple[str, str]:
    """Returns the registered model's name and the new version."""
    import mlflow
    from mlflow.data.spark_dataset import load_delta
    from mlflow.models import infer_signature
    from mlflow.tracking import MlflowClient

    registered_name = model_name(catalog, schema)
    table = f"{catalog}.{schema}.{FEATURE_TABLE}"
    data_version = latest_version(spark, table)
    frame = spark.sql(f"SELECT * FROM {table} VERSION AS OF {data_version}").toPandas()
    data = split(frame)
    train_features = feature_frame(data.train)
    holdout_features = feature_frame(data.holdout)

    mlflow.set_registry_uri("databricks-uc")
    lineage = {
        "model_kind": kind,
        "training_table": table,
        "training_data_version": str(data_version),
        "holdout_id": HOLDOUT_ID,
        "package_version": __version__,
        "git_commit": git_commit,
    }
    with mlflow.start_run(experiment_id=experiment_id, run_name=f"{kind} on {FEATURE_TABLE} v{data_version}"):
        mlflow.set_tags(lineage)
        mlflow.log_params(
            {
                **lineage,
                "training_first_day": str(data.train["delivery_day"].min()),
                "training_last_day": str(data.train["delivery_day"].max()),
                "training_hours": len(data.train),
                "features": ",".join(FEATURE_COLUMNS),
            }
        )
        mlflow.log_input(load_delta(table_name=table, version=str(data_version)), context="training")

        if kind == SEASONAL_NAIVE:
            predicted = seasonal_naive_forecast(holdout_features)
            signature = infer_signature(holdout_features, predicted)
            info = mlflow.pyfunc.log_model(
                artifact_path="model",
                python_model=SeasonalNaive(),
                code_paths=[str(Path(__file__).parent)],
                signature=signature,
                input_example=holdout_features.head(INPUT_EXAMPLE_ROWS),
                pip_requirements=list(RUNTIME_REQUIREMENTS),
                registered_model_name=registered_name,
            )
        else:
            mlflow.log_params(GRADIENT_BOOSTING_PARAMETERS)
            estimator = gradient_boosting().fit(train_features, data.train[TARGET])
            predicted = pd.Series(estimator.predict(holdout_features), index=holdout_features.index)
            signature = infer_signature(holdout_features, predicted)
            info = mlflow.sklearn.log_model(
                estimator,
                artifact_path="model",
                signature=signature,
                input_example=holdout_features.head(INPUT_EXAMPLE_ROWS),
                pip_requirements=list(RUNTIME_REQUIREMENTS),
                registered_model_name=registered_name,
            )
        mlflow.log_metrics(evaluate(data.holdout, predicted))

    version = str(info.registered_model_version)
    client = MlflowClient()
    for key, value in lineage.items():
        client.set_model_version_tag(registered_name, version, key, value)
    return registered_name, version


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--model", choices=MODEL_KINDS, default=GRADIENT_BOOSTING)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--git-commit", default="unknown")
    arguments = parser.parse_args(argv)

    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    name, version = train_and_register(
        spark,
        catalog=arguments.catalog,
        schema=arguments.schema,
        kind=arguments.model,
        experiment_id=arguments.experiment_id,
        git_commit=arguments.git_commit,
    )
    print(f"registered {name} version {version} ({arguments.model})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
