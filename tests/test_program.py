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
            information_text="Připravte se na show plnou dobrodružství.",
            city="Praha",
        ),
        Event(
            title="Dobrodružství začíná",
            starts_at=datetime(2026, 2, 22, 16, 0),
            location="Litvínov, Kino Máj",
            detail_url="https://karolakvido.cz/akce_karol_a_kvido/dobrodruzstvi-zacina-22-unora-litvinov/",
            information_text="Hudební představení pro celou rodinu.",
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
    assert f"X-WR-TIMEZONE:{TZ_NAME}" in content
    assert f"DTSTART;TZID={TZ_NAME}:20260214T100000" in content


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


def test_description_contains_info_and_link(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(KarolAKvidoClient, "collect_events", lambda self, url: _sample_events())

    output = tmp_path / "description.ics"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["karolakvido", "--output", str(output)])

    main()

    content = output.read_text(encoding="utf-8")
    unfolded = content.replace("\r\n ", "").replace("\n ", "")
    assert (
        "DESCRIPTION:Připravte se na show plnou dobrodružství.\\n\\n"
        "https://karolakvido.cz/"
    ) in unfolded


def test_description_includes_info_section_when_missing_info(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events = _sample_events()
    events[0].information_text = ""
    monkeypatch.setattr(KarolAKvidoClient, "collect_events", lambda self, url: events)

    output = tmp_path / "description-missing-info.ics"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["karolakvido", "--output", str(output)])

    main()

    content = output.read_text(encoding="utf-8")
    unfolded = content.replace("\r\n ", "").replace("\n ", "")
    assert "DESCRIPTION:Neuvedeno\\n\\nhttps://karolakvido.cz/" in unfolded


def test_parser_extracts_events_from_fixture(fixtures_dir: Path) -> None:
    client = KarolAKvidoClient()
    calendar_html = (fixtures_dir / "calendar_sample.html").read_text(encoding="utf-8")
    detail_html = (fixtures_dir / "detail_praha.html").read_text(encoding="utf-8")

    basic_events = client.parse_events(calendar_html, "https://karolakvido.cz/kalendar-koncertu/")
    assert len(basic_events) == 2

    event = client.parse_detail(
        detail_html,
        basic_events[0]["detail_url"],
        basic_events[0]["title"],
        basic_events[0]["city"],
    )
    assert event.location.startswith("Praha")
    assert "Program je vhodný" in event.information_text
    assert not event.information_text.startswith("Informace:")


def test_parser_falls_back_when_kdy_omits_year(fixtures_dir: Path) -> None:
    client = KarolAKvidoClient()
    detail_html = (fixtures_dir / "detail_missing_year_in_kdy.html").read_text(encoding="utf-8")

    event = client.parse_detail(
        detail_html,
        "https://karolakvido.cz/akce_karol_a_kvido/piratsky-poklad-14-unora-v-15-hodin-praha/",
        "Pirátský poklad",
        "Praha",
    )

    assert event.starts_at.year == 2026
    assert event.starts_at.month == 2
    assert event.starts_at.day == 14
    assert event.starts_at.hour == 15


def test_parser_handles_time_without_minutes(fixtures_dir: Path) -> None:
    client = KarolAKvidoClient()
    detail_html = (fixtures_dir / "detail_without_minutes.html").read_text(encoding="utf-8")

    event = client.parse_detail(
        detail_html,
        "https://karolakvido.cz/akce_karol_a_kvido/piratsky-poklad-14-unora-v-15-hodin-praha/",
        "Pirátský poklad",
        "Praha",
    )

    assert event.starts_at.year == 2026
    assert event.starts_at.month == 2
    assert event.starts_at.day == 14
    assert event.starts_at.hour == 15
    assert event.starts_at.minute == 0


def test_parser_prefers_kdy_over_related_events(fixtures_dir: Path) -> None:
    client = KarolAKvidoClient()
    detail_html = (fixtures_dir / "detail_kdy_with_noisy_related_dates.html").read_text(
        encoding="utf-8"
    )

    event = client.parse_detail(
        detail_html,
        "https://karolakvido.cz/akce_karol_a_kvido/piratsky-poklad-14-unora-v-15-hodin-praha/",
        "Pirátský poklad",
        "Praha",
    )

    assert event.starts_at.year == 2026
    assert event.starts_at.month == 2
    assert event.starts_at.day == 14
    assert event.starts_at.hour == 15


def test_parser_uses_nonempty_kdy_block_and_avoids_false_hour_from_full_text() -> None:
    client = KarolAKvidoClient()
    detail_html = """
    <h1>Dobrodružství začíná 1. března 2026 Svitavy</h1>
    <h2>Kdy:</h2>
    <h2>Kde:</h2>
    <p>Svitavy, Lidové divadlo</p>
    <h2>Kdy:</h2>
    <p>1. března 2026, v 16:00 hodin</p>
    """

    event = client.parse_detail(
        detail_html,
        "https://karolakvido.cz/akce_karol_a_kvido/dobrodruzstvi-zacina-1-brezna-2026-svitavy/",
        "Dobrodružství začíná",
        "Svitavy",
    )

    assert event.starts_at.year == 2026
    assert event.starts_at.month == 3
    assert event.starts_at.day == 1
    assert event.starts_at.hour == 16
    assert event.starts_at.minute == 0


def test_parser_handles_kdy_with_time_without_v_prefix() -> None:
        client = KarolAKvidoClient()
        detail_html = """
        <h1>Karol a Kvído v zoologické zahradě 7. listopadu 2026 Veselí nad Moravou</h1>
        <h2>Kdy:</h2>
        <p>7. listopadu 2026, 16:00 hodin</p>
        <h2>Kde:</h2>
        <p>Veselí nad Moravou, Kino Morava</p>
        <h2>Informace:</h2>
        <p>VSTUPENKY</p>
        <h3>Všechny akce Karol a Kvído</h3>
        <a href="/akce_karol_a_kvido/vanocni-pribeh-23-prosince-2026-ve-14-hodin-praha/">
            Vánoční příběh 23. prosince 2026 ve 14 hodin Praha
        </a>
        """

        event = client.parse_detail(
                detail_html,
                "https://karolakvido.cz/akce_karol_a_kvido/karol-a-kvido-v-zoologicke-zahrade-7-listopadu-2026-veseli-nad-moravou/",
                "Karol a Kvído",
                "Veselí nad Moravou",
        )

        assert event.starts_at.year == 2026
        assert event.starts_at.month == 11
        assert event.starts_at.day == 7
        assert event.starts_at.hour == 16
        assert event.starts_at.minute == 0


def test_parser_handles_numeric_date_without_kdy(fixtures_dir: Path) -> None:
    client = KarolAKvidoClient()
    detail_html = (fixtures_dir / "detail_numeric_date_without_kdy.html").read_text(
        encoding="utf-8"
    )

    event = client.parse_detail(
        detail_html,
        "https://karolakvido.cz/karol-a-kvido-slavi-5-narozeniny/",
        "Narozeninový koncert",
        "Praha",
    )

    assert event.starts_at.year == 2026
    assert event.starts_at.month == 8
    assert event.starts_at.day == 22


def test_live_snapshot_support(web_snapshot_loader) -> None:
    client = KarolAKvidoClient()
    calendar_html = web_snapshot_loader(
        "live_calendar.html", "https://karolakvido.cz/kalendar-koncertu/"
    )
    events = client.parse_events(calendar_html, "https://karolakvido.cz/kalendar-koncertu/")
    assert events, "Na stránce kalendáře nebyly nalezeny žádné akce"


def test_collect_events_skips_unreachable_detail_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    client = KarolAKvidoClient()
    calendar_url = "https://karolakvido.cz/kalendar-koncertu/"
    detail_ok = "https://karolakvido.cz/akce_karol_a_kvido/ok/"
    detail_missing = "https://karolakvido.cz/akce_karol_a_kvido/missing/"

    calendar_html = """
    <h3>Praha</h3>
    <h5><a href=\"/akce_karol_a_kvido/ok/\">A</a></h5>
    <h5><a href=\"/akce_karol_a_kvido/missing/\">B</a></h5>
    """
    detail_ok_html = """
    <h1>Akce A</h1>
    <h2>Kdy:</h2><p>14. února 2026, v 10:00 hodin</p>
    <h2>Kde:</h2><p>Praha, Divadlo</p>
    <h2>Informace:</h2><p>Info</p>
    """

    def fake_fetch(self: KarolAKvidoClient, url: str) -> str:
        if url == calendar_url:
            return calendar_html
        if url == detail_ok:
            return detail_ok_html
        if url == detail_missing:
            raise requests.HTTPError("404")
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(KarolAKvidoClient, "fetch_text", fake_fetch)

    events = client.collect_events(calendar_url)

    assert len(events) == 1
    assert events[0].detail_url == detail_ok


def test_fetch_text_retries_on_http_429(monkeypatch: pytest.MonkeyPatch) -> None:
    client = KarolAKvidoClient()
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


def test_parser_extracts_information_when_not_direct_sibling() -> None:
    client = KarolAKvidoClient()
    detail_html = """
    <h1>Akce A</h1>
    <h2>Kdy:</h2><p>14. února 2026, v 10:00 hodin</p>
    <h2>Kde:</h2><p>Praha, Divadlo</p>
    <div><h2>Informace:</h2></div>
    <div><p>Děti čeká hravý příběh.</p></div>
    <h2>Všechny akce Karol a Kvído</h2>
    """

    event = client.parse_detail(
        detail_html,
        "https://karolakvido.cz/akce_karol_a_kvido/test/",
        "Akce A",
        "Praha",
    )

    assert "Děti čeká hravý příběh." in event.information_text


def test_parser_ignores_vstupenky_label_in_information() -> None:
    client = KarolAKvidoClient()
    detail_html = """
    <h1>Akce B</h1>
    <h2>Kdy:</h2><p>14. února 2026, v 10:00 hodin</p>
    <h2>Kde:</h2><p>Praha, Divadlo</p>
    <h2>Informace:</h2>
    <p>Skvělá show pro děti.</p>
    <button>VSTUPENKY</button>
    <h2>Všechny akce Karol a Kvído</h2>
    """

    event = client.parse_detail(
        detail_html,
        "https://karolakvido.cz/akce_karol_a_kvido/test-b/",
        "Akce B",
        "Praha",
    )

    assert "Skvělá show pro děti." in event.information_text
    assert "VSTUPENKY" not in event.information_text
