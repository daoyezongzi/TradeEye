from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def check_signals(data: dict[str, Any]) -> dict[str, Any]:
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

    score = 0
    reasons: list[str] = []
    risks: list[str] = []

    if market_score >= 15:
        score += 10
        reasons.append("市场收盘情绪偏强")
    elif market_score <= -15:
        score -= 15
        risks.append("全市场收盘偏弱，隔夜溢价容易被压缩")

    if close > ma5 > ma10 > ma20 and ma20 > 0:
        score += 18
        reasons.append("收盘位于多头均线之上")
    elif close > ma5 > ma10 and ma10 > 0:
        score += 12
        reasons.append("短线均线保持上拐")
    elif close > ma5 and ma5 > 0:
        score += 6
        reasons.append("收盘仍守住短均线")
    else:
        score -= 10
        risks.append("收盘失守短均线")

    if ma5_slope_pct > 0.2:
        score += 4
        reasons.append("MA5 继续抬升")
    elif ma5_slope_pct < -0.2:
        score -= 4
        risks.append("MA5 走平转弱")

    if close_strength >= 0.8:
        score += 18
        reasons.append("收盘靠近日内高位，尾盘承接较强")
    elif close_strength >= 0.68:
        score += 10
        reasons.append("收盘位置偏强")
    elif close_strength < 0.45:
        score -= 15
        risks.append("收盘位置偏低，尾盘不够强")

    if 1.2 <= pct_chg <= 6.5:
        score += 12
        reasons.append("涨幅适中，兼顾动能和次日空间")
    elif 0 < pct_chg < 1.2:
        score += 5
        reasons.append("日内温和走强")
    elif pct_chg < -1.5:
        score -= 18
        risks.append("收盘偏弱，不适合做隔夜")
    elif pct_chg > 8:
        score -= 12
        risks.append("涨幅过大，次日追高风险高")

    if close > open_price:
        score += 8
        reasons.append("实体收阳")
    else:
        score -= 4
        risks.append("收盘未能站上开盘价")

    if upper_shadow_pct <= 1.2:
        score += 6
        reasons.append("上影线短，抛压可控")
    elif upper_shadow_pct > 2.5:
        score -= 10
        risks.append("上影较长，尾盘抛压偏重")

    if 2 <= turnover_rate <= 12:
        score += 10
        reasons.append("换手处于短线舒适区间")
    elif 0.8 <= turnover_rate < 2:
        score += 4
        reasons.append("换手合格但不算活跃")
    elif turnover_rate > 18:
        score -= 8
        risks.append("换手过热，隔夜一致性风险升高")
    else:
        score -= 8
        risks.append("换手不足，次日兑现流动性偏弱")

    if 1.2 <= amount_ratio_5d <= 3:
        score += 10
        reasons.append("成交额较近五日明显放大")
    elif amount_ratio_5d > 4:
        score -= 6
        risks.append("放量过猛，容易透支次日空间")
    elif 0 < amount_ratio_5d < 0.8:
        score -= 6
        risks.append("成交额未放大，尾盘跟风不足")

    if 1 <= volume_ratio <= 2.5:
        score += 8
        reasons.append("量比配合合理")
    elif volume_ratio > 4:
        score -= 4
        risks.append("量比过高，波动容易失真")
    elif 0 < volume_ratio < 0.6:
        score -= 4
        risks.append("量比偏低，主动资金不明显")

    if net_mf_ratio_pct >= 3:
        score += 14
        reasons.append("资金净流入占成交额较高")
    elif net_mf_ratio_pct >= 1:
        score += 8
        reasons.append("资金净流入为正")
    elif net_mf_ratio_pct <= -2:
        score -= 14
        risks.append("资金净流出明显")

    if large_order_net_pct >= 2:
        score += 12
        reasons.append("大单承接占优")
    elif large_order_net_pct >= 0.5:
        score += 6
        reasons.append("大单净额为正")
    elif large_order_net_pct <= -1:
        score -= 12
        risks.append("大单流出，次日承接需谨慎")

    if -1 <= breakout_pct <= 2.5:
        score += 8
        reasons.append("接近或小幅突破近十日高点")
    elif breakout_pct < -3:
        score -= 8
        risks.append("距离近十日高点偏远，动能不足")

    if 2 <= up_limit_room_pct <= 7:
        score += 6
        reasons.append("距离涨停仍有合理空间")
    elif 0 < up_limit_room_pct < 1.2:
        score -= 10
        risks.append("离涨停过近，但无竞价/封单权限确认强度")

    if turnover_pct_rank >= 0.75:
        score += 4
        reasons.append("换手位于市场前列")
    if net_mf_ratio_rank >= 0.8:
        score += 4
        reasons.append("资金净流入强于多数个股")
    if large_order_net_rank >= 0.8:
        score += 4
        reasons.append("大单承接强于多数个股")

    if "ST" in stock_name.upper():
        score -= 40
        risks.append("ST 标的隔夜波动不可控")
    if list_age_days and list_age_days < 120:
        score -= 25
        risks.append("上市未满 120 天，历史样本不足")
    if ts_code.endswith(".BJ") or "北交所" in board_name:
        score -= 20
        risks.append("北交所标的次日流动性与滑点风险偏大")

    score = max(0, min(100, score))
    risk_text = "；".join(dict.fromkeys(risks)) if risks else "无显著额外风险"
    detail_text = " + ".join(dict.fromkeys(reasons)) if reasons else "缺少足够的尾盘强势信号"

    if score >= 80:
        status = "【强候选】尾盘隔夜"
    elif score >= 65:
        status = "【候选】可跟踪"
    elif score >= 50:
        status = "【观察】等待更优确认"
    else:
        status = "【回避】"

    action_plan = _build_action_plan(score, market_score, up_limit_room_pct, pct_chg)

    return {
        "score": score,
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


def load_yaml_config(strategy_name: str = "shrink_pullback") -> dict[str, Any]:
    yaml_path = Path(__file__).with_name(f"{strategy_name}.yaml")
    if yaml_path.exists():
        with yaml_path.open("r", encoding="utf-8") as file_obj:
            return yaml.safe_load(file_obj)
    return {}


def _build_action_plan(score: int, market_score: float, up_limit_room_pct: float, pct_chg: float) -> str:
    if score >= 80:
        base = "轻仓参与隔夜，不追临近涨停的尾盘拉板；次日若高开 2% 到 4% 优先分批兑现。"
    elif score >= 65:
        base = "仅列入尾盘观察名单，必须确认尾盘强势未衰减再考虑；次日优先快进快出。"
    elif score >= 50:
        base = "只观察，不建议机械买入。"
    else:
        return "放弃本次隔夜交易，等待更强的收盘结构与资金确认。"

    if market_score <= -15:
        base += " 市场环境偏弱，仓位需要再降一档。"
    if 0 < up_limit_room_pct < 1.2 or pct_chg > 8:
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
