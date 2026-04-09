from __future__ import annotations

import logging
from typing import Any

import requests

from tradeeye.config import Settings

logger = logging.getLogger(__name__)


def build_dify_input(stock_data: dict[str, Any], tech_result: dict[str, Any], stock_code: str) -> str:
    latest = stock_data.get("latest", {})
    prev = stock_data.get("prev", {})

    return (
        f"\u540d\u79f0:{stock_data.get('name')}, \u4ee3\u7801:{stock_code}, \u73b0\u4ef7:{latest.get('close')}, "
        f"MA20:{latest.get('ma20')}, \u91cf\u6bd4:{tech_result.get('vol_ratio')}, "
        f"\u6362\u624b\u7387:{tech_result.get('turnover_rate', '\u6682\u65e0')}, "
        f"\u672c\u5730\u5f97\u5206:{tech_result.get('score')}, \u6280\u672f\u903b\u8f91:{tech_result.get('detail')}, "
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
    if not settings.dify_api_key:
        return "\u274c Dify \u5de5\u4f5c\u6d41\u8c03\u7528\u5931\u8d25: missing DIFY_API_KEY"

    payload = {
        "inputs": {"stock_data": build_dify_input(stock_data, tech_result, stock_code)},
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
        return "\u26a0\ufe0f \u5de5\u4f5c\u6d41\u8fd0\u884c\u6210\u529f\u4f46\u672a\u8fd4\u56de\u6709\u6548\u6587\u672c"
    except Exception as exc:
        logger.exception("Dify workflow failed for %s", stock_code)
        return f"\u274c Dify \u5de5\u4f5c\u6d41\u8c03\u7528\u5931\u8d25: {exc}"
