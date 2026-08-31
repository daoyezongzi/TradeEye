from __future__ import annotations

import datetime as dt
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse
from xml.parsers import expat

import requests

from tradeeye.config import (
    DEFAULT_NEWS_RSS_ALLOWED_HOSTS,
    NEWS_RESOURCES_DIR,
    Settings,
    resolve_repo_path,
)

logger = logging.getLogger(__name__)

_USER_AGENT = "TradeEyeRSS/1.0 (+https://github.com)"
MAX_FEED_SOURCES = 20
MAX_FEED_FILE_BYTES = 128 * 1024
MAX_FEED_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_FEED_ITEMS = 200
MAX_FEED_URL_CHARS = 2048
MAX_REDIRECTS = 3
MAX_TITLE_CHARS = 512
MAX_SUMMARY_CHARS = 4096
MAX_LINK_CHARS = 2048
MAX_LOG_PATH_CHARS = 256
_FORBIDDEN_XML_DECLARATION = b"<!doctype"
_FORBIDDEN_XML_ENTITY = b"<!entity"


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published_at: dt.datetime
    summary: str = ""


FeedFetcher = Callable[[str], list[NewsItem]]


class NewsCollectionError(RuntimeError):
    """Raised when feeds were configured but none could be fetched."""


class FeedSecurityError(ValueError):
    """Raised when a configured feed violates the RSS trust boundary."""


class FeedFetchError(RuntimeError):
    """Raised when a feed cannot be safely downloaded or parsed."""


def fetch_feed(
    url: str,
    timeout: int = 10,
    http_client=requests,
    allowed_hosts: Iterable[str] | None = None,
) -> list[NewsItem]:
    current_url = validate_feed_url(url, allowed_hosts=allowed_hosts)
    for redirect_index in range(MAX_REDIRECTS + 1):
        response = None
        try:
            response = http_client.get(
                current_url,
                headers={"User-Agent": _USER_AGENT},
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
            status_code = int(getattr(response, "status_code", 200) or 200)
            if 300 <= status_code < 400:
                if redirect_index >= MAX_REDIRECTS:
                    raise FeedSecurityError("RSS redirect limit exceeded")
                location = _header_value(response, "Location")
                if not location:
                    raise FeedFetchError("RSS redirect did not include a Location header")
                current_url = validate_feed_url(
                    urljoin(current_url, location),
                    allowed_hosts=allowed_hosts,
                )
                continue

            response.raise_for_status()
            content = _read_response_content(response)
            return _parse_feed_xml(content, source_url=current_url)
        except FeedSecurityError:
            raise
        except FeedFetchError:
            raise
        except Exception as exc:
            raise FeedFetchError(
                f"RSS fetch failed for {redact_feed_url(current_url)} ({type(exc).__name__})"
            ) from None
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    raise FeedSecurityError("RSS redirect limit exceeded")


def collect_news(
    settings: Settings,
    now: dt.datetime | None = None,
    fetcher: FeedFetcher | None = None,
) -> list[NewsItem]:
    feed_urls = load_feed_urls(settings)
    if not feed_urls:
        logger.warning("No RSS feed configured, skip daily news collection")
        return []

    all_items: list[NewsItem] = []
    successful_feeds = 0
    if fetcher is None:
        fetcher = lambda feed_url: fetch_feed(
            feed_url,
            allowed_hosts=settings.news_rss_allowed_hosts,
        )
    for url in feed_urls:
        try:
            all_items.extend(fetcher(url))
            successful_feeds += 1
        except Exception as exc:
            logger.warning(
                "Failed to pull RSS feed: %s (%s)",
                redact_feed_url(url),
                type(exc).__name__,
            )

    if successful_feeds == 0:
        raise NewsCollectionError(f"All {len(feed_urls)} configured RSS feeds failed")

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
    return sorted_items[: min(settings.news_max_items, MAX_FEED_ITEMS)]


def load_feed_urls(settings: Settings) -> list[str]:
    urls = list(settings.news_rss_feeds[:MAX_FEED_SOURCES])
    if len(settings.news_rss_feeds) > MAX_FEED_SOURCES:
        logger.warning("RSS source limit reached; ignoring configured sources after %d", MAX_FEED_SOURCES)

    feed_file = resolve_repo_path(
        settings.news_rss_feeds_file,
        NEWS_RESOURCES_DIR,
        "NEWS_RSS_FEEDS_FILE",
    )
    if feed_file.exists():
        if feed_file.stat().st_size > MAX_FEED_FILE_BYTES:
            raise ValueError(
                f"NEWS_RSS_FEEDS_FILE exceeds the {MAX_FEED_FILE_BYTES}-byte limit"
            )
        for line in feed_file.read_text(encoding="utf-8").splitlines():
            cleaned = line.split("#", maxsplit=1)[0].strip()
            if cleaned:
                urls.append(cleaned)
                if len(urls) >= MAX_FEED_SOURCES:
                    logger.warning("RSS source limit reached; ignoring remaining feed file entries")
                    break

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


def validate_feed_url(url: str, allowed_hosts: Iterable[str] | None = None) -> str:
    """Validate one feed URL before every request, including redirects."""
    raw_url = str(url or "").strip()
    if len(raw_url) > MAX_FEED_URL_CHARS:
        raise FeedSecurityError("RSS URL exceeds the character limit")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw_url):
        raise FeedSecurityError("RSS URL contains control characters")
    try:
        parsed = urlparse(raw_url)
    except ValueError:
        raise FeedSecurityError("RSS URL is malformed") from None
    scheme = parsed.scheme.lower()
    if scheme != "https":
        raise FeedSecurityError("RSS URL must use HTTPS")
    if parsed.username or parsed.password:
        raise FeedSecurityError("RSS URL must not contain embedded credentials")
    if not parsed.hostname:
        raise FeedSecurityError("RSS URL must contain a hostname")
    try:
        port = parsed.port
    except ValueError:
        raise FeedSecurityError("RSS URL contains an invalid port") from None
    if port not in (None, 443):
        raise FeedSecurityError("RSS URL must use the default HTTPS port")

    host = parsed.hostname.rstrip(".").lower()
    hosts = DEFAULT_NEWS_RSS_ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts
    configured_hosts = tuple(
        str(item).strip().rstrip(".").lower()
        for item in hosts
        if str(item).strip()
    )
    if host not in configured_hosts:
        raise FeedSecurityError(f"RSS host is not allowlisted: {host}")

    # Even an explicitly configured host must not be a literal private or
    # special-use address. Host allowlisting remains the primary control.
    try:
        address = ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise FeedSecurityError("RSS URL must not target a private or special-use address")

    return raw_url


def redact_feed_url(url: str) -> str:
    """Keep only a safe URL skeleton for logs and error messages."""
    try:
        parsed = urlparse(str(url or "").strip())
        hostname = parsed.hostname
    except ValueError:
        return "<invalid-rss-url>"
    if not parsed.scheme or not hostname:
        return "<invalid-rss-url>"
    try:
        port = parsed.port
    except ValueError:
        port = None
    host = _sanitize_log_component(hostname.rstrip(".").lower(), max_chars=256)
    netloc = host if port in (None, 443) else f"{host}:{port}"
    path = _sanitize_log_component(parsed.path or "/", max_chars=MAX_LOG_PATH_CHARS)
    return f"{parsed.scheme.lower()}://{netloc}{path}"


def _header_value(response: object, name: str) -> str:
    headers = getattr(response, "headers", {}) or {}
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return ""
    return str(getter(name, "") or "").strip()


def _read_response_content(response: object) -> bytes:
    content_length = _header_value(response, "Content-Length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise FeedFetchError("RSS response has an invalid Content-Length") from None
        if declared_length < 0 or declared_length > MAX_FEED_RESPONSE_BYTES:
            raise FeedFetchError("RSS response exceeds the byte limit")

    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        chunks: list[bytes] = []
        total = 0
        for chunk in iterator(chunk_size=64 * 1024):
            if not chunk:
                continue
            chunk_bytes = bytes(chunk)
            total += len(chunk_bytes)
            if total > MAX_FEED_RESPONSE_BYTES:
                raise FeedFetchError("RSS response exceeds the byte limit")
            chunks.append(chunk_bytes)
        return b"".join(chunks)

    # Small test doubles and compatible clients may only expose ``content``.
    content = bytes(getattr(response, "content", b"") or b"")
    if len(content) > MAX_FEED_RESPONSE_BYTES:
        raise FeedFetchError("RSS response exceeds the byte limit")
    return content


def _parse_feed_xml(content: bytes, source_url: str) -> list[NewsItem]:
    normalized_content = bytes(content or b"")
    lowered_content = normalized_content.lower()
    if _FORBIDDEN_XML_DECLARATION in lowered_content or _FORBIDDEN_XML_ENTITY in lowered_content:
        raise FeedSecurityError("RSS XML must not contain DTD or entity declarations")

    # Build the ElementTree through Expat callbacks so DTD/entity declarations
    # are rejected by the parser itself, including encodings where a byte-level
    # marker scan would not match. XInclude is not processed automatically.
    root = _parse_xml_safely(normalized_content)
    root_tag = _local_name(root.tag).lower()
    if root_tag in {"rss", "rdf", "rdf:rdf"}:
        return _parse_rss_items(root, source_url=source_url)
    if root_tag == "feed":
        return _parse_atom_items(root, source_url=source_url)
    logger.warning("Unknown feed root tag; ignoring feed")
    return []


def _parse_xml_safely(content: bytes) -> ET.Element:
    parser = expat.ParserCreate(namespace_separator="}")
    builder = ET.TreeBuilder()

    def reject_xml_declaration(*_args: object) -> None:
        raise FeedSecurityError("RSS XML must not contain DTD or entity declarations")

    parser.StartDoctypeDeclHandler = reject_xml_declaration
    parser.EntityDeclHandler = reject_xml_declaration
    parser.ExternalEntityRefHandler = reject_xml_declaration
    parser.UnparsedEntityDeclHandler = reject_xml_declaration
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(content, True)
        return builder.close()
    except FeedSecurityError:
        raise
    except expat.ExpatError as exc:
        raise FeedFetchError("RSS XML could not be parsed") from exc


def _parse_rss_items(root: ET.Element, source_url: str) -> list[NewsItem]:
    channel = root.find("channel")
    if channel is None:
        return []

    source = _clean_text(_find_child_text(channel, "title"), MAX_TITLE_CHARS) or _domain_from_url(source_url)
    items: list[NewsItem] = []
    for node in channel.findall("item"):
        if len(items) >= MAX_FEED_ITEMS:
            break
        title = _clean_text(_find_child_text(node, "title"), MAX_TITLE_CHARS)
        if not title:
            continue

        link = _clean_text(_find_child_text(node, "link"), MAX_LINK_CHARS)
        summary = _clean_text(
            _find_child_text(node, "description") or _find_child_text(node, "summary"),
            MAX_SUMMARY_CHARS,
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
    source = _clean_text(_find_child_text(root, "title"), MAX_TITLE_CHARS) or _domain_from_url(source_url)
    items: list[NewsItem] = []

    for node in _find_children(root, "entry"):
        if len(items) >= MAX_FEED_ITEMS:
            break
        title = _clean_text(_find_child_text(node, "title"), MAX_TITLE_CHARS)
        if not title:
            continue

        link = _clean_text(_find_atom_link(node), MAX_LINK_CHARS)
        summary = _clean_text(
            _find_child_text(node, "summary") or _find_child_text(node, "content"),
            MAX_SUMMARY_CHARS,
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


def _clean_text(value: str, max_chars: int) -> str:
    return " ".join(value.split()).strip()[:max_chars]


def _sanitize_log_component(value: str, max_chars: int) -> str:
    safe = "".join(character if character.isprintable() else "?" for character in value)
    if len(safe) > max_chars:
        return f"{safe[:max_chars]}..."
    return safe


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", maxsplit=1)[-1]
    return tag


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)
