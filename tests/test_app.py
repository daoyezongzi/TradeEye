import datetime as dt

from tradeeye.app import build_final_content, main
from tradeeye.config import Settings


def make_settings(debug_mode: bool = True) -> Settings:
    return Settings(
        tushare_token="token",
        dify_api_key="api",
        feishu_webhook="https://example.com",
        dify_base_url="https://api.dify.ai/v1",
        debug_mode=debug_mode,
        my_stocks=["000001.SZ"],
    )


def test_build_final_content_uses_report_date():
    content = build_final_content(["report-a", "report-b"], report_date=dt.date(2026, 4, 9))
    assert "2026-04-09" in content
    assert "report-a" in content
    assert "report-b" in content


def test_build_final_content_lists_failed_codes():
    content = build_final_content(
        ["report-a"],
        failed_codes=["000001.SZ", "000002.SZ"],
        report_date=dt.date(2026, 4, 9),
    )

    assert "report-a" in content
    assert "000001.SZ" in content
    assert "000002.SZ" in content


def test_main_runs_end_to_end_with_injected_services():
    calls: list[str] = []

    def fake_fetcher(code, settings):
        calls.append(f"fetch:{code}")
        return {
            "name": "Ping An Bank",
            "latest": {"vol": 60, "pct_chg": 1, "close": 9.2, "open": 9, "ma20": 9, "ma5": 10},
            "prev": {"vol": 100, "low": 8},
        }

    def fake_analyzer(stock_data, tech_result, stock_code, settings):
        calls.append(f"analyze:{stock_code}:{tech_result['score']}")
        return "analysis-result"

    def fake_notifier(content, settings):
        calls.append(f"notify:{content.count('analysis-result')}")
        return True

    exit_code = main(
        settings=make_settings(),
        data_fetcher=fake_fetcher,
        analyzer=fake_analyzer,
        notifier=fake_notifier,
    )

    assert exit_code == 0
    assert calls == ["fetch:000001.SZ", "analyze:000001.SZ:80", "notify:1"]


def test_main_returns_nonzero_when_tushare_token_missing():
    settings = Settings(
        tushare_token="",
        dify_api_key="api",
        feishu_webhook="https://example.com",
        dify_base_url="https://api.dify.ai/v1",
        debug_mode=True,
        my_stocks=["000001.SZ"],
    )

    exit_code = main(settings=settings)

    assert exit_code == 1


def test_main_reports_failed_codes_and_returns_nonzero():
    notifications: list[str] = []
    settings = Settings(
        tushare_token="token",
        dify_api_key="api",
        feishu_webhook="https://example.com",
        dify_base_url="https://api.dify.ai/v1",
        debug_mode=True,
        my_stocks=["000001.SZ", "000002.SZ"],
    )

    def fake_fetcher(code, settings):
        if code == "000001.SZ":
            return {
                "name": "Ping An Bank",
                "latest": {"vol": 60, "pct_chg": 1, "close": 9.2, "open": 9, "ma20": 9, "ma5": 10},
                "prev": {"vol": 100, "low": 8},
            }
        return None

    def fake_analyzer(stock_data, tech_result, stock_code, settings):
        return f"analysis-result:{stock_code}:{tech_result['score']}"

    def fake_notifier(content, settings):
        notifications.append(content)
        return True

    exit_code = main(
        settings=settings,
        data_fetcher=fake_fetcher,
        analyzer=fake_analyzer,
        notifier=fake_notifier,
    )

    assert exit_code == 1
    assert len(notifications) == 1
    assert "analysis-result:000001.SZ:80" in notifications[0]
    assert "000002.SZ" in notifications[0]


def test_main_returns_nonzero_when_notification_fails():
    settings = make_settings()

    def fake_fetcher(code, settings):
        return {
            "name": "Ping An Bank",
            "latest": {"vol": 60, "pct_chg": 1, "close": 9.2, "open": 9, "ma20": 9, "ma5": 10},
            "prev": {"vol": 100, "low": 8},
        }

    def fake_analyzer(stock_data, tech_result, stock_code, settings):
        return "analysis-result"

    def fake_notifier(content, settings):
        return False

    exit_code = main(
        settings=settings,
        data_fetcher=fake_fetcher,
        analyzer=fake_analyzer,
        notifier=fake_notifier,
    )

    assert exit_code == 1
