from __future__ import annotations

from typing import Any

from tradeeye.strategies.rules import AnalysisRules, get_rules


def check_signals(data: dict[str, Any], rules: AnalysisRules | None = None) -> dict[str, Any]:
    if not data or "latest" not in data or "prev" not in data:
        return {
            "score": 0,
            "status": "【数据缺失】",
            "detail": "无法获取隔夜策略所需行情",
            "risk": "数据不足",
            "vol_ratio": 0.0,
            "turnover_rate": 0.0,
            "amount_ratio_5d": 0.0,
            "net_mf_ratio_pct": 0.0,
            "large_order_net_pct": 0.0,
            "up_limit_room_pct": 0.0,
            "close_strength": 0.0,
            "breakout_pct": 0.0,
            "market_bias": "未知",
            "action_plan": "跳过本次分析。",
        }

    rules = rules or get_rules().analysis
    r = rules.rules

    latest = data["latest"]
    prev = data["prev"]
    market_regime = data.get("market_regime", {})

    close = _to_float(latest.get("close"))
    open_price = _to_float(latest.get("open"))
    pct_chg = _to_float(latest.get("pct_chg"))
    turnover_rate = _to_float(latest.get("turnover_rate"))
    volume_ratio = _pick_first_float(latest.get("volume_ratio"), latest.get("day_vol_ratio"))
    amount_ratio_5d = _to_float(latest.get("amount_ratio_5d"))
    net_mf_ratio_pct = _to_float(latest.get("net_mf_ratio_pct"))
    large_order_net_pct = _to_float(latest.get("large_order_net_pct"))
    up_limit_room_pct = _to_float(latest.get("up_limit_room_pct"))
    close_strength = _to_float(latest.get("close_strength"))
    upper_shadow_pct = _to_float(latest.get("upper_shadow_pct"))
    breakout_pct = _to_float(latest.get("breakout_10_pct"))
    ma5 = _to_float(latest.get("ma5"))
    ma10 = _to_float(latest.get("ma10"))
    ma20 = _to_float(latest.get("ma20"))
    ma5_slope_pct = _to_float(latest.get("ma5_slope_pct"))
    turnover_pct_rank = _to_float(latest.get("turnover_pct_rank"))
    net_mf_ratio_rank = _to_float(latest.get("net_mf_ratio_rank"))
    large_order_net_rank = _to_float(latest.get("large_order_net_rank"))
    list_age_days = int(_to_float(latest.get("list_age_days")))
    market_score = _to_float(market_regime.get("score"))
    market_bias = str(market_regime.get("status", "未知"))
    stock_name = str(data.get("name") or latest.get("name") or "")
    ts_code = str(latest.get("ts_code") or "")
    board_name = str(latest.get("market") or "")

    score = 0.0
    reasons: list[str] = []
    risks: list[str] = []

    if market_score >= r.market_regime.strong_min:
        score += r.market_regime.strong_score
        reasons.append("市场收盘情绪偏强")
    elif market_score <= r.market_regime.weak_max:
        score += r.market_regime.weak_penalty
        risks.append("全市场收盘偏弱，隔夜溢价容易被压缩")

    if close > ma5 > ma10 > ma20 and ma20 > 0:
        score += r.ma_alignment.full_score
        reasons.append("收盘位于多头均线之上")
    elif close > ma5 > ma10 and ma10 > 0:
        score += r.ma_alignment.mid_score
        reasons.append("短线均线保持上拐")
    elif close > ma5 and ma5 > 0:
        score += r.ma_alignment.weak_score
        reasons.append("收盘仍守住短均线")
    else:
        score += r.ma_alignment.fail_penalty
        risks.append("收盘失守短均线")

    if ma5_slope_pct > r.ma5_slope.up_min:
        score += r.ma5_slope.up_score
        reasons.append("MA5 继续抬升")
    elif ma5_slope_pct < r.ma5_slope.down_max:
        score += r.ma5_slope.down_penalty
        risks.append("MA5 走平转弱")

    if close_strength >= r.close_strength.strong_min:
        score += r.close_strength.strong_score
        reasons.append("收盘靠近日内高位，尾盘承接较强")
    elif close_strength >= r.close_strength.mid_min:
        score += r.close_strength.mid_score
        reasons.append("收盘位置偏强")
    elif close_strength < r.close_strength.weak_max:
        score += r.close_strength.weak_penalty
        risks.append("收盘位置偏低，尾盘不够强")

    if r.pct_chg.sweet_min <= pct_chg <= r.pct_chg.sweet_max:
        score += r.pct_chg.sweet_score
        reasons.append("涨幅适中，兼顾动能和次日空间")
    elif 0 < pct_chg < r.pct_chg.sweet_min:
        score += r.pct_chg.mild_score
        reasons.append("日内温和走强")
    elif pct_chg < r.pct_chg.weak_max:
        score += r.pct_chg.weak_penalty
        risks.append("收盘偏弱，不适合做隔夜")
    elif pct_chg > r.pct_chg.hot_min:
        score += r.pct_chg.hot_penalty
        risks.append("涨幅过大，次日追高风险高")

    if close > open_price:
        score += r.candle_body.bull_score
        reasons.append("实体收阳")
    else:
        score += r.candle_body.bear_penalty
        risks.append("收盘未能站上开盘价")

    if upper_shadow_pct <= r.upper_shadow.short_max:
        score += r.upper_shadow.short_score
        reasons.append("上影线短，抛压可控")
    elif upper_shadow_pct > r.upper_shadow.long_min:
        score += r.upper_shadow.long_penalty
        risks.append("上影较长，尾盘抛压偏重")

    if r.turnover.sweet_min <= turnover_rate <= r.turnover.sweet_max:
        score += r.turnover.sweet_score
        reasons.append("换手处于短线舒适区间")
    elif r.turnover.ok_min <= turnover_rate < r.turnover.sweet_min:
        score += r.turnover.ok_score
        reasons.append("换手合格但不算活跃")
    elif turnover_rate > r.turnover.hot_min:
        score += r.turnover.hot_penalty
        risks.append("换手过热，隔夜一致性风险升高")
    else:
        score += r.turnover.cold_penalty
        risks.append("换手不足，次日兑现流动性偏弱")

    if r.amount_ratio_5d.sweet_min <= amount_ratio_5d <= r.amount_ratio_5d.sweet_max:
        score += r.amount_ratio_5d.sweet_score
        reasons.append("成交额较近五日明显放大")
    elif amount_ratio_5d > r.amount_ratio_5d.hot_min:
        score += r.amount_ratio_5d.hot_penalty
        risks.append("放量过猛，容易透支次日空间")
    elif 0 < amount_ratio_5d < r.amount_ratio_5d.cold_max:
        score += r.amount_ratio_5d.cold_penalty
        risks.append("成交额未放大，尾盘跟风不足")

    if r.volume_ratio.sweet_min <= volume_ratio <= r.volume_ratio.sweet_max:
        score += r.volume_ratio.sweet_score
        reasons.append("量比配合合理")
    elif volume_ratio > r.volume_ratio.hot_min:
        score += r.volume_ratio.hot_penalty
        risks.append("量比过高，波动容易失真")
    elif 0 < volume_ratio < r.volume_ratio.cold_max:
        score += r.volume_ratio.cold_penalty
        risks.append("量比偏低，主动资金不明显")

    if net_mf_ratio_pct >= r.net_mf.strong_min:
        score += r.net_mf.strong_score
        reasons.append("资金净流入占成交额较高")
    elif net_mf_ratio_pct >= r.net_mf.ok_min:
        score += r.net_mf.ok_score
        reasons.append("资金净流入为正")
    elif net_mf_ratio_pct <= r.net_mf.weak_max:
        score += r.net_mf.weak_penalty
        risks.append("资金净流出明显")

    if large_order_net_pct >= r.large_order.strong_min:
        score += r.large_order.strong_score
        reasons.append("大单承接占优")
    elif large_order_net_pct >= r.large_order.ok_min:
        score += r.large_order.ok_score
        reasons.append("大单净额为正")
    elif large_order_net_pct <= r.large_order.weak_max:
        score += r.large_order.weak_penalty
        risks.append("大单流出，次日承接需谨慎")

    if r.breakout.sweet_min <= breakout_pct <= r.breakout.sweet_max:
        score += r.breakout.sweet_score
        reasons.append("接近或小幅突破近十日高点")
    elif breakout_pct < r.breakout.far_max:
        score += r.breakout.far_penalty
        risks.append("距离近十日高点偏远，动能不足")

    if r.up_limit_room.sweet_min <= up_limit_room_pct <= r.up_limit_room.sweet_max:
        score += r.up_limit_room.sweet_score
        reasons.append("距离涨停仍有合理空间")
    elif 0 < up_limit_room_pct < r.up_limit_room.near_max:
        score += r.up_limit_room.near_penalty
        risks.append("离涨停过近，但无竞价/封单权限确认强度")

    if turnover_pct_rank >= r.ranks.turnover_rank_min:
        score += r.ranks.turnover_rank_score
        reasons.append("换手位于市场前列")
    if net_mf_ratio_rank >= r.ranks.net_mf_rank_min:
        score += r.ranks.net_mf_rank_score
        reasons.append("资金净流入强于多数个股")
    if large_order_net_rank >= r.ranks.large_order_rank_min:
        score += r.ranks.large_order_rank_score
        reasons.append("大单承接强于多数个股")

    if "ST" in stock_name.upper():
        score += r.penalties.st_penalty
        risks.append("ST 标的隔夜波动不可控")
    if list_age_days and list_age_days < r.penalties.new_stock_age_days:
        score += r.penalties.new_stock_penalty
        risks.append(f"上市未满 {r.penalties.new_stock_age_days} 天，历史样本不足")
    if ts_code.endswith(".BJ") or "北交所" in board_name:
        score += r.penalties.bj_penalty
        risks.append("北交所标的次日流动性与滑点风险偏大")

    final_score = int(round(max(0.0, min(100.0, score))))
    risk_text = "；".join(dict.fromkeys(risks)) if risks else "无显著额外风险"
    detail_text = " + ".join(dict.fromkeys(reasons)) if reasons else "缺少足够的尾盘强势信号"

    if final_score >= rules.status_bands.strong:
        status = "【强候选】尾盘隔夜"
    elif final_score >= rules.status_bands.candidate:
        status = "【候选】可跟踪"
    elif final_score >= rules.status_bands.watch:
        status = "【观察】等待更优确认"
    else:
        status = "【回避】"

    action_plan = _build_action_plan(final_score, market_score, up_limit_room_pct, pct_chg, rules)

    return {
        "score": final_score,
        "status": status,
        "detail": detail_text,
        "risk": risk_text,
        "vol_ratio": round(volume_ratio, 2),
        "turnover_rate": round(turnover_rate, 2),
        "amount_ratio_5d": round(amount_ratio_5d, 2),
        "net_mf_ratio_pct": round(net_mf_ratio_pct, 2),
        "large_order_net_pct": round(large_order_net_pct, 2),
        "up_limit_room_pct": round(up_limit_room_pct, 2),
        "close_strength": round(close_strength, 2),
        "breakout_pct": round(breakout_pct, 2),
        "market_bias": market_bias,
        "action_plan": action_plan,
    }


def _build_action_plan(
    score: int,
    market_score: float,
    up_limit_room_pct: float,
    pct_chg: float,
    rules: AnalysisRules,
) -> str:
    r = rules.rules
    if score >= rules.status_bands.strong:
        base = "轻仓参与隔夜，不追临近涨停的尾盘拉板；次日若高开 2% 到 4% 优先分批兑现。"
    elif score >= rules.status_bands.candidate:
        base = "仅列入尾盘观察名单，必须确认尾盘强势未衰减再考虑；次日优先快进快出。"
    elif score >= rules.status_bands.watch:
        base = "只观察，不建议机械买入。"
    else:
        return "放弃本次隔夜交易，等待更强的收盘结构与资金确认。"

    if market_score <= r.market_regime.weak_max:
        base += " 市场环境偏弱，仓位需要再降一档。"
    if 0 < up_limit_room_pct < r.up_limit_room.near_max or pct_chg > r.pct_chg.hot_min:
        base += " 该股过于贴近涨停，因缺少竞价与封单权限，不宜重仓。"

    base += " 若次日开盘弱于昨收约 1.5%，优先止损，不做日内扛单。"
    return base


def _pick_first_float(*values: Any) -> float:
    for value in values:
        candidate = _to_float(value)
        if candidate != 0:
            return candidate
    return 0.0


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
