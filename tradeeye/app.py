from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable, Optional

from tradeeye.config import Settings, load_settings, split_stocks_by_exchange
from tradeeye.logging_utils import configure_logging
from tradeeye.services.analysis import get_llm_analysis
from tradeeye.services.data import get_clean_data
from tradeeye.services.notifier import send_report
from tradeeye.strategies.strategy import check_signals

logger = logging.getLogger(__name__)

DataFetcher = Callable[[str, Settings], Optional[dict[str, Any]]]
Analyzer = Callable[[dict[str, Any], dict[str, Any], str, Settings], str]
Notifier = Callable[[str, Settings], bool]
LLM_SCORE_THRESHOLD = 70


def build_final_content(
    reports: list[str],
    failed_codes: list[str] | None = None,
    report_date: dt.date | None = None,
) -> str:
    today = (report_date or dt.date.today()).strftime("%Y-%m-%d")
    sections: list[str] = []

    if reports:
        sections.append("\n\n".join(reports))
    else:
        sections.append("今日无有效个股分析结果。")

    if failed_codes:
        failed_list = "\n".join(f"- {code}" for code in failed_codes)
        sections.append(f"以下标的获取或分析失败：\n{failed_list}")

    return f"📊 {today} 个股复盘汇总报告：\n\n" + "\n\n".join(sections)


def main(
    settings: Settings | None = None,
    data_fetcher: DataFetcher = get_clean_data,
    analyzer: Analyzer = get_llm_analysis,
    notifier: Notifier = send_report,
) -> int:
    settings = settings or load_settings()
    configure_logging(settings.debug_mode)

    mode = "debug" if settings.debug_mode else "production"
    logger.info("TradeEye started | mode=%s", mode)

    if settings.my_stocks and not settings.tushare_token:
        logger.error("TradeEye cannot fetch market data: missing TUSHARE_TOKEN")
        return 1

    all_reports: list[str] = []
    failed_codes: list[str] = []
    selected_codes, excluded_codes = split_stocks_by_exchange(settings.my_stocks, settings.allowed_exchanges)
    if excluded_codes:
        logger.info(
            "Skipping stocks outside ALLOWED_EXCHANGES=%s: %s",
            ",".join(settings.allowed_exchanges),
            ", ".join(excluded_codes),
        )

    if settings.my_stocks and not selected_codes:
        logger.warning("No stocks matched ALLOWED_EXCHANGES=%s", ",".join(settings.allowed_exchanges))

    for code in selected_codes:
        data = data_fetcher(code, settings)
        if not data:
            failed_codes.append(code)
            logger.warning("Skipping %s: data fetch returned no usable payload", code)
            continue

        tech_result = check_signals(data)
        score = _safe_score(tech_result.get("score"))
        if score >= LLM_SCORE_THRESHOLD:
            logger.info("Requesting AI analysis for %s (%s), score=%s", data.get("name"), code, score)
            ai_analysis = analyzer(data, tech_result, code, settings)
            all_reports.append(ai_analysis)
            logger.info("Analysis completed for %s (%s)", data.get("name"), code)
            continue

        logger.info(
            "Skipping AI analysis for %s (%s): local score=%s below threshold=%s",
            data.get("name"),
            code,
            score,
            LLM_SCORE_THRESHOLD,
        )
        all_reports.append(_build_local_report(data, tech_result, code))

    if not all_reports:
        logger.warning("No valid stock data available for today")

    if all_reports or failed_codes:
        final_content = build_final_content(all_reports, failed_codes=failed_codes)
        if not notifier(final_content, settings):
            logger.error("TradeEye finished with notification failure")
            return 1

    if failed_codes:
        logger.error("TradeEye finished with stock failures: %s", ", ".join(failed_codes))
        return 1

    return 0


def _build_local_report(stock_data: dict[str, Any], tech_result: dict[str, Any], stock_code: str) -> str:
    name = stock_data.get("name") or stock_code
    trade_date = stock_data.get("trade_date") or "unknown"
    return (
        f"【{name} ({stock_code})】\n"
        f"交易日: {trade_date}\n"
        f"本地得分: {_safe_score(tech_result.get('score'))}\n"
        f"状态: {tech_result.get('status', '')}\n"
        f"理由: {tech_result.get('detail', '')}\n"
        f"风险: {tech_result.get('risk', '')}\n"
        f"执行建议: {tech_result.get('action_plan', '')}\n"
        "说明：本地得分未达阈值，未调用 LLM 分析。"
    )


def _safe_score(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0

