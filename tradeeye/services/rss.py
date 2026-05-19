from __future__ import annotations

import datetime as dt
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlparse

import requests

from tradeeye.config import Settings

logger = logging.getLogger(__name__)

_USER_AGENT = "TradeEyeRSS/1.0 (+https://github.com)"


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published_at: dt.datetime
    summary: str = ""


FeedFetcher = Callable[[str], list[NewsItem]]


def fetch_feed(
    url: str,
    timeout: int = 10,
    http_client=requests,
) -> list[NewsItem]:
    response = http_client.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return _parse_feed_xml(response.content, source_url=url)


def collect_news(
    settings: Settings,
    now: dt.datetime | None = None,
    fetcher: FeedFetcher = fetch_feed,
) -> list[NewsItem]:
    feed_urls = load_feed_urls(settings)
    if not feed_urls:
        logger.warning("No RSS feed configured, skip daily news collection")
        return []

    all_items: list[NewsItem] = []
    for url in feed_urls:
        try:
            all_items.extend(fetcher(url))
        except Exception:
            logger.exception("Failed to pull RSS feed: %s", url)

    filtered_items = filter_news(
        all_items,
        include_keywords=settings.news_include_keywords,
        exclude_keywords=settings.news_exclude_keywords,
        lookback_hours=settings.news_lookback_hours,
        now=now,
    )
    deduped_items = dedupe_news(filtered_items)
    sorted_items = sorted(
        deduped_items,
        key=lambda item: _as_utc(item.published_at),
        reverse=True,
    )
    return sorted_items[: settings.news_max_items]


def load_feed_urls(settings: Settings) -> list[str]:
    urls = list(settings.news_rss_feeds)

    feed_file = Path(settings.news_rss_feeds_file)
    if feed_file.exists():
        for line in feed_file.read_text(encoding="utf-8").splitlines():
            cleaned = line.split("#", maxsplit=1)[0].strip()
            if cleaned:
                urls.append(cleaned)

    return list(dict.fromkeys(urls))


def dedupe_news(items: Iterable[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    deduped: list[NewsItem] = []

    for item in items:
        key = _build_dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def filter_news(
    items: Iterable[NewsItem],
    include_keywords: Iterable[str],
    exclude_keywords: Iterable[str],
    lookback_hours: int,
    now: dt.datetime | None = None,
) -> list[NewsItem]:
    now_utc = _as_utc(now or dt.datetime.now(dt.timezone.utc))
    cutoff = now_utc - dt.timedelta(hours=lookback_hours)
    include_words = tuple(word.strip().lower() for word in include_keywords if word.strip())
    exclude_words = tuple(word.strip().lower() for word in exclude_keywords if word.strip())

    filtered: list[NewsItem] = []
    for item in items:
        published = _as_utc(item.published_at)
        if published < cutoff:
            continue

        text = f"{item.title}\n{item.summary}\n{item.source}".lower()
        if include_words and not any(word in text for word in include_words):
            continue
        if exclude_words and any(word in text for word in exclude_words):
            continue
        filtered.append(item)

    return filtered


def _parse_feed_xml(content: bytes, source_url: str) -> list[NewsItem]:
    root = ET.fromstring(content)
    root_tag = _local_name(root.tag).lower()
    if root_tag in {"rss", "rdf", "rdf:rdf"}:
        return _parse_rss_items(root, source_url=source_url)
    if root_tag == "feed":
        return _parse_atom_items(root, source_url=source_url)
    logger.warning("Unknown feed root tag: %s", root.tag)
    return []


def _parse_rss_items(root: ET.Element, source_url: str) -> list[NewsItem]:
    channel = root.find("channel")
    if channel is None:
        return []

    source = _clean_text(_find_child_text(channel, "title")) or _domain_from_url(source_url)
    items: list[NewsItem] = []
    for node in channel.findall("item"):
        title = _clean_text(_find_child_text(node, "title"))
        if not title:
            continue

        link = _clean_text(_find_child_text(node, "link"))
        summary = _clean_text(
            _find_child_text(node, "description") or _find_child_text(node, "summary")
        )
        published_at = _parse_datetime_text(
            _find_child_text(node, "pubDate")
            or _find_child_text(node, "date")
            or _find_child_text(node, "published")
        )
        items.append(
            NewsItem(
                title=title,
                link=link,
                source=source,
                published_at=published_at,
                summary=summary,
            )
        )
    return items


def _parse_atom_items(root: ET.Element, source_url: str) -> list[NewsItem]:
    source = _clean_text(_find_child_text(root, "title")) or _domain_from_url(source_url)
    items: list[NewsItem] = []

    for node in _find_children(root, "entry"):
        title = _clean_text(_find_child_text(node, "title"))
        if not title:
            continue

        link = _clean_text(_find_atom_link(node))
        summary = _clean_text(
            _find_child_text(node, "summary") or _find_child_text(node, "content")
        )
        published_at = _parse_datetime_text(
            _find_child_text(node, "published") or _find_child_text(node, "updated")
        )
        items.append(
            NewsItem(
                title=title,
                link=link,
                source=source,
                published_at=published_at,
                summary=summary,
            )
        )
    return items


def _find_atom_link(node: ET.Element) -> str:
    for child in node:
        if _local_name(child.tag).lower() != "link":
            continue
        href = child.attrib.get("href", "")
        if href:
            return href
        if child.text:
            return child.text
    return ""


def _find_child_text(node: ET.Element, child_name: str) -> str:
    child_name = child_name.lower()
    for child in node:
        if _local_name(child.tag).lower() == child_name:
            return child.text or ""
    return ""


def _find_children(node: ET.Element, child_name: str) -> list[ET.Element]:
    child_name = child_name.lower()
    return [child for child in node if _local_name(child.tag).lower() == child_name]


def _build_dedupe_key(item: NewsItem) -> str:
    if item.link:
        return f"link:{item.link.strip().lower()}"
    published = _as_utc(item.published_at).isoformat()
    return f"title:{item.title.strip().lower()}|published:{published}"


def _parse_datetime_text(value: str) -> dt.datetime:
    raw = value.strip() if isinstance(value, str) else ""
    if raw:
        try:
            parsed_dt = parsedate_to_datetime(raw)
            if parsed_dt.tzinfo is None:
                return parsed_dt.replace(tzinfo=dt.timezone.utc)
            return parsed_dt.astimezone(dt.timezone.utc)
        except (TypeError, ValueError):
            pass

        try:
            iso_candidate = raw.replace("Z", "+00:00")
            parsed_dt = dt.datetime.fromisoformat(iso_candidate)
            if parsed_dt.tzinfo is None:
                return parsed_dt.replace(tzinfo=dt.timezone.utc)
            return parsed_dt.astimezone(dt.timezone.utc)
        except ValueError:
            pass

    return dt.datetime.now(dt.timezone.utc)


def _domain_from_url(url: str) -> str:
    return urlparse(url).netloc or "Unknown Source"


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", maxsplit=1)[-1]
    return tag


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)
