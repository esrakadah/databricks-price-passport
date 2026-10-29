"""Day-ahead prices from the Energy-Charts API (Fraunhofer ISE), normalised to hourly rows.

The DE-LU day-ahead market moved from hourly to 15-minute products on 1 October 2025, so the API returns 24 points
per day before that date and 96 after it. Everything downstream works in hours, so quarter-hours are averaged into
the hour they start in.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

SECONDS_PER_HOUR = 3600
EXPECTED_UNIT = "EUR / MWh"


class EnergyChartsResponseError(ValueError):
    """The response does not have the shape this parser relies on."""


@dataclass(frozen=True)
class HourlyPrice:
    hour_start: datetime
    price_eur_mwh: float
    source_points: int


def parse_day_ahead_prices(payload: Mapping[str, object]) -> list[HourlyPrice]:
    """Turns a `/price` response into one row per UTC hour, oldest first.

    Points without a price are skipped; an hour whose points are all missing does not appear at all, so a gap stays
    visible as a gap instead of becoming a zero.
    """
    unit = payload.get("unit")
    if unit != EXPECTED_UNIT:
        raise EnergyChartsResponseError(f"expected unit {EXPECTED_UNIT!r}, got {unit!r}")

    timestamps = payload.get("unix_seconds")
    prices = payload.get("price")
    if not isinstance(timestamps, list) or not isinstance(prices, list):
        raise EnergyChartsResponseError("unix_seconds and price must both be lists")
    if len(timestamps) != len(prices):
        raise EnergyChartsResponseError(f"{len(timestamps)} timestamps but {len(prices)} prices")

    prices_by_hour: dict[int, list[float]] = {}
    for timestamp, price in zip(timestamps, prices, strict=True):
        if price is None:
            continue
        hour_start = timestamp - timestamp % SECONDS_PER_HOUR
        prices_by_hour.setdefault(hour_start, []).append(float(price))

    return [
        HourlyPrice(
            hour_start=datetime.fromtimestamp(hour_start, tz=UTC),
            price_eur_mwh=sum(hour_prices) / len(hour_prices),
            source_points=len(hour_prices),
        )
        for hour_start, hour_prices in sorted(prices_by_hour.items())
    ]
