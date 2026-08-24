from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


def market_today(now: dt.datetime | None = None) -> dt.date:
    """Return the current calendar date used by the China-market reports."""
    current = now or dt.datetime.now(MARKET_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=MARKET_TIMEZONE)
    return current.astimezone(MARKET_TIMEZONE).date()
