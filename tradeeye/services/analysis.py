from __future__ import annotations

import json
import logging
from typing import Any, Mapping

import requests

from tradeeye.config import Settings

logger = logging.getLogger(__name__)

REC_QUERY_PREFIX = "[REC]"
STK_QUERY_PREFIX = "[STK]"


def build_dify_input(stock_data: dict[str, Any], tech_result: dict[str, Any], stock_code: str) -> str:
    latest = stock_data.get("latest", {})
    prev = stock_data.get("prev", {})
    market = stock_data.get("market_regime", {})

    return (
        f"\u540d\u79f0:{stock_data.get('name')}, \u4ee3\u7801:{stock_code}, "
        f"\u4ea4\u6613\u65e5:{stock_data.get('trade_date')}, \u6536\u76d8\u4ef7:{latest.get('close')}, "
        f"\u5f53\u65e5\u6da8\u5e45:{latest.get('pct_chg')}, MA5:{latest.get('ma5')}, MA10:{latest.get('ma10')}, MA20:{latest.get('ma20')}, "
        f"\u672c\u5730\u72b6\u6001:{tech_result.get('status')}, \u672c\u5730\u5f97\u5206:{tech_result.get('score')}, "
        f"\u5c3e\u76d8\u5f3a\u5ea6:{tech_result.get('close_strength')}, \u91cf\u6bd4:{tech_result.get('vol_ratio')}, "
        f"\u6362\u624b\u7387:{tech_result.get('turnover_rate')}, \u6210\u4ea4\u989d/\u8fd15\u65e5:{tech_result.get('amount_ratio_5d')}, "
        f"\u8d44\u91d1\u51c0\u6d41\u5165\u5360\u6bd4:{tech_result.get('net_mf_ratio_pct')}%, "
        f"\u5927\u5355\u51c0\u989d\u5360\u6bd4:{tech_result.get('large_order_net_pct')}%, "
        f"\u8ddd\u6da8\u505c\u5269\u4f59\u7a7a\u95f4:{tech_result.get('up_limit_room_pct')}%, "
        f"\u8fd110\u65e5\u7a81\u7834\u5e45\u5ea6:{tech_result.get('breakout_pct')}%, "
        f"\u5e02\u573a\u73af\u5883:{tech_result.get('market_bias')}, "
        f"\u5168\u5e02\u573a\u4e0a\u6da8\u5360\u6bd4:{market.get('up_ratio_pct')}%, "
        f"\u5f3a\u52bf\u80a1\u5360\u6bd4:{market.get('strong_ratio_pct')}%, "
        f"\u6280\u672f/\u8d44\u91d1\u7406\u7531:{tech_result.get('detail')}, "
        f"\u98ce\u9669:{tech_result.get('risk')}, \u6267\u884c\u5efa\u8bae:{tech_result.get('action_plan')}, "
        f"\u4eca\u65e5\u9ad8\u70b9:{latest.get('high')}, \u4eca\u65e5\u6700\u4f4e:{latest.get('low')}, "
        f"\u6628\u65e5\u4f4e\u70b9:{prev.get('low')}"
    )


def get_dify_analysis(
    stock_data: dict[str, Any],
    tech_result: dict[str, Any],
    stock_code: str,
    settings: Settings,
    http_client=requests,
) -> str:
    query = f"{STK_QUERY_PREFIX}{build_dify_input(stock_data, tech_result, stock_code)}"
    return _run_dify_workflow(
        query=query,
        settings=settings,
        http_client=http_client,
        log_key=stock_code,
    )


def get_dify_recommendation_analysis(
    recommendations_json: str,
    settings: Settings,
    input_key: str = "query",
    http_client=requests,
) -> str:
    # Backward compatibility: callers may still pass a custom input_key, but
    # we now always submit Dify input via `inputs.query`.
    _ = input_key
    if not recommendations_json:
        return "Warning: recommendation payload is empty"

    query = f"{REC_QUERY_PREFIX}{_normalize_recommendation_payload(recommendations_json)}"
    return _run_dify_workflow(
        query=query,
        settings=settings,
        http_client=http_client,
        log_key="daily_recommendation",
    )


def _run_dify_workflow(
    query: str | Mapping[str, Any],
    settings: Settings,
    http_client,
    log_key: str,
) -> str:
    if not settings.dify_api_key:
        return "Dify workflow failed: missing DIFY_API_KEY"

    normalized_query = _normalize_query(query)
    if not normalized_query:
        return "Warning: empty query for Dify workflow"

    payload = {
        "inputs": {"query": normalized_query},
        "response_mode": "blocking",
        "user": "TradeEye_Runner",
    }
    headers = {
        "Authorization": f"Bearer {settings.dify_api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = http_client.post(
            settings.dify_workflow_url,
            headers=headers,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        res_data = response.json()
        analysis_result = res_data.get("data", {}).get("outputs", {}).get("text")
        if analysis_result:
            return analysis_result
        return "Warning: workflow succeeded but returned no text output"
    except Exception as exc:
        logger.exception("Dify workflow failed for %s", log_key)
        return f"Dify workflow failed: {exc}"


def _normalize_query(query: str | Mapping[str, Any]) -> str:
    if isinstance(query, str):
        return query.strip()

    query_value = query.get("query")
    if isinstance(query_value, str) and query_value.strip():
        return query_value.strip()

    for value in query.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_recommendation_payload(recommendations_json: str) -> str:
    try:
        parsed = json.loads(recommendations_json)
    except (TypeError, ValueError):
        return recommendations_json.strip()

    if not isinstance(parsed, dict):
        if isinstance(parsed, list):
            parsed = {"low_price_group": parsed, "mid_price_group": []}
        else:
            parsed = {"low_price_group": [], "mid_price_group": []}
    parsed.setdefault("low_price_group", [])
    parsed.setdefault("mid_price_group", [])
    return json.dumps(parsed, ensure_ascii=False)
