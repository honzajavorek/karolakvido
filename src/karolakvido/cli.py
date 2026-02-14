from __future__ import annotations

import argparse
from pathlib import Path

from . import DEFAULT_CALENDAR_URL, DEFAULT_OUTPUT_FILE
from .ical import write_ics
from .scraper import Event, KarolAKvidoClient


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
    client = KarolAKvidoClient()

    events = client.collect_events(args.url)
    events = _filter_events(events, args.region)

    output_path = Path(args.output)
    write_ics(events, output_path)

    return 0
