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


def build_final_content(reports: list[str], report_date: dt.date | None = None) -> str:
    today = (report_date or dt.date.today()).strftime("%Y-%m-%d")
    return f"\U0001f4ca {today} \u4e2a\u80a1\u590d\u76d8\u6c47\u603b\u62a5\u544a\uff1a\n\n" + "\n\n".join(reports)


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
        return 0

    all_reports: list[str] = []
    for code in settings.my_stocks:
        data = data_fetcher(code, settings)
        if not data:
            continue

        tech_result = check_signals(data)
        logger.info("Requesting AI analysis for %s (%s)", data.get("name"), code)
        ai_analysis = analyzer(data, tech_result, code, settings)
        all_reports.append(ai_analysis)
        logger.info("Analysis completed for %s (%s)", data.get("name"), code)

    if all_reports:
        final_content = build_final_content(all_reports)
        notifier(final_content, settings)
    else:
        logger.warning("No valid stock data available for today")

    return 0
