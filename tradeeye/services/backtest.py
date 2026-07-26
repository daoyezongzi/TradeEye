from __future__ import annotations

import csv
import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

from tradeeye.config import Settings
from tradeeye.services.data import build_pro_client
from tradeeye.strategies.rules import get_rules

logger = logging.getLogger(__name__)

ANALYSIS_SIGNALS_FILE = Path("data/signals/analysis.csv")
RECOMMEND_SIGNALS_FILE = Path("data/signals/recommend.csv")
MIN_SAMPLE_SIZE = 5


@dataclass(frozen=True)
class SignalRecord:
    date: str
    ts_code: str
    name: str
    kind: str
    group: str
    close: float


@dataclass(frozen=True)
class SignalResult:
    record: SignalRecord
    overnight_return_pct: float
    day_return_pct: float


def load_signals(
    analysis_path: str | Path = ANALYSIS_SIGNALS_FILE,
    recommend_path: str | Path = RECOMMEND_SIGNALS_FILE,
    lookback_days: int = 45,
    today: dt.date | None = None,
) -> list[SignalRecord]:
    cutoff = (today or dt.date.today()) - dt.timedelta(days=lookback_days)
    records = _load_analysis_signals(Path(analysis_path), cutoff)
    records.extend(_load_recommend_signals(Path(recommend_path), cutoff))
    return records


def evaluate_signals(
    records: list[SignalRecord],
    settings: Settings,
    pro_client=None,
) -> tuple[list[SignalResult], int]:
    if not records:
        return [], 0

    client = pro_client or build_pro_client(settings)
    signal_dates = sorted({record.date for record in records})
    next_day_map = _resolve_next_trade_days(client, signal_dates)

    quotes: dict[str, dict[str, tuple[float, float]]] = {}
    for next_day in sorted(set(next_day_map.values())):
        quotes[next_day] = _fetch_day_quotes(client, next_day)

    results: list[SignalResult] = []
    missing = 0
    for record in records:
        next_day = next_day_map.get(record.date)
        quote = quotes.get(next_day, {}).get(record.ts_code) if next_day else None
        if not quote or quote[0] <= 0 or quote[1] <= 0 or record.close <= 0:
            missing += 1
            continue
        next_open, next_close = quote
        results.append(
            SignalResult(
                record=record,
                overnight_return_pct=(next_open / record.close - 1) * 100,
                day_return_pct=(next_close / record.close - 1) * 100,
            )
        )
    return results, missing


def build_backtest_report(
    results: list[SignalResult],
    missing_count: int,
    lookback_days: int,
) -> str:
    lines = [f"回看窗口：近 {lookback_days} 天"]

    if not results:
        lines.append("窗口内无可评估信号。")
    else:
        groups: dict[str, list[SignalResult]] = {}
        for result in results:
            groups.setdefault(result.record.group, []).append(result)

        for group_name in sorted(groups):
            group_results = groups[group_name]
            sample_size = len(group_results)
            overnight = [item.overnight_return_pct for item in group_results]
            day = [item.day_return_pct for item in group_results]
            suffix = "（样本不足，仅供参考）" if sample_size < MIN_SAMPLE_SIZE else ""
            lines.append(
                f"\n【{group_name}】样本 {sample_size} 条{suffix}\n"
                f"- 隔夜(收盘→次日开盘)：胜率 {_win_rate_pct(overnight):.0f}% | 平均 {_mean(overnight):+.2f}%\n"
                f"- T+1 全天(收盘→次日收盘)：胜率 {_win_rate_pct(day):.0f}% | 平均 {_mean(day):+.2f}%"
            )

    if missing_count:
        lines.append(f"\n另有 {missing_count} 条信号缺少 T+1 行情（停牌/数据未出），未纳入统计。")
    return "\n".join(lines)


def _load_analysis_signals(path: Path, cutoff: dt.date) -> list[SignalRecord]:
    bands = get_rules().analysis.status_bands
    records: list[SignalRecord] = []
    for row in _read_csv_rows(path):
        signal_date = _parse_date(row.get("date", ""))
        close = _to_float(row.get("close"))
        if signal_date is None or signal_date < cutoff or close <= 0:
            continue
        score = _to_float(row.get("score"))
        if score >= bands.strong:
            group = f"复盘 强候选(≥{bands.strong:g})"
        elif score >= bands.candidate:
            group = f"复盘 候选({bands.candidate:g}-{bands.strong:g})"
        else:
            group = f"复盘 低分(<{bands.candidate:g})"
        records.append(
            SignalRecord(
                date=row.get("date", ""),
                ts_code=row.get("ts_code", ""),
                name=row.get("name", ""),
                kind="analysis",
                group=group,
                close=close,
            )
        )
    return records


def _load_recommend_signals(path: Path, cutoff: dt.date) -> list[SignalRecord]:
    group_labels = {
        "low_price_group": "荐股 低价组",
        "mid_price_group": "荐股 中价组",
    }
    records: list[SignalRecord] = []
    for row in _read_csv_rows(path):
        signal_date = _parse_date(row.get("date", ""))
        close = _to_float(row.get("close"))
        if signal_date is None or signal_date < cutoff or close <= 0:
            continue
        group = group_labels.get(row.get("price_group", ""), "荐股 其他")
        records.append(
            SignalRecord(
                date=row.get("date", ""),
                ts_code=row.get("ts_code", ""),
                name=row.get("name", ""),
                kind="recommend",
                group=group,
                close=close,
            )
        )
    return records


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        logger.exception("Failed to read signals file %s", path)
        return []


def _resolve_next_trade_days(client, signal_dates: list[str]) -> dict[str, str]:
    if not signal_dates:
        return {}
    end_date = (dt.date.today() + dt.timedelta(days=1)).strftime("%Y%m%d")
    try:
        calendar_df = client.trade_cal(
            exchange="", start_date=min(signal_dates), end_date=end_date, fields="cal_date,is_open"
        )
    except Exception:
        logger.exception("Tushare trade_cal query failed")
        return {}
    if calendar_df is None or calendar_df.empty:
        return {}

    open_days = sorted(
        str(cal_date)
        for cal_date, is_open in zip(calendar_df["cal_date"], calendar_df["is_open"])
        if _to_float(is_open) == 1
    )
    mapping: dict[str, str] = {}
    for date_text in signal_dates:
        next_day = next((day for day in open_days if day > date_text), None)
        if next_day:
            mapping[date_text] = next_day
    return mapping


def _fetch_day_quotes(client, trade_date: str) -> dict[str, tuple[float, float]]:
    try:
        df = client.daily(trade_date=trade_date, fields="ts_code,open,close")
    except Exception:
        logger.exception("Tushare daily query failed for %s", trade_date)
        return {}
    if df is None or df.empty:
        return {}
    return {
        str(row["ts_code"]): (_to_float(row["open"]), _to_float(row["close"]))
        for _, row in df.iterrows()
    }


def _parse_date(value: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(value).strip(), "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def _win_rate_pct(values: list[float]) -> float:
    return sum(1 for value in values if value > 0) / len(values) * 100


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _to_float(value) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
