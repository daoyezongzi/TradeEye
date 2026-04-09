from tradeeye.config import DEFAULT_STOCKS, Settings, load_settings, parse_bool, parse_stock_list


def test_parse_bool_respects_common_values():
    assert parse_bool("true") is True
    assert parse_bool("False") is False
    assert parse_bool("1") is True
    assert parse_bool("0") is False


def test_parse_stock_list_falls_back_to_defaults():
    assert parse_stock_list(None) == list(DEFAULT_STOCKS)
    assert parse_stock_list("") == list(DEFAULT_STOCKS)


def test_load_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setenv("DIFY_API_KEY", "api-key")
    monkeypatch.setenv("FEISHU_WEBHOOK", "https://example.com")
    monkeypatch.setenv("DIFY_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("DEBUG_MODE", "true")
    monkeypatch.setenv("MY_STOCKS", "000001.SZ,000002.SZ")
    load_settings.cache_clear()

    settings = load_settings()

    assert isinstance(settings, Settings)
    assert settings.tushare_token == "token"
    assert settings.dify_api_key == "api-key"
    assert settings.feishu_webhook == "https://example.com"
    assert settings.dify_base_url == "https://api.example.com/v1"
    assert settings.debug_mode is True
    assert settings.my_stocks == ["000001.SZ", "000002.SZ"]
