from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from . import TZ_NAME

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
    r"(?P<day>\d{1,2})\.\s*(?P<month>[A-Za-zÁ-ž]+)\s*(?P<year>\d{4})[^\d]*(?P<hour>\d{1,2}):(?P<minute>\d{2})",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Event:
    title: str
    starts_at: datetime
    location: str
    detail_url: str
    information_text: str
    city: str | None = None


class KarolAKvidoClient:
    def __init__(self, connect_timeout: float = 10.0, read_timeout: float = 30.0) -> None:
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def fetch_text(self, url: str) -> str:
        response = requests.get(url, timeout=(self.connect_timeout, self.read_timeout))
        response.raise_for_status()
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
        return list(deduplicated.values())

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
        calendar_html = self.fetch_text(calendar_url)
        basic_events = self.parse_events(calendar_html, calendar_url)

        events: list[Event] = []
        for basic in basic_events:
            detail_html = self.fetch_text(basic["detail_url"])
            events.append(
                self.parse_detail(
                    detail_html,
                    basic["detail_url"],
                    basic["title"],
                    basic["city"] or None,
                )
            )

        events.sort(key=lambda event: event.starts_at)
        return events

    def _extract_title(self, soup: BeautifulSoup) -> str | None:
        heading = soup.find("h1")
        if heading:
            text = heading.get_text(" ", strip=True)
            if text:
                return text
        return None

    def _extract_datetime(self, soup: BeautifulSoup) -> datetime:
        when_heading = soup.find(
            lambda tag: isinstance(tag, Tag)
            and tag.name in {"h2", "h3"}
            and "kdy" in tag.get_text(" ", strip=True).lower()
        )
        search_text = ""
        if when_heading:
            for sibling in when_heading.next_siblings:
                if isinstance(sibling, Tag) and sibling.name in {"h2", "h3"}:
                    break
                if isinstance(sibling, (Tag, NavigableString)):
                    search_text += " " + self._normalize_whitespace(str(sibling))
        if not search_text:
            search_text = soup.get_text(" ", strip=True)

        match = _DATETIME_RE.search(search_text)
        if not match:
            raise ValueError("Nelze najít datum a čas akce.")

        month_key = self._strip_diacritics(match.group("month")).lower()
        month = _MONTHS.get(month_key)
        if month is None:
            raise ValueError(f"Neznámý měsíc: {match.group('month')}")

        dt = datetime(
            int(match.group("year")),
            month,
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            tzinfo=ZoneInfo(TZ_NAME),
        )
        return dt

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
        for sibling in info_heading.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in {"h2", "h3"}:
                break
            if isinstance(sibling, Tag) and sibling.name in {"script", "style"}:
                continue
            text = ""
            if isinstance(sibling, Tag):
                text = sibling.get_text(" ", strip=True)
            elif isinstance(sibling, NavigableString):
                text = self._normalize_whitespace(str(sibling))

            if not text:
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
