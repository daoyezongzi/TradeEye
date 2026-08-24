from __future__ import annotations

import math
from typing import Any, Mapping

from tradeeye.strategies.strategy import DIMENSION_CAPS


def build_analysis_report(
    stock_data: Mapping[str, Any],
    analysis_result: Mapping[str, Any],
    stock_code: str,
) -> str:
    """Render the local post-close diagnosis in a stable, deterministic format."""

    name = stock_data.get("name") or stock_code
    trade_date = stock_data.get("trade_date") or "未知"
    dimensions = analysis_result.get("dimensions")
    if not isinstance(dimensions, Mapping):
        dimensions = {}

    lines = [
        f"【{name} ({stock_code})】",
        f"交易日：{trade_date}",
        "盘后诊断：本报告仅描述收盘后的结构与风险，不构成交易建议。",
        "五维评分：",
    ]
    for dimension, maximum in DIMENSION_CAPS.items():
        lines.append(f"- {dimension}：{_format_dimension(dimensions.get(dimension), maximum)}")

    raw_score = analysis_result.get("raw_score", analysis_result.get("score"))
    lines.extend(
        [
            f"原始总分：{_format_total(raw_score)}",
            f"风险等级：{analysis_result.get('risk_level') or '无法判定'}",
            f"最终状态：{analysis_result.get('final_status') or analysis_result.get('status') or '数据不足'}",
            "主要依据：",
        ]
    )
    reasons = _as_text_items(analysis_result.get("reasons"))
    if not reasons:
        reasons = _as_text_items(analysis_result.get("detail"))
    lines.extend(f"- {reason}" for reason in (reasons or ["暂无可用依据"]))

    lines.append(f"风险说明：{analysis_result.get('risk') or '未发现主要风险'}")
    lines.append("次日观察点：")
    watch_points = _as_text_items(analysis_result.get("next_day_watch"))
    if not watch_points:
        watch_points = _as_text_items(analysis_result.get("action_plan"))
    lines.extend(f"- {point}" for point in (watch_points or ["观察完整日线数据是否出现新的结构变化"]))
    return "\n".join(lines)


def _format_dimension(value: Any, maximum: int) -> str:
    if value is None:
        return f"不评分/{maximum}"
    return f"{_format_number(value)}/{maximum}"


def _format_total(value: Any) -> str:
    if value is None:
        return "不评分"
    return f"{_format_number(value)}/100"


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "不评分"
    if not math.isfinite(number):
        return "不评分"
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _as_text_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
