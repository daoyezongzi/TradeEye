import datetime as dt

import pandas as pd
import pytest

from tradeeye.config import Settings
from tradeeye.services.backtest import (
    SignalRecord,
    build_backtest_report,
    build_backtest_windows,
    evaluate_signals,
    load_signals,
)
from tradeeye.services.portfolio import (
    CLOSED,
    ENTRY_UNAVAILABLE,
    EXPIRED_UNFILLED,
    OPEN,
    SKIPPED_DAILY_LIMIT,
    TradeRecord,
)


def make_settings() -> Settings:
    return Settings(
        tushare_token="token",
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


class FakeClient:
    def trade_cal(self, **kwargs):
        return pd.DataFrame({"cal_date": ["20260803", "20260804"], "is_open": [1, 1]})

    def daily(self, trade_date="", **kwargs):
        return pd.DataFrame([{"ts_code": "600001.SH", "open": 10.2, "close": 9.9}])


def test_load_signals_reads_only_recommend_and_maps_legacy(tmp_path):
    analysis = tmp_path / "analysis.csv"
    analysis.write_text(
        "date,ts_code,name,score,status,close,called_llm\n"
        "20260803,600009.SH,Analysis,90,s,10,False\n",
        encoding="utf-8",
    )
    recommend = tmp_path / "recommend.csv"
    recommend.write_text(
        "date,ts_code,name,price_group,total_score,dimensions,close\n"
        "20260803,600001.SH,Rec,low_price_group,66,t_active,9.5\n",
        encoding="utf-8",
    )
    records = load_signals(
        analysis_path=analysis,
        recommend_path=recommend,
        lookback_days=45,
        today=dt.date(2026, 8, 7),
    )
    assert len(records) == 1
    assert records[0].kind == "recommend"
    assert records[0].strategy_version == "legacy_v1"


def test_legacy_evaluator_remains_read_only_compatibility_helper():
    record = SignalRecord(
        date="20260803",
        ts_code="600001.SH",
        name="X",
        kind="recommend",
        group="荐股",
        close=10.0,
    )
    results, missing = evaluate_signals([record], make_settings(), pro_client=FakeClient())
    assert missing == 0
    assert results[0].overnight_return_pct == pytest.approx(2.0)
    assert results[0].day_return_pct == pytest.approx(-1.0)


def _trade(code, *, status, signal_date="20260803", **values):
    defaults = {
        "trade_id": f"trd-{code}-{signal_date}",
        "signal_id": f"sig-{code}-{signal_date}",
        "strategy_version": "recommend_v2",
        "signal_date": signal_date,
        "ts_code": code,
        "industry": "Power",
        "status": status,
        "portfolio_status": "not_entered",
    }
    defaults.update(values)
    return TradeRecord(**defaults)


def _sample_records():
    return [
        _trade(
            "600001.SH",
            status=CLOSED,
            entry_date="20260804",
            actual_exit_date="20260805",
            exit_reason="take_profit",
            net_return_pct=3.85,
            slot_id=1,
            portfolio_status=CLOSED,
            allocated_capital=0.2,
            realized_value=0.2077,
        ),
        _trade("600002.SH", status=ENTRY_UNAVAILABLE),
        _trade("600003.SH", status=EXPIRED_UNFILLED),
        _trade(
            "600004.SH",
            status=CLOSED,
            signal_date="20260804",
            entry_date="20260805",
            actual_exit_date="20260806",
            exit_reason="stop_loss",
            net_return_pct=-3.15,
            portfolio_status=SKIPPED_DAILY_LIMIT,
        ),
        _trade(
            "600005.SH",
            status=OPEN,
            signal_date="20260806",
            entry_date="20260807",
            slot_id=2,
            portfolio_status=OPEN,
            allocated_capital=0.2,
            industry="Tech",
        ),
    ]


def _nav_rows():
    return [
        {
            "strategy_version": "recommend_v2",
            "trade_date": "20260807",
            "slot_utilization_pct": "40",
            "industry_weights": '{"Power":55,"Tech":45}',
            "max_industry": "Power",
            "max_industry_weight_pct": "55",
            "unknown_industry_positions": "0",
        }
    ]


def test_weekly_and_rolling_metrics_exclude_unavailable_and_open_from_win_rate():
    windows = build_backtest_windows(
        _sample_records(), _nav_rows(), lookback_days=45, today=dt.date(2026, 8, 7)
    )
    weekly, rolling = windows["recommend_v2"]
    assert weekly.signal.recommendations == 5
    assert weekly.signal.entry_unavailable == 1
    assert weekly.signal.trigger_denominator == 4
    assert weekly.signal.triggers == 3
    assert weekly.signal.trigger_rate_pct == pytest.approx(75.0)
    assert weekly.signal.settled == 2
    assert weekly.signal.open_count == 1
    assert weekly.signal.win_rate_pct == pytest.approx(50.0)
    assert weekly.portfolio.selected == 2
    assert weekly.portfolio.settled == 1
    assert weekly.portfolio.skipped_daily_limit == 1
    assert weekly.portfolio.max_industry == "Power"
    assert rolling.signal.recommendations == weekly.signal.recommendations


def test_report_shows_two_layers_open_exclusion_and_display_only_industry():
    report = build_backtest_report(
        _sample_records(),
        lookback_days=45,
        nav_rows=_nav_rows(),
        today=dt.date(2026, 8, 7),
    )
    assert "仅 recommend" in report
    assert "本周" in report and "滚动 45 日" in report
    assert "信号层" in report and "组合层" in report
    assert "entry_unavailable 1" in report
    assert "open/延迟中 1" in report
    assert "胜率 50.0%" in report
    assert "行业集中度（仅展示）" in report


def test_report_empty_ledger_is_explicit():
    assert "暂无荐股交易账本" in build_backtest_report([], lookback_days=45)


def test_cross_week_exit_is_counted_in_exit_week_not_lost_with_signal_cohort():
    prior_friday_trade = _trade(
        "600010.SH",
        status=CLOSED,
        signal_date="20260807",
        entry_date="20260810",
        actual_exit_date="20260811",
        exit_reason="take_profit",
        net_return_pct=3.85,
        slot_id=1,
        portfolio_status=CLOSED,
        allocated_capital=0.2,
        realized_value=0.2077,
    )
    windows = build_backtest_windows(
        [prior_friday_trade],
        [],
        lookback_days=45,
        today=dt.date(2026, 8, 14),
    )
    weekly, _ = windows["recommend_v2"]

    assert weekly.signal.recommendations == 0
    assert weekly.signal.triggers == 0
    assert weekly.signal.settled == 1
    assert weekly.signal.win_rate_pct == pytest.approx(100.0)
    assert weekly.signal.exit_reasons == {"take_profit": 1}
    assert weekly.portfolio.selected == 0
    assert weekly.portfolio.settled == 1
    assert weekly.portfolio.realized_contribution == pytest.approx(0.0077)
