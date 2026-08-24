from __future__ import annotations

import pandas as pd
import pytest

from tradeeye.config import Settings
from tradeeye.services import data


def _settings(*exchanges: str) -> Settings:
    return Settings(
        tushare_token="token",
        feishu_webhook="",
        debug_mode=False,
        my_stocks=["600000.SH"],
        allowed_exchanges=tuple(exchanges),
    )


def _daily_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "trade_date": "20260821",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "pre_close": 10.0,
                "change": 0.2,
                "pct_chg": 2.0,
                "vol": 1000,
                "amount": 10000,
            },
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260821",
                "open": 12.0,
                "high": 12.4,
                "low": 11.8,
                "close": 12.2,
                "pre_close": 12.0,
                "change": 0.2,
                "pct_chg": 1.7,
                "vol": 1200,
                "amount": 12000,
            },
        ]
    )


class _Client:
    def __init__(self, *, fail_daily: bool = False, fail_auxiliary: bool = False):
        self.fail_daily = fail_daily
        self.fail_auxiliary = fail_auxiliary
        self.daily_calls = 0

    def daily(self, **_kwargs):
        self.daily_calls += 1
        if self.fail_daily:
            raise RuntimeError("daily unavailable")
        return _daily_rows()

    def daily_basic(self, **_kwargs):
        if self.fail_auxiliary:
            raise RuntimeError("daily_basic unavailable")
        return pd.DataFrame()

    def moneyflow(self, **_kwargs):
        if self.fail_auxiliary:
            raise RuntimeError("moneyflow unavailable")
        return pd.DataFrame()

    def stk_limit(self, **_kwargs):
        if self.fail_auxiliary:
            raise RuntimeError("stk_limit unavailable")
        return pd.DataFrame()

    def stock_basic(self, **_kwargs):
        if self.fail_auxiliary:
            raise RuntimeError("stock_basic unavailable")
        return pd.DataFrame()


@pytest.fixture(autouse=True)
def _clear_caches():
    data._SNAPSHOT_CACHE.clear()
    data._HISTORY_CACHE.clear()
    yield
    data._SNAPSHOT_CACHE.clear()
    data._HISTORY_CACHE.clear()


def test_snapshot_cache_key_includes_allowed_exchanges(monkeypatch):
    monkeypatch.setattr(data, "resolve_trade_date", lambda _client: "20260821")
    client = _Client()

    sh_snapshot = data.get_market_snapshot(_settings("SH"), client)
    sz_snapshot = data.get_market_snapshot(_settings("SZ"), client)

    assert sh_snapshot.market_df["ts_code"].tolist() == ["600000.SH"]
    assert sz_snapshot.market_df["ts_code"].tolist() == ["000001.SZ"]
    assert client.daily_calls == 2


def test_required_daily_failure_is_not_cached(monkeypatch):
    monkeypatch.setattr(data, "resolve_trade_date", lambda _client: "20260821")
    client = _Client(fail_daily=True)

    with pytest.raises(data.DataProviderError, match="Required Tushare query failed: daily"):
        data.get_market_snapshot(_settings("SH"), client)
    with pytest.raises(data.DataProviderError):
        data.get_market_snapshot(_settings("SH"), client)

    assert client.daily_calls == 2
    assert data._SNAPSHOT_CACHE == {}


def test_auxiliary_failures_degrade_without_breaking_features(monkeypatch):
    monkeypatch.setattr(data, "resolve_trade_date", lambda _client: "20260821")
    snapshot = data.get_market_snapshot(_settings("SH"), _Client(fail_auxiliary=True))

    assert snapshot.market_df["ts_code"].tolist() == ["600000.SH"]
    assert set(snapshot.degraded_sources) == {"daily_basic", "moneyflow", "stk_limit", "stock_basic"}
    assert "net_mf_ratio_pct" in snapshot.market_df
    assert snapshot.market_df["net_mf_ratio_pct"].fillna(0).eq(0).all()
    assert not snapshot.market_df["daily_basic_available"].any()
    assert not snapshot.market_df["moneyflow_available"].any()


def test_empty_trading_calendar_fails_closed():
    class CalendarClient:
        def trade_cal(self, **_kwargs):
            return pd.DataFrame()

    with pytest.raises(data.DataProviderError, match="Trading calendar is empty"):
        data.resolve_trade_date(CalendarClient())


def test_individual_missing_snapshot_row_becomes_unscored_payload(monkeypatch):
    snapshot = data.MarketSnapshot(
        trade_date="20260821",
        market_df=_daily_rows().iloc[1:].copy(),
        market_regime={"status": "中性", "score": 0},
    )
    monkeypatch.setattr(data, "get_market_snapshot", lambda _settings, _client: snapshot)

    payload = data.get_clean_data("600000.SH", _settings("SH"), pro_client=object())

    assert payload is not None
    assert payload["latest"] is None
    assert payload["data_quality_issue"] == "snapshot_row_missing"
