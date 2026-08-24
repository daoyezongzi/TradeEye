from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable, Optional

from tradeeye.config import Settings, load_settings, split_stocks_by_exchange
from tradeeye.logging_utils import configure_logging
from tradeeye.services.analysis import build_analysis_report
from tradeeye.services.data import get_clean_data
from tradeeye.services.notifier import send_report
from tradeeye.strategies.strategy import check_signals

logger = logging.getLogger(__name__)

DataFetcher = Callable[[str, Settings], Optional[dict[str, Any]]]
ReportBuilder = Callable[[dict[str, Any], dict[str, Any], str], str]
Notifier = Callable[[str, Settings], bool]


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

    return f"📊 {today} 个股盘后诊断汇总报告：\n\n" + "\n\n".join(sections)


def main(
    settings: Settings | None = None,
    data_fetcher: DataFetcher = get_clean_data,
    notifier: Notifier = send_report,
    report_builder: ReportBuilder = build_analysis_report,
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
        try:
            data = data_fetcher(code, settings)
        except Exception:
            failed_codes.append(code)
            logger.exception("Skipping %s: data fetch failed", code)
            continue
        if not data:
            failed_codes.append(code)
            logger.warning("Skipping %s: data fetch returned no usable payload", code)
            continue

        tech_result = check_signals(data)
        all_reports.append(report_builder(data, tech_result, code))
        logger.info(
            "Post-close diagnosis completed for %s (%s), status=%s",
            data.get("name"),
            code,
            tech_result.get("status"),
        )

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
