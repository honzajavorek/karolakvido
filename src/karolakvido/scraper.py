from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from . import TZ_NAME

_LOG = logging.getLogger(__name__)

_MONTH_FROM_HEADING = {
    "leden": 1,
    "unor": 2,
    "brezen": 3,
    "duben": 4,
    "kveten": 5,
    "cerven": 6,
    "cervenec": 7,
    "srpen": 8,
    "zari": 9,
    "rijen": 10,
    "listopad": 11,
    "prosinec": 12,
}

_MONTH_FROM_DAY_LABEL = {
    "led": 1,
    "unor": 2,
    "brez": 3,
    "dub": 4,
    "kvet": 5,
    "cerv": 6,
    "cvc": 7,
    "srp": 8,
    "zar": 9,
    "rij": 10,
    "lis": 11,
    "pro": 12,
}

_YEAR_AND_MONTH_RE = re.compile(r"(?P<month>[A-Za-zÁ-ž]+)\s+(?P<year>20\d{2})")
_DAY_LABEL_RE = re.compile(r"(?P<month>[A-Za-zÁ-ž]+)?\s*(?P<day>\d{1,2})")
_TIME_RE = re.compile(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})")
_LOCATION_RE = re.compile(r"^(?P<location>.+?),\s*v(?:e)?\s*\d{1,2}:\d{2}\b", re.IGNORECASE)


def _should_retry_http_error(exc: BaseException) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True

    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None:
            return False
        return response.status_code == 429 or response.status_code >= 500

    return False


def _parse_retry_after_seconds(header_value: str | None) -> float | None:
    if not header_value:
        return None

    value = header_value.strip()
    if not value:
        return None

    if value.isdigit():
        return float(value)

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)

    seconds = (retry_at - datetime.now(UTC)).total_seconds()
    if seconds <= 0:
        return 0.0
    return seconds


def _wait_before_retry(retry_state) -> float:
    default_wait = wait_exponential(multiplier=1, min=1, max=8)(retry_state)
    if retry_state.outcome is None or not retry_state.outcome.failed:
        return default_wait

    exc = retry_state.outcome.exception()
    if not isinstance(exc, requests.HTTPError) or exc.response is None:
        return default_wait
    if exc.response.status_code != 429:
        return default_wait

    retry_after = _parse_retry_after_seconds(exc.response.headers.get("Retry-After"))
    if retry_after is None:
        return default_wait

    return max(default_wait, min(retry_after, 90.0))


@dataclass(slots=True)
class Event:
    title: str
    starts_at: datetime
    location: str
    detail_url: str
    information_text: str = ""
    city: str | None = None


class KarolAKvidoClient:
    def __init__(
        self,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        request_delay: float = 1.0,
        max_request_delay: float = 90.0,
        adaptive_backoff_factor: float = 2.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.request_delay = max(0.0, request_delay)
        self.max_request_delay = max(self.request_delay, max_request_delay)
        self.adaptive_backoff_factor = max(1.0, adaptive_backoff_factor)
        self._current_delay = self.request_delay
        self._sleep = sleep_fn
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "karolakvido-ics-export/0.1 (+https://github.com/honzajavorek/karolakvido)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def _throttle_before_request(self, url: str) -> None:
        if self._current_delay <= 0:
            return

        _LOG.debug("Čekám %.1f s před požadavkem na %s", self._current_delay, url)
        self._sleep(self._current_delay)

    def _increase_delay_after_429(self) -> None:
        if self._current_delay <= 0:
            self._current_delay = self.request_delay or 1.0
        else:
            self._current_delay *= self.adaptive_backoff_factor

        self._current_delay = min(self._current_delay, self.max_request_delay)

    def _relax_delay_after_success(self) -> None:
        if self._current_delay <= self.request_delay:
            self._current_delay = self.request_delay
            return

        self._current_delay = max(self.request_delay, self._current_delay * 0.9)

    @retry(
        retry=retry_if_exception(_should_retry_http_error),
        stop=stop_after_attempt(5),
        wait=_wait_before_retry,
        reraise=True,
    )
    def fetch_text(self, url: str) -> str:
        self._throttle_before_request(url)
        _LOG.debug("HTTP GET %s", url)
        response = self._session.get(url, timeout=(self.connect_timeout, self.read_timeout))
        if response.status_code == 429:
            self._increase_delay_after_429()
        response.raise_for_status()
        self._relax_delay_after_success()
        _LOG.debug("HTTP %s pro %s", response.status_code, url)
        return response.text

    def parse_events(self, html: str, base_url: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")

        year: int | None = None
        month: int | None = None
        current_city: str | None = None
        day: int | None = None

        events: list[Event] = []
        for tag in soup.find_all(["h2", "h3", "h4", "h5"]):
            year, month, day = self._parse_heading_state(tag, year, month, day)

            if tag.name == "h3":
                current_city = self._normalize_whitespace(tag.get_text(" ", strip=True)) or None
                continue

            if tag.name != "h5":
                continue

            for link in tag.find_all("a", href=True):
                event = self._build_event_from_list_item(
                    link=link,
                    event_heading=tag,
                    base_url=base_url,
                    year=year,
                    month=month,
                    day=day,
                    city=current_city,
                )
                if event is not None:
                    events.append(event)

        deduplicated_by_url: dict[str, Event] = {}
        for event in events:
            deduplicated_by_url[event.detail_url] = event
        deduplicated_events = sorted(
            deduplicated_by_url.values(), key=lambda event: event.starts_at
        )
        _LOG.info("Na stránce %s nalezeno %d událostí", base_url, len(deduplicated_events))
        return deduplicated_events

    def collect_events(self, calendar_url: str) -> list[Event]:
        _LOG.info("Stahuji hlavní kalendář %s", calendar_url)
        calendar_html = self.fetch_text(calendar_url)
        return self.parse_events(calendar_html, calendar_url)

    def _build_event_from_list_item(
        self,
        *,
        link: Tag,
        event_heading: Tag,
        base_url: str,
        year: int | None,
        month: int | None,
        day: int | None,
        city: str | None,
    ) -> Event | None:
        href_value = link.get("href")
        if not isinstance(href_value, str):
            return None

        href = href_value.strip()
        if not href:
            return None

        full_url = urljoin(base_url, href)
        if "karolakvido.cz" not in full_url:
            return None
        if "/akce_karol_a_kvido/" not in full_url and "karol-a-kvido-slavi" not in full_url:
            return None

        title = self._normalize_whitespace(link.get_text(" ", strip=True))
        if not title:
            return None

        block_text = self._collect_event_block_text(event_heading)
        hour, minute = self._extract_time(block_text)
        location = self._extract_location_from_list_block(block_text, city)

        if year is None or month is None or day is None:
            _LOG.warning("Přeskakuji '%s' (%s): chybí datum v seznamu", title, full_url)
            return None

        starts_at = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(TZ_NAME))
        return Event(
            title=title,
            starts_at=starts_at,
            location=location,
            detail_url=full_url,
            city=city,
        )

    def _collect_event_block_text(self, event_heading: Tag) -> str:
        chunks: list[str] = []
        for sibling in event_heading.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in {"h2", "h3", "h4", "h5"}:
                break
            if isinstance(sibling, Tag) and sibling.name in {"script", "style"}:
                continue

            if isinstance(sibling, Tag):
                text = self._normalize_whitespace(sibling.get_text(" ", strip=True))
            elif isinstance(sibling, NavigableString):
                text = self._normalize_whitespace(str(sibling))
            else:
                text = ""

            if not text:
                continue
            normalized = self._strip_diacritics(text).lower()
            if normalized in {"vstupenky", "jiz brzy"}:
                continue
            chunks.append(text)

        return " ".join(chunks).strip()

    def _extract_time(self, block_text: str) -> tuple[int, int]:
        match = _TIME_RE.search(block_text)
        if match is None:
            _LOG.warning("U události chybí čas, nastavuji 00:00")
            return 0, 0
        return int(match.group("hour")), int(match.group("minute"))

    def _extract_location_from_list_block(self, block_text: str, city: str | None) -> str:
        if block_text:
            location_match = _LOCATION_RE.search(block_text)
            if location_match:
                location = location_match.group("location").strip(" ,")
                if location:
                    return location

            simplified = re.sub(
                r",\s*v(?:e)?\s*\d{1,2}:\d{2}.*$", "", block_text, flags=re.IGNORECASE
            )
            simplified = simplified.strip(" ,")
            if simplified and not re.fullmatch(
                r"v(?:e)?\s*\d{1,2}:\d{2}(?:\s*hodin?)?", simplified, flags=re.IGNORECASE
            ):
                return simplified

        if city:
            return city
        return "Neuvedeno"

    def _parse_heading_state(
        self,
        tag: Tag,
        current_year: int | None,
        current_month: int | None,
        current_day: int | None,
    ) -> tuple[int | None, int | None, int | None]:
        text = self._normalize_whitespace(tag.get_text(" ", strip=True))
        if not text:
            return current_year, current_month, current_day

        if tag.name == "h2":
            match = _YEAR_AND_MONTH_RE.search(text)
            if match:
                month_token = self._strip_diacritics(match.group("month")).lower()
                month_number = _MONTH_FROM_HEADING.get(month_token)
                if month_number is not None:
                    return int(match.group("year")), month_number, current_day
            return current_year, current_month, current_day

        if tag.name == "h4":
            match = _DAY_LABEL_RE.search(text)
            if match:
                day_number = int(match.group("day"))
                month_token = self._strip_diacritics(match.group("month") or "").lower()
                month_from_day = _MONTH_FROM_DAY_LABEL.get(month_token[:4]) if month_token else None
                return current_year, (month_from_day or current_month), day_number

        return current_year, current_month, current_day

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return " ".join(text.split())

    @staticmethod
    def _strip_diacritics(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(char for char in normalized if not unicodedata.combining(char))
