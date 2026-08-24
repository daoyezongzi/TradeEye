import datetime as dt
import inspect

from tradeeye.app import build_final_content, main
from tradeeye.config import Settings


def make_settings(debug_mode: bool = True, stocks: list[str] | None = None) -> Settings:
    return Settings(
        tushare_token="token",
        feishu_webhook="https://example.com",
        debug_mode=debug_mode,
        my_stocks=stocks or ["000001.SZ"],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


def make_strong_payload():
    return {
        "name": "Momentum Corp",
        "trade_date": "20260822",
        "market_regime": {"status": "偏强", "score": 20},
        "latest": {
            "ts_code": "000001.SZ",
            "close": 10.4,
            "open": 10.0,
            "pct_chg": 3.5,
            "turnover_rate": 6.0,
            "volume_ratio": 1.8,
            "amount_ratio_5d": 1.6,
            "net_mf_ratio_pct": 4.2,
            "large_order_net_pct": 2.6,
            "up_limit_room_pct": 5.3,
            "close_strength": 0.88,
            "upper_shadow_pct": 0.4,
            "breakout_10_pct": 0.8,
            "ma5": 10.1,
            "ma10": 9.9,
            "ma20": 9.6,
            "ma5_slope_pct": 0.6,
            "turnover_pct_rank": 0.82,
            "net_mf_ratio_rank": 0.87,
            "large_order_net_rank": 0.83,
            "list_age_days": 600,
            "market": "主板",
        },
        "prev": {"vol": 100, "low": 9.7},
    }


def test_build_final_content_uses_report_date():
    content = build_final_content(["report-a", "report-b"], report_date=dt.date(2026, 4, 9))

    assert "2026-04-09" in content
    assert "盘后诊断汇总报告" in content
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


def test_main_runs_every_stock_through_local_deterministic_report():
    calls: list[str] = []

    def fake_fetcher(code, settings):
        calls.append(f"fetch:{code}")
        return make_strong_payload()

    def fake_builder(stock_data, result, code):
        calls.append(f"build:{code}:{result['raw_score']}:{result['final_status']}")
        return "local-report"

    def fake_notifier(content, settings):
        calls.append(f"notify:{content.count('local-report')}")
        return True

    exit_code = main(
        settings=make_settings(),
        data_fetcher=fake_fetcher,
        notifier=fake_notifier,
        report_builder=fake_builder,
    )

    assert exit_code == 0
    assert calls == ["fetch:000001.SZ", "build:000001.SZ:100:强", "notify:1"]


def test_main_has_no_analyzer_or_signal_recorder_dependency():
    parameters = inspect.signature(main).parameters

    assert "analyzer" not in parameters
    assert "signal_recorder" not in parameters
    assert "llm" not in inspect.getsource(main).lower()


def test_main_returns_nonzero_when_tushare_token_missing():
    settings = Settings(
        tushare_token="",
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=["000001.SZ"],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )

    assert main(settings=settings) == 1


def test_main_reports_failed_codes_and_returns_nonzero():
    notifications: list[str] = []
    settings = make_settings(stocks=["000001.SZ", "000002.SZ"])

    def fake_fetcher(code, settings):
        return make_strong_payload() if code == "000001.SZ" else None

    def fake_notifier(content, settings):
        notifications.append(content)
        return True

    exit_code = main(settings=settings, data_fetcher=fake_fetcher, notifier=fake_notifier)

    assert exit_code == 1
    assert len(notifications) == 1
    assert "Momentum Corp" in notifications[0]
    assert "000002.SZ" in notifications[0]


def test_main_reports_data_provider_exception_as_failed_code():
    notifications: list[str] = []

    def failing_fetcher(code, settings):
        raise RuntimeError("market snapshot unavailable")

    exit_code = main(
        settings=make_settings(),
        data_fetcher=failing_fetcher,
        notifier=lambda content, settings: notifications.append(content) or True,
    )

    assert exit_code == 1
    assert len(notifications) == 1
    assert "000001.SZ" in notifications[0]


def test_main_returns_nonzero_when_notification_fails():
    exit_code = main(
        settings=make_settings(),
        data_fetcher=lambda code, settings: make_strong_payload(),
        notifier=lambda content, settings: False,
    )

    assert exit_code == 1


def test_main_skips_codes_filtered_by_exchange_without_failing():
    calls: list[str] = []
    settings = Settings(
        tushare_token="token",
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=["000001.SZ", "430001.BJ"],
        allowed_exchanges=("SH", "SZ"),
    )

    def fake_fetcher(code, settings):
        calls.append(code)
        return make_strong_payload()

    exit_code = main(
        settings=settings,
        data_fetcher=fake_fetcher,
        notifier=lambda content, settings: True,
    )

    assert exit_code == 0
    assert calls == ["000001.SZ"]


def test_main_reports_key_data_gap_without_assigning_score():
    payload = make_strong_payload()
    del payload["latest"]["ma20"]
    notifications: list[str] = []

    exit_code = main(
        settings=make_settings(),
        data_fetcher=lambda code, settings: payload,
        notifier=lambda content, settings: notifications.append(content) or True,
    )

    assert exit_code == 0
    assert "原始总分：不评分" in notifications[0]
    assert "最终状态：数据不足" in notifications[0]
    assert "latest.ma20" in notifications[0]
