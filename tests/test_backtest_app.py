from tradeeye.backtest_app import main
from tradeeye.config import Settings
from tradeeye.services.backtest import SignalRecord, SignalResult


def make_settings(token: str = "token") -> Settings:
    return Settings(
        tushare_token=token,
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


def _record() -> SignalRecord:
    return SignalRecord(
        date="20260723", ts_code="600001.SH", name="X",
        kind="analysis", group="复盘 强候选(≥80)", close=10.0,
    )


def test_main_no_signals_sends_empty_notice():
    sent = []
    result = main(
        settings=make_settings(),
        loader=lambda lookback_days: [],
        evaluator=lambda records, settings: ([], 0),
        notifier=lambda content, settings: sent.append(content) or True,
    )
    assert result == 0
    assert "暂无历史信号数据" in sent[0]


def test_main_with_signals_sends_report():
    sent = []
    results = [SignalResult(record=_record(), overnight_return_pct=2.0, day_return_pct=-1.0)]
    result = main(
        settings=make_settings(),
        loader=lambda lookback_days: [_record()],
        evaluator=lambda records, settings: (results, 0),
        notifier=lambda content, settings: sent.append(content) or True,
    )
    assert result == 0
    assert "强候选" in sent[0]
    assert "胜率" in sent[0]


def test_main_missing_token_with_signals_fails():
    result = main(
        settings=make_settings(token=""),
        loader=lambda lookback_days: [_record()],
        notifier=lambda content, settings: True,
    )
    assert result == 1


def test_main_notifier_failure_returns_error():
    result = main(
        settings=make_settings(),
        loader=lambda lookback_days: [],
        notifier=lambda content, settings: False,
    )
    assert result == 1
