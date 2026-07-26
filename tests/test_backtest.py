import datetime as dt

import pandas as pd

from tradeeye.config import Settings
from tradeeye.services.backtest import (
    SignalRecord,
    build_backtest_report,
    evaluate_signals,
    load_signals,
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
    """信号日 20260723，下一交易日 20260724。"""

    def trade_cal(self, **kwargs):
        return pd.DataFrame(
            {"cal_date": ["20260723", "20260724", "20260725"], "is_open": [1, 1, 0]}
        )

    def daily(self, trade_date="", **kwargs):
        if trade_date == "20260724":
            return pd.DataFrame(
                [
                    {"ts_code": "600001.SH", "open": 10.2, "close": 9.9},
                    {"ts_code": "600002.SH", "open": 14.8, "close": 15.5},
                ]
            )
        return pd.DataFrame()


def _record(ts_code: str, close: float, group: str = "复盘 强候选(≥80)") -> SignalRecord:
    return SignalRecord(
        date="20260723", ts_code=ts_code, name="X", kind="analysis", group=group, close=close
    )


def test_load_signals_filters_by_lookback_and_groups(tmp_path):
    analysis = tmp_path / "analysis.csv"
    analysis.write_text(
        "date,ts_code,name,score,status,close,called_llm\n"
        "20260101,600009.SH,Old,90,s,10.0,True\n"
        "20260723,600001.SH,Strong,85,s,10.0,True\n"
        "20260723,600002.SH,Mid,70,s,15.0,True\n"
        "20260723,600003.SH,Low,40,s,5.0,False\n"
        "20260723,600004.SH,BadClose,85,s,0,False\n",
        encoding="utf-8",
    )
    recommend = tmp_path / "recommend.csv"
    recommend.write_text(
        "date,ts_code,name,price_group,total_score,dimensions,close\n"
        "20260723,600005.SH,Rec,low_price_group,66.0,t_active,9.5\n",
        encoding="utf-8",
    )

    records = load_signals(
        analysis_path=analysis,
        recommend_path=recommend,
        lookback_days=45,
        today=dt.date(2026, 7, 27),
    )

    assert len(records) == 4
    groups = {record.ts_code: record.group for record in records}
    assert "强候选" in groups["600001.SH"]
    assert "候选" in groups["600002.SH"] and "强" not in groups["600002.SH"]
    assert "低分" in groups["600003.SH"]
    assert "低价组" in groups["600005.SH"]


def test_load_signals_missing_files_returns_empty(tmp_path):
    records = load_signals(
        analysis_path=tmp_path / "none1.csv",
        recommend_path=tmp_path / "none2.csv",
        lookback_days=45,
    )
    assert records == []


def test_evaluate_signals_computes_two_return_metrics():
    records = [_record("600001.SH", close=10.0), _record("600002.SH", close=16.0)]
    results, missing = evaluate_signals(records, make_settings(), pro_client=FakeClient())

    assert missing == 0
    assert len(results) == 2
    first = next(r for r in results if r.record.ts_code == "600001.SH")
    # 隔夜: 10.2/10.0-1 = +2%；全天: 9.9/10.0-1 = -1%
    assert round(first.overnight_return_pct, 2) == 2.0
    assert round(first.day_return_pct, 2) == -1.0


def test_evaluate_signals_counts_missing_quotes():
    records = [_record("999999.SH", close=10.0)]
    results, missing = evaluate_signals(records, make_settings(), pro_client=FakeClient())
    assert results == []
    assert missing == 1


def test_build_backtest_report_groups_and_flags_small_samples():
    records = [_record("600001.SH", close=10.0)]
    results, missing = evaluate_signals(records, make_settings(), pro_client=FakeClient())
    report = build_backtest_report(results, missing_count=2, lookback_days=45)

    assert "强候选" in report
    assert "样本不足" in report
    assert "胜率 100%" in report
    assert "2 条信号缺少 T+1 行情" in report
    assert "45" in report


def test_build_backtest_report_empty_results():
    report = build_backtest_report([], missing_count=0, lookback_days=45)
    assert "窗口内无可评估信号" in report
