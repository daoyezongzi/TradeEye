from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

from tradeeye.config import PRICE_RANGES, Settings, extract_exchange
from tradeeye.services.data import build_pro_client, get_market_snapshot

logger = logging.getLogger(__name__)

SHORT_BURST_VOLUME_RATIO_MIN = 2.0
SHORT_BURST_TURNOVER_MIN = 5.0
SHORT_BURST_TURNOVER_MAX = 15.0
SHORT_BURST_PCT_CHG_MIN = 2.0

T_ACTIVE_AMPLITUDE_MIN = 4.5
T_ACTIVE_AMOUNT_MIN = 500_000.0  # Tushare daily.amount unit: thousand CNY.

LONG_VALUE_PE_RANK_MAX = 0.4
LONG_VALUE_MV_RANK_MIN = 0.8

LOW_PRICE_GROUP_KEY = "low_price_group"
MID_PRICE_GROUP_KEY = "mid_price_group"
DEFAULT_TOP_N_PER_GROUP = 5


def recommend_top_stocks(
    settings: Settings,
    top_n: int = DEFAULT_TOP_N_PER_GROUP,
    pro_client=None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch market snapshot via existing data service and return grouped recommendations."""
    if not settings.tushare_token:
        logger.error("Stock recommender skipped: missing TUSHARE_TOKEN")
        return _empty_grouped_result()

    client = pro_client or build_pro_client(settings)
    snapshot = get_market_snapshot(settings, pro_client=client)
    if snapshot.market_df.empty:
        return _empty_grouped_result()

    return rank_market_candidates(
        market_df=snapshot.market_df,
        allowed_exchanges=settings.allowed_exchanges,
        recommender_industries=settings.recommender_industries,
        trade_date=snapshot.trade_date,
        top_n_each_group=top_n,
    )


def rank_market_candidates(
    market_df: pd.DataFrame,
    allowed_exchanges: tuple[str, ...],
    recommender_industries: tuple[str, ...] = (),
    trade_date: str | None = None,
    top_n_each_group: int = DEFAULT_TOP_N_PER_GROUP,
) -> dict[str, list[dict[str, Any]]]:
    if market_df.empty:
        return _empty_grouped_result()

    ranked_df = _build_scored_market_frame(market_df, allowed_exchanges, recommender_industries)
    if ranked_df.empty:
        return _empty_grouped_result()

    date_value = trade_date or _resolve_trade_date_from_frame(ranked_df)
    low_min, low_max = _get_price_range("low", (0.0, 10.0))
    mid_min, mid_max = _get_price_range("mid", (10.0, 20.0))

    low_df = ranked_df.loc[(ranked_df["close"] >= low_min) & (ranked_df["close"] <= low_max)].copy()
    mid_df = ranked_df.loc[(ranked_df["close"] > mid_min) & (ranked_df["close"] <= mid_max)].copy()

    low_top = low_df.sort_values(["total_score", "amount"], ascending=[False, False]).head(top_n_each_group)
    mid_top = mid_df.sort_values(["total_score", "amount"], ascending=[False, False]).head(top_n_each_group)

    return {
        LOW_PRICE_GROUP_KEY: [_to_output_record(row, date_value, LOW_PRICE_GROUP_KEY) for _, row in low_top.iterrows()],
        MID_PRICE_GROUP_KEY: [_to_output_record(row, date_value, MID_PRICE_GROUP_KEY) for _, row in mid_top.iterrows()],
    }


def recommendations_to_json(recommendations: dict[str, list[dict[str, Any]]] | list[dict[str, Any]]) -> str:
    grouped = _normalize_grouped_recommendations(recommendations)
    return json.dumps(grouped, ensure_ascii=False)


def build_recommendation_brief(recommendations: dict[str, list[dict[str, Any]]]) -> str:
    grouped = _normalize_grouped_recommendations(recommendations)
    low_group = grouped[LOW_PRICE_GROUP_KEY]
    mid_group = grouped[MID_PRICE_GROUP_KEY]

    if not low_group and not mid_group:
        return "今日无满足筛选条件的推荐股票。"

    lines: list[str] = ["每日好股推荐："]
    lines.extend(_format_group_lines("[0-10元组] Top5", low_group))
    lines.extend(_format_group_lines("[10-20元组] Top5", mid_group))
    return "\n".join(lines)


def _format_group_lines(title: str, group_items: list[dict[str, Any]]) -> list[str]:
    lines = [title]
    if not group_items:
        lines.append("- 无入选标的")
        return lines

    for index, item in enumerate(group_items, start=1):
        lines.append(
            (
                f"- {index}. {item.get('ts_code')} {item.get('name')} "
                f"| 现价 {item.get('close')} "
                f"| 总分 {item.get('total_score')} "
                f"| 维度 {','.join(item.get('dimensions', []))}"
            )
        )
    return lines


def _build_scored_market_frame(
    market_df: pd.DataFrame,
    allowed_exchanges: tuple[str, ...],
    recommender_industries: tuple[str, ...],
) -> pd.DataFrame:
    frame = market_df.copy()
    frame = _ensure_columns(
        frame,
        [
            "ts_code",
            "name",
            "industry",
            "trade_date",
            "close",
            "pct_chg",
            "turnover_rate",
            "volume_ratio",
            "high",
            "low",
            "pre_close",
            "amount",
            "total_mv",
            "pe",
            "pe_ttm",
        ],
    )
    frame = _coerce_numeric(
        frame,
        [
            "close",
            "pct_chg",
            "turnover_rate",
            "volume_ratio",
            "high",
            "low",
            "pre_close",
            "amount",
            "total_mv",
            "pe",
            "pe_ttm",
        ],
    )

    allowed_set = {exchange.upper() for exchange in allowed_exchanges}
    frame = frame.loc[frame["ts_code"].astype(str).map(lambda code: extract_exchange(code) in allowed_set)].copy()
    if frame.empty:
        return frame

    max_price = max(float(bounds[1]) for bounds in PRICE_RANGES.values())
    frame = frame.loc[(frame["close"] > 0) & (frame["close"] <= max_price)].copy()
    if frame.empty:
        return frame

    # Filter out ST and delisted symbols before scoring.
    name_series = frame["name"].fillna("").astype(str)
    name_upper = name_series.str.upper()
    is_st = name_upper.str.contains("ST", regex=False)
    is_delisted = name_series.str.contains("退", regex=False) | name_upper.str.contains("DELIST", regex=False)
    frame = frame.loc[~(is_st | is_delisted)].copy()
    if frame.empty:
        return frame

    frame["intraday_amplitude_pct"] = _safe_divide_series(
        frame["high"] - frame["low"],
        frame["pre_close"],
    ) * 100
    frame["amount_yi"] = frame["amount"] / 100_000
    frame["pe_value"] = frame["pe_ttm"]
    frame.loc[(frame["pe_value"] <= 0) | frame["pe_value"].isna(), "pe_value"] = frame["pe"]
    frame.loc[frame["industry"].isna(), "industry"] = ""

    short_mask = (
        (frame["volume_ratio"] > SHORT_BURST_VOLUME_RATIO_MIN)
        & (frame["turnover_rate"] >= SHORT_BURST_TURNOVER_MIN)
        & (frame["turnover_rate"] <= SHORT_BURST_TURNOVER_MAX)
        & (frame["pct_chg"] > SHORT_BURST_PCT_CHG_MIN)
    )
    frame["short_burst_score"] = 0.0
    frame.loc[short_mask, "short_burst_score"] = (
        55
        + ((frame.loc[short_mask, "volume_ratio"] - SHORT_BURST_VOLUME_RATIO_MIN).clip(lower=0, upper=5) / 5) * 20
        + (1 - ((frame.loc[short_mask, "turnover_rate"] - 10).abs().clip(upper=5) / 5)) * 15
        + ((frame.loc[short_mask, "pct_chg"] - SHORT_BURST_PCT_CHG_MIN).clip(lower=0, upper=8) / 8) * 10
    ).clip(lower=0, upper=100)

    t_mask = (frame["intraday_amplitude_pct"] > T_ACTIVE_AMPLITUDE_MIN) & (frame["amount"] > T_ACTIVE_AMOUNT_MIN)
    frame["t_active_score"] = 0.0
    frame.loc[t_mask, "t_active_score"] = (
        50
        + ((frame.loc[t_mask, "intraday_amplitude_pct"] - T_ACTIVE_AMPLITUDE_MIN).clip(lower=0, upper=8) / 8) * 25
        + ((frame.loc[t_mask, "amount"] - T_ACTIVE_AMOUNT_MIN).clip(lower=0, upper=1_000_000) / 1_000_000) * 25
    ).clip(lower=0, upper=100)

    frame["long_value_score"] = 0.0
    long_df = frame.loc[(frame["pe_value"] > 0) & (frame["total_mv"] > 0) & (frame["industry"] != "")].copy()
    industry_filter = {item.strip() for item in recommender_industries if item.strip()}
    if industry_filter:
        long_df = long_df.loc[long_df["industry"].isin(industry_filter)].copy()

    if not long_df.empty:
        long_df["pe_rank"] = long_df.groupby("industry")["pe_value"].rank(pct=True, ascending=True)
        long_df["mv_rank"] = long_df.groupby("industry")["total_mv"].rank(pct=True, ascending=True)
        long_mask = (long_df["pe_rank"] <= LONG_VALUE_PE_RANK_MAX) & (long_df["mv_rank"] >= LONG_VALUE_MV_RANK_MIN)
        long_df.loc[long_mask, "long_value_score"] = (
            50
            + ((LONG_VALUE_PE_RANK_MAX - long_df.loc[long_mask, "pe_rank"]) / LONG_VALUE_PE_RANK_MAX) * 25
            + ((long_df.loc[long_mask, "mv_rank"] - LONG_VALUE_MV_RANK_MIN) / (1 - LONG_VALUE_MV_RANK_MIN)) * 25
        ).clip(lower=0, upper=100)
        frame.loc[long_df.index, "long_value_score"] = long_df["long_value_score"]

    frame["dimension_hits"] = (
        (frame["short_burst_score"] > 0).astype(int)
        + (frame["t_active_score"] > 0).astype(int)
        + (frame["long_value_score"] > 0).astype(int)
    )
    frame = frame.loc[frame["dimension_hits"] > 0].copy()
    if frame.empty:
        return frame

    frame["total_score"] = (
        frame["short_burst_score"] * 0.4
        + frame["t_active_score"] * 0.3
        + frame["long_value_score"] * 0.3
        + (frame["dimension_hits"] - 1).clip(lower=0) * 4
    ).clip(lower=0, upper=100)
    return frame


def _to_output_record(row: pd.Series, trade_date: str | None, price_group: str) -> dict[str, Any]:
    dimensions: list[str] = []
    if _to_float(row.get("short_burst_score")) > 0:
        dimensions.append("short_burst")
    if _to_float(row.get("t_active_score")) > 0:
        dimensions.append("t_active")
    if _to_float(row.get("long_value_score")) > 0:
        dimensions.append("long_value")

    return {
        "trade_date": trade_date or str(row.get("trade_date") or ""),
        "price_group": price_group,
        "ts_code": str(row.get("ts_code") or ""),
        "name": str(row.get("name") or ""),
        "industry": str(row.get("industry") or ""),
        "close": round(_to_float(row.get("close")), 2),
        "total_score": round(_to_float(row.get("total_score")), 2),
        "short_burst_score": round(_to_float(row.get("short_burst_score")), 2),
        "t_active_score": round(_to_float(row.get("t_active_score")), 2),
        "long_value_score": round(_to_float(row.get("long_value_score")), 2),
        "pct_chg": round(_to_float(row.get("pct_chg")), 2),
        "volume_ratio": round(_to_float(row.get("volume_ratio")), 2),
        "turnover_rate": round(_to_float(row.get("turnover_rate")), 2),
        "intraday_amplitude_pct": round(_to_float(row.get("intraday_amplitude_pct")), 2),
        "amount_yi": round(_to_float(row.get("amount_yi")), 2),
        "pe": round(_to_float(row.get("pe_value")), 2),
        "total_mv": round(_to_float(row.get("total_mv")), 2),
        "dimensions": dimensions,
    }


def _resolve_trade_date_from_frame(frame: pd.DataFrame) -> str | None:
    if "trade_date" not in frame.columns:
        return None
    values = frame["trade_date"].dropna().astype(str).tolist()
    return values[0] if values else None


def _normalize_grouped_recommendations(
    recommendations: dict[str, list[dict[str, Any]]] | list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    if isinstance(recommendations, list):
        return {
            LOW_PRICE_GROUP_KEY: recommendations,
            MID_PRICE_GROUP_KEY: [],
        }

    return {
        LOW_PRICE_GROUP_KEY: list(recommendations.get(LOW_PRICE_GROUP_KEY, [])),
        MID_PRICE_GROUP_KEY: list(recommendations.get(MID_PRICE_GROUP_KEY, [])),
    }


def _empty_grouped_result() -> dict[str, list[dict[str, Any]]]:
    return {
        LOW_PRICE_GROUP_KEY: [],
        MID_PRICE_GROUP_KEY: [],
    }


def _get_price_range(group_key: str, default: tuple[float, float]) -> tuple[float, float]:
    raw_range = PRICE_RANGES.get(group_key)
    if not raw_range or len(raw_range) < 2:
        return default
    return float(raw_range[0]), float(raw_range[1])


def _ensure_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame


def _coerce_numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _safe_divide_series(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    safe_denominator = denominator.replace(0, pd.NA)
    return numerator.divide(safe_denominator).fillna(0.0)


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
