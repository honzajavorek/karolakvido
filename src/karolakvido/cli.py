from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import DEFAULT_CALENDAR_URL, DEFAULT_OUTPUT_FILE
from .ical import write_ics
from .scraper import Event, KarolAKvidoClient

_LOG = logging.getLogger(__name__)


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export vystoupení Karol a Kvído do iCalendar")
    parser.add_argument("--url", default=DEFAULT_CALENDAR_URL, help="URL stránky kalendáře")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help="Výstupní soubor .ics (relativně vůči aktuálnímu adresáři)",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="Filtr na region (prakticky textový filtr nad městem/lokací, např. Praha)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Úroveň logování průběhu programu",
    )
    return parser.parse_args()


def _filter_events(events: list[Event], region: str | None) -> list[Event]:
    if not region:
        return events

    needle = region.casefold()
    filtered: list[Event] = []
    for event in events:
        haystacks = [event.location, event.city or "", event.title]
        if any(needle in text.casefold() for text in haystacks):
            filtered.append(event)
    return filtered


def main() -> int:
    args = _parse_args()
    _configure_logging(args.log_level)

    _LOG.info("Start exportu kalendáře")
    _LOG.info("Načítám události z %s", args.url)
    client = KarolAKvidoClient()

    events = client.collect_events(args.url)
    _LOG.info("Načteno %d událostí", len(events))
    events = _filter_events(events, args.region)
    if args.region:
        _LOG.info("Po filtru regionu '%s' zůstalo %d událostí", args.region, len(events))

    output_path = Path(args.output)
    _LOG.info("Zapisuji iCalendar do %s", output_path)
    write_ics(events, output_path)
    _LOG.info("Export dokončen")

    return 0
