from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import requests

from karolakvido import DEFAULT_CALENDAR_URL, DEFAULT_OUTPUT_FILE, TZ_NAME
from karolakvido.cli import main
from karolakvido.scraper import Event, KarolAKvidoClient


def _build_response(
    *,
    status_code: int,
    url: str,
    body: str = "",
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response.request = requests.Request("GET", url).prepare()
    response._content = body.encode("utf-8")
    response.headers.update(headers or {})
    return response


def _sample_events() -> list[Event]:
    return [
        Event(
            title="Pirátský poklad",
            starts_at=datetime(2026, 2, 14, 10, 0),
            location="Praha, Divadlo Lucie Bílé",
            detail_url="https://karolakvido.cz/akce_karol_a_kvido/piratsky-poklad-14-unora-2026-praha/",
            city="Praha",
        ),
        Event(
            title="Dobrodružství začíná",
            starts_at=datetime(2026, 2, 22, 16, 0),
            location="Litvínov, Kino Máj",
            detail_url="https://karolakvido.cz/akce_karol_a_kvido/dobrodruzstvi-zacina-22-unora-litvinov/",
            city="Litvínov",
        ),
    ]


def test_default_url_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called = {}

    def fake_collect(self: KarolAKvidoClient, url: str) -> list[Event]:
        called["url"] = url
        return _sample_events()

    monkeypatch.setattr(KarolAKvidoClient, "collect_events", fake_collect)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["karolakvido"])

    exit_code = main()

    assert exit_code == 0
    assert called["url"] == DEFAULT_CALENDAR_URL


def test_custom_url_can_be_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called = {}

    def fake_collect(self: KarolAKvidoClient, url: str) -> list[Event]:
        called["url"] = url
        return _sample_events()

    monkeypatch.setattr(KarolAKvidoClient, "collect_events", fake_collect)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["karolakvido", "--url", "https://example.com/kalendar"])

    main()

    assert called["url"] == "https://example.com/kalendar"


def test_default_output_file_is_written(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(KarolAKvidoClient, "collect_events", lambda self, url: _sample_events())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["karolakvido"])

    main()

    assert (tmp_path / DEFAULT_OUTPUT_FILE).exists()


def test_custom_output_path_is_written(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(KarolAKvidoClient, "collect_events", lambda self, url: _sample_events())
    output = tmp_path / "custom" / "events.ics"
    output.parent.mkdir(parents=True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["karolakvido", "--output", str(output)])

    main()

    assert output.exists()


def test_filter_by_region(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(KarolAKvidoClient, "collect_events", lambda self, url: _sample_events())
    output = tmp_path / "praha.ics"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["karolakvido", "--region", "Praha", "--output", str(output)])

    main()

    content = output.read_text(encoding="utf-8")
    unfolded = content.replace("\r\n ", "")
    assert "Praha\\, Divadlo Lucie Bílé" in unfolded
    assert "Litvínov\\, Kino Máj" not in unfolded


def test_ics_uses_czech_timezone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(KarolAKvidoClient, "collect_events", lambda self, url: _sample_events())

    output = tmp_path / "timezone.ics"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["karolakvido", "--output", str(output)])

    main()

    content = output.read_text(encoding="utf-8")
    assert "BEGIN:VTIMEZONE" in content
    assert TZ_NAME in content
    assert "DTSTART;TZID=" in content
    assert "20260214T100000" in content


def test_location_is_always_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    events = _sample_events()
    events[0].location = ""
    monkeypatch.setattr(KarolAKvidoClient, "collect_events", lambda self, url: events)

    output = tmp_path / "location.ics"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["karolakvido", "--output", str(output)])

    main()

    content = output.read_text(encoding="utf-8")
    assert "LOCATION:Neuvedeno" in content


def test_description_contains_only_link(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(KarolAKvidoClient, "collect_events", lambda self, url: _sample_events())

    output = tmp_path / "description.ics"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["karolakvido", "--output", str(output)])

    main()

    content = output.read_text(encoding="utf-8")
    unfolded = content.replace("\r\n ", "").replace("\n ", "")
    assert "DESCRIPTION:https://karolakvido.cz/akce_karol_a_kvido/piratsky-poklad" in unfolded
    assert "Připravte se na show plnou dobrodružství" not in unfolded


def test_parser_extracts_events_from_fixture() -> None:
    client = KarolAKvidoClient()
    calendar_html = """
        <html>
            <body>
                <h2>ÚNOR 2026</h2>
                <h3>Praha</h3>
                <h4>Únor14</h4>
                <h5>
                    <a href="/akce_karol_a_kvido/piratsky-poklad-14-unora-2026-praha/">
                        Pirátský poklad
                    </a>
                </h5>
                <p>Divadlo Lucie Bílé, v 10:00 hodin</p>

                <h3>Litvínov</h3>
                <h4>Únor22</h4>
                <h5>
                    <a href="https://karolakvido.cz/akce_karol_a_kvido/dobrodruzstvi-zacina-22-unora-litvinov/">
                        Dobrodružství začíná
                    </a>
                </h5>
                <p>Kino Máj, v 16:00 hodin</p>
            </body>
        </html>
        """

    events = client.parse_events(calendar_html, "https://karolakvido.cz/kalendar-koncertu/")

    assert len(events) == 2

    first = events[0]
    assert first.title == "Pirátský poklad"
    assert first.starts_at.year == 2026
    assert first.starts_at.month == 2
    assert first.starts_at.day == 14
    assert first.starts_at.hour == 10
    assert first.starts_at.minute == 0
    assert first.location == "Divadlo Lucie Bílé"


def test_parser_handles_sparse_markup_without_location() -> None:
    client = KarolAKvidoClient()
    calendar_html = """
    <h2>KVĚTEN 2026</h2>
    <h3>Praha</h3>
    <h4>Květ16</h4>
        <h5>
            <a href=\"/akce_karol_a_kvido/pokacova-o2-arena-16-kvetna-2026-v-18-hodin/\">
                Pokáčova O2 Aréna
            </a>
        </h5>
    <p>v 18:00 hodin</p>
    """

    events = client.parse_events(calendar_html, "https://karolakvido.cz/kalendar-koncertu/")

    assert len(events) == 1
    assert events[0].location == "Praha"
    assert events[0].starts_at.hour == 18
    assert events[0].starts_at.minute == 0


def test_collect_events_fetches_calendar_once(monkeypatch: pytest.MonkeyPatch) -> None:
    client = KarolAKvidoClient()
    calendar_url = "https://karolakvido.cz/kalendar-koncertu/"
    calls: list[str] = []
    calendar_html = """
    <h2>ÚNOR 2026</h2>
    <h3>Praha</h3>
    <h4>Únor14</h4>
    <h5><a href=\"/akce_karol_a_kvido/ok/\">A</a></h5>
    <p>Divadlo, v 10:00 hodin</p>
    """

    def fake_fetch(self: KarolAKvidoClient, url: str) -> str:
        calls.append(url)
        return calendar_html

    monkeypatch.setattr(KarolAKvidoClient, "fetch_text", fake_fetch)

    events = client.collect_events(calendar_url)

    assert len(events) == 1
    assert calls == [calendar_url]


def test_fetch_text_retries_on_http_429(monkeypatch: pytest.MonkeyPatch) -> None:
    client = KarolAKvidoClient()
    client._sleep = lambda _: None
    url = "https://example.com/kalendar"
    responses = [
        _build_response(status_code=429, url=url, headers={"Retry-After": "0"}),
        _build_response(status_code=200, url=url, body="ok"),
    ]
    calls: list[tuple[str, Any]] = []

    def fake_get(request_url: str, timeout: tuple[float, float]) -> requests.Response:
        calls.append((request_url, timeout))
        return responses.pop(0)

    monkeypatch.setattr(client._session, "get", fake_get)
    monkeypatch.setattr(KarolAKvidoClient.fetch_text.retry, "sleep", lambda _: None)

    body = client.fetch_text(url)

    assert body == "ok"
    assert len(calls) == 2


def test_fetch_text_does_not_retry_on_http_404(monkeypatch: pytest.MonkeyPatch) -> None:
    client = KarolAKvidoClient()
    client._sleep = lambda _: None
    url = "https://example.com/missing"
    response_404 = _build_response(status_code=404, url=url)
    calls: list[tuple[str, Any]] = []

    def fake_get(request_url: str, timeout: tuple[float, float]) -> requests.Response:
        calls.append((request_url, timeout))
        return response_404

    monkeypatch.setattr(client._session, "get", fake_get)
    monkeypatch.setattr(KarolAKvidoClient.fetch_text.retry, "sleep", lambda _: None)

    with pytest.raises(requests.HTTPError):
        client.fetch_text(url)

    assert len(calls) == 1
