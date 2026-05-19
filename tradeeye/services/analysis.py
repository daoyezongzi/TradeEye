from __future__ import annotations

import json
import logging
from typing import Any, Mapping

import requests

from tradeeye.config import Settings

logger = logging.getLogger(__name__)

REC_QUERY_PREFIX = "[REC]"
STK_QUERY_PREFIX = "[STK]"

STK_SYSTEM_PROMPT = """角色：资深短线交易员（实战派）
输入数据：来源于用户输入。请自动忽略字符串开头的 [STK] 标签，并解析其后的内容。

核心分析指令（必须严格执行）：
1. 数据内化：必须提取现价、MA20、量比、换手率、本地得分。
2. 确定性定性（拒绝模棱两可）：
   - 现价 > MA20 判定为“多头趋势”；现价 < MA20 判定为“空头趋势”。
   - 量比 > 1.5 判定为“放量”；量比 < 0.8 判定为“缩量”。
   - 换手率 > 10% 判定为“情绪高涨”；换手率 < 2% 判定为“关注度极低”。
3. 严禁造假：支撑位/压力位必须且只能从 MA20、今日最高、今日最低、昨日最低 中选择最接近数值。

输出模板：
【名称 (代码)】
📉 个股简评：本地评分 [数值] 分。目前处于 [多头/空头] 趋势。今日 [放量/缩量] [上涨/下跌]，反映 [洗盘/出货/吸筹] 迹象。换手率 [数值]%，市场关注度 [高/低]。
🎯 操作策略：[具体动作建议，如：持股/逢高减仓/空仓观望]。
压力位：看 [来源名] ([具体数值] 元)
支撑位：看 [来源名] ([具体数值] 元)
"""

REC_SYSTEM_PROMPT = """角色：顶级量化游资分析师（实战派）
任务：对输入中的两组（共 10 只）潜力股列表进行盘后复盘。

核心指令：
1. 忽略输入开头的 [REC] 标签，解析 JSON 中的 low_price_group 和 mid_price_group。
2. 拒绝废话：不得使用“可能”、“大概”、“或许”，必须用确定语气点评。
3. 核心指标：关注 short_burst（短线爆发）、t_active（做T活跃度）和 total_score（总分）。

输出模板：
📊 今日选股内参 (分档精选)
🚀 【0-10元 · 低价爆发组】
[名称 (代码)] | 总分: [数值]
核心逻辑：[结合维度字段点评]
技术定性：[直接判定趋势]
(此处简要列出该组其余 4 只标的及核心逻辑)
⚖️ 【10-20元 · 稳健博弈组】
[名称 (代码)] | 总分: [数值]
核心逻辑：[结合维度字段点评]
技术定性：[直接判定趋势]
(此处简要列出该组其余 4 只标的及核心逻辑)
💡 综合操盘结论：[对比两组整体质量给出唯一建议]
"""


def build_llm_input(stock_data: dict[str, Any], tech_result: dict[str, Any], stock_code: str) -> str:
    latest = stock_data.get("latest", {})
    prev = stock_data.get("prev", {})
    market = stock_data.get("market_regime", {})

    return (
        f"名称:{stock_data.get('name')}, 代码:{stock_code}, "
        f"交易日:{stock_data.get('trade_date')}, 收盘价:{latest.get('close')}, "
        f"当日涨幅:{latest.get('pct_chg')}, MA5:{latest.get('ma5')}, MA10:{latest.get('ma10')}, MA20:{latest.get('ma20')}, "
        f"本地状态:{tech_result.get('status')}, 本地得分:{tech_result.get('score')}, "
        f"尾盘强度:{tech_result.get('close_strength')}, 量比:{tech_result.get('vol_ratio')}, "
        f"换手率:{tech_result.get('turnover_rate')}, 成交额/近5日:{tech_result.get('amount_ratio_5d')}, "
        f"资金净流入占比:{tech_result.get('net_mf_ratio_pct')}%, "
        f"大单净额占比:{tech_result.get('large_order_net_pct')}%, "
        f"距涨停剩余空间:{tech_result.get('up_limit_room_pct')}%, "
        f"近10日突破幅度:{tech_result.get('breakout_pct')}%, "
        f"市场环境:{tech_result.get('market_bias')}, "
        f"全市场上涨占比:{market.get('up_ratio_pct')}%, "
        f"强势股占比:{market.get('strong_ratio_pct')}%, "
        f"技术/资金理由:{tech_result.get('detail')}, "
        f"风险:{tech_result.get('risk')}, 执行建议:{tech_result.get('action_plan')}, "
        f"今日高点:{latest.get('high')}, 今日最低:{latest.get('low')}, "
        f"昨日低点:{prev.get('low')}"
    )


def get_llm_analysis(
    stock_data: dict[str, Any],
    tech_result: dict[str, Any],
    stock_code: str,
    settings: Settings,
    http_client=requests,
) -> str:
    query = f"{STK_QUERY_PREFIX}{build_llm_input(stock_data, tech_result, stock_code)}"
    return run_llm_call(
        query=query,
        settings=settings,
        http_client=http_client,
        log_key=stock_code,
    )


def get_llm_recommendation_analysis(
    recommendations_json: str,
    settings: Settings,
    input_key: str = "query",
    http_client=requests,
) -> str:
    _ = input_key
    if not recommendations_json:
        return "Warning: recommendation payload is empty"

    query = f"{REC_QUERY_PREFIX}{_normalize_recommendation_payload(recommendations_json)}"
    return run_llm_call(
        query=query,
        settings=settings,
        http_client=http_client,
        log_key="daily_recommendation",
    )


def run_llm_call(
    query: str | Mapping[str, Any],
    settings: Settings,
    http_client,
    log_key: str,
) -> str:
    api_key = settings.llm_api_key
    if not api_key:
        return "LLM call failed: missing LLM_API_KEY"

    normalized_query = _normalize_query(query)
    if not normalized_query:
        return "Warning: empty query for LLM call"

    query_kind, normalized_payload = _split_query_and_kind(normalized_query)
    system_prompt = REC_SYSTEM_PROMPT if query_kind == "rec" else STK_SYSTEM_PROMPT
    temperature = 0.7 if query_kind == "rec" else 0.0

    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": normalized_payload},
        ],
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = http_client.post(
            settings.llm_chat_completions_url,
            headers=headers,
            json=payload,
            timeout=settings.llm_timeout_sec,
        )
        response.raise_for_status()
        res_data = response.json()
        choices = res_data.get("choices") or []
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        return "Warning: LLM call succeeded but returned no text output"
    except Exception as exc:
        logger.exception("LLM call failed for %s", log_key)
        return f"LLM call failed: {exc}"


def _split_query_and_kind(value: str) -> tuple[str, str]:
    text = value.strip()
    if text.startswith(REC_QUERY_PREFIX):
        return "rec", text[len(REC_QUERY_PREFIX) :].strip()
    if text.startswith(STK_QUERY_PREFIX):
        return "stk", text[len(STK_QUERY_PREFIX) :].strip()
    return "stk", text


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
