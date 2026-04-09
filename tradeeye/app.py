from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable

from tradeeye.config import Settings, load_settings
from tradeeye.logging_utils import configure_logging
from tradeeye.services.analysis import get_dify_analysis
from tradeeye.services.data import get_clean_data
from tradeeye.services.notifier import send_report
from tradeeye.strategies.strategy import check_signals

logger = logging.getLogger(__name__)

DataFetcher = Callable[[str, Settings], dict[str, Any] | None]
Analyzer = Callable[[dict[str, Any], dict[str, Any], str, Settings], str]
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
        sections.append("\u4eca\u65e5\u65e0\u6709\u6548\u4e2a\u80a1\u5206\u6790\u7ed3\u679c\u3002")

    if failed_codes:
        failed_list = "\n".join(f"- {code}" for code in failed_codes)
        sections.append(f"\u4ee5\u4e0b\u6807\u7684\u83b7\u53d6\u6216\u5206\u6790\u5931\u8d25\uff1a\n{failed_list}")

    return f"\U0001f4ca {today} \u4e2a\u80a1\u590d\u76d8\u6c47\u603b\u62a5\u544a\uff1a\n\n" + "\n\n".join(sections)


def main(
    settings: Settings | None = None,
    data_fetcher: DataFetcher = get_clean_data,
    analyzer: Analyzer = get_dify_analysis,
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
    for code in settings.my_stocks:
        data = data_fetcher(code, settings)
        if not data:
            failed_codes.append(code)
            logger.warning("Skipping %s: data fetch returned no usable payload", code)
            continue

        tech_result = check_signals(data)
        logger.info("Requesting AI analysis for %s (%s)", data.get("name"), code)
        ai_analysis = analyzer(data, tech_result, code, settings)
        all_reports.append(ai_analysis)
        logger.info("Analysis completed for %s (%s)", data.get("name"), code)

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
