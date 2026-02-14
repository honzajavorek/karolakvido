from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from . import TZ_NAME
from .scraper import Event

_LOG = logging.getLogger(__name__)


def _escape_ics(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold_ics_line(line: str) -> str:
    max_len = 75
    if len(line) <= max_len:
        return line

    chunks = [line[:max_len]]
    rest = line[max_len:]
    while rest:
        chunks.append(" " + rest[: max_len - 1])
        rest = rest[max_len - 1 :]
    return "\r\n".join(chunks)


def _dtstamp_utc() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _build_description(event: Event) -> str:
    info_text = event.information_text.strip() or "Neuvedeno"
    return f"{info_text}\n\n{event.detail_url}"


def build_ics(events: list[Event]) -> str:
    _LOG.info("Generuji ICS obsah pro %d událostí", len(events))
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//karolakvido//calendar-export//CS",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-TIMEZONE:{TZ_NAME}",
    ]

    for event in events:
        uid = f"{uuid5(NAMESPACE_URL, event.detail_url)}@karolakvido"
        description = _build_description(event)

        lines.extend(
            [
                "BEGIN:VEVENT",
                _fold_ics_line(f"UID:{uid}"),
                f"DTSTAMP:{_dtstamp_utc()}",
                f"DTSTART;TZID={TZ_NAME}:{event.starts_at.strftime('%Y%m%dT%H%M%S')}",
                _fold_ics_line(f"SUMMARY:{_escape_ics(event.title)}"),
                _fold_ics_line(f"LOCATION:{_escape_ics(event.location or 'Neuvedeno')}"),
                _fold_ics_line(f"DESCRIPTION:{_escape_ics(description)}"),
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_ics(events: list[Event], output_path: Path) -> None:
    _LOG.debug("Vytvářím adresář pro výstup: %s", output_path.parent)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_ics(events), encoding="utf-8")
    _LOG.info("Soubor uložen: %s", output_path)
