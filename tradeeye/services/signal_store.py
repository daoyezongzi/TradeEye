from __future__ import annotations

import csv
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

ANALYSIS_SIGNALS_FILE = Path("data/signals/analysis.csv")
RECOMMEND_SIGNALS_FILE = Path("data/signals/recommend.csv")
ETF_RECOMMEND_SIGNALS_FILE = Path("data/signals/etf_recommend.csv")

LEGACY_SCHEMA_VERSION = "legacy_v1"
ANALYSIS_SCHEMA_VERSION = "analysis_signal_v2"
RECOMMEND_SCHEMA_VERSION = "recommend_signal_v2"
ETF_RECOMMEND_SCHEMA_VERSION = "etf_recommend_signal_v1"

DEFAULT_ANALYSIS_STRATEGY_VERSION = "analysis_v1"
DEFAULT_RECOMMEND_STRATEGY_VERSION = "recommend_v1"
DEFAULT_ETF_STRATEGY_VERSION = "etf_recommend_v1"

ANALYSIS_FIELDS = [
    "schema_version",
    "signal_id",
    "strategy_version",
    "date",
    "ts_code",
    "name",
    "score",
    "status",
    "close",
    "called_llm",
]
RECOMMEND_FIELDS = [
    "schema_version",
    "signal_id",
    "strategy_version",
    "generated_at",
    "trade_date",
    "date",
    "ts_code",
    "name",
    "industry",
    "momentum_score",
    "close_quality_score",
    "volume_funds_score",
    "quality_score",
    "risk_level",
    "risk_flags",
    "planned_entry_price",
    "close",
    "price_preference",
    "selection_rank",
    "rules_fingerprint",
    "price_group",
    "total_score",
    "dimensions",
]
ETF_RECOMMEND_FIELDS = [
    "schema_version",
    "signal_id",
    "strategy_version",
    "generated_at",
    "trade_date",
    "date",
    "ts_code",
    "name",
    "fund_type",
    "momentum_score",
    "close_quality_score",
    "liquidity_score",
    "quality_score",
    "risk_level",
    "risk_flags",
    "planned_entry_price",
    "close",
    "price_preference",
    "selection_rank",
    "rules_fingerprint",
    "dimensions",
]


def append_analysis_signals(
    rows: Iterable[dict[str, Any]],
    path: str | Path = ANALYSIS_SIGNALS_FILE,
) -> bool:
    return _append_signals(
        rows,
        Path(path),
        ANALYSIS_FIELDS,
        kind="analysis",
        schema_version=ANALYSIS_SCHEMA_VERSION,
        strategy_version=DEFAULT_ANALYSIS_STRATEGY_VERSION,
    )


def append_recommend_signals(
    rows: Iterable[dict[str, Any]],
    path: str | Path = RECOMMEND_SIGNALS_FILE,
) -> bool:
    return _append_signals(
        rows,
        Path(path),
        RECOMMEND_FIELDS,
        kind="recommend",
        schema_version=RECOMMEND_SCHEMA_VERSION,
        strategy_version=DEFAULT_RECOMMEND_STRATEGY_VERSION,
    )


def append_etf_recommend_signals(
    rows: Iterable[dict[str, Any]],
    path: str | Path = ETF_RECOMMEND_SIGNALS_FILE,
) -> bool:
    """Persist ETF research signals in their own versioned data stream."""
    return _append_signals(
        rows,
        Path(path),
        ETF_RECOMMEND_FIELDS,
        kind="etf_recommend",
        schema_version=ETF_RECOMMEND_SCHEMA_VERSION,
        strategy_version=DEFAULT_ETF_STRATEGY_VERSION,
    )


def read_analysis_signals(path: str | Path = ANALYSIS_SIGNALS_FILE) -> list[dict[str, str]]:
    return _read_signals(
        Path(path),
        ANALYSIS_FIELDS,
        kind="analysis",
        schema_version=ANALYSIS_SCHEMA_VERSION,
        strategy_version=DEFAULT_ANALYSIS_STRATEGY_VERSION,
    )


def read_recommend_signals(path: str | Path = RECOMMEND_SIGNALS_FILE) -> list[dict[str, str]]:
    """Read both current rows and header-compatible legacy_v1 recommendation CSVs."""
    return _read_signals(
        Path(path),
        RECOMMEND_FIELDS,
        kind="recommend",
        schema_version=RECOMMEND_SCHEMA_VERSION,
        strategy_version=DEFAULT_RECOMMEND_STRATEGY_VERSION,
    )


def read_etf_recommend_signals(
    path: str | Path = ETF_RECOMMEND_SIGNALS_FILE,
) -> list[dict[str, str]]:
    return _read_signals(
        Path(path),
        ETF_RECOMMEND_FIELDS,
        kind="etf_recommend",
        schema_version=ETF_RECOMMEND_SCHEMA_VERSION,
        strategy_version=DEFAULT_ETF_STRATEGY_VERSION,
    )


def stable_signal_id(kind: str, strategy_version: str, date: str, ts_code: str) -> str:
    """Return an opaque deterministic ID; reruns of the same strategy signal collide."""
    identity = "|".join(
        (kind.strip().lower(), strategy_version.strip(), date.strip(), ts_code.strip().upper())
    )
    return f"sig_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def _append_signals(
    rows: Iterable[dict[str, Any]],
    path: Path,
    fieldnames: list[str],
    *,
    kind: str,
    schema_version: str,
    strategy_version: str,
) -> bool:
    """Append immutable signals by stable ID and atomically replace on success."""
    try:
        existing: dict[str, dict[str, str]] = {}
        for existing_row in _read_signals(
            path,
            fieldnames,
            kind=kind,
            schema_version=schema_version,
            strategy_version=strategy_version,
            strict=True,
        ):
            existing.setdefault(existing_row["signal_id"], existing_row)
        changed = False
        for row in rows:
            normalized = _normalize_row(
                row,
                fieldnames,
                kind=kind,
                schema_version=schema_version,
                strategy_version=strategy_version,
                legacy=False,
            )
            if normalized["signal_id"] not in existing:
                existing[normalized["signal_id"]] = normalized
                changed = True

        if path.exists() and not changed:
            return True

        ordered_rows = sorted(
            existing.values(),
            key=lambda row: (
                row.get("trade_date", "") or row.get("date", ""),
                _rank_key(row.get("selection_rank", "")),
                row.get("ts_code", ""),
                row.get("signal_id", ""),
            ),
        )
        _atomic_write_csv(path, fieldnames, ordered_rows)
        return True
    except Exception:
        logger.exception("Failed to append signals to %s", path)
        return False


def _read_signals(
    path: Path,
    fieldnames: list[str],
    *,
    kind: str,
    schema_version: str,
    strategy_version: str,
    strict: bool = False,
) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            legacy = not reader.fieldnames or "schema_version" not in reader.fieldnames
            return [
                _normalize_row(
                    row,
                    fieldnames,
                    kind=kind,
                    schema_version=schema_version,
                    strategy_version=strategy_version,
                    legacy=legacy,
                )
                for row in reader
            ]
    except Exception:
        if strict:
            raise
        logger.exception("Failed to read signals file %s", path)
        return []


def _normalize_row(
    row: dict[str, Any],
    fieldnames: list[str],
    *,
    kind: str,
    schema_version: str,
    strategy_version: str,
    legacy: bool,
) -> dict[str, str]:
    normalized = {key: _to_cell(row.get(key)) for key in fieldnames}
    if "trade_date" in normalized:
        normalized["trade_date"] = normalized["trade_date"] or normalized.get("date", "")
        normalized["date"] = normalized.get("date", "") or normalized["trade_date"]
    if legacy:
        normalized["schema_version"] = LEGACY_SCHEMA_VERSION
        normalized["strategy_version"] = LEGACY_SCHEMA_VERSION
    else:
        normalized["schema_version"] = normalized["schema_version"] or schema_version
        normalized["strategy_version"] = normalized["strategy_version"] or strategy_version

    normalized["signal_id"] = normalized["signal_id"] or stable_signal_id(
        kind,
        normalized["strategy_version"],
        normalized.get("trade_date", "") or normalized.get("date", ""),
        normalized.get("ts_code", ""),
    )
    return normalized


def _atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            temp_path = Path(fh.name)
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _rank_key(value: str) -> tuple[int, float | str]:
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, value or "")


def _to_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
