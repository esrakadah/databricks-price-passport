"""Scores delivery days with the `@champion` model and stores every price with its lineage (decisions 1, 7 and 10).

The alias is resolved once into a model version, and that exact version is loaded, so the version stored is the one
that ran even if the gate moves the alias meanwhile. Features are read at one Delta version, which is stored as
`scoring_feature_version`. Only days after the champion's training window are scored, so no stored price is a forecast
of an hour the model has already seen. Writing merges on hour, model version, feature version and tariff rule, so
scoring the same feature version again adds nothing. After writing, the lineage of the whole table is checked against
the registry and the rules in code, and any mismatch fails the run.
"""

import argparse
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from price_passport.energy_charts import TARIFF_TIMEZONE
from price_passport.features import latest_version, package_sql
from price_passport.gate import CHAMPION
from price_passport.models import feature_frame
from price_passport.tariff import CURRENT_RULE, RULES, TariffRule
from price_passport.training import FEATURE_TABLE, model_name

PRICES_TABLE = "prices"
PRICE_COLUMNS = (
    "hour_start",
    "delivery_day",
    "forecast_eur_mwh",
    "price_ct_kwh",
    "model_name",
    "model_version",
    "mlflow_run_id",
    "model_alias",
    "training_data_version",
    "scoring_feature_version",
    "tariff_rule_version",
    "tariff_rule_hash",
    "forecast_issued_at",
    "horizon_hours",
    "scored_at",
)
SPARK_SCHEMA = (
    "hour_start TIMESTAMP, delivery_day DATE, forecast_eur_mwh DOUBLE, price_ct_kwh DOUBLE, model_name STRING, "
    "model_version INT, mlflow_run_id STRING, model_alias STRING, training_data_version BIGINT, "
    "scoring_feature_version BIGINT, tariff_rule_version INT, tariff_rule_hash STRING, forecast_issued_at TIMESTAMP, "
    "horizon_hours INT, scored_at TIMESTAMP"
)
MERGE_KEYS = ("hour_start", "model_version", "scoring_feature_version", "tariff_rule_version")


@dataclass(frozen=True)
class Champion:
    name: str
    version: int
    run_id: str
    training_data_version: int
    training_last_day: date


@dataclass(frozen=True)
class Lineage:
    model_version: int
    mlflow_run_id: str
    tariff_rule_version: int
    tariff_rule_hash: str


def tomorrow(now: datetime) -> date:
    return now.astimezone(TARIFF_TIMEZONE).date() + timedelta(days=1)


def days_to_score(first: date, last: date, champion: Champion) -> list[date]:
    if last < first:
        raise ValueError(f"{last} is before {first}")
    if first <= champion.training_last_day:
        raise ValueError(
            f"version {champion.version} was trained on days up to {champion.training_last_day}; "
            f"scoring {first} would publish a forecast of an hour the model has seen"
        )
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def hours_in_local_day(day: date) -> int:
    start = datetime(day.year, day.month, day.day, tzinfo=TARIFF_TIMEZONE)
    following = day + timedelta(days=1)
    end = datetime(following.year, following.month, following.day, tzinfo=TARIFF_TIMEZONE)
    # Aware datetimes in the same zone subtract as wall-clock times, so the difference is taken in UTC.
    return int((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() // 3600)


def require_complete_days(features: pd.DataFrame, days: Sequence[date]) -> None:
    """Every requested day must have a feature row for each of its local hours, or nothing is scored."""
    counts = features.groupby("delivery_day").size()
    incomplete = [
        f"{day} has {int(counts.get(day, 0))} of {hours_in_local_day(day)} hours"
        for day in days
        if int(counts.get(day, 0)) != hours_in_local_day(day)
    ]
    if incomplete:
        raise ValueError("features are not ready: " + "; ".join(incomplete))


def priced_rows(
    features: pd.DataFrame,
    forecasts: Any,
    *,
    champion: Champion,
    scoring_feature_version: int,
    rule: TariffRule,
    scored_at: datetime,
) -> pd.DataFrame:
    """One price row per feature row, in the column order of the prices table; timestamps are naive UTC."""
    forecast = pd.Series(forecasts, index=features.index, dtype="float64")
    rows = pd.DataFrame(
        {
            "hour_start": features["hour_start"],
            "delivery_day": features["delivery_day"],
            "forecast_eur_mwh": forecast,
            "price_ct_kwh": forecast.map(rule.price_ct_kwh),
            "model_name": champion.name,
            "model_version": champion.version,
            "mlflow_run_id": champion.run_id,
            "model_alias": CHAMPION,
            "training_data_version": champion.training_data_version,
            "scoring_feature_version": scoring_feature_version,
            "tariff_rule_version": rule.version,
            "tariff_rule_hash": rule.parameter_hash,
            "forecast_issued_at": features["forecast_issued_at"],
            "horizon_hours": features["horizon_hours"],
            "scored_at": scored_at.astimezone(UTC).replace(tzinfo=None),
        }
    )
    return rows.loc[:, list(PRICE_COLUMNS)].reset_index(drop=True)


def lineage_problems(lineages: Iterable[Lineage], run_of_version: Callable[[int], str]) -> list[str]:
    """Every stored (model version, run) pair must be what the registry reports, and every rule must exist in code."""
    problems = []
    for lineage in lineages:
        registered_run = run_of_version(lineage.model_version)
        if registered_run != lineage.mlflow_run_id:
            problems.append(
                f"model version {lineage.model_version} names run {lineage.mlflow_run_id}, "
                f"the registry says {registered_run}"
            )
        rule = RULES.get(lineage.tariff_rule_version)
        if rule is None:
            problems.append(f"tariff rule {lineage.tariff_rule_version} does not exist in code")
        elif rule.parameter_hash != lineage.tariff_rule_hash:
            problems.append(
                f"tariff rule {lineage.tariff_rule_version} has hash {rule.parameter_hash}, "
                f"a stored price says {lineage.tariff_rule_hash}"
            )
    return problems


def resolve_champion(client: Any, name: str) -> Champion:
    model_version = client.get_model_version_by_alias(name, CHAMPION)
    params = client.get_run(model_version.run_id).data.params
    return Champion(
        name=name,
        version=int(model_version.version),
        run_id=model_version.run_id,
        training_data_version=int(params["training_data_version"]),
        training_last_day=date.fromisoformat(params["training_last_day"]),
    )


def score(
    spark: Any, client: Any, *, catalog: str, schema: str, first: date | None, last: date | None, now: datetime
) -> int:
    """Scores the days from first to last (default: tomorrow) and returns the number of rows added."""
    import mlflow

    name = model_name(catalog, schema)
    champion = resolve_champion(client, name)
    first = first or tomorrow(now)
    days = days_to_score(first, last or first, champion)

    features_table = f"{catalog}.{schema}.{FEATURE_TABLE}"
    feature_version = latest_version(spark, features_table)
    features = spark.sql(
        f"SELECT * FROM {features_table} VERSION AS OF {feature_version} "
        f"WHERE delivery_day BETWEEN DATE'{days[0].isoformat()}' AND DATE'{days[-1].isoformat()}' ORDER BY hour_start"
    ).toPandas()
    require_complete_days(features, days)

    model = mlflow.pyfunc.load_model(f"models:/{name}/{champion.version}")
    rows = priced_rows(
        features,
        model.predict(feature_frame(features)),
        champion=champion,
        scoring_feature_version=feature_version,
        rule=CURRENT_RULE,
        scored_at=now,
    )

    prices_table = f"{catalog}.{schema}.{PRICES_TABLE}"
    spark.sql(package_sql("prices_table.sql", catalog, schema))
    spark.sql(package_sql("current_prices_view.sql", catalog, schema))
    before = spark.table(prices_table).count()
    spark.createDataFrame(rows, schema=SPARK_SCHEMA).createOrReplaceTempView("scored_prices")
    on = " AND ".join(f"target.{key} = source.{key}" for key in MERGE_KEYS)
    spark.sql(
        f"MERGE INTO {prices_table} AS target USING scored_prices AS source ON {on} WHEN NOT MATCHED THEN INSERT *"
    )
    added = int(spark.table(prices_table).count() - before)

    stored = spark.sql(
        f"SELECT DISTINCT model_version, mlflow_run_id, tariff_rule_version, tariff_rule_hash FROM {prices_table}"
    ).collect()
    problems = lineage_problems(
        (Lineage(int(row[0]), row[1], int(row[2]), row[3]) for row in stored),
        lambda version: str(client.get_model_version(name, str(version)).run_id),
    )
    if problems:
        raise RuntimeError("lineage check failed: " + "; ".join(problems))
    return added


def optional_day(text: str) -> date | None:
    """Job parameters cannot be left out, only left empty, so an empty day means the default."""
    return date.fromisoformat(text) if text else None


def main(argv: Sequence[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--start", type=optional_day, help="first delivery day; default tomorrow in Berlin")
    parser.add_argument("--end", type=optional_day, help="last delivery day; default the first")
    arguments = parser.parse_args(argv)

    import mlflow
    from mlflow.tracking import MlflowClient
    from pyspark.sql import SparkSession

    mlflow.set_registry_uri("databricks-uc")
    spark = SparkSession.builder.getOrCreate()
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    added = score(
        spark,
        MlflowClient(),
        catalog=arguments.catalog,
        schema=arguments.schema,
        first=arguments.start,
        last=arguments.end,
        now=now or datetime.now(UTC),
    )
    print(f"added {added} price rows; lineage check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
