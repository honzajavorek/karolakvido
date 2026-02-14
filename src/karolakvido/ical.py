from __future__ import annotations

import logging
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from ics import Calendar
from ics.event import Event as IcsEvent

from . import TZ_NAME
from .scraper import Event as ScrapedEvent

_LOG = logging.getLogger(__name__)


def _build_description(event: ScrapedEvent) -> str:
    return event.detail_url


def build_ics(events: list[ScrapedEvent]) -> str:
    _LOG.info("Generuji ICS obsah pro %d událostí", len(events))
    calendar = Calendar(creator="-//karolakvido//calendar-export//CS")

    for event in events:
        starts_at = event.starts_at.replace(tzinfo=ZoneInfo(TZ_NAME))
        ics_event = IcsEvent(
            uid=f"{uuid5(NAMESPACE_URL, event.detail_url)}@karolakvido",
            summary=event.title,
            begin=starts_at,
            location=event.location or "Neuvedeno",
            description=_build_description(event),
        )
        calendar.events.append(ics_event)

    serialized = calendar.serialize()
    if f"X-WR-TIMEZONE:{TZ_NAME}" not in serialized:
        serialized = serialized.replace(
            "CALSCALE:GREGORIAN\r\n",
            f"CALSCALE:GREGORIAN\r\nX-WR-TIMEZONE:{TZ_NAME}\r\n",
        )
    return serialized


def write_ics(events: list[ScrapedEvent], output_path: Path) -> None:
    _LOG.debug("Vytvářím adresář pro výstup: %s", output_path.parent)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_ics(events), encoding="utf-8")
    _LOG.info("Soubor uložen: %s", output_path)
