import datetime as dt

from tradeeye.config import Settings
from tradeeye.services.rss import NewsItem, collect_news, fetch_feed, load_feed_urls


class _DummyResponse:
    def __init__(self, content: str):
        self.content = content.encode("utf-8")

    def raise_for_status(self):
        return None


class _DummyHttpClient:
    def __init__(self, payloads: dict[str, str]):
        self._payloads = payloads

    def get(self, url, headers, timeout):
        if url not in self._payloads:
            raise RuntimeError(f"missing payload for {url}")
        return _DummyResponse(self._payloads[url])


def _make_settings(**kwargs) -> Settings:
    base = dict(
        tushare_token="token",
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
        recommender_industries=(),
        news_rss_feeds=(),
        news_rss_feeds_file="not-exists.txt",
        news_lookback_hours=24,
        news_max_items=15,
        news_include_keywords=(),
        news_exclude_keywords=(),
        news_push_when_empty=False,
        news_template_file="tradeeye/resources/news_template.txt",
        llm_api_key="llm-key",
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

    items = fetch_feed("https://example.com/rss", http_client=client)

    assert len(items) == 1
    assert items[0].source == "Example Business"
    assert items[0].title == "Market rises on earnings"
    assert items[0].link == "https://example.com/a"
    assert items[0].published_at.tzinfo is not None


def test_load_feed_urls_merges_env_and_file(tmp_path):
    feed_file = tmp_path / "feeds.txt"
    feed_file.write_text(
        "# comments are ignored\nhttps://c.example/rss\nhttps://a.example/rss\n",
        encoding="utf-8",
    )
    settings = _make_settings(
        news_rss_feeds=("https://a.example/rss", "https://b.example/rss"),
        news_rss_feeds_file=str(feed_file),
    )

    urls = load_feed_urls(settings)

    assert urls == [
        "https://a.example/rss",
        "https://b.example/rss",
        "https://c.example/rss",
    ]


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
