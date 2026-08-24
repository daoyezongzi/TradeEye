from tradeeye.backtest_app import main
from tradeeye.config import Settings
from tradeeye.services.portfolio import CLOSED, TradeRecord


def make_settings(token: str = "") -> Settings:
    return Settings(
        tushare_token=token,
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


def _record():
    return TradeRecord(
        trade_id="trd-1",
        signal_id="sig-1",
        strategy_version="recommend_v2",
        signal_date="20260803",
        ts_code="600001.SH",
        status=CLOSED,
        entry_date="20260804",
        actual_exit_date="20260805",
        exit_reason="take_profit",
        net_return_pct=3.85,
        portfolio_status=CLOSED,
        slot_id=1,
        allocated_capital=0.2,
        realized_value=0.2077,
    )


def test_main_no_ledger_sends_empty_notice():
    sent = []
    result = main(
        settings=make_settings(),
        loader=lambda: ([], []),
        notifier=lambda content, settings: sent.append(content) or True,
    )
    assert result == 0
    assert "暂无荐股交易账本" in sent[0]


def test_main_reads_local_trade_and_nav_without_market_token():
    sent = []
    result = main(
        settings=make_settings(token=""),
        loader=lambda: ([_record()], []),
        notifier=lambda content, settings: sent.append(content) or True,
    )
    assert result == 0
    assert "策略版本：recommend_v2" in sent[0]
    assert "信号层" in sent[0]


def test_main_unsupported_loader_record_fails():
    result = main(
        settings=make_settings(),
        loader=lambda: ([object()], []),
        notifier=lambda content, settings: True,
    )
    assert result == 1


def test_main_notifier_failure_returns_error():
    result = main(
        settings=make_settings(),
        loader=lambda: ([], []),
        notifier=lambda content, settings: False,
    )
    assert result == 1
