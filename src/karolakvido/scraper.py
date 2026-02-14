from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from . import TZ_NAME

_LOG = logging.getLogger(__name__)

_MONTHS = {
    "ledna": 1,
    "unora": 2,
    "brezna": 3,
    "dubna": 4,
    "kvetna": 5,
    "cervna": 6,
    "cervence": 7,
    "srpna": 8,
    "zari": 9,
    "rijna": 10,
    "listopadu": 11,
    "prosince": 12,
}

_DATETIME_RE = re.compile(
    r"(?P<day>\d{1,2})\.\s*(?P<month>[A-Za-zÁ-ž]+)\s*(?P<year>\d{4})\s*,?\s*(?:(?:v|ve)\s*)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?:\s*hodin)?",
    re.IGNORECASE,
)

_DATETIME_WITHOUT_YEAR_RE = re.compile(
    r"(?P<day>\d{1,2})\.\s*(?P<month>[A-Za-zÁ-ž]+)\s*,?\s*(?:(?:v|ve)\s*)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?:\s*hodin)?",
    re.IGNORECASE,
)

_YEAR_RE = re.compile(r"\b(?P<year>20\d{2})\b")
_NUMERIC_DATE_RE = re.compile(r"\b(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>20\d{2})\b")
_TIME_RE = re.compile(r"\b(?P<hour>\d{1,2})[:\.](?P<minute>\d{2})\b")


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
        retry_at = retry_at.replace(tzinfo=datetime.UTC)

    seconds = (retry_at - datetime.now(datetime.UTC)).total_seconds()
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
    information_text: str
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

    def parse_events(self, html: str, base_url: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[dict[str, str]] = []
        current_city: str | None = None

        for heading in soup.find_all(["h3", "h5"]):
            if heading.name == "h3":
                current_city = heading.get_text(" ", strip=True) or None
                continue

            links = heading.find_all("a", href=True)
            for link in links:
                href = link["href"].strip()
                if not href:
                    continue
                full_url = urljoin(base_url, href)
                if "karolakvido.cz" not in full_url:
                    continue
                if "/akce_karol_a_kvido/" not in full_url and "karol-a-kvido-slavi" not in full_url:
                    continue

                title = link.get_text(" ", strip=True)
                if not title:
                    continue

                events.append({"title": title, "detail_url": full_url, "city": current_city or ""})

        deduplicated: dict[str, dict[str, str]] = {}
        for event in events:
            deduplicated[event["detail_url"]] = event
        deduplicated_events = list(deduplicated.values())
        _LOG.info(
            "Na stránce %s nalezeno %d kandidátů, po deduplikaci %d",
            base_url,
            len(events),
            len(deduplicated_events),
        )
        return deduplicated_events

    def parse_detail(
        self,
        html: str,
        detail_url: str,
        fallback_title: str,
        city: str | None,
    ) -> Event:
        soup = BeautifulSoup(html, "html.parser")

        title = self._extract_title(soup) or fallback_title
        starts_at = self._extract_datetime(soup)
        location = self._extract_location(soup, city)
        info = self._extract_information(soup)

        return Event(
            title=title,
            starts_at=starts_at,
            location=location,
            detail_url=detail_url,
            information_text=info,
            city=city,
        )

    def collect_events(self, calendar_url: str) -> list[Event]:
        _LOG.info("Stahuji hlavní kalendář %s", calendar_url)
        calendar_html = self.fetch_text(calendar_url)
        basic_events = self.parse_events(calendar_html, calendar_url)
        _LOG.info("Zpracovávám detaily %d událostí", len(basic_events))

        events: list[Event] = []
        for basic in basic_events:
            while True:
                try:
                    detail_html = self.fetch_text(basic["detail_url"])
                    event = self.parse_detail(
                        detail_html,
                        basic["detail_url"],
                        basic["title"],
                        basic["city"] or None,
                    )
                    events.append(event)
                    break
                except requests.HTTPError as exc:
                    response = exc.response
                    status_code = response.status_code if response is not None else None
                    if status_code == 429:
                        self._increase_delay_after_429()
                        retry_after = _parse_retry_after_seconds(response.headers.get("Retry-After"))
                        wait_seconds = retry_after if retry_after is not None else self._current_delay
                        wait_seconds = min(max(wait_seconds, self.request_delay), self.max_request_delay)
                        _LOG.warning(
                            "Událost '%s' (%s) vrátila 429, čekám %.1f s a zkouším znovu",
                            basic["title"],
                            basic["detail_url"],
                            wait_seconds,
                        )
                        self._sleep(wait_seconds)
                        continue

                    _LOG.warning(
                        "Přeskakuji událost '%s' (%s): %s",
                        basic["title"],
                        basic["detail_url"],
                        exc,
                    )
                    break
                except (requests.RequestException, ValueError) as exc:
                    _LOG.warning(
                        "Přeskakuji událost '%s' (%s): %s",
                        basic["title"],
                        basic["detail_url"],
                        exc,
                    )
                    break

        events.sort(key=lambda event: event.starts_at)
        _LOG.info("Úspěšně zpracováno %d událostí", len(events))
        return events

    def _extract_title(self, soup: BeautifulSoup) -> str | None:
        heading = soup.find("h1")
        if heading:
            text = heading.get_text(" ", strip=True)
            if text:
                return text
        return None

    def _extract_datetime(self, soup: BeautifulSoup) -> datetime:
        when_headings = soup.find_all(
            lambda tag: isinstance(tag, Tag)
            and tag.name in {"h2", "h3"}
            and "kdy" in tag.get_text(" ", strip=True).lower()
        )

        full_text = soup.get_text(" ", strip=True)

        for when_heading in when_headings:
            search_text = ""
            for sibling in when_heading.next_siblings:
                if isinstance(sibling, Tag) and sibling.name in {"h2", "h3"}:
                    break
                if isinstance(sibling, Tag):
                    search_text += " " + sibling.get_text(" ", strip=True)
                elif isinstance(sibling, NavigableString):
                    search_text += " " + self._normalize_whitespace(str(sibling))

            if not search_text:
                continue

            when_dt = self._find_valid_datetime_with_year(search_text)
            if when_dt is not None:
                return when_dt

            when_dt_without_year = self._find_valid_datetime_without_year(search_text, full_text)
            if when_dt_without_year is not None:
                return when_dt_without_year

        fallback_dt = self._find_valid_datetime_with_year(full_text)
        if fallback_dt is not None:
            return fallback_dt

        numeric_dt = self._find_valid_numeric_date(full_text)
        if numeric_dt is not None:
            return numeric_dt

        raise ValueError("Nelze najít datum a čas akce.")

    def _find_valid_datetime_with_year(self, text: str) -> datetime | None:
        for match in _DATETIME_RE.finditer(text):
            try:
                return self._build_datetime(
                    year=match.group("year"),
                    month=match.group("month"),
                    day=match.group("day"),
                    hour=match.group("hour"),
                    minute=match.group("minute") or "00",
                )
            except ValueError:
                continue
        return None

    def _find_valid_datetime_without_year(self, text: str, full_text: str) -> datetime | None:
        year_match = _YEAR_RE.search(full_text)
        if not year_match:
            return None

        for match in _DATETIME_WITHOUT_YEAR_RE.finditer(text):
            try:
                return self._build_datetime(
                    year=year_match.group("year"),
                    month=match.group("month"),
                    day=match.group("day"),
                    hour=match.group("hour"),
                    minute=match.group("minute") or "00",
                )
            except ValueError:
                continue
        return None

    def _find_valid_numeric_date(self, full_text: str) -> datetime | None:
        for match in _NUMERIC_DATE_RE.finditer(full_text):
            day = int(match.group("day"))
            month = int(match.group("month"))
            year = int(match.group("year"))

            hour = 0
            minute = 0
            window = full_text[match.end() : match.end() + 48]
            time_match = _TIME_RE.search(window)
            if time_match:
                hour = int(time_match.group("hour"))
                minute = int(time_match.group("minute"))

            try:
                return datetime(
                    year,
                    month,
                    day,
                    hour,
                    minute,
                    tzinfo=ZoneInfo(TZ_NAME),
                )
            except ValueError:
                continue

        return None

    def _build_datetime(
        self,
        *,
        year: str,
        month: str,
        day: str,
        hour: str,
        minute: str,
    ) -> datetime:
        month_key = self._strip_diacritics(month).lower()
        month_number = _MONTHS.get(month_key)
        if month_number is None:
            raise ValueError(f"Neznámý měsíc: {month}")

        return datetime(
            int(year),
            month_number,
            int(day),
            int(hour),
            int(minute),
            tzinfo=ZoneInfo(TZ_NAME),
        )

    def _extract_location(self, soup: BeautifulSoup, city: str | None) -> str:
        where_heading = soup.find(
            lambda tag: isinstance(tag, Tag)
            and tag.name in {"h2", "h3"}
            and "kde" in tag.get_text(" ", strip=True).lower()
        )
        if where_heading:
            location_parts: list[str] = []
            for sibling in where_heading.next_siblings:
                if isinstance(sibling, Tag) and sibling.name in {"h2", "h3"}:
                    break
                if isinstance(sibling, Tag):
                    text = sibling.get_text(" ", strip=True)
                    if text:
                        location_parts.append(text)
                elif isinstance(sibling, NavigableString):
                    text = self._normalize_whitespace(str(sibling))
                    if text:
                        location_parts.append(text)
            location = ", ".join(part for part in location_parts if part).strip(", ")
            if location:
                return location

        if city:
            return city
        return "Neuvedeno"

    def _extract_information(self, soup: BeautifulSoup) -> str:
        info_heading = soup.find(
            lambda tag: isinstance(tag, Tag)
            and tag.name in {"h2", "h3"}
            and "informace" in tag.get_text(" ", strip=True).lower()
        )
        if not info_heading:
            return ""

        chunks: list[str] = []
        for node in info_heading.next_elements:
            if node is info_heading:
                continue
            if isinstance(node, NavigableString) and node.parent is info_heading:
                continue

            if isinstance(node, Tag) and node.name in {"h2", "h3"}:
                break
            if isinstance(node, Tag) and node.name in {"script", "style"}:
                continue

            text = ""
            if isinstance(node, NavigableString):
                text = self._normalize_whitespace(str(node))

            if not text:
                continue
            normalized = text.strip(" :").lower()
            if normalized in {"informace", "vstupenky"}:
                continue
            if "všechny akce karol a kvído" in text.lower():
                break
            chunks.append(text)

        return "\n".join(chunks).strip()

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return " ".join(text.split())

    @staticmethod
    def _strip_diacritics(text: str) -> str:
        table = str.maketrans(
            "áäčďéěëíľĺňóôöřšťúůüýž",
            "aacdeeeillnooorstuuuyz",
        )
        return text.translate(table)
