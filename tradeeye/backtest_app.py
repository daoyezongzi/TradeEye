from __future__ import annotations

import logging
from typing import Callable

from tradeeye.config import Settings, load_settings
from tradeeye.logging_utils import configure_logging
from tradeeye.services.backtest import (
    SignalRecord,
    SignalResult,
    build_backtest_report,
    load_backtest_data,
)
from tradeeye.services.notifier import send_text
from tradeeye.services.portfolio import TradeRecord

logger = logging.getLogger(__name__)

Notifier = Callable[[str, Settings], bool]
_EMPTY_MESSAGE = "暂无荐股交易账本，先运行每日组合结算积累交易与净值数据。"


def main(
    settings: Settings | None = None,
    loader: Callable | None = None,
    evaluator: Callable[[list[SignalRecord], Settings], tuple[list[SignalResult], int]] | None = None,
    notifier: Notifier | None = None,
) -> int:
    """Render the local recommend trade/NAV ledger; no market query is performed."""
    settings = settings or load_settings()
    configure_logging(settings.debug_mode)

    if loader is None:
        records, nav_rows = load_backtest_data()
    else:
        loaded = _call_loader(loader, settings.backtest_lookback_days)
        if isinstance(loaded, tuple) and len(loaded) == 2:
            records, nav_rows = loaded
        else:
            records, nav_rows = loaded, []

    if not records:
        logger.info("No recommend trade ledger found")
        content = _EMPTY_MESSAGE
    elif isinstance(records[0], TradeRecord):
        content = build_backtest_report(
            records,
            lookback_days=settings.backtest_lookback_days,
            nav_rows=nav_rows,
        )
    elif evaluator is not None:
        # Transitional compatibility for custom callers still injecting old T+1 records.
        results, missing_count = evaluator(records, settings)
        content = build_backtest_report(
            results,
            missing_count=missing_count,
            lookback_days=settings.backtest_lookback_days,
        )
    else:
        logger.error("Backtest loader returned an unsupported record type")
        return 1

    notifier = notifier or _send_report
    if not notifier(content, settings):
        logger.error("Backtest workflow finished with notification failure")
        return 1
    return 0


def _call_loader(loader: Callable, lookback_days: int):
    try:
        return loader()
    except TypeError:
        return loader(lookback_days=lookback_days)


def _send_report(content: str, settings: Settings) -> bool:
    return send_text(content=content, settings=settings, title="荐股交易周报", icon="\U0001f4c8")
