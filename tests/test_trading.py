import pytest
import pandas as pd

from tradeeye.services.trading import (
    MarketDataUnavailable,
    MarketQuote,
    TushareMarketDataProvider,
    decide_exit,
    entry_fill_price,
    net_return_pct,
    planned_entry_price,
)


class FakeTushareClient:
    def __init__(self, daily, limits):
        self._daily = daily
        self._limits = limits

    def daily(self, **_kwargs):
        return self._daily

    def stk_limit(self, **_kwargs):
        return self._limits


def quote(open_, high, low, close, *, down_limit=None, locked=False):
    return MarketQuote(
        trade_date="20260804",
        ts_code="600001.SH",
        open=open_,
        high=high,
        low=low,
        close=close,
        down_limit=down_limit,
        one_price_down_limit=locked,
    )


def test_entry_plan_and_fill_use_two_percent_discount_and_gap_open():
    assert planned_entry_price(10.0) == pytest.approx(9.8)
    assert entry_fill_price(10.0, quote(9.7, 10.0, 9.6, 9.9)) == pytest.approx(9.7)
    assert entry_fill_price(10.0, quote(9.9, 10.0, 9.7, 9.9)) == pytest.approx(9.8)
    assert entry_fill_price(10.0, quote(9.9, 10.1, 9.81, 10.0)) is None


def test_exit_gap_and_intraday_tie_rules():
    assert decide_exit(10.0, quote(9.6, 9.8, 9.5, 9.7)).reason == "stop_loss_gap"
    assert decide_exit(10.0, quote(10.5, 10.6, 10.4, 10.5)).reason == "take_profit_gap"
    tie = decide_exit(10.0, quote(10.0, 10.5, 9.6, 10.1))
    assert tie.reason == "stop_loss"
    assert tie.price == pytest.approx(9.7)


def test_timeout_uses_close_and_locked_down_limit_defers():
    timeout = decide_exit(10.0, quote(10.0, 10.2, 9.9, 10.1), force_timeout=True)
    assert timeout.reason == "timeout_close"
    assert timeout.price == pytest.approx(10.1)
    locked = decide_exit(
        10.0,
        quote(9.0, 9.0, 9.0, 9.0, down_limit=9.0),
        force_timeout=True,
    )
    assert locked.action == "defer"
    assert locked.reason == "one_price_down_limit"


def test_round_trip_cost_is_deducted_at_exit():
    assert net_return_pct(10.0, 10.4) == pytest.approx(3.85)


@pytest.mark.parametrize("down_limit", [None, 0, float("nan"), float("inf")])
def test_tushare_batch_requires_valid_down_limit_for_every_daily_row(down_limit):
    daily = pd.DataFrame(
        [
            {
                "ts_code": "600001.SH",
                "trade_date": "20260804",
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
            },
            {
                "ts_code": "600002.SH",
                "trade_date": "20260804",
                "open": 20.0,
                "high": 20.2,
                "low": 19.9,
                "close": 20.1,
            },
        ]
    )
    limits = pd.DataFrame(
        [
            {"ts_code": "600001.SH", "trade_date": "20260804", "down_limit": 9.0},
            {"ts_code": "600002.SH", "trade_date": "20260804", "down_limit": down_limit},
        ]
    )
    provider = TushareMarketDataProvider(FakeTushareClient(daily, limits))

    with pytest.raises(MarketDataUnavailable, match="600002.SH"):
        provider.get_daily_market("20260804")


def test_tushare_batch_attaches_valid_down_limits_to_all_quotes():
    daily = pd.DataFrame(
        [
            {
                "ts_code": "600001.SH",
                "trade_date": "20260804",
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
            }
        ]
    )
    limits = pd.DataFrame(
        [{"ts_code": "600001.SH", "trade_date": "20260804", "down_limit": 9.0}]
    )
    provider = TushareMarketDataProvider(FakeTushareClient(daily, limits))

    batch = provider.get_daily_market("20260804")

    assert batch.quotes["600001.SH"].down_limit == pytest.approx(9.0)
