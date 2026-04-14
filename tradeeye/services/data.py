from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import tushare as ts

from tradeeye.config import Settings, extract_exchange

logger = logging.getLogger(__name__)

MARKET_TZ = ZoneInfo("Asia/Shanghai")
SNAPSHOT_READY_TIME = dt.time(17, 10)
HISTORY_LOOKBACK_DAYS = 60
DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
DAILY_BASIC_FIELDS = "ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,total_mv,circ_mv"
MONEYFLOW_FIELDS = (
    "ts_code,trade_date,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_amount"
)
LIMIT_FIELDS = "ts_code,trade_date,up_limit,down_limit"
STOCK_BASIC_FIELDS = "ts_code,name,market,list_date"

_SNAPSHOT_CACHE: dict[tuple[str, str], "MarketSnapshot"] = {}
_HISTORY_CACHE: dict[tuple[str, str, str], pd.DataFrame] = {}


@dataclass(frozen=True)
class MarketSnapshot:
    trade_date: str
    market_df: pd.DataFrame
    market_regime: dict[str, Any]


def build_pro_client(settings: Settings):
    ts.set_token(settings.tushare_token)
    return ts.pro_api()


def get_clean_data(code: str, settings: Settings, pro_client=None) -> dict[str, Any] | None:
    if not settings.tushare_token:
        logger.error("Tushare data skipped for %s: missing TUSHARE_TOKEN", code)
        return None

    client = pro_client or build_pro_client(settings)

    try:
        snapshot = get_market_snapshot(settings, client)
        if snapshot.market_df.empty:
            logger.warning("Market snapshot is empty on %s", snapshot.trade_date)
            return None

        market_row = snapshot.market_df.loc[snapshot.market_df["ts_code"] == code]
        if market_row.empty:
            logger.warning("%s has no market snapshot row on %s", code, snapshot.trade_date)
            return None

        history_df = get_history_data(code, settings, snapshot.trade_date, client)
        if history_df.empty:
            logger.warning("No history returned for %s", code)
            return None

        history_df = history_df.sort_values("trade_date").reset_index(drop=True)
        if len(history_df.index) < 2:
            logger.warning("Not enough rows returned for %s", code)
            return None

        latest = history_df.iloc[-1].to_dict()
        prev = history_df.iloc[-2].to_dict()
        market_payload = market_row.iloc[0].to_dict()
        if latest.get("trade_date") != snapshot.trade_date:
            logger.warning(
                "%s latest history trade date %s does not match snapshot %s",
                code,
                latest.get("trade_date"),
                snapshot.trade_date,
            )
            return None

        latest.update(market_payload)
        latest["list_age_days"] = _get_list_age_days(market_payload.get("list_date"), snapshot.trade_date)
        latest["day_vol_ratio"] = _safe_divide(_to_float(latest.get("vol")), _to_float(prev.get("vol")))

        if settings.debug_mode:
            debug_dir = Path("debug_data")
            debug_dir.mkdir(exist_ok=True)
            history_df.to_csv(debug_dir / f"{code}_debug.csv", index=False, encoding="utf_8_sig")

        stock_name = market_payload.get("name")
        if pd.isna(stock_name) or not stock_name:
            stock_name = "Unknown"

        return {
            "name": stock_name,
            "trade_date": snapshot.trade_date,
            "df": history_df,
            "latest": latest,
            "prev": prev,
            "market_regime": snapshot.market_regime,
        }
    except Exception:
        logger.exception("Data engine failed for %s", code)
        return None


def get_market_snapshot(settings: Settings, pro_client=None) -> MarketSnapshot:
    client = pro_client or build_pro_client(settings)
    trade_date = resolve_trade_date(client)
    cache_key = (settings.tushare_token, trade_date)
    cached = _SNAPSHOT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    daily_df = _fetch_dataframe(
        "daily",
        lambda: client.daily(trade_date=trade_date, fields=DAILY_FIELDS),
    )
    daily_df = _filter_by_allowed_exchanges(daily_df, settings.allowed_exchanges)
    if daily_df.empty:
        snapshot = MarketSnapshot(
            trade_date=trade_date,
            market_df=pd.DataFrame(),
            market_regime=_build_market_regime(pd.DataFrame()),
        )
        _SNAPSHOT_CACHE[cache_key] = snapshot
        return snapshot

    daily_basic_df = _fetch_dataframe(
        "daily_basic",
        lambda: client.daily_basic(trade_date=trade_date, fields=DAILY_BASIC_FIELDS),
    )
    daily_basic_df = _filter_by_allowed_exchanges(daily_basic_df, settings.allowed_exchanges)
    moneyflow_df = _fetch_dataframe(
        "moneyflow",
        lambda: client.moneyflow(trade_date=trade_date, fields=MONEYFLOW_FIELDS),
    )
    moneyflow_df = _filter_by_allowed_exchanges(moneyflow_df, settings.allowed_exchanges)
    limit_df = _fetch_dataframe(
        "stk_limit",
        lambda: client.stk_limit(trade_date=trade_date, fields=LIMIT_FIELDS),
    )
    limit_df = _filter_by_allowed_exchanges(limit_df, settings.allowed_exchanges)
    stock_basic_df = _fetch_dataframe(
        "stock_basic",
        lambda: client.stock_basic(exchange="", list_status="L", fields=STOCK_BASIC_FIELDS),
    )
    stock_basic_df = _filter_by_allowed_exchanges(stock_basic_df, settings.allowed_exchanges)

    market_df = daily_df.copy()
    for extra_df, keys in (
        (daily_basic_df, ["ts_code", "trade_date"]),
        (moneyflow_df, ["ts_code", "trade_date"]),
        (limit_df, ["ts_code", "trade_date"]),
        (stock_basic_df, ["ts_code"]),
    ):
        if extra_df.empty:
            continue
        market_df = market_df.merge(extra_df, on=keys, how="left")

    market_df = _build_market_features(market_df)
    market_regime = _build_market_regime(market_df)
    snapshot = MarketSnapshot(trade_date=trade_date, market_df=market_df, market_regime=market_regime)
    _SNAPSHOT_CACHE[cache_key] = snapshot

    if settings.debug_mode and not market_df.empty:
        debug_dir = Path("debug_data")
        debug_dir.mkdir(exist_ok=True)
        market_df.to_csv(debug_dir / f"market_snapshot_{trade_date}.csv", index=False, encoding="utf_8_sig")

    return snapshot


def get_history_data(code: str, settings: Settings, trade_date: str, pro_client=None) -> pd.DataFrame:
    client = pro_client or build_pro_client(settings)
    cache_key = (settings.tushare_token, trade_date, code)
    cached = _HISTORY_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()

    end_date = dt.datetime.strptime(trade_date, "%Y%m%d").date()
    start_date = (end_date - dt.timedelta(days=HISTORY_LOOKBACK_DAYS)).strftime("%Y%m%d")
    history_df = _fetch_dataframe(
        f"daily:{code}",
        lambda: client.daily(ts_code=code, start_date=start_date, end_date=trade_date, fields=DAILY_FIELDS),
    )
    if history_df.empty:
        return history_df

    history_df = history_df.sort_values("trade_date").reset_index(drop=True)
    history_df = _coerce_numeric(
        history_df,
        ["open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"],
    )
    history_df["ma5"] = history_df["close"].rolling(window=5, min_periods=5).mean()
    history_df["ma10"] = history_df["close"].rolling(window=10, min_periods=10).mean()
    history_df["ma20"] = history_df["close"].rolling(window=20, min_periods=20).mean()
    history_df["amount_ratio_5d"] = _safe_divide_series(
        history_df["amount"],
        history_df["amount"].shift(1).rolling(window=5, min_periods=3).mean(),
    )
    history_df["close_strength"] = _safe_divide_series(
        history_df["close"] - history_df["low"],
        (history_df["high"] - history_df["low"]).replace(0, pd.NA),
    ).clip(lower=0, upper=1)
    history_df["upper_shadow_pct"] = _safe_divide_series(
        history_df["high"] - history_df[["open", "close"]].max(axis=1),
        history_df["pre_close"].replace(0, pd.NA),
    ) * 100
    history_df["breakout_10_pct"] = _safe_divide_series(
        history_df["close"] - history_df["high"].shift(1).rolling(window=10, min_periods=5).max(),
        history_df["high"].shift(1).rolling(window=10, min_periods=5).max(),
    ) * 100
    history_df["return_3d_pct"] = history_df["close"].pct_change(periods=3) * 100
    history_df["ma5_slope_pct"] = _safe_divide_series(
        history_df["ma5"] - history_df["ma5"].shift(1),
        history_df["ma5"].shift(1),
    ) * 100

    _HISTORY_CACHE[cache_key] = history_df
    return history_df.copy()


def resolve_trade_date(pro_client, now: dt.datetime | None = None) -> str:
    now_in_market_tz = _coerce_market_time(now)
    end_date = now_in_market_tz.strftime("%Y%m%d")
    start_date = (now_in_market_tz.date() - dt.timedelta(days=14)).strftime("%Y%m%d")
    calendar_df = _fetch_dataframe(
        "trade_cal",
        lambda: pro_client.trade_cal(exchange="", start_date=start_date, end_date=end_date, fields="cal_date,is_open"),
    )
    if calendar_df.empty:
        return end_date

    calendar_df = _coerce_numeric(calendar_df, ["is_open"])
    open_days = sorted(calendar_df.loc[calendar_df["is_open"] == 1, "cal_date"].astype(str).tolist())
    if not open_days:
        return end_date

    latest_open_day = open_days[-1]
    if latest_open_day == end_date and now_in_market_tz.time() < SNAPSHOT_READY_TIME and len(open_days) >= 2:
        return open_days[-2]
    return latest_open_day


def _build_market_features(market_df: pd.DataFrame) -> pd.DataFrame:
    if market_df.empty:
        return market_df

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "total_mv",
        "circ_mv",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
        "net_mf_amount",
        "up_limit",
        "down_limit",
    ]
    market_df = _coerce_numeric(market_df, numeric_columns)

    amount_wan = market_df["amount"] / 10
    large_order_net_amount = (
        market_df["buy_lg_amount"].fillna(0)
        + market_df["buy_elg_amount"].fillna(0)
        - market_df["sell_lg_amount"].fillna(0)
        - market_df["sell_elg_amount"].fillna(0)
    )
    market_df["net_mf_ratio_pct"] = _safe_divide_series(market_df["net_mf_amount"], amount_wan.replace(0, pd.NA)) * 100
    market_df["large_order_net_pct"] = _safe_divide_series(large_order_net_amount, amount_wan.replace(0, pd.NA)) * 100
    market_df["close_strength"] = _safe_divide_series(
        market_df["close"] - market_df["low"],
        (market_df["high"] - market_df["low"]).replace(0, pd.NA),
    ).clip(lower=0, upper=1)
    market_df["upper_shadow_pct"] = _safe_divide_series(
        market_df["high"] - market_df[["open", "close"]].max(axis=1),
        market_df["pre_close"].replace(0, pd.NA),
    ) * 100
    market_df["up_limit_room_pct"] = _safe_divide_series(
        market_df["up_limit"] - market_df["close"],
        market_df["close"].replace(0, pd.NA),
    ) * 100

    for source_col, rank_col in (
        ("turnover_rate", "turnover_pct_rank"),
        ("volume_ratio", "volume_ratio_rank"),
        ("net_mf_ratio_pct", "net_mf_ratio_rank"),
        ("large_order_net_pct", "large_order_net_rank"),
        ("amount", "amount_pct_rank"),
        ("pct_chg", "pct_chg_rank"),
    ):
        if source_col not in market_df:
            continue
        market_df[rank_col] = market_df[source_col].rank(pct=True, na_option="bottom")

    return market_df


def _build_market_regime(market_df: pd.DataFrame) -> dict[str, Any]:
    if market_df.empty or "pct_chg" not in market_df:
        return {"status": "未知", "score": 0, "up_ratio_pct": 0.0, "strong_ratio_pct": 0.0, "weak_ratio_pct": 0.0}

    up_ratio = float((market_df["pct_chg"] > 0).mean())
    strong_ratio = float((market_df["pct_chg"] >= 5).mean())
    weak_ratio = float((market_df["pct_chg"] <= -3).mean())
    positive_flow_ratio = (
        float((market_df["net_mf_ratio_pct"].fillna(0) > 0).mean()) if "net_mf_ratio_pct" in market_df else 0.5
    )

    score = 0
    if up_ratio >= 0.55:
        score += 15
    elif up_ratio <= 0.45:
        score -= 15

    if strong_ratio >= 0.08:
        score += 10
    elif strong_ratio <= 0.03:
        score -= 5

    if weak_ratio >= 0.12:
        score -= 10
    elif weak_ratio <= 0.06:
        score += 5

    if positive_flow_ratio >= 0.55:
        score += 5
    elif positive_flow_ratio <= 0.45:
        score -= 5

    if score >= 15:
        status = "偏强"
    elif score <= -15:
        status = "偏弱"
    else:
        status = "中性"

    return {
        "status": status,
        "score": score,
        "up_ratio_pct": round(up_ratio * 100, 1),
        "strong_ratio_pct": round(strong_ratio * 100, 1),
        "weak_ratio_pct": round(weak_ratio * 100, 1),
        "positive_flow_ratio_pct": round(positive_flow_ratio * 100, 1),
    }


def _fetch_dataframe(label: str, query) -> pd.DataFrame:
    try:
        df = query()
        if df is None:
            return pd.DataFrame()
        return df.copy()
    except Exception:
        logger.exception("Tushare query failed for %s", label)
        return pd.DataFrame()


def _coerce_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def _filter_by_allowed_exchanges(df: pd.DataFrame, allowed_exchanges: tuple[str, ...]) -> pd.DataFrame:
    if df.empty or "ts_code" not in df.columns:
        return df

    allowed_set = {exchange.upper() for exchange in allowed_exchanges}
    filtered_df = df.loc[df["ts_code"].astype(str).map(lambda code: extract_exchange(code) in allowed_set)]
    return filtered_df.reset_index(drop=True)


def _coerce_market_time(now: dt.datetime | None) -> dt.datetime:
    if now is None:
        return dt.datetime.now(MARKET_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=MARKET_TZ)
    return now.astimezone(MARKET_TZ)


def _get_list_age_days(list_date: Any, trade_date: str) -> int:
    if not list_date:
        return 9999

    try:
        listed_on = dt.datetime.strptime(str(list_date), "%Y%m%d").date()
        traded_on = dt.datetime.strptime(trade_date, "%Y%m%d").date()
    except ValueError:
        return 9999
    return max((traded_on - listed_on).days, 0)


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0 or pd.isna(denominator):
        return 0.0
    return float(numerator / denominator)


def _safe_divide_series(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    aligned_denominator = denominator.replace(0, pd.NA)
    return numerator.divide(aligned_denominator).fillna(0.0)


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
