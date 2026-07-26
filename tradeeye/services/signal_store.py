from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

ANALYSIS_SIGNALS_FILE = Path("data/signals/analysis.csv")
RECOMMEND_SIGNALS_FILE = Path("data/signals/recommend.csv")
ANALYSIS_FIELDS = ["date", "ts_code", "name", "score", "status", "close", "called_llm"]
RECOMMEND_FIELDS = ["date", "ts_code", "name", "price_group", "total_score", "dimensions", "close"]


def append_analysis_signals(rows: Iterable[dict[str, Any]], path: str | Path = ANALYSIS_SIGNALS_FILE) -> bool:
    return _append_signals(rows, Path(path), ANALYSIS_FIELDS)


def append_recommend_signals(rows: Iterable[dict[str, Any]], path: str | Path = RECOMMEND_SIGNALS_FILE) -> bool:
    return _append_signals(rows, Path(path), RECOMMEND_FIELDS)


def _append_signals(rows: Iterable[dict[str, Any]], path: Path, fieldnames: list[str]) -> bool:
    """追加信号并按 (date, ts_code) 去重，后写覆盖先写。信号落地是旁路，失败只记日志。"""
    try:
        existing: dict[tuple[str, str], dict[str, str]] = {}
        if path.exists() and path.is_file():
            with path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    existing[(row.get("date", ""), row.get("ts_code", ""))] = {
                        key: row.get(key, "") for key in fieldnames
                    }

        for row in rows:
            normalized = {key: _to_cell(row.get(key)) for key in fieldnames}
            existing[(normalized["date"], normalized["ts_code"])] = normalized

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for key in sorted(existing):
                writer.writerow(existing[key])
        return True
    except Exception:
        logger.exception("Failed to append signals to %s", path)
        return False


def _to_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
