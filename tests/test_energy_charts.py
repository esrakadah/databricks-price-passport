import json
import statistics
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest

import price_passport
from price_passport.energy_charts import (
    EXPECTED_UNIT,
    FIRST_QUARTER_HOUR_DELIVERY,
    QUARTER_HOUR_SECONDS,
    QUARTER_HOURS_PER_HOUR,
    SECONDS_PER_HOUR,
    EnergyChartsResponseError,
    parse_day_ahead_prices,
)

FIXTURES = Path(__file__).parent / "fixtures"
HOURS_PER_ORDINARY_DAY = 24
HOURS_ON_SPRING_FORWARD_DAY = 23
HOURS_ON_FALL_BACK_DAY = 25
QUARTER_HOUR_ERA_HOUR = 1793055600
HOURLY_ERA_HOUR = 1759096800
ONE_HOUR = timedelta(hours=1)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def response(timestamps: list, prices: list, **extra: object) -> dict:
    return {"unit": EXPECTED_UNIT, "unix_seconds": timestamps, "price": prices, **extra}


def quarter_hours(hour: int) -> list[int]:
    return [hour + offset * QUARTER_HOUR_SECONDS for offset in range(QUARTER_HOURS_PER_HOUR)]


def assert_consecutive_hours(hourly: list) -> None:
    starts = [row.hour_start for row in hourly]
    assert all(later - earlier == ONE_HOUR for earlier, later in pairwise(starts))


def test_every_hour_of_a_quarter_hourly_day_is_the_mean_of_its_four_quarters():
    payload = load_fixture("energy_charts_price_quarter_hourly_2026-10-27.json")
    expected_means = [
        statistics.fmean(payload["price"][start : start + QUARTER_HOURS_PER_HOUR])
        for start in range(0, len(payload["price"]), QUARTER_HOURS_PER_HOUR)
    ]

    hourly = parse_day_ahead_prices(payload)

    assert [row.price_eur_mwh for row in hourly] == pytest.approx(expected_means)
    assert len(hourly) == HOURS_PER_ORDINARY_DAY
    assert all(row.is_complete and row.expected_points == QUARTER_HOURS_PER_HOUR for row in hourly)
    assert hourly[0].hour_start == datetime(2026, 10, 26, 23, tzinfo=UTC)
    assert hourly[0].local_hour_start.hour == 0
    assert_consecutive_hours(hourly)


def test_hourly_day_from_before_the_15_minute_switch_passes_through():
    payload = load_fixture("energy_charts_price_hourly_2025-09-29.json")

    hourly = parse_day_ahead_prices(payload)

    assert [row.price_eur_mwh for row in hourly] == payload["price"]
    assert all(row.is_complete and row.expected_points == 1 for row in hourly)
    assert hourly[0].hour_start == datetime(2025, 9, 28, 22, tzinfo=UTC)
    assert_consecutive_hours(hourly)


@pytest.mark.parametrize(
    ("fixture", "expected_hours"),
    [
        ("energy_charts_price_spring_forward_2026-03-29.json", HOURS_ON_SPRING_FORWARD_DAY),
        ("energy_charts_price_fall_back_2026-10-25.json", HOURS_ON_FALL_BACK_DAY),
    ],
    ids=["spring forward", "fall back"],
)
def test_clock_change_days_have_23_or_25_complete_hours(fixture, expected_hours):
    hourly = parse_day_ahead_prices(load_fixture(fixture))

    assert len(hourly) == expected_hours
    assert all(row.is_complete for row in hourly)
    assert hourly[0].local_hour_start.hour == 0
    assert_consecutive_hours(hourly)


def test_fall_back_day_shows_the_repeated_local_hour_twice():
    hourly = parse_day_ahead_prices(load_fixture("energy_charts_price_fall_back_2026-10-25.json"))

    local_hours = [row.local_hour_start.hour for row in hourly]

    assert local_hours.count(2) == 2


def test_spring_forward_day_skips_the_missing_local_hour():
    hourly = parse_day_ahead_prices(load_fixture("energy_charts_price_spring_forward_2026-03-29.json"))

    local_hours = [row.local_hour_start.hour for row in hourly]

    assert 2 not in local_hours


def test_negative_prices_stay_negative():
    payload = load_fixture("energy_charts_price_negative_2026-05-24.json")
    negative_hours_by_hand = sum(
        statistics.fmean(payload["price"][start : start + QUARTER_HOURS_PER_HOUR]) < 0
        for start in range(0, len(payload["price"]), QUARTER_HOURS_PER_HOUR)
    )

    hourly = parse_day_ahead_prices(payload)

    assert negative_hours_by_hand > 0
    assert sum(row.price_eur_mwh < 0 for row in hourly) == negative_hours_by_hand


def test_an_hour_without_any_price_is_a_gap_not_a_zero():
    next_hour = QUARTER_HOUR_ERA_HOUR + SECONDS_PER_HOUR
    payload = response(
        quarter_hours(QUARTER_HOUR_ERA_HOUR) + quarter_hours(next_hour),
        [10.0, 20.0, 30.0, 40.0, None, None, None, None],
    )

    hourly = parse_day_ahead_prices(payload)

    assert [row.hour_start.timestamp() for row in hourly] == [QUARTER_HOUR_ERA_HOUR]


def test_an_hour_with_missing_quarters_is_kept_but_marked_incomplete():
    payload = response(quarter_hours(QUARTER_HOUR_ERA_HOUR), [10.0, None, 10.0, 100.0])

    (hour,) = parse_day_ahead_prices(payload)

    assert hour.price_eur_mwh == pytest.approx(40.0)
    assert (hour.source_points, hour.expected_points, hour.is_complete) == (3, QUARTER_HOURS_PER_HOUR, False)


def test_unordered_points_are_bucketed_and_sorted():
    first, second = quarter_hours(QUARTER_HOUR_ERA_HOUR), quarter_hours(QUARTER_HOUR_ERA_HOUR + SECONDS_PER_HOUR)
    timestamps = [second[3], first[0], second[0], first[3], second[1], first[1], second[2], first[2]]
    prices = [2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0]

    hourly = parse_day_ahead_prices(response(timestamps, prices))

    assert [row.price_eur_mwh for row in hourly] == [1.0, 2.0]
    assert all(row.is_complete for row in hourly)


def test_the_first_quarter_hour_delivery_hour_expects_four_points():
    switch = int(FIRST_QUARTER_HOUR_DELIVERY.timestamp())
    payload = response([switch - SECONDS_PER_HOUR, *quarter_hours(switch)], [1.0, 2.0, 2.0, 2.0, 2.0])

    before, after = parse_day_ahead_prices(payload)

    assert (before.expected_points, after.expected_points) == (1, QUARTER_HOURS_PER_HOUR)
    assert before.is_complete
    assert after.is_complete


@pytest.mark.parametrize(
    "payload",
    [response([], []), response(quarter_hours(QUARTER_HOUR_ERA_HOUR), [None] * QUARTER_HOURS_PER_HOUR)],
    ids=["no points", "points without prices"],
)
def test_a_response_without_prices_is_allowed_only_when_asked_for(payload):
    assert parse_day_ahead_prices(payload, allow_empty=True) == []
    with pytest.raises(EnergyChartsResponseError, match="no prices"):
        parse_day_ahead_prices(payload)


def test_the_package_reports_its_version():
    assert price_passport.__version__


HUGE_INTEGER_PRICE = 10**400
NEAR_FLOAT_LIMIT_PRICE = 1.7e308


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        pytest.param([], "expected a JSON object", id="not an object"),
        pytest.param(response([QUARTER_HOUR_ERA_HOUR], [1.0], deprecated=True), "deprecated", id="deprecated"),
        pytest.param(
            {"unit": "EUR / kWh", "unix_seconds": [QUARTER_HOUR_ERA_HOUR], "price": [1.0]}, "unit", id="wrong unit"
        ),
        pytest.param(
            response([QUARTER_HOUR_ERA_HOUR, QUARTER_HOUR_ERA_HOUR + QUARTER_HOUR_SECONDS], [1.0]),
            "timestamps but",
            id="length mismatch",
        ),
        pytest.param(response(None, []), "must both be lists", id="missing list"),
        pytest.param(response([QUARTER_HOUR_ERA_HOUR], [float("nan")]), "not finite", id="NaN price"),
        pytest.param(response([QUARTER_HOUR_ERA_HOUR], [float("inf")]), "not finite", id="infinite price"),
        pytest.param(response([QUARTER_HOUR_ERA_HOUR], [True]), "not a number", id="boolean price"),
        pytest.param(response([QUARTER_HOUR_ERA_HOUR], ["12.5"]), "not a number", id="text price"),
        pytest.param(response([QUARTER_HOUR_ERA_HOUR], [HUGE_INTEGER_PRICE]), "too large", id="huge integer price"),
        pytest.param(
            response(quarter_hours(QUARTER_HOUR_ERA_HOUR), [NEAR_FLOAT_LIMIT_PRICE] * QUARTER_HOURS_PER_HOUR),
            "overflow",
            id="prices that overflow when averaged",
        ),
        pytest.param(response([str(QUARTER_HOUR_ERA_HOUR)], [1.0]), "not an integer", id="text timestamp"),
        pytest.param(response([float(QUARTER_HOUR_ERA_HOUR)], [1.0]), "not an integer", id="float timestamp"),
        pytest.param(response([True], [1.0]), "not an integer", id="boolean timestamp"),
        pytest.param(
            response([QUARTER_HOUR_SECONDS * 10**17], [1.0]), "outside 2000 to 2100", id="far-future timestamp"
        ),
        pytest.param(response([0], [1.0]), "outside 2000 to 2100", id="epoch zero"),
        pytest.param(
            response([QUARTER_HOUR_ERA_HOUR, QUARTER_HOUR_ERA_HOUR], [1.0, 3.0]),
            "appears twice",
            id="duplicate timestamp",
        ),
        pytest.param(
            response([QUARTER_HOUR_ERA_HOUR + 1], [1.0]), "does not start a market product", id="off the quarter-hour"
        ),
        pytest.param(
            response([HOURLY_ERA_HOUR + QUARTER_HOUR_SECONDS], [1.0]),
            "does not start a market product",
            id="quarter-hour point in the hourly era",
        ),
    ],
)
def test_malformed_responses_raise_the_parser_error(payload, message):
    with pytest.raises(EnergyChartsResponseError, match=message):
        parse_day_ahead_prices(payload)
