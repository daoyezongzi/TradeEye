from __future__ import annotations

import math
from typing import Any, Mapping

from tradeeye.strategies.rules import AnalysisRules, get_rules


DIMENSION_CAPS: dict[str, int] = {
    "趋势结构": 30,
    "收盘与价格行为": 25,
    "量能与流动性": 20,
    "资金确认": 15,
    "市场环境": 10,
}

_REQUIRED_LATEST_FIELDS: tuple[str, ...] = (
    "close",
    "open",
    "pct_chg",
    "ma5",
    "ma10",
    "ma20",
    "ma5_slope_pct",
    "breakout_10_pct",
    "close_strength",
    "upper_shadow_pct",
    "turnover_rate",
    "amount_ratio_5d",
    "turnover_pct_rank",
    "net_mf_ratio_pct",
    "large_order_net_pct",
    "net_mf_ratio_rank",
    "large_order_net_rank",
)


def check_signals(data: dict[str, Any], rules: AnalysisRules | None = None) -> dict[str, Any]:
    """Return a deterministic post-close diagnosis, never a trading signal."""

    rules = rules or get_rules().analysis
    latest = data.get("latest") if isinstance(data, Mapping) else None
    market = data.get("market_regime") if isinstance(data, Mapping) else None
    missing_fields = _find_missing_fields(data, latest, market)
    if missing_fields:
        return _insufficient_result(missing_fields)

    assert isinstance(latest, Mapping)
    assert isinstance(market, Mapping)

    close = _number(latest["close"])
    open_price = _number(latest["open"])
    pct_chg = _number(latest["pct_chg"])
    ma5 = _number(latest["ma5"])
    ma10 = _number(latest["ma10"])
    ma20 = _number(latest["ma20"])
    ma5_slope_pct = _number(latest["ma5_slope_pct"])
    breakout_pct = _number(latest["breakout_10_pct"])
    close_strength = _number(latest["close_strength"])
    upper_shadow_pct = _number(latest["upper_shadow_pct"])
    turnover_rate = _number(latest["turnover_rate"])
    amount_ratio_5d = _number(latest["amount_ratio_5d"])
    volume_ratio = _volume_ratio(latest)
    turnover_pct_rank = _number(latest["turnover_pct_rank"])
    net_mf_ratio_pct = _number(latest["net_mf_ratio_pct"])
    large_order_net_pct = _number(latest["large_order_net_pct"])
    net_mf_ratio_rank = _number(latest["net_mf_ratio_rank"])
    large_order_net_rank = _number(latest["large_order_net_rank"])
    market_score = _number(market["score"])

    reasons: list[str] = []
    dimension_scores = {
        "趋势结构": _score_trend(
            close, ma5, ma10, ma20, ma5_slope_pct, breakout_pct, rules, reasons
        ),
        "收盘与价格行为": _score_price_action(
            close, open_price, pct_chg, close_strength, upper_shadow_pct, rules, reasons
        ),
        "量能与流动性": _score_volume(
            turnover_rate, amount_ratio_5d, volume_ratio, turnover_pct_rank, rules, reasons
        ),
        "资金确认": _score_funds(
            net_mf_ratio_pct,
            large_order_net_pct,
            net_mf_ratio_rank,
            large_order_net_rank,
            rules,
            reasons,
        ),
        "市场环境": _score_market(market_score, rules, reasons),
    }
    dimension_scores = {
        name: round(max(0.0, min(float(DIMENSION_CAPS[name]), value)), 1)
        for name, value in dimension_scores.items()
    }
    raw_score = int(round(sum(dimension_scores.values())))
    raw_band = _raw_band(raw_score)

    risk_level, risk_items = _assess_risk(data, latest, market_score, rules)
    final_status = _final_status(raw_band, risk_level)
    watch_points = _build_watch_points(
        ma5=ma5,
        ma10=ma10,
        volume_ratio=volume_ratio,
        net_mf_ratio_pct=net_mf_ratio_pct,
        large_order_net_pct=large_order_net_pct,
        risk_items=risk_items,
    )

    detail = "；".join(dict.fromkeys(reasons))
    risk_text = "；".join(risk_items) if risk_items else "未发现主要风险"
    return {
        "score": raw_score,
        "raw_score": raw_score,
        "raw_band": raw_band,
        "base_status": f"结构{raw_band}",
        "status": final_status,
        "final_status": final_status,
        "risk_level": risk_level,
        "risk": risk_text,
        "dimensions": dimension_scores,
        "dimension_scores": dict(dimension_scores),
        "dimension_caps": dict(DIMENSION_CAPS),
        "reasons": list(dict.fromkeys(reasons)),
        "detail": detail,
        "next_day_watch": watch_points,
        "action_plan": "；".join(watch_points),
        "data_quality": "完整",
        "missing_fields": [],
        "vol_ratio": round(volume_ratio, 2),
        "turnover_rate": round(turnover_rate, 2),
        "amount_ratio_5d": round(amount_ratio_5d, 2),
        "net_mf_ratio_pct": round(net_mf_ratio_pct, 2),
        "large_order_net_pct": round(large_order_net_pct, 2),
        "up_limit_room_pct": round(_optional_number(latest.get("up_limit_room_pct")), 2),
        "close_strength": round(close_strength, 2),
        "breakout_pct": round(breakout_pct, 2),
        "market_bias": str(market.get("status") or _market_status(market_score, rules)),
    }


def _find_missing_fields(data: Mapping[str, Any], latest: Any, market: Any) -> list[str]:
    if not isinstance(latest, Mapping):
        missing = ["latest"]
        issue = str(data.get("data_quality_issue") or "").strip()
        if issue:
            missing.append(f"data_status.{issue}")
        return missing
    if not isinstance(market, Mapping):
        return ["market_regime"]

    missing = [
        f"latest.{field}"
        for field in _REQUIRED_LATEST_FIELDS
        if _optional_number(latest.get(field), default=None) is None
    ]
    if _volume_ratio(latest, default=None) is None:
        missing.append("latest.volume_ratio/day_vol_ratio")
    if _optional_number(market.get("score"), default=None) is None:
        missing.append("market_regime.score")

    for flag, source in (
        ("daily_basic_available", "daily_basic"),
        ("moneyflow_available", "moneyflow"),
    ):
        value = latest.get(flag)
        if value is not None and not bool(value):
            missing.append(f"data_source.{source}.{latest.get('ts_code') or 'unknown'}")

    degraded_sources = data.get("degraded_sources")
    if isinstance(degraded_sources, (list, tuple, set)):
        for source in degraded_sources:
            source_name = str(source).strip()
            if source_name:
                missing.append(f"data_source.{source_name}")

    for field in ("close", "open", "ma5", "ma10", "ma20"):
        value = _optional_number(latest.get(field), default=None)
        if value is not None and value <= 0 and f"latest.{field}" not in missing:
            missing.append(f"latest.{field}")
    return missing


def _insufficient_result(missing_fields: list[str]) -> dict[str, Any]:
    missing_text = "、".join(missing_fields)
    watch_points = ["补齐完整盘后行情后再观察结构变化，不以缺失值推断强弱"]
    return {
        "score": None,
        "raw_score": None,
        "raw_band": None,
        "base_status": "数据不足",
        "status": "数据不足",
        "final_status": "数据不足",
        "risk_level": "无法判定",
        "risk": "关键数据缺失，无法判定风险等级",
        "dimensions": {name: None for name in DIMENSION_CAPS},
        "dimension_scores": {name: None for name in DIMENSION_CAPS},
        "dimension_caps": dict(DIMENSION_CAPS),
        "reasons": [f"缺少关键数据：{missing_text}"],
        "detail": f"缺少关键数据：{missing_text}",
        "next_day_watch": watch_points,
        "action_plan": watch_points[0],
        "data_quality": "数据不足",
        "missing_fields": missing_fields,
        "vol_ratio": None,
        "turnover_rate": None,
        "amount_ratio_5d": None,
        "net_mf_ratio_pct": None,
        "large_order_net_pct": None,
        "up_limit_room_pct": None,
        "close_strength": None,
        "breakout_pct": None,
        "market_bias": "未知",
    }


def _score_trend(
    close: float,
    ma5: float,
    ma10: float,
    ma20: float,
    ma5_slope_pct: float,
    breakout_pct: float,
    rules: AnalysisRules,
    reasons: list[str],
) -> float:
    r = rules.rules
    if close > ma5 > ma10 > ma20:
        alignment = 18.0
        reasons.append("收盘位于 MA5、MA10、MA20 多头排列上方")
    elif close > ma5 > ma10:
        alignment = 12.0
        reasons.append("收盘守住 MA5 与 MA10，短线趋势仍向上")
    elif close > ma5:
        alignment = 6.0
        reasons.append("收盘仅守住 MA5，趋势确认有限")
    else:
        alignment = 0.0
        reasons.append("收盘未能守住 MA5，趋势结构偏弱")

    if ma5_slope_pct > r.ma5_slope.up_min:
        slope = 5.0
        reasons.append("MA5 斜率向上")
    elif ma5_slope_pct < r.ma5_slope.down_max:
        slope = 0.0
        reasons.append("MA5 斜率向下")
    else:
        slope = 2.5
        reasons.append("MA5 斜率走平")

    if r.breakout.sweet_min <= breakout_pct <= r.breakout.sweet_max:
        position = 7.0
        reasons.append("收盘接近近十日高位")
    elif breakout_pct < r.breakout.far_max:
        position = 0.0
        reasons.append("收盘距离近十日高位较远")
    else:
        position = 3.5
        reasons.append("近十日位置处于中间区间")
    return alignment + slope + position


def _score_price_action(
    close: float,
    open_price: float,
    pct_chg: float,
    close_strength: float,
    upper_shadow_pct: float,
    rules: AnalysisRules,
    reasons: list[str],
) -> float:
    r = rules.rules
    if close_strength >= r.close_strength.strong_min:
        closing = 8.0
        reasons.append("收盘靠近日内高位")
    elif close_strength >= r.close_strength.mid_min:
        closing = 5.0
        reasons.append("收盘位置偏强")
    elif close_strength < r.close_strength.weak_max:
        closing = 0.0
        reasons.append("收盘位置偏低")
    else:
        closing = 2.5
        reasons.append("收盘位置居中")

    if r.pct_chg.sweet_min <= pct_chg <= r.pct_chg.sweet_max:
        change = 7.0
        reasons.append("当日涨跌幅处于稳健区间")
    elif 0 < pct_chg < r.pct_chg.sweet_min:
        change = 4.0
        reasons.append("当日温和走强")
    elif pct_chg < r.pct_chg.weak_max:
        change = 0.0
        reasons.append("当日跌幅较大")
    elif pct_chg > r.pct_chg.hot_min:
        change = 0.0
        reasons.append("当日涨幅过热")
    else:
        change = 3.0
        reasons.append("当日涨跌幅中性")

    candle = 5.0 if close > open_price else 0.0
    reasons.append("日线实体收阳" if candle else "收盘未高于开盘价")

    if upper_shadow_pct <= r.upper_shadow.short_max:
        shadow = 5.0
        reasons.append("上影线较短")
    elif upper_shadow_pct > r.upper_shadow.long_min:
        shadow = 0.0
        reasons.append("上影线较长")
    else:
        shadow = 2.5
        reasons.append("上影线长度中性")
    return closing + change + candle + shadow


def _score_volume(
    turnover_rate: float,
    amount_ratio_5d: float,
    volume_ratio: float,
    turnover_pct_rank: float,
    rules: AnalysisRules,
    reasons: list[str],
) -> float:
    r = rules.rules
    if r.turnover.sweet_min <= turnover_rate <= r.turnover.sweet_max:
        turnover = 5.0
        reasons.append("换手率处于活跃但不过热区间")
    elif r.turnover.ok_min <= turnover_rate < r.turnover.sweet_min:
        turnover = 3.5
        reasons.append("换手率达到基本流动性要求")
    elif turnover_rate > r.turnover.hot_min:
        turnover = 0.0
        reasons.append("换手率过热")
    elif turnover_rate < r.turnover.ok_min:
        turnover = 0.0
        reasons.append("换手率偏低")
    else:
        turnover = 2.5
        reasons.append("换手率处于普通区间")
    turnover += _rank_points(turnover_pct_rank, r.ranks.turnover_rank_min, 2.0)

    if r.amount_ratio_5d.sweet_min <= amount_ratio_5d <= r.amount_ratio_5d.sweet_max:
        amount = 7.0
        reasons.append("成交额相对近五日温和放大")
    elif amount_ratio_5d > r.amount_ratio_5d.hot_min:
        amount = 0.0
        reasons.append("成交额放大过快")
    elif amount_ratio_5d < r.amount_ratio_5d.cold_max:
        amount = 0.0
        reasons.append("成交额低于近五日常态")
    else:
        amount = 3.5
        reasons.append("成交额处于近五日常态")

    if r.volume_ratio.sweet_min <= volume_ratio <= r.volume_ratio.sweet_max:
        volume = 6.0
        reasons.append("量比处于健康区间")
    elif volume_ratio > r.volume_ratio.hot_min:
        volume = 0.0
        reasons.append("量比过热")
    elif volume_ratio < r.volume_ratio.cold_max:
        volume = 0.0
        reasons.append("量比偏低")
    else:
        volume = 3.0
        reasons.append("量比处于普通区间")
    return turnover + amount + volume


def _score_funds(
    net_mf_ratio_pct: float,
    large_order_net_pct: float,
    net_mf_ratio_rank: float,
    large_order_net_rank: float,
    rules: AnalysisRules,
    reasons: list[str],
) -> float:
    r = rules.rules
    if net_mf_ratio_pct >= r.net_mf.strong_min:
        net_flow = 5.5
        reasons.append("资金净流入强")
    elif net_mf_ratio_pct >= r.net_mf.ok_min:
        net_flow = 4.0
        reasons.append("资金净流入为正")
    elif net_mf_ratio_pct <= r.net_mf.weak_max:
        net_flow = 0.0
        reasons.append("资金净流出明显")
    else:
        net_flow = 2.0
        reasons.append("资金净流向中性")
    net_flow += _rank_points(net_mf_ratio_rank, r.ranks.net_mf_rank_min, 2.0)

    if large_order_net_pct >= r.large_order.strong_min:
        large_orders = 5.5
        reasons.append("大单净流入强")
    elif large_order_net_pct >= r.large_order.ok_min:
        large_orders = 4.0
        reasons.append("大单净流入为正")
    elif large_order_net_pct <= r.large_order.weak_max:
        large_orders = 0.0
        reasons.append("大单净流出明显")
    else:
        large_orders = 2.0
        reasons.append("大单净流向中性")
    large_orders += _rank_points(large_order_net_rank, r.ranks.large_order_rank_min, 2.0)
    return net_flow + large_orders


def _score_market(market_score: float, rules: AnalysisRules, reasons: list[str]) -> float:
    r = rules.rules.market_regime
    if market_score >= r.strong_min:
        reasons.append("市场环境偏强")
        return 10.0
    if market_score <= r.weak_max:
        reasons.append("市场环境偏弱")
        return 0.0
    reasons.append("市场环境中性")
    return 5.0


def _rank_points(rank: float, strong_min: float, maximum: float) -> float:
    if rank >= strong_min:
        return maximum
    if rank >= 0.5:
        return maximum / 2
    return 0.0


def _assess_risk(
    data: Mapping[str, Any],
    latest: Mapping[str, Any],
    market_score: float,
    rules: AnalysisRules,
) -> tuple[str, list[str]]:
    r = rules.rules
    name = str(data.get("name") or latest.get("name") or "")
    ts_code = str(latest.get("ts_code") or "")
    market_name = str(latest.get("market") or "")
    list_age_days = _optional_number(latest.get("list_age_days"), default=None)
    pct_chg = _number(latest["pct_chg"])
    turnover_rate = _number(latest["turnover_rate"])
    up_limit_room = _optional_number(latest.get("up_limit_room_pct"), default=None)
    close_strength = _number(latest["close_strength"])
    upper_shadow_pct = _number(latest["upper_shadow_pct"])
    net_mf_ratio_pct = _number(latest["net_mf_ratio_pct"])
    large_order_net_pct = _number(latest["large_order_net_pct"])

    hard_risks: list[str] = []
    major_risks: list[str] = []
    warnings: list[str] = []
    normalized_name = name.strip().upper()
    if normalized_name.startswith(("ST", "*ST")):
        hard_risks.append("ST 标的存在硬风险")
    if list_age_days is not None and 0 <= list_age_days < r.penalties.new_stock_age_days:
        major_risks.append(f"上市未满 {r.penalties.new_stock_age_days} 天")
    if ts_code.endswith(".BJ") or "北交所" in market_name:
        major_risks.append("北交所流动性与波动风险较高")
    if up_limit_room is not None and 0 < up_limit_room < r.up_limit_room.near_max:
        major_risks.append("收盘接近涨停，次日价格波动风险较高")
    if pct_chg > r.pct_chg.hot_min:
        major_risks.append("当日涨幅过热")
    if turnover_rate > r.turnover.hot_min:
        major_risks.append("换手率过热")

    if market_score <= r.market_regime.weak_max:
        warnings.append("市场环境偏弱")
    if close_strength < r.close_strength.weak_max:
        warnings.append("收盘位置偏低")
    if upper_shadow_pct > r.upper_shadow.long_min:
        warnings.append("上影线较长")
    if net_mf_ratio_pct <= r.net_mf.weak_max:
        warnings.append("资金净流出明显")
    if large_order_net_pct <= r.large_order.weak_max:
        warnings.append("大单净流出明显")

    if hard_risks or len(major_risks) >= 2:
        level = "高风险"
    elif len(major_risks) == 1 or len(warnings) >= 2:
        level = "中风险"
    else:
        level = "低风险"
    return level, list(dict.fromkeys(hard_risks + major_risks + warnings))


def _raw_band(score: int) -> str:
    if score >= 80:
        return "强"
    if score >= 65:
        return "较强"
    if score >= 50:
        return "中性"
    return "弱"


def _final_status(raw_band: str, risk_level: str) -> str:
    if risk_level == "高风险":
        return "高风险"
    if risk_level == "低风险":
        return raw_band
    return {"强": "观察", "较强": "观察", "中性": "谨慎", "弱": "弱"}[raw_band]


def _build_watch_points(
    *,
    ma5: float,
    ma10: float,
    volume_ratio: float,
    net_mf_ratio_pct: float,
    large_order_net_pct: float,
    risk_items: list[str],
) -> list[str]:
    points = [f"观察次日收盘能否守住 MA5（{ma5:.2f}），并关注 MA10（{ma10:.2f}）附近的结构变化"]
    if volume_ratio > 2.5:
        points.append("观察量能能否从高位回归，避免异常放量延续")
    elif volume_ratio < 0.8:
        points.append("观察量能能否恢复到近日日均水平")
    else:
        points.append("观察量能是否保持在近期常态区间")

    if net_mf_ratio_pct > 0 and large_order_net_pct > 0:
        points.append("观察资金净流入与大单净额能否继续同向为正")
    else:
        points.append("观察资金净流向与大单净额是否转为同向改善")
    if risk_items:
        points.append(f"重点观察风险项是否缓解：{risk_items[0]}")
    return points


def _market_status(score: float, rules: AnalysisRules) -> str:
    r = rules.rules.market_regime
    if score >= r.strong_min:
        return "偏强"
    if score <= r.weak_max:
        return "偏弱"
    return "中性"


def _volume_ratio(latest: Mapping[str, Any], default: Any = 0.0) -> Any:
    for field in ("volume_ratio", "day_vol_ratio"):
        value = _optional_number(latest.get(field), default=None)
        if value is not None:
            return value
    return default


def _number(value: Any) -> float:
    number = _optional_number(value, default=None)
    if number is None:  # guarded by the data-quality gate
        raise ValueError("expected a finite number")
    return number


def _optional_number(value: Any, default: Any = 0.0) -> Any:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, str) and not value.strip():
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default
