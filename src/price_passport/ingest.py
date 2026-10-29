"""Fetches day-ahead prices and weather forecasts and stores them unchanged in a Unity Catalog Volume.

Runs as a Databricks job on serverless compute, which can reach both APIs (decisions section 3). Every API call
becomes one file named after the delivery days it covers: a daily run writes one file per day, a backfill one file per
calendar month, because Energy-Charts rate-limits single-day calls to about one every 25 seconds. Files are rewritten
on every run, so a repeated run changes nothing, and silver keeps the most recently written value of every hour.
Responses are validated before they are written: a file in the Volume is always a parseable, complete response.
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from price_passport.energy_charts import TARIFF_TIMEZONE, EnergyChartsResponseError, parse_day_ahead_prices

ENERGY_CHARTS_PRICE_URL = "https://api.energy-charts.info/price"
OPEN_METEO_PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
BIDDING_ZONE = "DE-LU"
WEATHER_VARIABLES = ("temperature_2m", "wind_speed_100m", "shortwave_radiation", "cloud_cover")
FORECAST_LEAD_SUFFIX = "_previous_day2"
MAX_ATTEMPTS = 5
DEFAULT_RETRY_AFTER_SECONDS = 30
LONGEST_RETRY_AFTER_SECONDS = 120
REQUEST_TIMEOUT_SECONDS = 60
ENERGY_CHARTS_PAUSE_SECONDS = 2.0
OPEN_METEO_PAUSE_SECONDS = 0.2
DEFAULT_REQUIRE_TOMORROW_FROM_HOUR = 15
DAYS_PAST_ANY_MONTH_START = 32


@dataclass(frozen=True)
class WeatherSite:
    name: str
    latitude: float
    longitude: float


WEATHER_SITES = (
    WeatherSite("hamburg", 53.55, 9.99),
    WeatherSite("berlin", 52.52, 13.41),
    WeatherSite("cologne", 50.94, 6.96),
    WeatherSite("frankfurt", 50.11, 8.68),
    WeatherSite("munich", 48.14, 11.58),
)


@dataclass(frozen=True)
class DayRange:
    first: date
    last: date

    def days(self) -> list[date]:
        return [self.first + timedelta(days=offset) for offset in range((self.last - self.first).days + 1)]

    @property
    def file_name(self) -> str:
        return f"range={self.first.isoformat()}_{self.last.isoformat()}.json"


Fetch = Callable[[str], bytes]
Sleep = Callable[[float], None]


class IngestError(RuntimeError):
    """A source could not be fetched, or returned something that must not be stored."""


class SourceNotFoundError(IngestError):
    """The source answered 404. Energy-Charts does this for a delivery day whose auction is not published yet."""


def retry_after_seconds(header: str | None) -> float:
    """Reads a `Retry-After` header given in seconds; an HTTP date or garbage falls back to a default wait."""
    try:
        seconds = float(header) if header is not None else DEFAULT_RETRY_AFTER_SECONDS
    except ValueError:
        seconds = DEFAULT_RETRY_AFTER_SECONDS
    return min(max(seconds, 0.0), LONGEST_RETRY_AFTER_SECONDS)


def http_get(url: str, *, sleep: Sleep = time.sleep, open_url: Callable[..., Any] = urllib.request.urlopen) -> bytes:
    """GETs a URL, waiting as told on HTTP 429 (Energy-Charts answers bursts with it), failing on anything else."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with open_url(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body: bytes = response.read()
                return body
        except urllib.error.HTTPError as error:
            if error.code == HTTPStatus.NOT_FOUND:
                raise SourceNotFoundError(f"GET {url} found nothing (HTTP 404)") from error
            if error.code != HTTPStatus.TOO_MANY_REQUESTS or attempt == MAX_ATTEMPTS:
                raise IngestError(f"GET {url} failed with HTTP {error.code} after {attempt} attempts") from error
            sleep(retry_after_seconds(error.headers.get("Retry-After")))
        except urllib.error.URLError as error:
            raise IngestError(f"GET {url} failed: {error.reason}") from error
    raise IngestError(f"GET {url} gave up after {MAX_ATTEMPTS} attempts")


def energy_charts_url(days: DayRange) -> str:
    """Energy-Charts treats start and end as local delivery days, so one day returns 23 to 25 hours of prices."""
    query = urlencode({"bzn": BIDDING_ZONE, "start": days.first.isoformat(), "end": days.last.isoformat()})
    return f"{ENERGY_CHARTS_PRICE_URL}?{query}"


def open_meteo_url(site: WeatherSite, days: DayRange) -> str:
    """Asks for the forecast each hour had two days before it, which is known by the 10:00 cutoff (section 7)."""
    query = urlencode(
        {
            "latitude": site.latitude,
            "longitude": site.longitude,
            "start_date": days.first.isoformat(),
            "end_date": days.last.isoformat(),
            "hourly": ",".join(f"{variable}{FORECAST_LEAD_SUFFIX}" for variable in WEATHER_VARIABLES),
            "timezone": "UTC",
        }
    )
    return f"{OPEN_METEO_PREVIOUS_RUNS_URL}?{query}"


def price_file(volume_root: Path, days: DayRange) -> Path:
    return volume_root / "energy_charts" / "price" / f"bzn={BIDDING_ZONE}" / days.file_name


def weather_file(volume_root: Path, site: WeatherSite, days: DayRange) -> Path:
    return volume_root / "open_meteo" / "previous_runs_day2" / f"site={site.name}" / days.file_name


def delivery_days_with_prices(body: bytes, url: str) -> set[date]:
    try:
        hourly = parse_day_ahead_prices(json.loads(body), allow_empty=True)
    except (ValueError, EnergyChartsResponseError) as error:
        raise IngestError(f"{url} returned an unusable response: {error}") from error
    return {row.local_hour_start.date() for row in hourly}


def validate_weather(body: bytes, url: str, days: DayRange) -> None:
    try:
        hourly = json.loads(body)["hourly"]
        series = [hourly["time"], *(hourly[f"{variable}{FORECAST_LEAD_SUFFIX}"] for variable in WEATHER_VARIABLES)]
        covered = {date.fromisoformat(timestamp[:10]) for timestamp in hourly["time"]}
    except (ValueError, KeyError, TypeError) as error:
        raise IngestError(f"{url} did not return the expected hourly weather") from error
    if len({len(values) for values in series}) != 1:
        raise IngestError(f"{url} returned hourly series of different lengths")
    if missing := set(days.days()) - covered:
        raise IngestError(f"{url} has no weather for {', '.join(sorted(day.isoformat() for day in missing))}")


def write_file(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


@dataclass(frozen=True)
class IngestResult:
    written: tuple[Path, ...]
    not_yet_published: tuple[DayRange, ...]


def ingest(
    volume_root: Path,
    price_ranges: Sequence[DayRange],
    weather_ranges: Sequence[DayRange],
    *,
    required_price_days: frozenset[date],
    fetch: Fetch | None = None,
    sleep: Sleep | None = None,
) -> IngestResult:
    """Fetches, validates and writes every requested range.

    A price range that comes back without prices, whether the API answers 404 or an empty list, is reported as not yet
    published and nothing is written for it, unless it holds a required day: then the run fails. A range that has
    prices must have them for every required day it covers, so a partial response never passes as complete.
    """
    fetch = fetch or http_get
    sleep = sleep or time.sleep
    written: list[Path] = []
    not_yet_published: list[DayRange] = []

    for days in price_ranges:
        url = energy_charts_url(days)
        try:
            body = fetch(url)
        except SourceNotFoundError:
            body = b""
        covered = delivery_days_with_prices(body, url) if body else set()
        required_here = {day for day in days.days() if day in required_price_days}
        if missing := sorted(required_here - covered):
            raise IngestError(f"no prices published for {', '.join(day.isoformat() for day in missing)}")
        if covered:
            path = price_file(volume_root, days)
            write_file(path, body)
            written.append(path)
        else:
            not_yet_published.append(days)
        sleep(ENERGY_CHARTS_PAUSE_SECONDS)

    for days in weather_ranges:
        for site in WEATHER_SITES:
            url = open_meteo_url(site, days)
            body = fetch(url)
            validate_weather(body, url, days)
            path = weather_file(volume_root, site, days)
            write_file(path, body)
            written.append(path)
            sleep(OPEN_METEO_PAUSE_SECONDS)

    return IngestResult(written=tuple(written), not_yet_published=tuple(not_yet_published))


def month_ranges(first: date, last: date) -> list[DayRange]:
    """Splits a backfill into calendar months, so each source is asked once per month."""
    if last < first:
        raise IngestError(f"{last.isoformat()} is before {first.isoformat()}")
    ranges = []
    start = first
    while start <= last:
        next_month = (start.replace(day=1) + timedelta(days=DAYS_PAST_ANY_MONTH_START)).replace(day=1)
        end = min(next_month - timedelta(days=1), last)
        ranges.append(DayRange(start, end))
        start = end + timedelta(days=1)
    return ranges


def plan_ranges(
    now: datetime,
    *,
    start: date | None,
    end: date | None,
    require_tomorrow_from_hour: int,
) -> tuple[list[DayRange], list[DayRange], frozenset[date]]:
    """Decides what a run fetches: monthly ranges for a backfill, otherwise yesterday, today and tomorrow, one by one.

    Every price day up to today is required. Tomorrow is required once the local hour has reached
    `require_tomorrow_from_hour`, which makes the afternoon run strict and the midday run not. Weather covers the same
    days as prices, tomorrow included, because the two-day-old forecast for tomorrow already exists.
    """
    local_now = now.astimezone(TARIFF_TIMEZONE)
    today = local_now.date()
    tomorrow = today + timedelta(days=1)
    if start is not None or end is not None:
        ranges = month_ranges(start or today, end or today)
    else:
        ranges = [DayRange(day, day) for day in (today - timedelta(days=1), today, tomorrow)]
    all_days = [day for days in ranges for day in days.days()]
    required = {day for day in all_days if day <= today}
    if tomorrow in all_days and local_now.hour >= require_tomorrow_from_hour:
        required.add(tomorrow)
    return ranges, ranges, frozenset(required)


def main(argv: Sequence[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume-root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, help="first delivery day of a backfill")
    parser.add_argument("--end", type=date.fromisoformat, help="last delivery day of a backfill")
    parser.add_argument("--require-tomorrow-from-hour", type=int, default=DEFAULT_REQUIRE_TOMORROW_FROM_HOUR)
    arguments = parser.parse_args(argv)

    price_ranges, weather_ranges, required = plan_ranges(
        now or datetime.now(TARIFF_TIMEZONE),
        start=arguments.start,
        end=arguments.end,
        require_tomorrow_from_hour=arguments.require_tomorrow_from_hour,
    )
    result = ingest(arguments.volume_root, price_ranges, weather_ranges, required_price_days=required)

    print(f"wrote {len(result.written)} files under {arguments.volume_root}")
    for days in result.not_yet_published:
        print(f"not published yet: {days.first.isoformat()} to {days.last.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
