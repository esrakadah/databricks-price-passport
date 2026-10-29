import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from price_passport.energy_charts import EnergyChartsResponseError, parse_day_ahead_prices

FIXTURES = Path(__file__).parent / "fixtures"
HOURS_PER_DAY = 24
QUARTER_HOURS_PER_HOUR = 4


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_quarter_hourly_day_becomes_24_hourly_means():
    payload = load_fixture("energy_charts_price_quarter_hourly_2026-10-27.json")

    hourly = parse_day_ahead_prices(payload)

    assert len(hourly) == HOURS_PER_DAY
    assert all(row.source_points == QUARTER_HOURS_PER_HOUR for row in hourly)
    assert hourly[0].hour_start == datetime(2026, 10, 26, 23, tzinfo=UTC)
    first_hour_quarters = payload["price"][:QUARTER_HOURS_PER_HOUR]
    assert hourly[0].price_eur_mwh == pytest.approx(sum(first_hour_quarters) / QUARTER_HOURS_PER_HOUR)


def test_hourly_day_from_before_the_15_minute_switch_passes_through():
    payload = load_fixture("energy_charts_price_hourly_2025-09-29.json")

    hourly = parse_day_ahead_prices(payload)

    assert len(hourly) == HOURS_PER_DAY
    assert all(row.source_points == 1 for row in hourly)
    assert hourly[0].hour_start == datetime(2025, 9, 28, 22, tzinfo=UTC)
    assert hourly[0].price_eur_mwh == payload["price"][0]


def test_missing_prices_leave_a_gap_instead_of_a_zero():
    first_hour = 1793055600
    payload = {
        "unit": "EUR / MWh",
        "unix_seconds": [first_hour, first_hour + 900, first_hour + 3600, first_hour + 4500],
        "price": [100.0, None, None, None],
    }

    hourly = parse_day_ahead_prices(payload)

    assert [(row.price_eur_mwh, row.source_points) for row in hourly] == [(100.0, 1)]


def test_rows_come_out_oldest_first():
    first_hour = 1793055600
    payload = {"unit": "EUR / MWh", "unix_seconds": [first_hour + 3600, first_hour], "price": [2.0, 1.0]}

    hourly = parse_day_ahead_prices(payload)

    assert [row.price_eur_mwh for row in hourly] == [1.0, 2.0]


@pytest.mark.parametrize(
    "payload",
    [
        {"unit": "EUR / kWh", "unix_seconds": [], "price": []},
        {"unit": "EUR / MWh", "unix_seconds": [1, 2], "price": [1.0]},
        {"unit": "EUR / MWh", "unix_seconds": None, "price": []},
    ],
    ids=["wrong unit", "length mismatch", "missing list"],
)
def test_unexpected_shapes_fail_loudly(payload):
    with pytest.raises(EnergyChartsResponseError):
        parse_day_ahead_prices(payload)
