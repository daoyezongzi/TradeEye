import datetime as dt

from tradeeye.config import Settings
from tradeeye.news_app import build_news_content, main
from tradeeye.services.rss import NewsItem


def _make_settings(**kwargs) -> Settings:
    base = dict(
        tushare_token="token",
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
        recommender_industries=(),
        news_rss_feeds=(),
        news_rss_feeds_file="tradeeye/resources/news_feeds.txt",
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


def test_build_news_content_includes_items():
    settings = _make_settings()
    items = [
        NewsItem(
            title="Market rebounds",
            link="https://n.example/1",
            source="Source A",
            published_at=dt.datetime(2026, 5, 13, 1, 0, tzinfo=dt.timezone.utc),
            summary="summary",
        )
    ]

    content = build_news_content(
        items,
        settings=settings,
        report_date=dt.date(2026, 5, 13),
        template_text="{date}\n{count}\n{items_block}",
    )

    assert "2026-05-13" in content
    assert "Market rebounds" in content
    assert "https://n.example/1" in content


def test_main_sends_news_when_items_exist():
    settings = _make_settings()
    items = [
        NewsItem(
            title="Market closes higher",
            link="https://n.example/1",
            source="Source A",
            published_at=dt.datetime.now(dt.timezone.utc),
            summary="summary",
        )
    ]
    calls: list[tuple[str, str]] = []

    def fake_collector(_settings):
        return items

    def fake_notifier(content, _settings, title):
        calls.append((title, content))
        return True

    exit_code = main(settings=settings, collector=fake_collector, notifier=fake_notifier)

    assert exit_code == 0
    assert len(calls) == 1
    assert "Market closes higher" in calls[0][1]


def test_main_skips_send_when_no_items_and_push_empty_disabled():
    settings = _make_settings(news_push_when_empty=False)
    called = False

    def fake_notifier(content, _settings, title):
        nonlocal called
        called = True
        return True

    exit_code = main(settings=settings, collector=lambda _settings: [], notifier=fake_notifier)

    assert exit_code == 0
    assert called is False


def test_main_sends_empty_report_when_enabled():
    settings = _make_settings(news_push_when_empty=True)
    calls: list[str] = []

    def fake_notifier(content, _settings, title):
        calls.append(content)
        return True

    exit_code = main(settings=settings, collector=lambda _settings: [], notifier=fake_notifier)

    assert exit_code == 0
    assert len(calls) == 1


def test_main_returns_nonzero_when_notification_fails():
    settings = _make_settings(news_push_when_empty=True)

    def fake_notifier(content, _settings, title):
        return False

    exit_code = main(settings=settings, collector=lambda _settings: [], notifier=fake_notifier)

    assert exit_code == 1
