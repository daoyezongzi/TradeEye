from tradeeye.config import (
    DEFAULT_ALLOWED_EXCHANGES,
    DEFAULT_STOCKS,
    PRICE_RANGES,
    Settings,
    extract_exchange,
    load_settings,
    parse_bool,
    parse_exchange_list,
    parse_industry_list,
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
    monkeypatch.setenv("DIFY_API_KEY", "api-key")
    monkeypatch.setenv("FEISHU_WEBHOOK", "https://example.com")
    monkeypatch.setenv("DIFY_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("DEBUG_MODE", "true")
    monkeypatch.setenv("MY_STOCKS", "000001.SZ,000002.SZ")
    monkeypatch.setenv("ALLOWED_EXCHANGES", "沪深")
    monkeypatch.setenv("RECOMMENDER_INDUSTRIES", "半导体,电力设备")
    load_settings.cache_clear()

    settings = load_settings()

    assert isinstance(settings, Settings)
    assert settings.tushare_token == "token"
    assert settings.dify_api_key == "api-key"
    assert settings.feishu_webhook == "https://example.com"
    assert settings.dify_base_url == "https://api.example.com/v1"
    assert settings.debug_mode is True
    assert settings.my_stocks == ["000001.SZ", "000002.SZ"]
    assert settings.allowed_exchanges == ("SH", "SZ")
    assert settings.recommender_industries == ("半导体", "电力设备")
