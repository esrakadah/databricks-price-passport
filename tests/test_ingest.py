import io
import json
import urllib.error
from datetime import UTC, date, datetime, time, timedelta
from email.message import Message
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from price_passport.energy_charts import EXPECTED_UNIT, QUARTER_HOUR_SECONDS, TARIFF_TIMEZONE
from price_passport.ingest import (
    DEFAULT_RETRY_AFTER_SECONDS,
    FORECAST_LEAD_SUFFIX,
    LONGEST_RETRY_AFTER_SECONDS,
    MAX_ATTEMPTS,
    WEATHER_SITES,
    WEATHER_VARIABLES,
    DayRange,
    IngestError,
    SourceNotFoundError,
    energy_charts_url,
    http_get,
    ingest,
    main,
    month_ranges,
    open_meteo_url,
    plan_ranges,
    price_file,
    retry_after_seconds,
    weather_file,
)

TODAY = date(2026, 10, 27)
YESTERDAY = date(2026, 10, 26)
TOMORROW = date(2026, 10, 28)
MIDDAY_RUN = datetime(2026, 10, 27, 13, 40, tzinfo=TARIFF_TIMEZONE)
AFTERNOON_RUN = datetime(2026, 10, 27, 16, 40, tzinfo=TARIFF_TIMEZONE)
REQUIRE_FROM_HOUR = 15
RETRY_AFTER_SEEN_ON_29_OCT = 22
TOO_MANY_REQUESTS = 429
NOT_FOUND = 404
SERVER_ERROR = 500
HOURS_PER_UTC_DAY = 24


def single(day: date) -> DayRange:
    return DayRange(day, day)


def local_midnight_epoch(day: date) -> int:
    return int(datetime.combine(day, time(), tzinfo=TARIFF_TIMEZONE).timestamp())


def price_response(days: DayRange, *, missing: frozenset[date] = frozenset()) -> bytes:
    """Quarter-hourly prices from local midnight of the first day to local midnight after the last, like the API."""
    timestamps: list[int] = []
    for day in days.days():
        if day not in missing:
            timestamps += range(
                local_midnight_epoch(day), local_midnight_epoch(day + timedelta(days=1)), QUARTER_HOUR_SECONDS
            )
    prices = [1.0] * len(timestamps)
    return json.dumps(
        {"unit": EXPECTED_UNIT, "unix_seconds": timestamps, "price": prices, "deprecated": False}
    ).encode()


def weather_response(days: DayRange) -> bytes:
    times = [
        (datetime.combine(day, time(), tzinfo=UTC) + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M")
        for day in days.days()
        for hour in range(HOURS_PER_UTC_DAY)
    ]
    hourly: dict[str, list] = {"time": times}
    hourly |= {f"{variable}{FORECAST_LEAD_SUFFIX}": [1.0] * len(times) for variable in WEATHER_VARIABLES}
    return json.dumps({"hourly": hourly}).encode()


def requested_range(url: str) -> DayRange:
    query = parse_qs(urlparse(url).query)
    first = query.get("start", query.get("start_date"))
    last = query.get("end", query.get("end_date"))
    assert first
    assert last
    return DayRange(date.fromisoformat(first[0]), date.fromisoformat(last[0]))


class FakeSources:
    """Answers like the real APIs: Energy-Charts returns 404 for a delivery day that is not published yet."""

    def __init__(self, unpublished: frozenset[date] = frozenset(), *, unpublished_as_empty: bool = False) -> None:
        self.unpublished = unpublished
        self.unpublished_as_empty = unpublished_as_empty
        self.requested: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.requested.append(url)
        days = requested_range(url)
        if "energy-charts" not in url:
            return weather_response(days)
        if set(days.days()) <= self.unpublished and not self.unpublished_as_empty:
            raise SourceNotFoundError(f"GET {url} found nothing (HTTP 404)")
        return price_response(days, missing=self.unpublished)


def no_sleep(seconds: float) -> None:
    del seconds


@pytest.fixture(autouse=True)
def never_really_sleep(monkeypatch):
    monkeypatch.setattr("price_passport.ingest.time.sleep", no_sleep)


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.test", code, "error", headers, io.BytesIO())


class ScriptedOpener:
    def __init__(self, *outcomes: Exception | bytes) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, url: str, timeout: float) -> io.BytesIO:
        del url, timeout
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(outcome)


def test_a_429_is_retried_after_the_wait_the_server_asked_for():
    waits: list[float] = []
    opener = ScriptedOpener(http_error(TOO_MANY_REQUESTS, str(RETRY_AFTER_SEEN_ON_29_OCT)), b"ok")

    body = http_get("https://example.test", sleep=waits.append, open_url=opener)

    assert body == b"ok"
    assert waits == [RETRY_AFTER_SEEN_ON_29_OCT]


def test_a_404_is_reported_as_not_found_at_once():
    opener = ScriptedOpener(http_error(NOT_FOUND))

    with pytest.raises(SourceNotFoundError, match="HTTP 404"):
        http_get("https://example.test", sleep=no_sleep, open_url=opener)
    assert opener.calls == 1


def test_other_http_errors_fail_at_once():
    opener = ScriptedOpener(http_error(SERVER_ERROR))

    with pytest.raises(IngestError, match="HTTP 500"):
        http_get("https://example.test", sleep=no_sleep, open_url=opener)
    assert opener.calls == 1


def test_repeated_429s_give_up_after_the_last_attempt():
    opener = ScriptedOpener(*[http_error(TOO_MANY_REQUESTS, "1") for _ in range(MAX_ATTEMPTS)])

    with pytest.raises(IngestError, match=f"after {MAX_ATTEMPTS} attempts"):
        http_get("https://example.test", sleep=no_sleep, open_url=opener)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("22", RETRY_AFTER_SEEN_ON_29_OCT),
        (None, DEFAULT_RETRY_AFTER_SECONDS),
        ("Wed, 21 Oct 2026 07:28:00 GMT", DEFAULT_RETRY_AFTER_SECONDS),
        ("-5", 0),
        ("100000", LONGEST_RETRY_AFTER_SECONDS),
    ],
)
def test_retry_after_is_read_defensively(header, expected):
    assert retry_after_seconds(header) == expected


def test_a_daily_run_writes_one_file_per_source_site_and_day(tmp_path):
    ranges = [single(YESTERDAY), single(TODAY)]

    result = ingest(tmp_path, ranges, ranges, required_price_days=frozenset({YESTERDAY, TODAY}), fetch=FakeSources())

    expected = [price_file(tmp_path, days) for days in ranges]
    expected += [weather_file(tmp_path, site, days) for days in ranges for site in WEATHER_SITES]
    assert list(result.written) == expected
    assert price_file(tmp_path, single(TODAY)).name == "range=2026-10-27_2026-10-27.json"


def test_a_repeated_run_leaves_the_same_files(tmp_path):
    ranges = [single(TODAY)]
    ingest(tmp_path, ranges, ranges, required_price_days=frozenset({TODAY}), fetch=FakeSources())
    first = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}

    ingest(tmp_path, ranges, ranges, required_price_days=frozenset({TODAY}), fetch=FakeSources())

    assert {path: path.read_bytes() for path in tmp_path.rglob("*.json")} == first


@pytest.mark.parametrize("unpublished_as_empty", [False, True], ids=["404", "empty list"])
def test_an_unpublished_optional_day_is_reported_and_never_overwrites_a_file(tmp_path, unpublished_as_empty):
    ingest(tmp_path, [single(TOMORROW)], [], required_price_days=frozenset(), fetch=FakeSources())
    complete = price_file(tmp_path, single(TOMORROW)).read_bytes()
    sources = FakeSources(frozenset({TOMORROW}), unpublished_as_empty=unpublished_as_empty)

    result = ingest(tmp_path, [single(TOMORROW)], [], required_price_days=frozenset(), fetch=sources)

    assert result.not_yet_published == (single(TOMORROW),)
    assert price_file(tmp_path, single(TOMORROW)).read_bytes() == complete


def test_an_unpublished_required_day_fails_the_run(tmp_path):
    with pytest.raises(IngestError, match="no prices published for 2026-10-28"):
        ingest(
            tmp_path,
            [single(TOMORROW)],
            [],
            required_price_days=frozenset({TOMORROW}),
            fetch=FakeSources(frozenset({TOMORROW})),
        )


def test_a_month_missing_one_required_day_fails_instead_of_passing_as_complete(tmp_path):
    october = DayRange(date(2026, 10, 1), date(2026, 10, 27))
    sources = FakeSources(frozenset({date(2026, 10, 25)}), unpublished_as_empty=True)

    with pytest.raises(IngestError, match="no prices published for 2026-10-25"):
        ingest(tmp_path, [october], [], required_price_days=frozenset(october.days()), fetch=sources)
    assert not list(tmp_path.rglob("*.json"))


def test_a_month_across_the_clock_change_is_complete(tmp_path):
    october = DayRange(date(2026, 10, 1), date(2026, 10, 31))

    result = ingest(tmp_path, [october], [october], required_price_days=frozenset(october.days()), fetch=FakeSources())

    assert price_file(tmp_path, october) in result.written


@pytest.mark.parametrize(
    "body",
    [b"not json", json.dumps({"unit": "EUR / kWh", "unix_seconds": [], "price": []}).encode()],
    ids=["not JSON", "wrong unit"],
)
def test_an_unusable_price_response_is_not_written(tmp_path, body):
    with pytest.raises(IngestError, match="unusable response"):
        ingest(tmp_path, [single(TODAY)], [], required_price_days=frozenset(), fetch=lambda url: body)
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        json.dumps({"hourly": {"time": ["2026-10-27T00:00"], "temperature_2m_previous_day2": []}}).encode(),
        weather_response(single(YESTERDAY)),
    ],
    ids=["no hourly block", "series of different length", "a different day"],
)
def test_an_unusable_weather_response_is_not_written(tmp_path, body):
    with pytest.raises(IngestError):
        ingest(tmp_path, [], [single(TODAY)], required_price_days=frozenset(), fetch=lambda url: body)
    assert not list(tmp_path.rglob("*.json"))


def test_the_midday_run_fetches_three_single_days_and_does_not_require_tomorrow():
    price_ranges, weather_ranges, required = plan_ranges(
        MIDDAY_RUN, start=None, end=None, require_tomorrow_from_hour=REQUIRE_FROM_HOUR
    )

    assert price_ranges == [single(YESTERDAY), single(TODAY), single(TOMORROW)]
    assert weather_ranges == price_ranges
    assert required == {YESTERDAY, TODAY}


def test_the_afternoon_run_requires_tomorrow():
    _, _, required = plan_ranges(AFTERNOON_RUN, start=None, end=None, require_tomorrow_from_hour=REQUIRE_FROM_HOUR)

    assert TOMORROW in required


def test_a_backfill_is_split_into_calendar_months():
    ranges = month_ranges(date(2024, 11, 15), date(2025, 2, 3))

    assert ranges == [
        DayRange(date(2024, 11, 15), date(2024, 11, 30)),
        DayRange(date(2024, 12, 1), date(2024, 12, 31)),
        DayRange(date(2025, 1, 1), date(2025, 1, 31)),
        DayRange(date(2025, 2, 1), date(2025, 2, 3)),
    ]


def test_a_backfill_requires_every_day_up_to_today_but_not_tomorrow_at_midday():
    price_ranges, _, required = plan_ranges(
        MIDDAY_RUN, start=date(2026, 10, 25), end=TOMORROW, require_tomorrow_from_hour=REQUIRE_FROM_HOUR
    )

    assert price_ranges == [DayRange(date(2026, 10, 25), TOMORROW)]
    assert TODAY in required
    assert TOMORROW not in required


def test_a_backfill_that_ends_before_it_starts_is_refused():
    with pytest.raises(IngestError, match="is before"):
        plan_ranges(MIDDAY_RUN, start=TODAY, end=YESTERDAY, require_tomorrow_from_hour=REQUIRE_FROM_HOUR)


def test_the_urls_ask_for_the_requested_days():
    october = DayRange(date(2026, 10, 1), date(2026, 10, 31))

    assert energy_charts_url(october).endswith("bzn=DE-LU&start=2026-10-01&end=2026-10-31")
    weather_url = open_meteo_url(WEATHER_SITES[0], october)
    assert "start_date=2026-10-01&end_date=2026-10-31" in weather_url
    assert "temperature_2m_previous_day2" in weather_url


def test_main_runs_end_to_end_against_fake_sources(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr("price_passport.ingest.http_get", FakeSources(frozenset({TOMORROW})))

    exit_code = main(["--volume-root", str(tmp_path)], now=MIDDAY_RUN)

    assert exit_code == 0
    assert "not published yet: 2026-10-28 to 2026-10-28" in capsys.readouterr().out
