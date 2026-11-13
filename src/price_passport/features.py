"""Builds the gold feature table from silver and reports the Delta version it wrote (decisions sections 7 and 9).

Runs as a Databricks job task on serverless compute, where a Spark session exists. The feature definition is the SQL
file shipped inside this package, so a feature change is a code change with a version, not an edit in a notebook.
"""

import argparse
import re
from collections.abc import Sequence
from importlib.resources import files
from typing import Any

FEATURE_SQL = "gold_features.sql"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def require_identifiers(*names: str) -> None:
    """Catalog and schema names go into SQL text, so only plain identifiers are accepted."""
    for name in names:
        if not IDENTIFIER.match(name):
            raise ValueError(f"{name!r} is not a plain SQL identifier")


def feature_sql(catalog: str, schema: str) -> str:
    """The feature statement for one catalog and schema; both must be plain identifiers, as they go into the SQL."""
    require_identifiers(catalog, schema)
    template = files("price_passport").joinpath("sql", FEATURE_SQL).read_text(encoding="utf-8")
    return template.format(catalog=catalog, schema=schema)


def latest_version(spark: Any, table: str) -> int:
    history = spark.sql(f"DESCRIBE HISTORY {table} LIMIT 1").collect()
    return int(history[0]["version"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    arguments = parser.parse_args(argv)

    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    spark.sql(feature_sql(arguments.catalog, arguments.schema))
    table = f"{arguments.catalog}.{arguments.schema}.gold_features"
    rows = spark.table(table).count()
    print(f"{table} version {latest_version(spark, table)} with {rows} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
