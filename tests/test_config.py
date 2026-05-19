from tradeeye.config import (
    DEFAULT_ALLOWED_EXCHANGES,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_NEWS_LOOKBACK_HOURS,
    DEFAULT_NEWS_MAX_ITEMS,
    DEFAULT_STOCKS,
    PRICE_RANGES,
    Settings,
    extract_exchange,
    load_settings,
    parse_bool,
    parse_csv_list,
    parse_exchange_list,
    parse_industry_list,
    parse_int,
    parse_stock_list,
    split_stocks_by_exchange,
)


def test_parse_bool_respects_common_values():
    assert parse_bool("true") is True
    assert parse_bool("False") is False
    assert parse_bool("1") is True
    assert parse_bool("0") is False


def test_parse_stock_list_falls_back_to_defaults():
    assert parse_stock_list(None) == list(DEFAULT_STOCKS)
    assert parse_stock_list("") == list(DEFAULT_STOCKS)


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


def test_parse_industry_list_parses_comma_separated_values():
    assert parse_industry_list(None) == ()
    assert parse_industry_list("半导体,电力设备") == ("半导体", "电力设备")
    assert parse_industry_list("半导体，电力设备,半导体") == ("半导体", "电力设备")


def test_split_stocks_by_exchange_uses_suffix():
    included, excluded = split_stocks_by_exchange(
        ["600000.SH", "000001.SZ", "430001.BJ"],
        ("SH", "SZ"),
    )

    assert included == ["600000.SH", "000001.SZ"]
    assert excluded == ["430001.BJ"]
    assert extract_exchange("430001.BJ") == "BJ"


def test_price_ranges_constant_exists():
    assert PRICE_RANGES["low"] == [0, 10]
    assert PRICE_RANGES["mid"] == [10, 20]


def test_load_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setenv("LLM_API_KEY", "llm-key")
    monkeypatch.setenv("FEISHU_WEBHOOK", "https://example.com")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("LLM_TIMEOUT_SEC", "120")
    monkeypatch.setenv("DEBUG_MODE", "true")
    monkeypatch.setenv("MY_STOCKS", "000001.SZ,000002.SZ")
    monkeypatch.setenv("ALLOWED_EXCHANGES", "沪深")
    monkeypatch.setenv("RECOMMENDER_INDUSTRIES", "半导体,电力设备")
    monkeypatch.setenv("NEWS_RSS_FEEDS", "https://a.example/rss.xml,https://b.example/feed.xml")
    monkeypatch.setenv("NEWS_RSS_FEEDS_FILE", "tradeeye/resources/custom_news_feeds.txt")
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
    assert settings.llm_api_key == "llm-key"
    assert settings.feishu_webhook == "https://example.com"
    assert settings.llm_base_url == "https://api.example.com"
    assert settings.llm_model == "deepseek-v4-flash"
    assert settings.llm_timeout_sec == 120
    assert settings.debug_mode is True
    assert settings.my_stocks == ["000001.SZ", "000002.SZ"]
    assert settings.allowed_exchanges == ("SH", "SZ")
    assert settings.recommender_industries == ("半导体", "电力设备")
    assert settings.news_rss_feeds == ("https://a.example/rss.xml", "https://b.example/feed.xml")
    assert settings.news_rss_feeds_file == "tradeeye/resources/custom_news_feeds.txt"
    assert settings.news_lookback_hours == 36
    assert settings.news_max_items == 20
    assert settings.news_include_keywords == ("A股", "美股")
    assert settings.news_exclude_keywords == ("广告", "竞猜")
    assert settings.news_push_when_empty is True
    assert settings.news_template_file == "tradeeye/resources/custom_template.txt"


def test_load_settings_uses_defaults_when_invalid(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("LLM_TIMEOUT_SEC", "0")
    monkeypatch.setenv("NEWS_RSS_FEEDS", "")
    monkeypatch.setenv("NEWS_RSS_FEEDS_FILE", "")
    monkeypatch.setenv("NEWS_LOOKBACK_HOURS", "0")
    monkeypatch.setenv("NEWS_MAX_ITEMS", "-1")
    monkeypatch.setenv("NEWS_PUSH_WHEN_EMPTY", "invalid")
    load_settings.cache_clear()

    settings = load_settings()

    assert settings.llm_base_url == DEFAULT_LLM_BASE_URL
    assert settings.llm_model == DEFAULT_LLM_MODEL
    assert settings.llm_timeout_sec == 60
    assert settings.news_rss_feeds == ()
    assert settings.news_lookback_hours == DEFAULT_NEWS_LOOKBACK_HOURS
    assert settings.news_max_items == DEFAULT_NEWS_MAX_ITEMS
    assert settings.news_push_when_empty is False
