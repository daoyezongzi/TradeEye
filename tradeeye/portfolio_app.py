from __future__ import annotations

import datetime as dt
import logging
from typing import Callable

from tradeeye.config import Settings, load_settings
from tradeeye.logging_utils import configure_logging
from tradeeye.services.data import build_pro_client
from tradeeye.services.portfolio import SettlementResult, settle_recommend_portfolio
from tradeeye.services.trading import MarketDataProvider, MarketDataUnavailable, TushareMarketDataProvider

logger = logging.getLogger(__name__)

Settler = Callable[..., SettlementResult]


def main(
    settings: Settings | None = None,
    *,
    provider: MarketDataProvider | None = None,
    as_of: str | dt.date | None = None,
    settler: Settler = settle_recommend_portfolio,
) -> int:
    """Advance the recommendation ledger after complete daily bars are available.

    Return 0 for success (including no signals/idempotent replay), and 1 when
    configuration, supplier completeness, or persistence prevents settlement.
    """
    settings = settings or load_settings()
    configure_logging(settings.debug_mode)
    if provider is None:
        if not settings.tushare_token:
            logger.error("Portfolio settlement requires TUSHARE_TOKEN")
            return 1
        provider = TushareMarketDataProvider(build_pro_client(settings))
    try:
        result = settler(provider, as_of=as_of)
    except (MarketDataUnavailable, OSError, ValueError):
        logger.exception("Portfolio settlement did not advance")
        return 1
    except Exception:
        logger.exception("Unexpected portfolio settlement failure; state was not confirmed")
        return 1
    logger.info(
        "Portfolio settled through %s: %s trades, %s NAV rows",
        result.as_of,
        result.trade_count,
        result.nav_row_count,
    )
    return 0
