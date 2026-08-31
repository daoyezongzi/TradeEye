from tradeeye.config import (
    DEFAULT_ALLOWED_EXCHANGES,
    DEFAULT_NEWS_LOOKBACK_HOURS,
    DEFAULT_NEWS_MAX_ITEMS,
    DEFAULT_NEWS_RSS_ALLOWED_HOSTS,
    DEFAULT_STOCKS,
    NEWS_RESOURCES_DIR,
    Settings,
    extract_exchange,
    load_settings,
    parse_bool,
    parse_csv_list,
    parse_exchange_list,
    parse_int,
    parse_stock_list,
    resolve_repo_path,
    split_stocks_by_exchange,
)

import pytest


def test_parse_bool_respects_common_values():
    assert parse_bool("true") is True
    assert parse_bool("False") is False
    assert parse_bool("1") is True
    assert parse_bool("0") is False


def test_parse_stock_list_falls_back_to_defaults():
    assert parse_stock_list(None) == list(DEFAULT_STOCKS)
    assert parse_stock_list("") == list(DEFAULT_STOCKS)


def test_parse_stock_list_validates_and_deduplicates():
    assert parse_stock_list("000001.sz，600000.SH,000001.SZ") == ["000001.SZ", "600000.SH"]

    with pytest.raises(ValueError, match="invalid stock codes"):
        parse_stock_list("not-a-code")


def test_parse_csv_list_supports_empty_and_dedup():
    assert parse_csv_list(None) == ()
    assert parse_csv_list("") == ()
    assert parse_csv_list("a,b,a, c ") == ("a", "b", "c")


def test_parse_int_respects_default_and_minimum():
    assert parse_int(None, default=5, minimum=1) == 5
    assert parse_int("9", default=5, minimum=1) == 9
    assert parse_int("0", default=5, minimum=1) == 5
    assert parse_int("bad", default=5, minimum=1) == 5


def test_parse_exchange_list_supports_aliases():
    assert parse_exchange_list(None) == DEFAULT_ALLOWED_EXCHANGES
    assert parse_exchange_list("SH,SZ") == ("SH", "SZ")
    assert parse_exchange_list("沪深") == ("SH", "SZ")
    assert parse_exchange_list("北交所") == ("BJ",)

    with pytest.raises(ValueError, match="invalid values"):
        parse_exchange_list("SH,UNKNOWN")


def test_split_stocks_by_exchange_uses_suffix():
    included, excluded = split_stocks_by_exchange(
        ["600000.SH", "000001.SZ", "430001.BJ"],
        ("SH", "SZ"),
    )

    assert included == ["600000.SH", "000001.SZ"]
    assert excluded == ["430001.BJ"]
    assert extract_exchange("430001.BJ") == "BJ"


def test_settings_rejects_invalid_direct_market_configuration():
    with pytest.raises(ValueError, match="Invalid stock codes"):
        Settings("token", "", False, ["bad-code"], ("SH",))

    with pytest.raises(ValueError, match="Invalid allowed exchanges"):
        Settings("token", "", False, [], ("US",))


def test_load_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setenv("FEISHU_WEBHOOK", "https://example.com")
    monkeypatch.setenv("DEBUG_MODE", "true")
    monkeypatch.setenv("MY_STOCKS", "000001.SZ,000002.SZ")
    monkeypatch.setenv("ALLOWED_EXCHANGES", "沪深")
    monkeypatch.setenv("NEWS_RSS_FEEDS", "https://a.example/rss.xml,https://b.example/feed.xml")
    monkeypatch.setenv("NEWS_RSS_FEEDS_FILE", "tradeeye/resources/custom_news_feeds.txt")
    monkeypatch.setenv("NEWS_RSS_ALLOWED_HOSTS", "a.example,b.example")
    monkeypatch.setenv("NEWS_LOOKBACK_HOURS", "36")
    monkeypatch.setenv("NEWS_MAX_ITEMS", "20")
    monkeypatch.setenv("NEWS_INCLUDE_KEYWORDS", "A股,美股")
    monkeypatch.setenv("NEWS_EXCLUDE_KEYWORDS", "广告,竞猜")
    monkeypatch.setenv("NEWS_PUSH_WHEN_EMPTY", "true")
    monkeypatch.setenv("NEWS_TEMPLATE_FILE", "tradeeye/resources/custom_template.txt")
    load_settings.cache_clear()

    settings = load_settings()

    assert isinstance(settings, Settings)
    assert settings.tushare_token == "token"
    assert settings.feishu_webhook == "https://example.com"
    assert settings.debug_mode is True
    assert settings.my_stocks == ["000001.SZ", "000002.SZ"]
    assert settings.allowed_exchanges == ("SH", "SZ")
    assert settings.news_rss_feeds == ("https://a.example/rss.xml", "https://b.example/feed.xml")
    assert settings.news_rss_feeds_file == "tradeeye/resources/custom_news_feeds.txt"
    assert settings.news_rss_allowed_hosts == ("a.example", "b.example")
    assert settings.news_lookback_hours == 36
    assert settings.news_max_items == 20
    assert settings.news_include_keywords == ("A股", "美股")
    assert settings.news_exclude_keywords == ("广告", "竞猜")
    assert settings.news_push_when_empty is True
    assert settings.news_template_file == "tradeeye/resources/custom_template.txt"


def test_load_settings_uses_defaults_when_invalid(monkeypatch):
    monkeypatch.setenv("NEWS_RSS_FEEDS", "")
    monkeypatch.setenv("NEWS_RSS_FEEDS_FILE", "")
    monkeypatch.delenv("NEWS_RSS_ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("NEWS_LOOKBACK_HOURS", "0")
    monkeypatch.setenv("NEWS_MAX_ITEMS", "-1")
    monkeypatch.setenv("NEWS_PUSH_WHEN_EMPTY", "invalid")
    load_settings.cache_clear()

    settings = load_settings()

    assert settings.news_rss_feeds == ()
    assert settings.news_rss_allowed_hosts == DEFAULT_NEWS_RSS_ALLOWED_HOSTS
    assert settings.news_lookback_hours == DEFAULT_NEWS_LOOKBACK_HOURS
    assert settings.news_max_items == DEFAULT_NEWS_MAX_ITEMS
    assert settings.news_push_when_empty is False


def test_backtest_lookback_days_default(monkeypatch):
    monkeypatch.delenv("BACKTEST_LOOKBACK_DAYS", raising=False)
    assert Settings.from_env().backtest_lookback_days == 45


def test_backtest_lookback_days_env(monkeypatch):
    monkeypatch.setenv("BACKTEST_LOOKBACK_DAYS", "30")
    assert Settings.from_env().backtest_lookback_days == 30


def test_backtest_lookback_days_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("BACKTEST_LOOKBACK_DAYS", "0")
    assert Settings.from_env().backtest_lookback_days == 45


def test_resolve_repo_path_rejects_paths_outside_allowed_directory(tmp_path):
    with pytest.raises(ValueError, match="NEWS_TEMPLATE_FILE"):
        resolve_repo_path(tmp_path / "secret.txt", NEWS_RESOURCES_DIR, "NEWS_TEMPLATE_FILE")
