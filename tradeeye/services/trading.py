from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import pandas as pd


class MarketDataUnavailable(RuntimeError):
    """The supplier/global batch is unavailable, so settlement must not advance."""


@dataclass(frozen=True)
class MarketQuote:
    trade_date: str
    ts_code: str
    open: float
    high: float
    low: float
    close: float
    down_limit: float | None = None
    one_price_down_limit: bool = False

    @property
    def valid(self) -> bool:
        values = (self.open, self.high, self.low, self.close)
        return (
            all(value > 0 for value in values)
            and self.high >= max(self.open, self.close, self.low)
            and self.low <= min(self.open, self.close, self.high)
        )

    @property
    def locked_at_down_limit(self) -> bool:
        if self.one_price_down_limit:
            return True
        if not self.valid or self.down_limit is None or self.down_limit <= 0:
            return False
        tolerance = max(abs(self.down_limit), 1.0) * 1e-8
        return all(
            abs(value - self.down_limit) <= tolerance
            for value in (self.open, self.high, self.low, self.close)
        )


@dataclass(frozen=True)
class DailyMarketData:
    trade_date: str
    quotes: dict[str, MarketQuote]
    complete: bool = True
    source: str = "injected"

    def quote(self, ts_code: str) -> MarketQuote | None:
        quote = self.quotes.get(ts_code)
        return quote if quote is not None and quote.valid else None


@runtime_checkable
class MarketDataProvider(Protocol):
    def get_trade_days(self, start_date: str, end_date: str) -> list[str]: ...

    def get_daily_market(self, trade_date: str) -> DailyMarketData: ...


@dataclass(frozen=True)
class ExitDecision:
    action: str
    price: float | None
    reason: str


class TushareMarketDataProvider:
    """Strict Tushare adapter: batch failures raise instead of becoming fake suspensions."""

    def __init__(self, pro_client) -> None:
        self._client = pro_client

    def get_trade_days(self, start_date: str, end_date: str) -> list[str]:
        try:
            frame = self._client.trade_cal(
                exchange="",
                start_date=start_date,
                end_date=end_date,
                fields="cal_date,is_open",
            )
        except Exception as exc:
            raise MarketDataUnavailable("trade calendar query failed") from exc
        if frame is None or frame.empty or not {"cal_date", "is_open"}.issubset(frame.columns):
            raise MarketDataUnavailable("trade calendar batch is empty or incomplete")
        return sorted(
            str(cal_date)
            for cal_date, is_open in zip(frame["cal_date"], frame["is_open"])
            if _to_float(is_open) == 1
        )

    def get_daily_market(self, trade_date: str) -> DailyMarketData:
        try:
            daily = self._client.daily(
                trade_date=trade_date,
                fields="ts_code,trade_date,open,high,low,close",
            )
            limits = self._client.stk_limit(
                trade_date=trade_date,
                fields="ts_code,trade_date,down_limit",
            )
        except Exception as exc:
            raise MarketDataUnavailable(f"market batch query failed for {trade_date}") from exc

        daily_fields = {"ts_code", "open", "high", "low", "close"}
        if daily is None or daily.empty or not daily_fields.issubset(daily.columns):
            raise MarketDataUnavailable(f"daily market batch is empty or incomplete for {trade_date}")
        if limits is None or limits.empty or not {"ts_code", "down_limit"}.issubset(limits.columns):
            raise MarketDataUnavailable(f"limit-price batch is empty or incomplete for {trade_date}")

        down_limits: dict[str, float] = {}
        for _, row in limits.iterrows():
            down_limit = _optional_float(row["down_limit"])
            if down_limit is not None:
                down_limits[str(row["ts_code"])] = down_limit
        missing_limits = sorted(
            {
                str(code)
                for code in daily["ts_code"]
                if str(code) not in down_limits
            }
        )
        if missing_limits:
            raise MarketDataUnavailable(
                f"limit-price batch has no valid down_limit for "
                f"{','.join(missing_limits)} on {trade_date}"
            )

        quotes: dict[str, MarketQuote] = {}
        for _, row in daily.iterrows():
            code = str(row["ts_code"])
            quote = MarketQuote(
                trade_date=trade_date,
                ts_code=code,
                open=_to_float(row["open"]),
                high=_to_float(row["high"]),
                low=_to_float(row["low"]),
                close=_to_float(row["close"]),
                down_limit=down_limits[code],
            )
            if quote.valid:
                quotes[code] = quote
        return DailyMarketData(
            trade_date=trade_date,
            quotes=quotes,
            complete=True,
            source="tushare",
        )


def planned_entry_price(signal_close: float) -> float:
    return signal_close * 0.98


def entry_fill_price(signal_close: float, quote: MarketQuote | None) -> float | None:
    if signal_close <= 0 or quote is None or not quote.valid:
        return None
    planned = planned_entry_price(signal_close)
    if quote.low > planned:
        return None
    return min(quote.open, planned)


def decide_exit(
    entry_price: float,
    quote: MarketQuote,
    *,
    force_timeout: bool = False,
) -> ExitDecision | None:
    """Evaluate one daily bar. Gap exits use open; intraday TP/SL ties prefer SL."""
    if entry_price <= 0 or not quote.valid:
        return None

    stop_price = entry_price * 0.97
    take_price = entry_price * 1.04
    stop_touched = quote.open <= stop_price or quote.low <= stop_price
    take_touched = quote.open >= take_price or quote.high >= take_price
    exit_due = stop_touched or take_touched or force_timeout
    if exit_due and quote.locked_at_down_limit:
        return ExitDecision(action="defer", price=None, reason="one_price_down_limit")

    if quote.open <= stop_price:
        return ExitDecision(action="exit", price=quote.open, reason="stop_loss_gap")
    if quote.open >= take_price:
        return ExitDecision(action="exit", price=quote.open, reason="take_profit_gap")
    if quote.low <= stop_price:
        return ExitDecision(action="exit", price=stop_price, reason="stop_loss")
    if quote.high >= take_price:
        return ExitDecision(action="exit", price=take_price, reason="take_profit")
    if force_timeout:
        return ExitDecision(action="exit", price=quote.close, reason="timeout_close")
    return None


def gross_return_pct(entry_price: float, exit_price: float) -> float:
    return (exit_price / entry_price - 1.0) * 100.0


def net_return_pct(entry_price: float, exit_price: float, cost_pct: float = 0.15) -> float:
    return gross_return_pct(entry_price, exit_price) - cost_pct


def realized_value(capital: float, entry_price: float, exit_price: float, cost_pct: float = 0.15) -> float:
    return capital * (exit_price / entry_price - cost_pct / 100.0)


def _optional_float(value) -> float | None:
    parsed = _to_float(value)
    if parsed <= 0 or not math.isfinite(parsed):
        return None
    return parsed


def _to_float(value) -> float:
    try:
        if value is None or value == "" or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
