import io
import json
import urllib.error
from datetime import date, datetime
from email.message import Message
from pathlib import Path

import pytest

from price_passport.energy_charts import TARIFF_TIMEZONE
from price_passport.ingest import (
    DEFAULT_RETRY_AFTER_SECONDS,
    LONGEST_RETRY_AFTER_SECONDS,
    MAX_ATTEMPTS,
    WEATHER_SITES,
    WEATHER_VARIABLES,
    IngestError,
    energy_charts_url,
    http_get,
    ingest,
    main,
    plan_days,
    price_file,
    retry_after_seconds,
    weather_file,
)

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 27)
YESTERDAY = date(2026, 10, 26)
TOMORROW = date(2026, 10, 28)
MIDDAY_RUN = datetime(2026, 10, 27, 13, 40, tzinfo=TARIFF_TIMEZONE)
AFTERNOON_RUN = datetime(2026, 10, 27, 16, 40, tzinfo=TARIFF_TIMEZONE)
REQUIRE_FROM_HOUR = 15
HOURS_PER_DAY = 24
RETRY_AFTER_SEEN_ON_29_OCT = 22
TOO_MANY_REQUESTS = 429
NOT_FOUND = 404


def price_body() -> bytes:
    return (FIXTURES / "energy_charts_price_quarter_hourly_2026-10-27.json").read_bytes()


def empty_price_body() -> bytes:
    return json.dumps({"unit": "EUR / MWh", "unix_seconds": [], "price": [], "deprecated": False}).encode()


def weather_body() -> bytes:
    hourly = {"time": [f"2026-10-27T{hour:02d}:00" for hour in range(HOURS_PER_DAY)]}
    hourly |= {variable: [1.0] * HOURS_PER_DAY for variable in WEATHER_VARIABLES}
    return json.dumps({"hourly": hourly}).encode()


class FakeSources:
    def __init__(self, unpublished: frozenset[date] = frozenset()) -> None:
        self.unpublished = unpublished
        self.requested: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.requested.append(url)
        if "energy-charts" in url:
            return empty_price_body() if any(day.isoformat() in url for day in self.unpublished) else price_body()
        return weather_body()


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


def test_other_http_errors_fail_at_once():
    opener = ScriptedOpener(http_error(NOT_FOUND))

    with pytest.raises(IngestError, match="HTTP 404"):
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


def test_a_run_writes_one_file_per_source_site_and_day(tmp_path):
    sources = FakeSources()

    result = ingest(tmp_path, [YESTERDAY, TODAY], [YESTERDAY, TODAY], required_price_days=frozenset(), fetch=sources)

    expected = [price_file(tmp_path, day) for day in (YESTERDAY, TODAY)]
    expected += [weather_file(tmp_path, site, day) for day in (YESTERDAY, TODAY) for site in WEATHER_SITES]
    assert list(result.written) == expected
    assert all(path.read_bytes() for path in expected)


def test_a_repeated_run_leaves_the_same_files(tmp_path):
    ingest(tmp_path, [TODAY], [TODAY], required_price_days=frozenset(), fetch=FakeSources())
    first = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}

    ingest(tmp_path, [TODAY], [TODAY], required_price_days=frozenset(), fetch=FakeSources())

    assert {path: path.read_bytes() for path in tmp_path.rglob("*.json")} == first


def test_an_unpublished_optional_day_is_reported_and_never_overwrites_a_file(tmp_path):
    ingest(tmp_path, [TOMORROW], [], required_price_days=frozenset(), fetch=FakeSources())
    complete = price_file(tmp_path, TOMORROW).read_bytes()

    result = ingest(tmp_path, [TOMORROW], [], required_price_days=frozenset(), fetch=FakeSources(frozenset({TOMORROW})))

    assert result.not_yet_published == (TOMORROW,)
    assert price_file(tmp_path, TOMORROW).read_bytes() == complete


def test_an_unpublished_required_day_fails_the_run(tmp_path):
    with pytest.raises(IngestError, match="no prices published for 2026-10-28"):
        ingest(
            tmp_path,
            [TOMORROW],
            [],
            required_price_days=frozenset({TOMORROW}),
            fetch=FakeSources(frozenset({TOMORROW})),
        )


@pytest.mark.parametrize(
    "body",
    [b"not json", json.dumps({"unit": "EUR / kWh", "unix_seconds": [], "price": []}).encode()],
    ids=["not JSON", "wrong unit"],
)
def test_an_unusable_price_response_is_not_written(tmp_path, body):
    with pytest.raises(IngestError, match="unusable response"):
        ingest(tmp_path, [TODAY], [], required_price_days=frozenset(), fetch=lambda url: body)
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize(
    "body",
    [b"{}", json.dumps({"hourly": {"time": ["2026-10-27T00:00"], "temperature_2m": []}}).encode()],
    ids=["no hourly block", "series of different length"],
)
def test_an_unusable_weather_response_is_not_written(tmp_path, body):
    with pytest.raises(IngestError):
        ingest(tmp_path, [], [TODAY], required_price_days=frozenset(), fetch=lambda url: body)
    assert not list(tmp_path.rglob("*.json"))


def test_the_midday_run_fetches_three_days_and_does_not_require_tomorrow():
    price_days, weather_days, required = plan_days(
        MIDDAY_RUN, start=None, end=None, require_tomorrow_from_hour=REQUIRE_FROM_HOUR
    )

    assert price_days == [YESTERDAY, TODAY, TOMORROW]
    assert weather_days == [YESTERDAY, TODAY]
    assert required == {YESTERDAY, TODAY}


def test_the_afternoon_run_requires_tomorrow():
    _, _, required = plan_days(AFTERNOON_RUN, start=None, end=None, require_tomorrow_from_hour=REQUIRE_FROM_HOUR)

    assert TOMORROW in required


def test_a_backfill_requires_every_day_up_to_today():
    price_days, weather_days, required = plan_days(
        MIDDAY_RUN, start=date(2026, 10, 25), end=TOMORROW, require_tomorrow_from_hour=REQUIRE_FROM_HOUR
    )

    assert price_days[0] == date(2026, 10, 25)
    assert weather_days[-1] == TODAY
    assert TOMORROW not in required
    assert TODAY in required


def test_a_backfill_that_ends_before_it_starts_is_refused():
    with pytest.raises(IngestError, match="is before"):
        plan_days(MIDDAY_RUN, start=TODAY, end=YESTERDAY, require_tomorrow_from_hour=REQUIRE_FROM_HOUR)


def test_the_price_url_asks_for_one_local_delivery_day():
    assert energy_charts_url(TODAY).endswith("bzn=DE-LU&start=2026-10-27&end=2026-10-27")


def test_main_runs_end_to_end_against_fake_sources(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("price_passport.ingest.http_get", FakeSources(frozenset({TOMORROW})))

    exit_code = main(["--volume-root", str(tmp_path)], now=MIDDAY_RUN)

    assert exit_code == 0
    assert "not published yet: 2026-10-28" in capsys.readouterr().out
