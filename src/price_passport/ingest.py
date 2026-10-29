"""Fetches day-ahead prices and archived weather forecasts and stores them unchanged in a Unity Catalog Volume.

Runs as a Databricks job on serverless compute, which can reach both APIs (decisions section 3). There is one file per
source, site and delivery day, rewritten on every run, so a repeated run changes nothing and a missed run is healed by
the next one. Responses are validated before they are written: a file in the Volume is always a parseable response.
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
OPEN_METEO_HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
BIDDING_ZONE = "DE-LU"
WEATHER_VARIABLES = ("temperature_2m", "wind_speed_100m", "shortwave_radiation", "cloud_cover")
MAX_ATTEMPTS = 5
DEFAULT_RETRY_AFTER_SECONDS = 30
LONGEST_RETRY_AFTER_SECONDS = 120
REQUEST_TIMEOUT_SECONDS = 30
ENERGY_CHARTS_PAUSE_SECONDS = 1.0
OPEN_METEO_PAUSE_SECONDS = 0.2
DEFAULT_REQUIRE_TOMORROW_FROM_HOUR = 15


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

Fetch = Callable[[str], bytes]
Sleep = Callable[[float], None]


class IngestError(RuntimeError):
    """A source could not be fetched, or returned something that must not be stored."""


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
            if error.code != HTTPStatus.TOO_MANY_REQUESTS or attempt == MAX_ATTEMPTS:
                raise IngestError(f"GET {url} failed with HTTP {error.code} after {attempt} attempts") from error
            sleep(retry_after_seconds(error.headers.get("Retry-After")))
        except urllib.error.URLError as error:
            raise IngestError(f"GET {url} failed: {error.reason}") from error
    raise IngestError(f"GET {url} gave up after {MAX_ATTEMPTS} attempts")


def energy_charts_url(delivery_day: date) -> str:
    """Energy-Charts treats start and end as local delivery days, so one day returns 23 to 25 hours of prices."""
    query = urlencode({"bzn": BIDDING_ZONE, "start": delivery_day.isoformat(), "end": delivery_day.isoformat()})
    return f"{ENERGY_CHARTS_PRICE_URL}?{query}"


def open_meteo_url(site: WeatherSite, utc_day: date) -> str:
    query = urlencode(
        {
            "latitude": site.latitude,
            "longitude": site.longitude,
            "start_date": utc_day.isoformat(),
            "end_date": utc_day.isoformat(),
            "hourly": ",".join(WEATHER_VARIABLES),
            "timezone": "UTC",
        }
    )
    return f"{OPEN_METEO_HISTORICAL_FORECAST_URL}?{query}"


def price_file(volume_root: Path, delivery_day: date) -> Path:
    return volume_root / "energy_charts" / "price" / f"bzn={BIDDING_ZONE}" / f"dt={delivery_day.isoformat()}.json"


def weather_file(volume_root: Path, site: WeatherSite, utc_day: date) -> Path:
    return volume_root / "open_meteo" / "historical_forecast" / f"site={site.name}" / f"dt={utc_day.isoformat()}.json"


def validate_weather(body: bytes, url: str) -> None:
    try:
        hourly = json.loads(body)["hourly"]
        lengths = {len(hourly[variable]) for variable in ("time", *WEATHER_VARIABLES)}
    except (ValueError, KeyError, TypeError) as error:
        raise IngestError(f"{url} did not return the expected hourly weather") from error
    if len(lengths) != 1 or not lengths.pop():
        raise IngestError(f"{url} returned hourly series of different or zero length")


def write_file(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


@dataclass(frozen=True)
class IngestResult:
    written: tuple[Path, ...]
    not_yet_published: tuple[date, ...]


def ingest(
    volume_root: Path,
    price_days: Sequence[date],
    weather_days: Sequence[date],
    *,
    required_price_days: frozenset[date],
    fetch: Fetch | None = None,
    sleep: Sleep | None = None,
) -> IngestResult:
    """Fetches, validates and writes every requested day.

    A price day without prices is an error if it is in `required_price_days`; otherwise it is reported as not yet
    published and nothing is written for it, so an earlier, complete file is never replaced by an empty one.
    """
    fetch = fetch or http_get
    sleep = sleep or time.sleep
    written: list[Path] = []
    not_yet_published: list[date] = []

    for delivery_day in price_days:
        url = energy_charts_url(delivery_day)
        body = fetch(url)
        try:
            hourly = parse_day_ahead_prices(json.loads(body), allow_empty=True)
        except (ValueError, EnergyChartsResponseError) as error:
            raise IngestError(f"{url} returned an unusable response: {error}") from error
        if not hourly:
            if delivery_day in required_price_days:
                raise IngestError(f"no prices published for {delivery_day.isoformat()}")
            not_yet_published.append(delivery_day)
        else:
            path = price_file(volume_root, delivery_day)
            write_file(path, body)
            written.append(path)
        sleep(ENERGY_CHARTS_PAUSE_SECONDS)

    for utc_day in weather_days:
        for site in WEATHER_SITES:
            url = open_meteo_url(site, utc_day)
            body = fetch(url)
            validate_weather(body, url)
            path = weather_file(volume_root, site, utc_day)
            write_file(path, body)
            written.append(path)
            sleep(OPEN_METEO_PAUSE_SECONDS)

    return IngestResult(written=tuple(written), not_yet_published=tuple(not_yet_published))


def days_between(first: date, last: date) -> list[date]:
    if last < first:
        raise IngestError(f"{last.isoformat()} is before {first.isoformat()}")
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def plan_days(
    now: datetime,
    *,
    start: date | None,
    end: date | None,
    require_tomorrow_from_hour: int,
) -> tuple[list[date], list[date], frozenset[date]]:
    """Decides which days a run fetches: a backfill range if given, otherwise yesterday, today and tomorrow.

    Weather comes from archived forecasts, so it is fetched up to today only. Tomorrow's prices are required once the
    local hour has reached `require_tomorrow_from_hour`, which makes the afternoon run strict and the midday run not.
    """
    today = now.astimezone(TARIFF_TIMEZONE).date()
    tomorrow = today + timedelta(days=1)
    if start is not None or end is not None:
        price_days = days_between(start or today, end or today)
        required = frozenset(day for day in price_days if day <= today)
    else:
        price_days = days_between(today - timedelta(days=1), tomorrow)
        required = frozenset({today - timedelta(days=1), today})
        if now.astimezone(TARIFF_TIMEZONE).hour >= require_tomorrow_from_hour:
            required |= {tomorrow}
    weather_days = [day for day in price_days if day <= today]
    return price_days, weather_days, required


def main(argv: Sequence[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume-root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, help="first delivery day of a backfill")
    parser.add_argument("--end", type=date.fromisoformat, help="last delivery day of a backfill")
    parser.add_argument("--require-tomorrow-from-hour", type=int, default=DEFAULT_REQUIRE_TOMORROW_FROM_HOUR)
    arguments = parser.parse_args(argv)

    price_days, weather_days, required = plan_days(
        now or datetime.now(TARIFF_TIMEZONE),
        start=arguments.start,
        end=arguments.end,
        require_tomorrow_from_hour=arguments.require_tomorrow_from_hour,
    )
    result = ingest(
        arguments.volume_root,
        price_days,
        weather_days,
        required_price_days=required,
    )

    print(f"wrote {len(result.written)} files under {arguments.volume_root}")
    for delivery_day in result.not_yet_published:
        print(f"not published yet: {delivery_day.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
