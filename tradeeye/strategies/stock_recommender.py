from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from enum import Enum
from typing import Any, Mapping

import pandas as pd

from tradeeye.config import Settings, extract_exchange
from tradeeye.services.data import build_pro_client, get_market_snapshot, resolve_trade_date
from tradeeye.strategies.rules import EtfRules, RecommenderRules, get_rules

logger = logging.getLogger(__name__)

STOCK_CANDIDATES_KEY = "candidates"
DEFAULT_TOP_N = 5
STRATEGY_VERSION = "recommend_v2"
ETF_STRATEGY_VERSION = "etf_recommend_v1"

# Import aliases retained while callers migrate from the legacy two-group result.
LOW_PRICE_GROUP_KEY = "low_price_group"
MID_PRICE_GROUP_KEY = "mid_price_group"
DEFAULT_TOP_N_PER_GROUP = DEFAULT_TOP_N

ETF_STATUS_DISABLED = "disabled"
ETF_STATUS_EMPTY_WHITELIST = "empty_whitelist"
ETF_STATUS_AVAILABLE = "available"
ETF_STATUS_NO_DATA = "no_data"
ETF_STATUS_UNAVAILABLE = "unavailable"


def recommend_top_stocks(
    settings: Settings,
    top_n: int = DEFAULT_TOP_N,
    pro_client=None,
    rules: RecommenderRules | None = None,
) -> dict[str, Any]:
    """Return one quality-gated stock pool capped at five candidates."""
    rules = rules or get_rules().recommender
    if not settings.tushare_token:
        logger.error("Stock recommender skipped: missing TUSHARE_TOKEN")
        return _empty_stock_result(rules, message="缺少 TUSHARE_TOKEN，股票荐股不可用。")

    client = pro_client or build_pro_client(settings)
    snapshot = get_market_snapshot(settings, pro_client=client)
    if snapshot.market_df.empty:
        return _empty_stock_result(rules, trade_date=snapshot.trade_date, message="当日股票行情为空。")

    result = rank_market_candidates(
        market_df=snapshot.market_df,
        allowed_exchanges=settings.allowed_exchanges,
        trade_date=snapshot.trade_date,
        top_n=top_n,
        rules=rules,
    )
    result["degraded_sources"] = list(getattr(snapshot, "degraded_sources", ()))
    return result


def rank_market_candidates(
    market_df: pd.DataFrame,
    allowed_exchanges: tuple[str, ...],
    recommender_industries: tuple[str, ...] = (),
    trade_date: str | None = None,
    top_n_each_group: int | None = None,
    rules: RecommenderRules | None = None,
    *,
    top_n: int | None = None,
) -> dict[str, Any]:
    """Score a snapshot deterministically and return a single stock pool.

    ``top_n_each_group`` is accepted as a legacy call-site alias. It now caps the
    unified pool and can never raise the configured or absolute five-stock cap.
    ``recommender_industries`` is retained for call compatibility; industry is
    metadata in recommend_v2 and does not filter or score candidates.
    """
    rules = rules or get_rules().recommender
    _ = recommender_industries
    requested_limit = top_n if top_n is not None else top_n_each_group
    limit = _resolve_stock_limit(requested_limit, rules.max_results)
    if market_df.empty or limit == 0:
        return _empty_stock_result(rules, trade_date=trade_date)

    ranked_df = _build_scored_stock_frame(market_df, allowed_exchanges, rules)
    date_value = trade_date or _resolve_trade_date_from_frame(ranked_df) or _resolve_trade_date_from_frame(market_df)
    if ranked_df.empty:
        return _empty_stock_result(rules, trade_date=date_value)

    selected = ranked_df.sort_values(
        ["risk_priority", "ranking_score", "quality_score", "amount", "ts_code"],
        ascending=[True, False, False, False, True],
        kind="stable",
    ).head(limit)
    fingerprint = rules_fingerprint(rules)
    candidates = [_to_stock_record(row, date_value, rules, fingerprint) for _, row in selected.iterrows()]
    return {
        "strategy_version": rules.strategy_version,
        "rules_fingerprint": fingerprint,
        "trade_date": date_value or "",
        STOCK_CANDIDATES_KEY: candidates,
        "message": "" if candidates else "今日无满足质量与风险门的推荐股票。",
    }


def recommend_top_etfs(
    settings: Settings,
    trade_date: str | None = None,
    top_n: int | None = None,
    pro_client=None,
    rules: EtfRules | None = None,
) -> dict[str, Any]:
    """Fetch and rank the optional ETF whitelist without affecting stocks."""
    rules = rules or get_rules().etf
    if not rules.enabled:
        return _empty_etf_result(rules, ETF_STATUS_DISABLED, trade_date, "ETF 推荐未启用。")
    if not rules.codes:
        return _empty_etf_result(rules, ETF_STATUS_EMPTY_WHITELIST, trade_date, "ETF 白名单为空，未调用接口。")
    if not settings.tushare_token:
        return _empty_etf_result(rules, ETF_STATUS_UNAVAILABLE, trade_date, "缺少 TUSHARE_TOKEN，ETF 分支不可用。")

    try:
        client = pro_client or build_pro_client(settings)
        date_value = trade_date or resolve_trade_date(client)
        basic_df = client.etf_basic(
            list_status="L",
            fields="ts_code,csname,extname,etf_type,list_status,list_date",
        )
        daily_df = client.fund_daily(
            trade_date=date_value,
            fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        )
    except Exception as exc:  # ETF is an explicitly isolated best-effort branch.
        logger.warning("ETF recommendation branch unavailable: %s", exc, exc_info=True)
        return _empty_etf_result(
            rules,
            ETF_STATUS_UNAVAILABLE,
            trade_date,
            f"ETF 接口不可用，股票荐股不受影响：{_external_error_text(exc)}",
        )

    basic_df = _copy_dataframe(basic_df)
    daily_df = _copy_dataframe(daily_df)
    if basic_df.empty:
        return _empty_etf_result(
            rules,
            ETF_STATUS_UNAVAILABLE,
            date_value,
            "etf_basic 未返回可用数据，ETF 分支已降级，股票荐股不受影响。",
        )
    if daily_df.empty:
        return _empty_etf_result(rules, ETF_STATUS_NO_DATA, date_value, "ETF 白名单在目标交易日无行情。")

    whitelist = set(rules.codes)
    basic_df = _ensure_columns(basic_df, ["ts_code", "csname", "extname", "etf_type", "fund_type"])
    daily_df = _ensure_columns(daily_df, ["ts_code", "trade_date"])
    basic_df = basic_df.loc[basic_df["ts_code"].astype(str).isin(whitelist)].copy()
    if basic_df.empty:
        return _empty_etf_result(
            rules,
            ETF_STATUS_NO_DATA,
            date_value,
            "ETF 白名单未匹配到上市基础信息。",
        )
    active_codes = set(basic_df["ts_code"].astype(str))
    daily_df = daily_df.loc[daily_df["ts_code"].astype(str).isin(active_codes)].copy()
    if daily_df.empty:
        return _empty_etf_result(rules, ETF_STATUS_NO_DATA, date_value, "ETF 白名单在目标交易日无行情。")

    basic_df["etf_name"] = basic_df["csname"].where(basic_df["csname"].notna(), basic_df["extname"])
    basic_df["fund_type"] = basic_df["etf_type"].where(basic_df["etf_type"].notna(), basic_df["fund_type"])
    basic_names = basic_df[["ts_code", "etf_name", "fund_type"]].drop_duplicates(
        subset=["ts_code"],
        keep="first",
    )
    market_df = daily_df.merge(basic_names, on="ts_code", how="left")
    ranked_df = _build_scored_etf_frame(market_df, rules)
    if ranked_df.empty:
        return _empty_etf_result(
            rules,
            ETF_STATUS_NO_DATA,
            date_value,
            "ETF 白名单无标的通过最低质量分。",
        )

    limit = max(0, min(top_n if top_n is not None else rules.max_results, rules.max_results))
    selected = ranked_df.sort_values(
        ["quality_score", "amount", "ts_code"],
        ascending=[False, False, True],
        kind="stable",
    ).head(limit)
    fingerprint = rules_fingerprint(rules)
    candidates = [_to_etf_record(row, date_value, rules, fingerprint) for _, row in selected.iterrows()]
    return {
        "strategy_version": rules.strategy_version,
        "rules_fingerprint": fingerprint,
        "status": ETF_STATUS_AVAILABLE,
        "trade_date": date_value or "",
        STOCK_CANDIDATES_KEY: candidates,
        "message": "",
    }


def recommendations_to_json(recommendations: Mapping[str, Any] | list[dict[str, Any]]) -> str:
    """Serialize the canonical pool; legacy grouped input is normalized first."""
    return json.dumps(_normalize_stock_result(recommendations), ensure_ascii=False, sort_keys=True)


def build_recommendation_brief(recommendations: Mapping[str, Any] | list[dict[str, Any]]) -> str:
    result = _normalize_stock_result(recommendations)
    candidates = result[STOCK_CANDIDATES_KEY]
    version = str(result.get("strategy_version") or STRATEGY_VERSION)
    degraded_sources = list(result.get("degraded_sources", []))
    degraded_line = (
        f"\n- 数据降级：{','.join(degraded_sources)} 不可用，对应评分子项按 0 分处理。"
        if degraded_sources
        else ""
    )
    if not candidates:
        return f"股票统一候选池（{version}）：\n- 今日无满足质量与风险门的推荐股票。{degraded_line}"

    lines = [f"股票统一候选池（{version}，最多5只）："]
    if degraded_sources:
        lines.append(f"- 数据降级：{','.join(degraded_sources)} 不可用，对应评分子项按 0 分处理。")
    for index, item in enumerate(candidates, start=1):
        risk_text = _risk_text(item.get("risk_level"), item.get("risk_flags"))
        preferred_max = item.get("preferred_price_max", 20)
        preference_text = (
            f"{preferred_max}元内排序偏好已应用"
            if item.get("price_preference_applied")
            else "未应用价格偏好"
        )
        lines.extend(
            [
                (
                    f"- {index}. {item.get('ts_code')} {item.get('name')} | 收盘 {item.get('close')} "
                    f"| 质量分 {item.get('quality_score', item.get('total_score'))}/100"
                ),
                (
                    f"  三维：短线动能 {item.get('momentum_score')}/40；"
                    f"收盘质量 {item.get('close_quality_score')}/35；"
                    f"量能资金 {item.get('volume_funds_score')}/25"
                ),
                f"  风险：{risk_text}；排序：{preference_text}",
                f"  入场计划：{item.get('entry_plan') or _fallback_entry_plan(item)}",
                f"  本地说明：{item.get('local_reason') or _fallback_local_reason(item)}",
            ]
        )
    return "\n".join(lines)


def build_etf_recommendation_brief(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or ETF_STATUS_NO_DATA)
    if status == ETF_STATUS_DISABLED:
        return ""

    version = str(result.get("strategy_version") or ETF_STRATEGY_VERSION)
    candidates = list(result.get(STOCK_CANDIDATES_KEY, []))
    lines = [f"ETF 白名单推荐（{version}，独立评分）："]
    if status != ETF_STATUS_AVAILABLE or not candidates:
        lines.append(f"- 状态：{result.get('message') or '无可用 ETF 候选。'}")
        return "\n".join(lines)

    for index, item in enumerate(candidates, start=1):
        lines.extend(
            [
                (
                    f"- {index}. {item.get('ts_code')} {item.get('name')} | 收盘 {item.get('close')} "
                    f"| 质量分 {item.get('quality_score')}/100"
                ),
                (
                    f"  三维：动能 {item.get('momentum_score')}/45；"
                    f"收盘质量 {item.get('close_quality_score')}/35；"
                    f"流动性 {item.get('liquidity_score')}/20"
                ),
                f"  入场计划：{item.get('entry_plan')}",
                f"  本地说明：{item.get('local_reason')}",
            ]
        )
    return "\n".join(lines)


def rules_fingerprint(rules: RecommenderRules | EtfRules) -> str:
    payload = json.dumps(asdict(rules), ensure_ascii=True, sort_keys=True, default=_json_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _build_scored_stock_frame(
    market_df: pd.DataFrame,
    allowed_exchanges: tuple[str, ...],
    rules: RecommenderRules,
) -> pd.DataFrame:
    frame = market_df.copy()
    frame = _ensure_columns(
        frame,
        [
            "ts_code",
            "name",
            "industry",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "pct_chg",
            "pct_chg_rank",
            "turnover_rate",
            "volume_ratio",
            "amount",
            "amount_pct_rank",
            "net_mf_ratio_pct",
            "large_order_net_pct",
            "close_strength",
            "upper_shadow_pct",
            "total_mv",
            "pe",
            "pe_ttm",
        ],
    )
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "pct_chg",
        "pct_chg_rank",
        "turnover_rate",
        "volume_ratio",
        "amount",
        "amount_pct_rank",
        "net_mf_ratio_pct",
        "large_order_net_pct",
        "close_strength",
        "upper_shadow_pct",
        "total_mv",
        "pe",
        "pe_ttm",
    ]
    frame = _coerce_numeric(frame, numeric_columns)

    allowed_set = {exchange.upper() for exchange in allowed_exchanges}
    frame = frame.loc[frame["ts_code"].astype(str).map(lambda code: extract_exchange(code) in allowed_set)].copy()
    frame = frame.loc[_valid_ohlc_mask(frame)].copy()
    if rules.hard_min is not None:
        frame = frame.loc[frame["close"] >= rules.hard_min].copy()
    if rules.hard_max is not None:
        frame = frame.loc[frame["close"] <= rules.hard_max].copy()
    if frame.empty:
        return frame

    name_series = frame["name"].fillna("").astype(str)
    name_upper = name_series.str.upper()
    is_st = name_upper.str.match(r"^(?:\*?ST|S\*ST|SST)(?![A-Z])")
    is_delisted = name_series.str.contains("退", regex=False) | name_upper.str.contains("DELIST", regex=False)
    frame = frame.loc[~(is_st | is_delisted)].copy()
    if frame.empty:
        return frame

    _fill_price_features(frame)
    frame["pct_chg_rank"] = frame["pct_chg_rank"].fillna(frame["pct_chg"].rank(pct=True, na_option="keep")).fillna(0)
    frame["amount_pct_rank"] = (
        frame["amount_pct_rank"].fillna(frame["amount"].rank(pct=True, na_option="keep")).fillna(0)
    )
    frame["body_pct"] = _safe_divide_series(frame["close"] - frame["open"], frame["pre_close"]) * 100

    risk = rules.risk_gate
    frame["overheat_flags"] = frame.apply(lambda row: _overheat_flags(row, risk), axis=1)
    frame["weak_close_long_shadow"] = (
        (frame["close_strength"] < risk.weak_close_max)
        & (frame["upper_shadow_pct"] > risk.long_upper_shadow_min)
    )
    frame["overheat_count"] = frame["overheat_flags"].map(len)
    hard_reject = frame["weak_close_long_shadow"] | (frame["overheat_count"] >= risk.reject_overheat_count)
    frame = frame.loc[~hard_reject].copy()
    if frame.empty:
        return frame

    momentum = rules.momentum
    frame["momentum_score"] = (
        _linear_points(frame["pct_chg"], momentum.pct_chg_min, momentum.pct_chg_full, 24)
        + _linear_points(frame["pct_chg_rank"], momentum.pct_rank_min, momentum.pct_rank_full, 16)
    ).clip(lower=0, upper=40)

    close = rules.close_quality
    frame["close_quality_score"] = (
        _linear_points(frame["close_strength"], close.close_strength_min, close.close_strength_full, 20)
        + _linear_points(frame["body_pct"], close.body_pct_min, close.body_pct_full, 10)
        + _inverse_points(frame["upper_shadow_pct"], close.upper_shadow_full, close.upper_shadow_zero, 5)
    ).clip(lower=0, upper=35)

    volume = rules.volume_funds
    frame["volume_funds_score"] = (
        _linear_points(frame["turnover_rate"], volume.turnover_min, volume.turnover_full, 6)
        + _linear_points(frame["volume_ratio"], volume.volume_ratio_min, volume.volume_ratio_full, 5)
        + _linear_points(frame["amount_pct_rank"], volume.amount_rank_min, volume.amount_rank_full, 4)
        + _linear_points(frame["net_mf_ratio_pct"], volume.net_mf_ratio_min, volume.net_mf_ratio_full, 5)
        + _linear_points(
            frame["large_order_net_pct"],
            volume.large_order_net_min,
            volume.large_order_net_full,
            5,
        )
    ).clip(lower=0, upper=25)
    frame["quality_score"] = (
        frame["momentum_score"] + frame["close_quality_score"] + frame["volume_funds_score"]
    ).clip(lower=0, upper=100)
    frame = frame.loc[frame["quality_score"] >= rules.minimum_quality_score].copy()
    if frame.empty:
        return frame

    frame["risk_level"] = frame["overheat_count"].map(lambda count: "overheat_watch" if count > 0 else "normal")
    frame["risk_priority"] = (frame["overheat_count"] > 0).astype(int)
    frame["price_preference_applied"] = frame["close"] <= rules.preferred_price_max
    frame["price_preference_bonus"] = frame["price_preference_applied"].astype(float) * rules.preferred_price_bonus
    frame["ranking_score"] = frame["quality_score"] + frame["price_preference_bonus"]
    return frame


def _build_scored_etf_frame(market_df: pd.DataFrame, rules: EtfRules) -> pd.DataFrame:
    frame = _ensure_columns(
        market_df.copy(),
        [
            "ts_code",
            "etf_name",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "pct_chg",
            "amount",
        ],
    )
    frame = _coerce_numeric(frame, ["open", "high", "low", "close", "pre_close", "pct_chg", "amount"])
    frame = frame.loc[_valid_ohlc_mask(frame)].copy()
    if frame.empty:
        return frame

    missing_pct = frame["pct_chg"].isna()
    frame.loc[missing_pct, "pct_chg"] = (
        _safe_divide_series(
            frame.loc[missing_pct, "close"] - frame.loc[missing_pct, "pre_close"],
            frame.loc[missing_pct, "pre_close"],
        )
        * 100
    )
    _fill_price_features(frame)
    frame["body_pct"] = _safe_divide_series(frame["close"] - frame["open"], frame["pre_close"]) * 100
    frame["pct_chg_rank"] = frame["pct_chg"].rank(pct=True, na_option="keep").fillna(0)
    frame["amount_pct_rank"] = frame["amount"].rank(pct=True, na_option="keep").fillna(0)

    momentum = rules.momentum
    frame["momentum_score"] = (
        _linear_points(frame["pct_chg"], momentum.pct_chg_min, momentum.pct_chg_full, 30)
        + _linear_points(frame["pct_chg_rank"], momentum.pct_rank_min, momentum.pct_rank_full, 15)
    ).clip(lower=0, upper=45)
    close = rules.close_quality
    frame["close_quality_score"] = (
        _linear_points(frame["close_strength"], close.close_strength_min, close.close_strength_full, 20)
        + _linear_points(frame["body_pct"], close.body_pct_min, close.body_pct_full, 10)
        + _inverse_points(frame["upper_shadow_pct"], close.upper_shadow_full, close.upper_shadow_zero, 5)
    ).clip(lower=0, upper=35)
    liquidity = rules.liquidity
    frame["liquidity_score"] = (
        _linear_points(frame["amount"], liquidity.amount_min, liquidity.amount_full, 12)
        + _linear_points(frame["amount_pct_rank"], liquidity.amount_rank_min, liquidity.amount_rank_full, 8)
    ).clip(lower=0, upper=20)
    frame["quality_score"] = (
        frame["momentum_score"] + frame["close_quality_score"] + frame["liquidity_score"]
    ).clip(lower=0, upper=100)
    return frame.loc[frame["quality_score"] >= rules.minimum_quality_score].copy()


def _to_stock_record(
    row: pd.Series,
    trade_date: str | None,
    rules: RecommenderRules,
    fingerprint: str,
) -> dict[str, Any]:
    close = round(_to_float(row.get("close")), 2)
    momentum_score = round(_to_float(row.get("momentum_score")), 2)
    close_quality_score = round(_to_float(row.get("close_quality_score")), 2)
    volume_funds_score = round(_to_float(row.get("volume_funds_score")), 2)
    quality_score = round(momentum_score + close_quality_score + volume_funds_score, 2)
    flags = list(row.get("overheat_flags") or [])
    preference_applied = bool(row.get("price_preference_applied"))
    entry_price = round(close * rules.entry_price_multiplier, 2)
    risk_level = str(row.get("risk_level") or "normal")
    industry = _clean_text(row.get("industry"), "未知")
    local_reason = (
        f"短线动能{momentum_score}/40、收盘质量{close_quality_score}/35、"
        f"量能资金{volume_funds_score}/25；风险层为{_risk_text(risk_level, flags)}。"
    )
    entry_plan = (
        f"D+1 仅在价格触及 {entry_price:.2f} 元（D收盘 {close:.2f}×{rules.entry_price_multiplier:.2f}）时计划入场，"
        "当日未触及则信号过期。"
    )
    return {
        "asset_type": "stock",
        "strategy_version": rules.strategy_version,
        "rules_fingerprint": fingerprint,
        "trade_date": trade_date or str(row.get("trade_date") or ""),
        "ts_code": str(row.get("ts_code") or ""),
        "name": _clean_text(row.get("name"), "未知"),
        "industry": industry,
        "close": close,
        "momentum_score": momentum_score,
        "close_quality_score": close_quality_score,
        "volume_funds_score": volume_funds_score,
        "quality_score": quality_score,
        "total_score": quality_score,
        "ranking_score": round(quality_score + (rules.preferred_price_bonus if preference_applied else 0), 2),
        "quality_gate_passed": True,
        "risk_level": risk_level,
        "risk_flags": flags,
        "price_preference_applied": preference_applied,
        "preferred_price_max": rules.preferred_price_max,
        "price_preference_bonus": rules.preferred_price_bonus if preference_applied else 0.0,
        "planned_entry_price": entry_price,
        "entry_price_multiplier": rules.entry_price_multiplier,
        "entry_plan": entry_plan,
        "local_reason": local_reason,
        "pct_chg": round(_to_float(row.get("pct_chg")), 2),
        "close_strength": round(_to_float(row.get("close_strength")), 4),
        "upper_shadow_pct": round(_to_float(row.get("upper_shadow_pct")), 2),
        "volume_ratio": round(_to_float(row.get("volume_ratio")), 2),
        "turnover_rate": round(_to_float(row.get("turnover_rate")), 2),
        "amount": round(_to_float(row.get("amount")), 2),
        "pe": round(_preferred_pe(row), 2),
        "total_mv": round(_to_float(row.get("total_mv")), 2),
        "dimensions": ["short_momentum", "close_quality", "volume_funds"],
    }


def _to_etf_record(row: pd.Series, trade_date: str, rules: EtfRules, fingerprint: str) -> dict[str, Any]:
    close = round(_to_float(row.get("close")), 3)
    momentum_score = round(_to_float(row.get("momentum_score")), 2)
    close_quality_score = round(_to_float(row.get("close_quality_score")), 2)
    liquidity_score = round(_to_float(row.get("liquidity_score")), 2)
    quality_score = round(momentum_score + close_quality_score + liquidity_score, 2)
    entry_price = round(close * rules.entry_price_multiplier, 3)
    return {
        "asset_type": "etf",
        "strategy_version": rules.strategy_version,
        "rules_fingerprint": fingerprint,
        "trade_date": trade_date or str(row.get("trade_date") or ""),
        "ts_code": str(row.get("ts_code") or ""),
        "name": _clean_text(row.get("etf_name"), "未知ETF"),
        "fund_type": _clean_text(row.get("fund_type"), "未知"),
        "close": close,
        "momentum_score": momentum_score,
        "close_quality_score": close_quality_score,
        "liquidity_score": liquidity_score,
        "quality_score": quality_score,
        "total_score": quality_score,
        "quality_gate_passed": True,
        "planned_entry_price": entry_price,
        "entry_price_multiplier": rules.entry_price_multiplier,
        "entry_plan": (
            f"D+1 仅在价格触及 {entry_price:.3f} 元（D收盘×{rules.entry_price_multiplier:.2f}）时计划入场，"
            "当日未触及则信号过期。"
        ),
        "local_reason": (
            f"ETF动能{momentum_score}/45、收盘质量{close_quality_score}/35、"
            f"流动性{liquidity_score}/20；仅在独立ETF白名单内排序。"
        ),
        "pct_chg": round(_to_float(row.get("pct_chg")), 2),
        "amount": round(_to_float(row.get("amount")), 2),
        "dimensions": ["etf_momentum", "close_quality", "liquidity"],
    }


def _normalize_stock_result(recommendations: Mapping[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(recommendations, list):
        candidates = list(recommendations)
        return {
            "strategy_version": STRATEGY_VERSION,
            "trade_date": _trade_date_from_items(candidates),
            STOCK_CANDIDATES_KEY: candidates,
            "message": "",
        }

    if STOCK_CANDIDATES_KEY in recommendations:
        normalized = {
            "strategy_version": recommendations.get("strategy_version", STRATEGY_VERSION),
            "rules_fingerprint": recommendations.get("rules_fingerprint", ""),
            "trade_date": recommendations.get("trade_date", ""),
            STOCK_CANDIDATES_KEY: list(recommendations.get(STOCK_CANDIDATES_KEY, [])),
            "message": recommendations.get("message", ""),
        }
        if "degraded_sources" in recommendations:
            normalized["degraded_sources"] = list(recommendations.get("degraded_sources", []))
        return normalized

    # Read legacy payloads during migration, but never emit the two hard groups.
    candidates = list(recommendations.get(LOW_PRICE_GROUP_KEY, [])) + list(
        recommendations.get(MID_PRICE_GROUP_KEY, [])
    )
    return {
        "strategy_version": STRATEGY_VERSION,
        "trade_date": _trade_date_from_items(candidates),
        STOCK_CANDIDATES_KEY: candidates,
        "message": "",
    }


def _empty_stock_result(
    rules: RecommenderRules,
    trade_date: str | None = None,
    message: str = "今日无满足质量与风险门的推荐股票。",
) -> dict[str, Any]:
    return {
        "strategy_version": rules.strategy_version,
        "rules_fingerprint": rules_fingerprint(rules),
        "trade_date": trade_date or "",
        STOCK_CANDIDATES_KEY: [],
        "message": message,
    }


def _empty_etf_result(
    rules: EtfRules,
    status: str,
    trade_date: str | None,
    message: str,
) -> dict[str, Any]:
    return {
        "strategy_version": rules.strategy_version,
        "rules_fingerprint": rules_fingerprint(rules),
        "status": status,
        "trade_date": trade_date or "",
        STOCK_CANDIDATES_KEY: [],
        "message": message,
    }


def _fill_price_features(frame: pd.DataFrame) -> None:
    derived_close_strength = _safe_divide_series(frame["close"] - frame["low"], frame["high"] - frame["low"]).clip(
        lower=0,
        upper=1,
    )
    frame["close_strength"] = frame.get("close_strength", pd.Series(index=frame.index, dtype=float)).fillna(
        derived_close_strength
    ).clip(lower=0, upper=1)
    derived_upper_shadow = (
        _safe_divide_series(frame["high"] - frame[["open", "close"]].max(axis=1), frame["pre_close"]) * 100
    ).clip(lower=0)
    frame["upper_shadow_pct"] = frame.get("upper_shadow_pct", pd.Series(index=frame.index, dtype=float)).fillna(
        derived_upper_shadow
    ).clip(lower=0)


def _valid_ohlc_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        frame[["open", "high", "low", "close", "pre_close"]].notna().all(axis=1)
        & (frame[["open", "high", "low", "close", "pre_close"]] > 0).all(axis=1)
        & (frame["high"] >= frame[["open", "close"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close"]].min(axis=1))
        & (frame["high"] >= frame["low"])
    )


def _overheat_flags(row: pd.Series, risk) -> list[str]:
    flags: list[str] = []
    if _to_float(row.get("pct_chg")) > risk.pct_chg_hot:
        flags.append("pct_chg_hot")
    if _to_float(row.get("turnover_rate")) > risk.turnover_hot:
        flags.append("turnover_hot")
    if _to_float(row.get("volume_ratio")) > risk.volume_ratio_hot:
        flags.append("volume_ratio_hot")
    return flags


def _linear_points(series: pd.Series, minimum: float, full: float, points: float) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").fillna(minimum)
    return ((numeric - minimum) / (full - minimum)).clip(lower=0, upper=1) * points


def _inverse_points(series: pd.Series, full: float, zero: float, points: float) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").fillna(zero)
    return ((zero - numeric) / (zero - full)).clip(lower=0, upper=1) * points


def _risk_text(level: Any, flags: Any) -> str:
    flag_labels = {
        "pct_chg_hot": "涨幅过热",
        "turnover_hot": "换手过热",
        "volume_ratio_hot": "量比过热",
    }
    normalized_flags = list(flags or [])
    if str(level) in {"overheat_watch", "single_overheat"} and normalized_flags:
        labels = "、".join(flag_labels.get(flag, flag) for flag in normalized_flags)
        return f"过热观察（{labels}），排在普通候选后"
    return "正常"


def _fallback_entry_plan(item: Mapping[str, Any]) -> str:
    entry = item.get("planned_entry_price", "")
    return f"D+1 计划价 {entry}，当日未触及则信号过期。"


def _fallback_local_reason(item: Mapping[str, Any]) -> str:
    return (
        f"短线动能{item.get('momentum_score', 0)}/40、收盘质量{item.get('close_quality_score', 0)}/35、"
        f"量能资金{item.get('volume_funds_score', 0)}/25。"
    )


def _resolve_stock_limit(requested: int | None, configured: int) -> int:
    value = configured if requested is None else requested
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = configured
    return max(0, min(parsed, configured, DEFAULT_TOP_N))


def _resolve_trade_date_from_frame(frame: pd.DataFrame) -> str | None:
    if "trade_date" not in frame.columns:
        return None
    values = frame["trade_date"].dropna().astype(str).tolist()
    return values[0] if values else None


def _trade_date_from_items(items: list[dict[str, Any]]) -> str:
    for item in items:
        value = item.get("trade_date")
        if value:
            return str(value)
    return ""


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
    safe_denominator = denominator.mask(denominator == 0)
    return numerator.divide(safe_denominator).replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)


def _preferred_pe(row: pd.Series) -> float:
    pe_ttm = _to_float(row.get("pe_ttm"))
    return pe_ttm if pe_ttm > 0 else _to_float(row.get("pe"))


def _copy_dataframe(value: Any) -> pd.DataFrame:
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _clean_text(value: Any, fallback: str) -> str:
    if value is None or pd.isna(value) or not str(value).strip():
        return fallback
    return str(value).strip()


def _external_error_text(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {message[:160]}" if message else type(exc).__name__


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "" or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
