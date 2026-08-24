from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from tradeeye.services.signal_store import RECOMMEND_SIGNALS_FILE, read_recommend_signals
from tradeeye.services.trading import (
    DailyMarketData,
    MarketDataProvider,
    MarketDataUnavailable,
    decide_exit,
    entry_fill_price,
    gross_return_pct,
    net_return_pct,
    planned_entry_price,
    realized_value,
)

RECOMMEND_TRADES_FILE = Path("data/trades/recommend_trades.csv")
RECOMMEND_NAV_FILE = Path("data/portfolio/recommend_nav.csv")
TRADE_SCHEMA_VERSION = "recommend_trade_v1"
NAV_SCHEMA_VERSION = "recommend_nav_v2"

SLOT_COUNT = 5
MAX_DAILY_ENTRIES = 2
ROUND_TRIP_COST_PCT = 0.15

PENDING_ENTRY = "pending_entry"
ENTRY_UNAVAILABLE = "entry_unavailable"
EXPIRED_UNFILLED = "expired_unfilled"
OPEN = "open"
EXIT_DEFERRED = "exit_deferred"
CLOSED = "closed"
INVALID_SIGNAL = "invalid_signal"

PORTFOLIO_PENDING = "pending"
PORTFOLIO_NOT_ENTERED = "not_entered"
PORTFOLIO_OPEN = "open"
PORTFOLIO_EXIT_DEFERRED = "exit_deferred"
PORTFOLIO_CLOSED = "closed"
SKIPPED_DAILY_LIMIT = "skipped_daily_limit"
SKIPPED_CAPACITY = "skipped_capacity"
SKIPPED_DUPLICATE = "skipped_duplicate"


@dataclass
class TradeRecord:
    schema_version: str = TRADE_SCHEMA_VERSION
    trade_id: str = ""
    signal_id: str = ""
    signal_schema_version: str = ""
    strategy_version: str = ""
    signal_date: str = ""
    ts_code: str = ""
    name: str = ""
    industry: str = "未知"
    quality_score: float = 0.0
    selection_rank: int = 0
    signal_close: float = 0.0
    planned_entry_date: str = ""
    planned_entry_price: float = 0.0
    status: str = PENDING_ENTRY
    entry_date: str = ""
    entry_price: float = 0.0
    planned_exit_date: str = ""
    actual_exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    deferred_reason: str = ""
    delay_trade_days: int = 0
    gross_return_pct: float = 0.0
    cost_pct: float = ROUND_TRIP_COST_PCT
    net_return_pct: float = 0.0
    last_valid_close: float = 0.0
    stale_price: bool = False
    stale_valuation_days: int = 0
    portfolio_status: str = PORTFOLIO_PENDING
    portfolio_skip_reason: str = ""
    slot_id: int = 0
    allocated_capital: float = 0.0
    realized_value: float = 0.0

    def to_row(self) -> dict[str, str]:
        return {key: _to_cell(value) for key, value in asdict(self).items()}

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "TradeRecord":
        integer_fields = {"selection_rank", "delay_trade_days", "stale_valuation_days", "slot_id"}
        float_fields = {
            "quality_score",
            "signal_close",
            "planned_entry_price",
            "entry_price",
            "exit_price",
            "gross_return_pct",
            "cost_pct",
            "net_return_pct",
            "last_valid_close",
            "allocated_capital",
            "realized_value",
        }
        values: dict[str, object] = {}
        for item in fields(cls):
            value = row.get(item.name, "")
            if item.name in integer_fields:
                values[item.name] = _to_int(value)
            elif item.name in float_fields:
                values[item.name] = _to_float(value)
            elif item.name == "stale_price":
                values[item.name] = str(value).strip().lower() in {"1", "true", "yes"}
            elif value != "":
                values[item.name] = value
        return cls(**values)


TRADE_FIELDS = [item.name for item in fields(TradeRecord)]
NAV_FIELDS = [
    "schema_version",
    "nav_id",
    "strategy_version",
    "trade_date",
    "settled_through",
    "nav",
    "daily_return_pct",
    "cash_value",
    "market_value",
    "occupied_slots",
    "cash_slots",
    "slot_utilization_pct",
    "open_positions",
    "open_trade_ids",
    "stale_positions",
    "stale_price_codes",
    "industry_weights",
    "max_industry",
    "max_industry_weight_pct",
    "unknown_industry_positions",
]


@dataclass(frozen=True)
class SettlementResult:
    as_of: str
    processed_trade_days: int
    trade_count: int
    nav_row_count: int
    strategy_versions: tuple[str, ...]


def settle_recommend_portfolio(
    provider: MarketDataProvider,
    *,
    as_of: str | dt.date | None = None,
    signal_path: str | Path = RECOMMEND_SIGNALS_FILE,
    trade_path: str | Path = RECOMMEND_TRADES_FILE,
    nav_path: str | Path = RECOMMEND_NAV_FILE,
) -> SettlementResult:
    """Incrementally advance recommendation signals through ``as_of``.

    Existing trade/NAV rows are the settlement watermark. Only market days after
    each strategy version's latest NAV are requested. All newly required complete
    batches are fetched before either output file is replaced, so a provider/global
    error cannot be misclassified as a suspension or advance the ledger.
    """
    as_of_text = _normalize_date(as_of)
    signal_rows = [
        row for row in read_recommend_signals(signal_path) if row.get("date", "") <= as_of_text
    ]
    trade_target = Path(trade_path)
    nav_target = Path(nav_path)
    existing_records = read_trade_records(trade_target)
    existing_nav_rows = read_nav_rows(nav_target)

    if not signal_rows:
        if not trade_target.exists() or not nav_target.exists():
            _atomic_replace_csv_pair(
                (trade_target, TRADE_FIELDS, []),
                (nav_target, NAV_FIELDS, []),
            )
        return SettlementResult(as_of_text, 0, 0, 0, ())

    if _is_fully_settled(as_of_text, signal_rows, existing_records, existing_nav_rows):
        return SettlementResult(
            as_of_text,
            0,
            len(existing_records),
            len(existing_nav_rows),
            tuple(sorted({record.strategy_version for record in existing_records})),
        )

    signal_dates = sorted(row.get("date", "") for row in signal_rows if _valid_date(row.get("date", "")))
    if not signal_dates:
        records, added = _merge_signal_records(signal_rows, existing_records, [])
        if added:
            _atomic_replace_csv_pair(
                (trade_target, TRADE_FIELDS, _trade_rows(records)),
                (nav_target, NAV_FIELDS, existing_nav_rows),
            )
        return SettlementResult(
            as_of_text,
            0,
            len(records),
            len(existing_nav_rows),
            tuple(sorted({r.strategy_version for r in records})),
        )

    advance_versions = _versions_to_advance(signal_rows, existing_records)
    calendar_start = _calendar_start(
        signal_rows,
        existing_records,
        existing_nav_rows,
        advance_versions,
    )
    calendar_end = (_parse_date(as_of_text) + dt.timedelta(days=31)).strftime("%Y%m%d")
    trade_days = _load_trade_days(provider, calendar_start, calendar_end)
    records, added = _merge_signal_records(signal_rows, existing_records, trade_days)
    versions = sorted({record.strategy_version for record in records})
    nav_by_version = {
        version: [row for row in existing_nav_rows if row.get("strategy_version") == version]
        for version in versions
    }
    processing_days: dict[str, list[str]] = {}
    for version in versions:
        version_records = [record for record in records if record.strategy_version == version]
        version_nav = nav_by_version[version]
        latest_nav_date = max((row.get("trade_date", "") for row in version_nav), default="")
        first_signal_date = min(
            (record.signal_date for record in version_records if _valid_date(record.signal_date)),
            default="",
        )
        watermark = latest_nav_date or first_signal_date
        processing_days[version] = (
            [day for day in trade_days if watermark < day <= as_of_text]
            if version in advance_versions
            else []
        )
        _reject_late_pending_signals(version_records, latest_nav_date, added)

    required_batch_days = sorted({day for days in processing_days.values() for day in days})
    batches = _preload_batches(provider, required_batch_days)
    nav_rows = list(existing_nav_rows)
    for version in versions:
        version_records = [record for record in records if record.strategy_version == version]
        nav_rows.extend(
            _simulate_version_incremental(
                version,
                version_records,
                trade_days,
                processing_days[version],
                batches,
                nav_by_version[version],
            )
        )

    watermark_changed = _mark_settled_through(nav_rows, advance_versions, as_of_text)
    if (
        not added
        and not required_batch_days
        and len(nav_rows) == len(existing_nav_rows)
        and not watermark_changed
    ):
        return SettlementResult(
            as_of_text,
            0,
            len(records),
            len(nav_rows),
            tuple(versions),
        )

    record_rows = _trade_rows(records)
    nav_rows.sort(key=lambda row: (row["strategy_version"], row["trade_date"]))
    _atomic_replace_csv_pair(
        (trade_target, TRADE_FIELDS, record_rows),
        (nav_target, NAV_FIELDS, nav_rows),
    )
    return SettlementResult(
        as_of=as_of_text,
        processed_trade_days=len(required_batch_days),
        trade_count=len(records),
        nav_row_count=len(nav_rows),
        strategy_versions=tuple(versions),
    )


def read_trade_records(path: str | Path = RECOMMEND_TRADES_FILE) -> list[TradeRecord]:
    rows = _read_csv(Path(path))
    return [TradeRecord.from_row(row) for row in rows]


def read_nav_rows(path: str | Path = RECOMMEND_NAV_FILE) -> list[dict[str, str]]:
    return _read_csv(Path(path))


def _is_fully_settled(
    as_of: str,
    signal_rows: list[dict[str, str]],
    records: list[TradeRecord],
    nav_rows: list[dict[str, str]],
) -> bool:
    record_ids = {record.signal_id for record in records}
    if any(row.get("signal_id", "") not in record_ids for row in signal_rows):
        return False
    versions = _versions_to_advance(signal_rows, records)
    for version in versions:
        version_rows = [row for row in signal_rows if (row.get("strategy_version", "") or "legacy_v1") == version]
        if not any(_valid_date(row.get("date", "")) for row in version_rows):
            continue
        settled_through = max(
            (
                row.get("settled_through", "") or row.get("trade_date", "")
                for row in nav_rows
                if row.get("strategy_version") == version
            ),
            default="",
        )
        if settled_through < as_of:
            return False
    return True


def _mark_settled_through(
    nav_rows: list[dict[str, str]],
    versions: set[str],
    as_of: str,
) -> bool:
    """Persist a non-trading-day watermark on each active version's latest NAV row."""
    changed = False
    for version in versions:
        version_rows = [row for row in nav_rows if row.get("strategy_version") == version]
        if not version_rows:
            continue
        latest_row = max(version_rows, key=lambda row: row.get("trade_date", ""))
        current = latest_row.get("settled_through", "") or latest_row.get("trade_date", "")
        if current < as_of:
            latest_row["settled_through"] = as_of
            changed = True
    return changed


def _calendar_start(
    signal_rows: list[dict[str, str]],
    records: list[TradeRecord],
    nav_rows: list[dict[str, str]],
    advance_versions: set[str],
) -> str:
    existing_ids = {record.signal_id for record in records}
    dates = [
        row.get("date", "")
        for row in signal_rows
        if row.get("signal_id", "") not in existing_ids and _valid_date(row.get("date", ""))
    ]
    dates.extend(
        record.signal_date
        for record in records
        if record.status == PENDING_ENTRY and _valid_date(record.signal_date)
    )
    dates.extend(
        record.entry_date
        for record in records
        if record.status in {OPEN, EXIT_DEFERRED} and _valid_date(record.entry_date)
    )
    for version in advance_versions:
        latest_nav = max(
            (
                row.get("trade_date", "")
                for row in nav_rows
                if row.get("strategy_version") == version
                and _valid_date(row.get("trade_date", ""))
            ),
            default="",
        )
        if latest_nav:
            dates.append(latest_nav)
    if not dates:
        dates.extend(
            row.get("date", "")
            for row in signal_rows
            if (row.get("strategy_version", "") or "legacy_v1") in advance_versions
            and _valid_date(row.get("date", ""))
        )
    return min(dates)


def _versions_to_advance(
    signal_rows: list[dict[str, str]],
    records: list[TradeRecord],
) -> set[str]:
    existing_ids = {record.signal_id for record in records}
    versions = {
        record.strategy_version
        for record in records
        if record.status in {PENDING_ENTRY, OPEN, EXIT_DEFERRED}
    }
    latest_signal_date = max((row.get("date", "") for row in signal_rows), default="")
    versions.update(
        row.get("strategy_version", "") or "legacy_v1"
        for row in signal_rows
        if row.get("date", "") == latest_signal_date
        or row.get("signal_id", "") not in existing_ids
    )
    return versions


def _merge_signal_records(
    signal_rows: list[dict[str, str]],
    existing_records: list[TradeRecord],
    trade_days: list[str],
) -> tuple[list[TradeRecord], set[str]]:
    records_by_signal: dict[str, TradeRecord] = {}
    for record in existing_records:
        records_by_signal.setdefault(record.signal_id, record)
    added: set[str] = set()
    for row in signal_rows:
        signal_id = row.get("signal_id", "")
        if signal_id in records_by_signal:
            continue
        record = _build_trade(row, trade_days)
        records_by_signal[signal_id] = record
        added.add(signal_id)
    for record in records_by_signal.values():
        if record.status == PENDING_ENTRY and not record.planned_entry_date:
            record.planned_entry_date = next(
                (day for day in trade_days if day > record.signal_date),
                "",
            )
    return list(records_by_signal.values()), added


def _reject_late_pending_signals(
    records: list[TradeRecord],
    latest_nav_date: str,
    added_signal_ids: set[str],
) -> None:
    if not latest_nav_date:
        return
    for record in records:
        if (
            record.signal_id in added_signal_ids
            and record.status == PENDING_ENTRY
            and record.planned_entry_date
            and record.planned_entry_date <= latest_nav_date
        ):
            raise ValueError(
                f"late signal {record.signal_id} requires an explicit historical backfill"
            )


def _trade_rows(records: list[TradeRecord]) -> list[dict[str, str]]:
    return [
        record.to_row()
        for record in sorted(
            records,
            key=lambda item: (item.strategy_version, item.signal_date, _record_sort_key(item)),
        )
    ]


def _load_trade_days(provider: MarketDataProvider, start_date: str, end_date: str) -> list[str]:
    try:
        days = provider.get_trade_days(start_date, end_date)
    except MarketDataUnavailable:
        raise
    except Exception as exc:
        raise MarketDataUnavailable("trade calendar provider failed") from exc
    normalized = sorted({str(day) for day in days if _valid_date(str(day))})
    if not normalized:
        raise MarketDataUnavailable("trade calendar has no usable open days")
    return normalized


def _preload_batches(
    provider: MarketDataProvider,
    trade_days: list[str],
) -> dict[str, DailyMarketData]:
    batches: dict[str, DailyMarketData] = {}
    for trade_date in trade_days:
        try:
            batch = provider.get_daily_market(trade_date)
        except MarketDataUnavailable:
            raise
        except Exception as exc:
            raise MarketDataUnavailable(f"market provider failed for {trade_date}") from exc
        if batch is None or not batch.complete or batch.trade_date != trade_date:
            raise MarketDataUnavailable(f"market batch is incomplete for {trade_date}")
        batches[trade_date] = batch
    return batches


def _build_trade(row: dict[str, str], trade_days: list[str]) -> TradeRecord:
    signal_date = row.get("date", "")
    code = row.get("ts_code", "").strip().upper()
    close = _to_float(row.get("close"))
    next_days = [day for day in trade_days if day > signal_date]
    status = PENDING_ENTRY
    portfolio_status = PORTFOLIO_PENDING
    if not _valid_date(signal_date) or not code or close <= 0:
        status = INVALID_SIGNAL
        portfolio_status = PORTFOLIO_NOT_ENTERED
    signal_id = row.get("signal_id", "")
    return TradeRecord(
        trade_id=_stable_trade_id(signal_id),
        signal_id=signal_id,
        signal_schema_version=row.get("schema_version", ""),
        strategy_version=row.get("strategy_version", "") or "legacy_v1",
        signal_date=signal_date,
        ts_code=code,
        name=row.get("name", ""),
        industry=row.get("industry", "").strip() or "未知",
        quality_score=_to_float(row.get("quality_score") or row.get("total_score")),
        selection_rank=_to_int(row.get("selection_rank")),
        signal_close=close,
        planned_entry_date=next_days[0] if next_days else "",
        planned_entry_price=planned_entry_price(close) if close > 0 else 0.0,
        status=status,
        portfolio_status=portfolio_status,
    )


def _simulate_version_incremental(
    strategy_version: str,
    records: list[TradeRecord],
    trade_days: list[str],
    processing_days: list[str],
    batches: dict[str, DailyMarketData],
    existing_nav_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    valid_signal_dates = [record.signal_date for record in records if _valid_date(record.signal_date)]
    if not valid_signal_dates:
        return []
    day_indexes = {day: index for index, day in enumerate(trade_days)}
    slot_cash, occupied = _restore_portfolio_state(records)
    nav_rows: list[dict[str, str]] = []
    if existing_nav_rows:
        latest_nav = max(existing_nav_rows, key=lambda row: row.get("trade_date", ""))
        previous_nav = _to_float(latest_nav.get("nav"))
    else:
        first_date = min(valid_signal_dates)
        previous_nav = 1.0
        nav_rows.append(
            _build_nav_row(
                strategy_version,
                first_date,
                occupied,
                slot_cash,
                previous_nav,
            )
        )

    for trade_date in processing_days:
        batch = batches[trade_date]
        # Capacity is decided from slots available before the session starts.
        # A slot released by an intraday/close exit is cash for the next batch,
        # not retroactively available to an entry whose exact intraday order is unknown.
        candidates = _process_entries(records, trade_date, batch)
        _allocate_candidates(candidates, occupied, slot_cash)
        _process_exits(records, occupied, slot_cash, trade_date, batch, day_indexes)
        nav_row = _build_nav_row(
            strategy_version,
            trade_date,
            occupied,
            slot_cash,
            previous_nav,
        )
        previous_nav = _to_float(nav_row["nav"])
        nav_rows.append(nav_row)
    return nav_rows


def _restore_portfolio_state(
    records: list[TradeRecord],
) -> tuple[dict[int, float], dict[int, TradeRecord]]:
    slot_cash = {slot_id: 1.0 / SLOT_COUNT for slot_id in range(1, SLOT_COUNT + 1)}
    selected = [record for record in records if record.slot_id in slot_cash]
    for record in sorted(selected, key=lambda item: (item.actual_exit_date, item.entry_date)):
        if record.status == CLOSED and record.realized_value >= 0:
            slot_cash[record.slot_id] = record.realized_value

    occupied: dict[int, TradeRecord] = {}
    for record in selected:
        if record.status not in {OPEN, EXIT_DEFERRED}:
            continue
        if record.slot_id in occupied:
            raise ValueError(f"slot {record.slot_id} has multiple open trades")
        occupied[record.slot_id] = record
    return slot_cash, occupied


def _process_exits(
    records: list[TradeRecord],
    occupied: dict[int, TradeRecord],
    slot_cash: dict[int, float],
    trade_date: str,
    batch: DailyMarketData,
    day_indexes: dict[str, int],
) -> None:
    for record in records:
        if record.status not in {OPEN, EXIT_DEFERRED} or not record.entry_date:
            continue
        entry_index = day_indexes.get(record.entry_date)
        current_index = day_indexes.get(trade_date)
        if entry_index is None or current_index is None or current_index <= entry_index:
            continue
        quote = batch.quote(record.ts_code)

        if record.status == EXIT_DEFERRED:
            if quote is None:
                record.stale_price = True
                record.stale_valuation_days += 1
                continue
            record.last_valid_close = quote.close
            record.stale_price = False
            if quote.locked_at_down_limit:
                record.deferred_reason = _append_reason(record.deferred_reason, "one_price_down_limit")
                continue
            _close_trade(record, trade_date, quote.open, "deferred_open", day_indexes)
            _release_slot(record, occupied, slot_cash)
            continue

        # D+1 is entry-only under A-share T+1. Exit checks start on D+2.
        if current_index < entry_index + 1:
            continue
        force_timeout = current_index >= entry_index + 2
        if quote is None:
            if force_timeout:
                _defer_trade(record, trade_date, "no_quote")
            else:
                record.stale_price = True
                record.stale_valuation_days += 1
            continue

        record.last_valid_close = quote.close
        record.stale_price = False
        decision = decide_exit(record.entry_price, quote, force_timeout=force_timeout)
        if decision is None:
            continue
        if decision.action == "defer":
            _defer_trade(record, trade_date, decision.reason)
            continue
        _close_trade(record, trade_date, decision.price or quote.close, decision.reason, day_indexes)
        _release_slot(record, occupied, slot_cash)


def _process_entries(
    records: list[TradeRecord],
    trade_date: str,
    batch: DailyMarketData,
) -> list[TradeRecord]:
    triggered: list[TradeRecord] = []
    for record in records:
        if record.status != PENDING_ENTRY or record.planned_entry_date != trade_date:
            continue
        quote = batch.quote(record.ts_code)
        if quote is None:
            record.status = ENTRY_UNAVAILABLE
            record.portfolio_status = PORTFOLIO_NOT_ENTERED
            record.portfolio_skip_reason = ENTRY_UNAVAILABLE
            continue
        fill = entry_fill_price(record.signal_close, quote)
        if fill is None:
            record.status = EXPIRED_UNFILLED
            record.portfolio_status = PORTFOLIO_NOT_ENTERED
            record.portfolio_skip_reason = EXPIRED_UNFILLED
            continue
        record.status = OPEN
        record.entry_date = trade_date
        record.entry_price = fill
        record.last_valid_close = quote.close
        triggered.append(record)
    return sorted(triggered, key=_record_sort_key)


def _allocate_candidates(
    candidates: list[TradeRecord],
    occupied: dict[int, TradeRecord],
    slot_cash: dict[int, float],
) -> None:
    new_entries = 0
    for record in candidates:
        held_codes = {item.ts_code for item in occupied.values()}
        if record.ts_code in held_codes:
            record.portfolio_status = SKIPPED_DUPLICATE
            record.portfolio_skip_reason = SKIPPED_DUPLICATE
            continue
        if new_entries >= MAX_DAILY_ENTRIES:
            record.portfolio_status = SKIPPED_DAILY_LIMIT
            record.portfolio_skip_reason = SKIPPED_DAILY_LIMIT
            continue
        free_slots = [slot_id for slot_id in slot_cash if slot_id not in occupied]
        if not free_slots:
            record.portfolio_status = SKIPPED_CAPACITY
            record.portfolio_skip_reason = SKIPPED_CAPACITY
            continue
        slot_id = min(free_slots)
        record.portfolio_status = PORTFOLIO_OPEN
        record.slot_id = slot_id
        record.allocated_capital = slot_cash[slot_id]
        occupied[slot_id] = record
        new_entries += 1


def _defer_trade(record: TradeRecord, trade_date: str, reason: str) -> None:
    record.status = EXIT_DEFERRED
    record.planned_exit_date = record.planned_exit_date or trade_date
    record.deferred_reason = _append_reason(record.deferred_reason, reason)
    record.stale_price = reason == "no_quote"
    if record.stale_price:
        record.stale_valuation_days += 1
    if record.slot_id:
        record.portfolio_status = PORTFOLIO_EXIT_DEFERRED


def _close_trade(
    record: TradeRecord,
    trade_date: str,
    exit_price: float,
    reason: str,
    day_indexes: dict[str, int],
) -> None:
    record.status = CLOSED
    record.planned_exit_date = record.planned_exit_date or trade_date
    record.actual_exit_date = trade_date
    record.exit_price = exit_price
    record.exit_reason = reason
    record.delay_trade_days = max(
        day_indexes.get(trade_date, 0) - day_indexes.get(record.planned_exit_date, 0),
        0,
    )
    record.gross_return_pct = gross_return_pct(record.entry_price, exit_price)
    record.net_return_pct = net_return_pct(
        record.entry_price,
        exit_price,
        cost_pct=record.cost_pct,
    )
    record.stale_price = False
    if record.slot_id:
        record.portfolio_status = PORTFOLIO_CLOSED
        record.realized_value = realized_value(
            record.allocated_capital,
            record.entry_price,
            exit_price,
            cost_pct=record.cost_pct,
        )


def _release_slot(
    record: TradeRecord,
    occupied: dict[int, TradeRecord],
    slot_cash: dict[int, float],
) -> None:
    if not record.slot_id or occupied.get(record.slot_id) is not record:
        return
    slot_cash[record.slot_id] = record.realized_value
    del occupied[record.slot_id]


def _build_nav_row(
    strategy_version: str,
    trade_date: str,
    occupied: dict[int, TradeRecord],
    slot_cash: dict[int, float],
    previous_nav: float,
) -> dict[str, str]:
    cash_value = sum(value for slot_id, value in slot_cash.items() if slot_id not in occupied)
    position_values = {
        slot_id: record.allocated_capital * record.last_valid_close / record.entry_price
        for slot_id, record in occupied.items()
        if record.entry_price > 0 and record.last_valid_close > 0
    }
    market_value = sum(position_values.values())
    nav = cash_value + market_value
    daily_return = (nav / previous_nav - 1.0) * 100.0 if previous_nav > 0 else 0.0
    industry_values: dict[str, float] = {}
    for slot_id, record in occupied.items():
        industry_values[record.industry] = industry_values.get(record.industry, 0.0) + position_values.get(slot_id, 0.0)
    invested = sum(industry_values.values())
    industry_weights = {
        industry: (value / invested * 100.0 if invested > 0 else 0.0)
        for industry, value in sorted(industry_values.items())
    }
    max_industry = max(industry_weights, key=industry_weights.get) if industry_weights else ""
    stale_records = [record for record in occupied.values() if record.stale_price]
    row: dict[str, object] = {
        "schema_version": NAV_SCHEMA_VERSION,
        "nav_id": _stable_nav_id(strategy_version, trade_date),
        "strategy_version": strategy_version,
        "trade_date": trade_date,
        "settled_through": trade_date,
        "nav": nav,
        "daily_return_pct": daily_return,
        "cash_value": cash_value,
        "market_value": market_value,
        "occupied_slots": len(occupied),
        "cash_slots": SLOT_COUNT - len(occupied),
        "slot_utilization_pct": len(occupied) / SLOT_COUNT * 100.0,
        "open_positions": len(occupied),
        "open_trade_ids": "|".join(sorted(record.trade_id for record in occupied.values())),
        "stale_positions": len(stale_records),
        "stale_price_codes": "|".join(sorted(record.ts_code for record in stale_records)),
        "industry_weights": json.dumps(industry_weights, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "max_industry": max_industry,
        "max_industry_weight_pct": industry_weights.get(max_industry, 0.0),
        "unknown_industry_positions": sum(1 for record in occupied.values() if record.industry == "未知"),
    }
    return {field: _to_cell(row.get(field, "")) for field in NAV_FIELDS}


def _record_sort_key(record: TradeRecord) -> tuple[int, float, str, str]:
    rank = record.selection_rank if record.selection_rank > 0 else 1_000_000
    return (rank, -record.quality_score, record.ts_code, record.signal_id)


def _stable_trade_id(signal_id: str) -> str:
    digest = hashlib.sha256(f"recommend_trade|{signal_id}".encode("utf-8")).hexdigest()[:24]
    return f"trd_{digest}"


def _stable_nav_id(strategy_version: str, trade_date: str) -> str:
    digest = hashlib.sha256(f"recommend_nav|{strategy_version}|{trade_date}".encode("utf-8")).hexdigest()[:24]
    return f"nav_{digest}"


def _append_reason(existing: str, reason: str) -> str:
    reasons = [item for item in existing.split("|") if item]
    if reason not in reasons:
        reasons.append(reason)
    return "|".join(reasons)


def _atomic_replace_csv_pair(
    first: tuple[Path, list[str], list[dict[str, str]]],
    second: tuple[Path, list[str], list[dict[str, str]]],
) -> None:
    staged: list[tuple[Path, Path]] = []
    backups: dict[Path, Path | None] = {}
    installed: list[Path] = []
    rollback_failed = False
    try:
        for target, fieldnames, rows in (first, second):
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                newline="",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as fh:
                temp_path = Path(fh.name)
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
                fh.flush()
                os.fsync(fh.fileno())
            staged.append((temp_path, target))

        for _, target in staged:
            if not target.exists():
                backups[target] = None
                continue
            with target.open("rb") as source, tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".bak",
                delete=False,
            ) as backup:
                backup_path = Path(backup.name)
                while chunk := source.read(1024 * 1024):
                    backup.write(chunk)
                backup.flush()
                os.fsync(backup.fileno())
            backups[target] = backup_path

        for temp_path, target in staged:
            os.replace(temp_path, target)
            installed.append(target)
    except Exception as exc:
        rollback_errors: list[Exception] = []
        for target in reversed(installed):
            backup_path = backups[target]
            try:
                if backup_path is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(backup_path, target)
            except Exception as rollback_exc:
                rollback_errors.append(rollback_exc)
        if rollback_errors:
            rollback_failed = True
            raise RuntimeError("CSV pair replacement failed and rollback was incomplete") from exc
        raise
    finally:
        for temp_path, _ in staged:
            if temp_path.exists():
                temp_path.unlink()
        if not rollback_failed:
            for backup_path in backups.values():
                if backup_path is not None and backup_path.exists():
                    backup_path.unlink()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _normalize_date(value: str | dt.date | None) -> str:
    if value is None:
        return dt.date.today().strftime("%Y%m%d")
    if isinstance(value, dt.date):
        return value.strftime("%Y%m%d")
    parsed = _parse_date(str(value))
    return parsed.strftime("%Y%m%d")


def _valid_date(value: str) -> bool:
    try:
        _parse_date(value)
        return True
    except ValueError:
        return False


def _parse_date(value: str) -> dt.date:
    return dt.datetime.strptime(str(value).strip(), "%Y%m%d").date()


def _to_float(value) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_cell(value) -> str:
    if isinstance(value, float):
        return format(value, ".12g")
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)
