from __future__ import annotations

import logging
from pathlib import Path

import click

from . import DEFAULT_CALENDAR_URL, DEFAULT_OUTPUT_FILE
from .ical import write_ics
from .scraper import Event, KarolAKvidoClient

_LOG = logging.getLogger(__name__)


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


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


@click.command(help="Export vystoupení Karol a Kvído do iCalendar")
@click.option(
    "--url", default=DEFAULT_CALENDAR_URL, show_default=True, help="URL stránky kalendáře"
)
@click.option(
    "--output",
    default=DEFAULT_OUTPUT_FILE,
    show_default=True,
    help="Výstupní soubor .ics (relativně vůči aktuálnímu adresáři)",
)
@click.option(
    "--region",
    default=None,
    help="Filtr na region (prakticky textový filtr nad městem/lokací, např. Praha)",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    default="INFO",
    show_default=True,
    help="Úroveň logování průběhu programu",
)
def cli(url: str, output: str, region: str | None, log_level: str) -> None:
    _configure_logging(log_level)

    _LOG.info("Start exportu kalendáře")
    _LOG.info("Načítám události z %s", url)
    client = KarolAKvidoClient()

    events = client.collect_events(url)
    _LOG.info("Načteno %d událostí", len(events))
    events = _filter_events(events, region)
    if region:
        _LOG.info("Po filtru regionu '%s' zůstalo %d událostí", region, len(events))

    output_path = Path(output)
    _LOG.info("Zapisuji iCalendar do %s", output_path)
    write_ics(events, output_path)
    _LOG.info("Export dokončen")


def main(argv: list[str] | None = None) -> int:
    try:
        cli.main(args=argv, prog_name="karolakvido", standalone_mode=False)
    except click.exceptions.Exit as exc:
        return exc.exit_code
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.Abort:
        click.echo("Aborted!", err=True)
        return 1

    return 0
