from __future__ import annotations

import logging
from typing import Callable

from tradeeye.config import Settings, load_settings
from tradeeye.logging_utils import configure_logging
from tradeeye.services.backtest import (
    SignalRecord,
    SignalResult,
    build_backtest_report,
    evaluate_signals,
    load_signals,
)
from tradeeye.services.notifier import send_text

logger = logging.getLogger(__name__)

Loader = Callable[..., list[SignalRecord]]
Evaluator = Callable[[list[SignalRecord], Settings], tuple[list[SignalResult], int]]
Notifier = Callable[[str, Settings], bool]

_EMPTY_MESSAGE = "暂无历史信号数据，先让每日工作流积累几天信号再来看周报。"


def main(
    settings: Settings | None = None,
    loader: Loader | None = None,
    evaluator: Evaluator = evaluate_signals,
    notifier: Notifier | None = None,
) -> int:
    settings = settings or load_settings()
    configure_logging(settings.debug_mode)

    loader = loader or load_signals
    records = loader(lookback_days=settings.backtest_lookback_days)

    if not records:
        logger.info("No signals found within lookback window")
        content = _EMPTY_MESSAGE
    else:
        if not settings.tushare_token:
            logger.error("Backtest cannot fetch market data: missing TUSHARE_TOKEN")
            return 1
        results, missing_count = evaluator(records, settings)
        content = build_backtest_report(results, missing_count, settings.backtest_lookback_days)

    notifier = notifier or _send_report
    if not notifier(content, settings):
        logger.error("Backtest workflow finished with notification failure")
        return 1
    return 0


def _send_report(content: str, settings: Settings) -> bool:
    return send_text(content=content, settings=settings, title="策略胜率周报", icon="\U0001f4c8")
