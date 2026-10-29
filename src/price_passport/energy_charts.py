"""Day-ahead prices from the Energy-Charts API (Fraunhofer ISE), normalised to hourly rows.

The DE-LU day-ahead market moved from hourly to 15-minute products with delivery day 1 October 2025, so the API
returns one point per hour before that day and four after it. The tariff is hourly, so quarter-hours are averaged into
the UTC hour they start in. Berlin's offset from UTC is always a whole hour, so a UTC hour is also a local hour; a local
day still has 23 or 25 hours when the clocks change.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

SECONDS_PER_HOUR = 3600
QUARTER_HOUR_SECONDS = 900
QUARTER_HOURS_PER_HOUR = SECONDS_PER_HOUR // QUARTER_HOUR_SECONDS
EXPECTED_UNIT = "EUR / MWh"
TARIFF_TIMEZONE = ZoneInfo("Europe/Berlin")
FIRST_QUARTER_HOUR_DELIVERY = datetime(2025, 9, 30, 22, tzinfo=UTC)
FIRST_QUARTER_HOUR_DELIVERY_EPOCH = int(FIRST_QUARTER_HOUR_DELIVERY.timestamp())
EARLIEST_PLAUSIBLE_EPOCH = int(datetime(2000, 1, 1, tzinfo=UTC).timestamp())
LATEST_PLAUSIBLE_EPOCH = int(datetime(2100, 1, 1, tzinfo=UTC).timestamp())


class EnergyChartsResponseError(ValueError):
    """The response does not have the shape this parser relies on."""


@dataclass(frozen=True)
class HourlyPrice:
    hour_start: datetime
    price_eur_mwh: float
    source_points: int
    expected_points: int

    @property
    def is_complete(self) -> bool:
        return self.source_points == self.expected_points

    @property
    def local_hour_start(self) -> datetime:
        return self.hour_start.astimezone(TARIFF_TIMEZONE)


def expected_points_per_hour(hour_start: datetime) -> int:
    """How many day-ahead products the market had for this hour: one before the 15-minute switch, four after."""
    return QUARTER_HOURS_PER_HOUR if hour_start >= FIRST_QUARTER_HOUR_DELIVERY else 1


def parse_day_ahead_prices(payload: object, *, allow_empty: bool = False) -> list[HourlyPrice]:
    """Turns a `/price` response into one row per UTC hour, oldest first.

    Points without a price are skipped. An hour with some points missing is kept but reports `is_complete == False`,
    so the caller decides what an incomplete hour is worth; an hour whose points are all missing does not appear, so a
    gap stays a gap instead of becoming a zero. Anything that is not a well-formed response raises
    `EnergyChartsResponseError`, including one without a single price unless `allow_empty` is set.
    """
    if not isinstance(payload, Mapping):
        raise EnergyChartsResponseError(f"expected a JSON object, got {type(payload).__name__}")
    if payload.get("deprecated") is True:
        raise EnergyChartsResponseError("the API marks this response as deprecated")

    unit = payload.get("unit")
    if unit != EXPECTED_UNIT:
        raise EnergyChartsResponseError(f"expected unit {EXPECTED_UNIT!r}, got {unit!r}")

    timestamps = payload.get("unix_seconds")
    prices = payload.get("price")
    if not isinstance(timestamps, list) or not isinstance(prices, list):
        raise EnergyChartsResponseError("unix_seconds and price must both be lists")
    if len(timestamps) != len(prices):
        raise EnergyChartsResponseError(f"{len(timestamps)} timestamps but {len(prices)} prices")

    seen_timestamps: set[int] = set()
    prices_by_hour: dict[int, list[float]] = {}
    for timestamp, price in zip(timestamps, prices, strict=True):
        validate_timestamp(timestamp, seen_timestamps)
        seen_timestamps.add(timestamp)
        if price is None:
            continue
        hour_epoch = timestamp - timestamp % SECONDS_PER_HOUR
        prices_by_hour.setdefault(hour_epoch, []).append(finite_price(price, timestamp))

    if not prices_by_hour and not allow_empty:
        raise EnergyChartsResponseError("the response contains no prices")

    hourly = []
    for hour_epoch, hour_prices in sorted(prices_by_hour.items()):
        hour_start = datetime.fromtimestamp(hour_epoch, tz=UTC)
        expected_points = expected_points_per_hour(hour_start)
        if len(hour_prices) > expected_points:
            raise EnergyChartsResponseError(
                f"{len(hour_prices)} prices for {hour_start.isoformat()}, the market had {expected_points}"
            )
        hourly.append(
            HourlyPrice(
                hour_start=hour_start,
                price_eur_mwh=hour_mean(hour_prices, hour_start),
                source_points=len(hour_prices),
                expected_points=expected_points,
            )
        )
    return hourly


def validate_timestamp(timestamp: object, seen_timestamps: set[int]) -> None:
    if type(timestamp) is not int:
        raise EnergyChartsResponseError(f"timestamp {timestamp!r} is not an integer")
    if not EARLIEST_PLAUSIBLE_EPOCH <= timestamp < LATEST_PLAUSIBLE_EPOCH:
        raise EnergyChartsResponseError(f"timestamp {timestamp} is outside 2000 to 2100")
    product_seconds = QUARTER_HOUR_SECONDS if timestamp >= FIRST_QUARTER_HOUR_DELIVERY_EPOCH else SECONDS_PER_HOUR
    if timestamp % product_seconds:
        raise EnergyChartsResponseError(f"timestamp {timestamp} does not start a market product")
    if timestamp in seen_timestamps:
        raise EnergyChartsResponseError(f"timestamp {timestamp} appears twice")


def finite_price(price: object, timestamp: int) -> float:
    if isinstance(price, bool) or not isinstance(price, int | float):
        raise EnergyChartsResponseError(f"price {price!r} at {timestamp} is not a number")
    try:
        value = float(price)
    except OverflowError as error:
        raise EnergyChartsResponseError(f"price at {timestamp} is too large for a float") from error
    if not math.isfinite(value):
        raise EnergyChartsResponseError(f"price {price!r} at {timestamp} is not finite")
    return value


def hour_mean(hour_prices: list[float], hour_start: datetime) -> float:
    try:
        mean = math.fsum(hour_prices) / len(hour_prices)
    except OverflowError as error:
        raise EnergyChartsResponseError(f"prices for {hour_start.isoformat()} overflow when averaged") from error
    if not math.isfinite(mean):
        raise EnergyChartsResponseError(f"prices for {hour_start.isoformat()} average to {mean}")
    return mean
