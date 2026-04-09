from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import tushare as ts

from tradeeye.config import Settings

logger = logging.getLogger(__name__)


def build_pro_client(settings: Settings):
    ts.set_token(settings.tushare_token)
    return ts.pro_api()


def get_clean_data(code: str, settings: Settings, pro_client=None) -> dict[str, Any] | None:
    if not settings.tushare_token:
        logger.error("Tushare data skipped for %s: missing TUSHARE_TOKEN", code)
        return None

    client = pro_client or build_pro_client(settings)

    try:
        base_info = client.stock_basic(ts_code=code, fields="name")
        name = base_info.iloc[0]["name"] if not base_info.empty else "Unknown"

        df = client.daily(ts_code=code, limit=30)
        if df.empty:
            logger.warning("No daily data returned for %s", code)
            return None

        df = df.sort_values("trade_date").reset_index(drop=True)
        if len(df.index) < 2:
            logger.warning("Not enough rows returned for %s", code)
            return None

        df["ma5"] = df["close"].rolling(window=5).mean()
        df["ma20"] = df["close"].rolling(window=20).mean()

        if settings.debug_mode:
            debug_dir = Path("debug_data")
            debug_dir.mkdir(exist_ok=True)
            df.to_csv(debug_dir / f"{code}_debug.csv", index=False, encoding="utf_8_sig")

        return {"name": name, "df": df, "latest": df.iloc[-1], "prev": df.iloc[-2]}
    except Exception:
        logger.exception("Data engine failed for %s", code)
        return None
