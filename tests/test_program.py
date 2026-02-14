from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from karolakvido import DEFAULT_CALENDAR_URL, DEFAULT_OUTPUT_FILE, TZ_NAME
from karolakvido.cli import main
from karolakvido.scraper import Event, KarolAKvidoClient


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


def test_live_snapshot_support(web_snapshot_loader) -> None:
    client = KarolAKvidoClient()
    calendar_html = web_snapshot_loader(
        "live_calendar.html", "https://karolakvido.cz/kalendar-koncertu/"
    )
    events = client.parse_events(calendar_html, "https://karolakvido.cz/kalendar-koncertu/")
    assert events, "Na stránce kalendáře nebyly nalezeny žádné akce"
