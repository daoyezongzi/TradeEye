import datetime as dt

import pytest

from tradeeye.config import Settings

import tradeeye.services.rss as rss_module
from tradeeye.services.rss import (
    FeedFetchError,
    FeedSecurityError,
    MAX_FEED_ITEMS,
    MAX_FEED_RESPONSE_BYTES,
    MAX_FEED_SOURCES,
    MAX_FEED_URL_CHARS,
    NewsCollectionError,
    NewsItem,
    collect_news,
    fetch_feed,
    load_feed_urls,
    redact_feed_url,
)


class _DummyResponse:
    def __init__(self, content: str | bytes, status_code: int = 200, headers: dict[str, str] | None = None):
        self.content = content.encode("utf-8") if isinstance(content, str) else content
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
        return None

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def close(self):
        self.closed = True


class _DummyHttpClient:
    def __init__(self, payloads: dict[str, str | _DummyResponse]):
        self._payloads = payloads

    def get(self, url, headers, timeout, **_kwargs):
        if url not in self._payloads:
            raise RuntimeError(f"missing payload for {url}")
        payload = self._payloads[url]
        return payload if isinstance(payload, _DummyResponse) else _DummyResponse(payload)


def _make_settings(**kwargs) -> Settings:
    base = dict(
        tushare_token="token",
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
        news_rss_feeds=(),
        news_rss_feeds_file="tradeeye/resources/not-exists.txt",
        news_lookback_hours=24,
        news_max_items=15,
        news_include_keywords=(),
        news_exclude_keywords=(),
        news_push_when_empty=False,
        news_template_file="tradeeye/resources/news_template.txt",
    )
    base.update(kwargs)
    return Settings(**base)


def test_fetch_feed_parses_rss_items():
    rss_xml = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>Example Business</title>
    <item>
      <title>Market rises on earnings</title>
      <link>https://example.com/a</link>
      <pubDate>Tue, 12 May 2026 06:00:00 GMT</pubDate>
      <description>Stocks moved higher.</description>
    </item>
  </channel>
</rss>
"""
    client = _DummyHttpClient({"https://example.com/rss": rss_xml})

    items = fetch_feed(
        "https://example.com/rss",
        http_client=client,
        allowed_hosts={"example.com"},
    )

    assert len(items) == 1
    assert items[0].source == "Example Business"
    assert items[0].title == "Market rises on earnings"
    assert items[0].link == "https://example.com/a"
    assert items[0].published_at.tzinfo is not None


def test_load_feed_urls_merges_env_and_file(tmp_path, monkeypatch):
    feed_file = tmp_path / "feeds.txt"
    feed_file.write_text(
        "# comments are ignored\nhttps://c.example/rss\nhttps://a.example/rss\n",
        encoding="utf-8",
    )
    settings = _make_settings(
        news_rss_feeds=("https://a.example/rss", "https://b.example/rss"),
        news_rss_feeds_file=str(feed_file),
    )
    monkeypatch.setattr(rss_module, "NEWS_RESOURCES_DIR", tmp_path)

    urls = load_feed_urls(settings)

    assert urls == [
        "https://a.example/rss",
        "https://b.example/rss",
        "https://c.example/rss",
    ]


def test_load_feed_urls_rejects_external_configured_file(tmp_path):
    settings = _make_settings(news_rss_feeds_file=str(tmp_path / "outside.txt"))

    with pytest.raises(ValueError, match="NEWS_RSS_FEEDS_FILE"):
        load_feed_urls(settings)


def test_collect_news_filters_dedupes_sorts_and_limits():
    now = dt.datetime(2026, 5, 13, 8, 0, tzinfo=dt.timezone.utc)
    settings = _make_settings(
        news_rss_feeds=("feed-a", "feed-b"),
        news_lookback_hours=24,
        news_max_items=2,
        news_include_keywords=("market",),
        news_exclude_keywords=("rumor",),
    )

    def fake_fetcher(url: str) -> list[NewsItem]:
        if url == "feed-a":
            return [
                NewsItem(
                    title="Market opens higher",
                    link="https://n.example/1",
                    source="Feed A",
                    published_at=now - dt.timedelta(hours=1),
                    summary="equity market update",
                ),
                NewsItem(
                    title="Old market recap",
                    link="https://n.example/old",
                    source="Feed A",
                    published_at=now - dt.timedelta(hours=40),
                    summary="market",
                ),
            ]
        return [
            NewsItem(
                title="Market opens higher",
                link="https://n.example/1",
                source="Feed B",
                published_at=now - dt.timedelta(hours=1),
                summary="duplicate link",
            ),
            NewsItem(
                title="Market rumor explodes",
                link="https://n.example/rumor",
                source="Feed B",
                published_at=now - dt.timedelta(hours=2),
                summary="rumor",
            ),
            NewsItem(
                title="Market closes strong",
                link="https://n.example/2",
                source="Feed B",
                published_at=now - dt.timedelta(hours=3),
                summary="market close",
            ),
        ]

    results = collect_news(settings, now=now, fetcher=fake_fetcher)

    assert [item.link for item in results] == [
        "https://n.example/1",
        "https://n.example/2",
    ]


def test_collect_news_continues_when_one_feed_fails():
    now = dt.datetime(2026, 5, 13, 8, 0, tzinfo=dt.timezone.utc)
    settings = _make_settings(news_rss_feeds=("bad-feed", "good-feed"))

    def fake_fetcher(url: str) -> list[NewsItem]:
        if url == "bad-feed":
            raise RuntimeError("network down")
        return [
            NewsItem(
                title="Market holds gains",
                link="https://n.example/ok",
                source="Good Feed",
                published_at=now - dt.timedelta(hours=1),
                summary="summary",
            )
        ]

    results = collect_news(settings, now=now, fetcher=fake_fetcher)

    assert len(results) == 1
    assert results[0].link == "https://n.example/ok"


def test_collect_news_fails_when_all_configured_feeds_fail():
    settings = _make_settings(news_rss_feeds=("bad-a", "bad-b"))

    def failed_fetcher(_url: str) -> list[NewsItem]:
        raise RuntimeError("network down")

    with pytest.raises(NewsCollectionError, match="All 2 configured RSS feeds failed"):
        collect_news(settings, fetcher=failed_fetcher)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://example.com/rss", "HTTPS"),
        ("https://evil.example/rss", "allowlisted"),
        ("https://user:password@example.com/rss", "credentials"),
    ],
)
def test_fetch_feed_rejects_unsafe_urls(url, message):
    with pytest.raises(FeedSecurityError, match=message):
        fetch_feed(url, http_client=_DummyHttpClient({}), allowed_hosts={"example.com"})


def test_fetch_feed_rejects_empty_allowlist():
    with pytest.raises(FeedSecurityError, match="allowlisted"):
        fetch_feed(
            "https://example.com/rss",
            http_client=_DummyHttpClient({}),
            allowed_hosts=set(),
        )


def test_fetch_feed_rejects_control_and_oversized_urls():
    for url, message in (
        ("https://example.com/rss\nX-Header: injected", "control"),
        (f"https://example.com/{'a' * MAX_FEED_URL_CHARS}", "character"),
    ):
        with pytest.raises(FeedSecurityError, match=message):
            fetch_feed(url, http_client=_DummyHttpClient({}), allowed_hosts={"example.com"})


def test_redact_feed_url_removes_credentials_query_and_fragment():
    redacted = redact_feed_url("https://user:password@example.com/rss?token=secret#latest")

    assert redacted == "https://example.com/rss"
    assert "password" not in redacted
    assert "secret" not in redacted


def test_fetch_feed_revalidates_redirect_destination():
    client = _DummyHttpClient(
        {
            "https://example.com/start": _DummyResponse(
                b"",
                status_code=302,
                headers={"Location": "https://evil.example/rss"},
            )
        }
    )

    with pytest.raises(FeedSecurityError, match="allowlisted"):
        fetch_feed(
            "https://example.com/start",
            http_client=client,
            allowed_hosts={"example.com"},
        )


def test_fetch_feed_rejects_oversized_response():
    client = _DummyHttpClient(
        {
            "https://example.com/rss": _DummyResponse(
                b"<rss />",
                headers={"Content-Length": str(MAX_FEED_RESPONSE_BYTES + 1)},
            )
        }
    )

    with pytest.raises(FeedFetchError, match="byte limit"):
        fetch_feed(
            "https://example.com/rss",
            http_client=client,
            allowed_hosts={"example.com"},
        )


def test_fetch_feed_rejects_dtd_or_entity_declarations():
    for payload in (
        b"<!DOCTYPE rss [<!ENTITY xxe 'blocked'>]><rss />",
        "<!DOCTYPE rss [<!ENTITY xxe 'blocked'>]><rss />".encode("utf-16"),
    ):
        client = _DummyHttpClient({"https://example.com/rss": _DummyResponse(payload)})

        with pytest.raises(FeedSecurityError, match="DTD or entity"):
            fetch_feed(
                "https://example.com/rss",
                http_client=client,
                allowed_hosts={"example.com"},
            )


def test_feed_item_count_is_bounded():
    items_xml = "".join(f"<item><title>Item {index}</title></item>" for index in range(MAX_FEED_ITEMS + 5))
    payload = f"<rss><channel><title>Source</title>{items_xml}</channel></rss>"
    client = _DummyHttpClient({"https://example.com/rss": _DummyResponse(payload)})

    items = fetch_feed(
        "https://example.com/rss",
        http_client=client,
        allowed_hosts={"example.com"},
    )

    assert len(items) == MAX_FEED_ITEMS


def test_feed_source_count_is_bounded(tmp_path, monkeypatch):
    feed_file = tmp_path / "feeds.txt"
    feed_file.write_text(
        "\n".join(f"https://source{index}.example/rss" for index in range(MAX_FEED_SOURCES + 5)),
        encoding="utf-8",
    )
    monkeypatch.setattr(rss_module, "NEWS_RESOURCES_DIR", tmp_path)
    settings = _make_settings(news_rss_feeds=(), news_rss_feeds_file=str(feed_file))

    urls = load_feed_urls(settings)

    assert len(urls) == MAX_FEED_SOURCES


def test_collect_news_redacts_query_credentials_in_logs(caplog):
    url = "https://example.com/rss?token=super-secret"
    caplog.set_level("WARNING", logger="tradeeye.services.rss")

    def failed_fetcher(_url: str):
        raise RuntimeError("network down")

    with pytest.raises(NewsCollectionError):
        collect_news(_make_settings(news_rss_feeds=(url,)), fetcher=failed_fetcher)

    assert "super-secret" not in caplog.text
    assert "https://example.com/rss" in caplog.text
