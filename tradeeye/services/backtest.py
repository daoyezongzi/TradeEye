from __future__ import annotations

import collections
import datetime as dt
import json
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path

from tradeeye.config import Settings
from tradeeye.services.data import build_pro_client
from tradeeye.services.portfolio import (
    CLOSED,
    ENTRY_UNAVAILABLE,
    EXIT_DEFERRED,
    INVALID_SIGNAL,
    OPEN,
    RECOMMEND_NAV_FILE,
    RECOMMEND_TRADES_FILE,
    SKIPPED_CAPACITY,
    SKIPPED_DAILY_LIMIT,
    SKIPPED_DUPLICATE,
    TradeRecord,
    read_nav_rows,
    read_trade_records,
)
from tradeeye.services.signal_store import (
    ANALYSIS_SIGNALS_FILE,
    RECOMMEND_SIGNALS_FILE,
    read_recommend_signals,
)

logger = logging.getLogger(__name__)
MIN_SAMPLE_SIZE = 5


@dataclass(frozen=True)
class SignalRecord:
    date: str
    ts_code: str
    name: str
    kind: str
    group: str
    close: float
    signal_id: str = ""
    strategy_version: str = ""
    industry: str = "未知"


@dataclass(frozen=True)
class SignalResult:
    """Compatibility type for callers of the retired T+1 diagnostic helper."""

    record: SignalRecord
    overnight_return_pct: float
    day_return_pct: float


@dataclass(frozen=True)
class SignalLayerMetrics:
    recommendations: int
    entry_unavailable: int
    trigger_denominator: int
    triggers: int
    trigger_rate_pct: float
    settled: int
    open_count: int
    wins: int
    win_rate_pct: float
    mean_net_return_pct: float | None
    median_net_return_pct: float | None
    average_win_pct: float | None
    average_loss_pct: float | None
    profit_loss_ratio: float | None
    max_single_loss_pct: float | None
    exit_reasons: dict[str, int]


@dataclass(frozen=True)
class PortfolioLayerMetrics:
    selected: int
    settled: int
    realized_contribution: float
    average_slot_utilization_pct: float
    open_positions: int
    deferred_positions: int
    skipped_daily_limit: int
    skipped_capacity: int
    skipped_duplicate: int
    max_industry: str
    max_industry_weight_pct: float
    unknown_industry_positions: int
    industry_weights: dict[str, float]


@dataclass(frozen=True)
class BacktestWindow:
    label: str
    start_date: str
    end_date: str
    signal: SignalLayerMetrics
    portfolio: PortfolioLayerMetrics


def load_backtest_data(
    trade_path: str | Path = RECOMMEND_TRADES_FILE,
    nav_path: str | Path = RECOMMEND_NAV_FILE,
) -> tuple[list[TradeRecord], list[dict[str, str]]]:
    return read_trade_records(trade_path), read_nav_rows(nav_path)


def build_backtest_windows(
    records: list[TradeRecord],
    nav_rows: list[dict[str, str]],
    *,
    lookback_days: int = 45,
    today: dt.date | None = None,
) -> dict[str, tuple[BacktestWindow, BacktestWindow]]:
    report_date = today or dt.date.today()
    end_text = report_date.strftime("%Y%m%d")
    week_start = report_date - dt.timedelta(days=report_date.weekday())
    rolling_start = report_date - dt.timedelta(days=max(lookback_days - 1, 0))
    versions = sorted({record.strategy_version for record in records})
    windows: dict[str, tuple[BacktestWindow, BacktestWindow]] = {}
    for version in versions:
        version_records = [record for record in records if record.strategy_version == version]
        version_nav = [row for row in nav_rows if row.get("strategy_version") == version]
        windows[version] = (
            _calculate_window(
                "本周",
                week_start.strftime("%Y%m%d"),
                end_text,
                version_records,
                version_nav,
            ),
            _calculate_window(
                f"滚动 {lookback_days} 日",
                rolling_start.strftime("%Y%m%d"),
                end_text,
                version_records,
                version_nav,
            ),
        )
    return windows


def build_backtest_report(
    results: list[TradeRecord] | list[SignalResult],
    missing_count: int | None = None,
    lookback_days: int = 45,
    *,
    nav_rows: list[dict[str, str]] | None = None,
    today: dt.date | None = None,
) -> str:
    """Build the recommend-only two-layer report.

    Passing ``missing_count`` keeps the old T+1 text formatter available for
    external callers, but the application entrypoint no longer uses that path.
    """
    if missing_count is not None:
        return _build_legacy_report(results, missing_count, lookback_days)  # type: ignore[arg-type]

    records = [item for item in results if isinstance(item, TradeRecord)]
    if not records:
        return "暂无荐股交易账本；开放交易不计入胜率，等待每日结算积累样本。"
    windows = build_backtest_windows(
        records,
        nav_rows or [],
        lookback_days=lookback_days,
        today=today,
    )
    lines = ["荐股交易周报（仅 recommend；扣除退出成本 0.15 个百分点）"]
    for version, version_windows in windows.items():
        lines.append(f"\n策略版本：{version}")
        for window in version_windows:
            lines.extend(_format_window(window))
    return "\n".join(lines)


def load_signals(
    analysis_path: str | Path = ANALYSIS_SIGNALS_FILE,
    recommend_path: str | Path = RECOMMEND_SIGNALS_FILE,
    lookback_days: int = 45,
    today: dt.date | None = None,
) -> list[SignalRecord]:
    """Compatibility loader, now deliberately restricted to recommend signals."""
    del analysis_path
    cutoff = (today or dt.date.today()) - dt.timedelta(days=lookback_days)
    records: list[SignalRecord] = []
    for row in read_recommend_signals(recommend_path):
        signal_date = _parse_date(row.get("date", ""))
        close = _to_float(row.get("close"))
        if signal_date is None or signal_date < cutoff or close <= 0:
            continue
        records.append(
            SignalRecord(
                date=row.get("date", ""),
                ts_code=row.get("ts_code", ""),
                name=row.get("name", ""),
                kind="recommend",
                group="荐股",
                close=close,
                signal_id=row.get("signal_id", ""),
                strategy_version=row.get("strategy_version", ""),
                industry=row.get("industry", "").strip() or "未知",
            )
        )
    return records


def evaluate_signals(
    records: list[SignalRecord],
    settings: Settings,
    pro_client=None,
) -> tuple[list[SignalResult], int]:
    """Legacy, read-only T+1 diagnostic helper; not used by the trading report."""
    if not records:
        return [], 0
    client = pro_client or build_pro_client(settings)
    signal_dates = sorted({record.date for record in records})
    next_day_map = _resolve_next_trade_days(client, signal_dates)
    quotes = {
        day: _fetch_day_quotes(client, day)
        for day in sorted(set(next_day_map.values()))
    }
    evaluated: list[SignalResult] = []
    missing = 0
    for record in records:
        next_day = next_day_map.get(record.date)
        quote = quotes.get(next_day, {}).get(record.ts_code) if next_day else None
        if not quote or record.close <= 0:
            missing += 1
            continue
        next_open, next_close = quote
        evaluated.append(
            SignalResult(
                record=record,
                overnight_return_pct=(next_open / record.close - 1.0) * 100.0,
                day_return_pct=(next_close / record.close - 1.0) * 100.0,
            )
        )
    return evaluated, missing


def _calculate_window(
    label: str,
    start_date: str,
    end_date: str,
    records: list[TradeRecord],
    nav_rows: list[dict[str, str]],
) -> BacktestWindow:
    cohort = [record for record in records if start_date <= record.signal_date <= end_date]
    unavailable = [record for record in cohort if record.status == ENTRY_UNAVAILABLE]
    invalid = [record for record in cohort if record.status == INVALID_SIGNAL]
    triggered = [record for record in cohort if record.entry_date and record.entry_date <= end_date]
    settled = [
        record
        for record in records
        if record.status == CLOSED and start_date <= record.actual_exit_date <= end_date
    ]
    open_records = [
        record
        for record in records
        if record.entry_date <= end_date and (not record.actual_exit_date or record.actual_exit_date > end_date)
        and bool(record.entry_date)
    ]
    denominator = max(len(cohort) - len(unavailable) - len(invalid), 0)
    returns = [record.net_return_pct for record in settled]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    signal_metrics = SignalLayerMetrics(
        recommendations=len(cohort),
        entry_unavailable=len(unavailable),
        trigger_denominator=denominator,
        triggers=len(triggered),
        trigger_rate_pct=_rate(len(triggered), denominator),
        settled=len(settled),
        open_count=len(open_records),
        wins=len(wins),
        win_rate_pct=_rate(len(wins), len(settled)),
        mean_net_return_pct=statistics.fmean(returns) if returns else None,
        median_net_return_pct=statistics.median(returns) if returns else None,
        average_win_pct=statistics.fmean(wins) if wins else None,
        average_loss_pct=statistics.fmean(losses) if losses else None,
        profit_loss_ratio=(
            statistics.fmean(wins) / abs(statistics.fmean(losses))
            if wins and losses and statistics.fmean(losses) != 0
            else None
        ),
        max_single_loss_pct=min(losses) if losses else None,
        exit_reasons=dict(sorted(collections.Counter(record.exit_reason for record in settled).items())),
    )

    selected = [record for record in cohort if record.slot_id > 0 and record.entry_date <= end_date]
    selected_settled = [
        record
        for record in records
        if record.slot_id > 0
        and record.status == CLOSED
        and start_date <= record.actual_exit_date <= end_date
    ]
    selected_open = [
        record
        for record in records
        if record.slot_id > 0
        and record.entry_date <= end_date
        and (not record.actual_exit_date or record.actual_exit_date > end_date)
    ]
    window_nav = [row for row in nav_rows if start_date <= row.get("trade_date", "") <= end_date]
    latest_nav_candidates = [row for row in nav_rows if row.get("trade_date", "") <= end_date]
    latest_nav = max(latest_nav_candidates, key=lambda row: row.get("trade_date", ""), default={})
    industry_weights = _parse_industry_weights(latest_nav.get("industry_weights", ""))
    portfolio_metrics = PortfolioLayerMetrics(
        selected=len(selected),
        settled=len(selected_settled),
        realized_contribution=sum(
            record.realized_value - record.allocated_capital for record in selected_settled
        ),
        average_slot_utilization_pct=(
            statistics.fmean(_to_float(row.get("slot_utilization_pct")) for row in window_nav)
            if window_nav
            else 0.0
        ),
        open_positions=len(selected_open),
        deferred_positions=sum(1 for record in selected_open if record.status == EXIT_DEFERRED),
        skipped_daily_limit=sum(1 for record in cohort if record.portfolio_status == SKIPPED_DAILY_LIMIT),
        skipped_capacity=sum(1 for record in cohort if record.portfolio_status == SKIPPED_CAPACITY),
        skipped_duplicate=sum(1 for record in cohort if record.portfolio_status == SKIPPED_DUPLICATE),
        max_industry=latest_nav.get("max_industry", ""),
        max_industry_weight_pct=_to_float(latest_nav.get("max_industry_weight_pct")),
        unknown_industry_positions=_to_int(latest_nav.get("unknown_industry_positions")),
        industry_weights=industry_weights,
    )
    return BacktestWindow(label, start_date, end_date, signal_metrics, portfolio_metrics)


def _format_window(window: BacktestWindow) -> list[str]:
    signal = window.signal
    portfolio = window.portfolio
    exit_reasons = "、".join(f"{reason} {count}" for reason, count in signal.exit_reasons.items()) or "无"
    industry_text = "、".join(
        f"{industry} {weight:.1f}%" for industry, weight in portfolio.industry_weights.items()
    ) or "无持仓"
    return [
        f"\n【{window.label} {window.start_date}-{window.end_date}】",
        (
            f"- 信号层：推荐 {signal.recommendations} | entry_unavailable {signal.entry_unavailable} "
            f"| 触发 {signal.triggers}/{signal.trigger_denominator} ({signal.trigger_rate_pct:.1f}%) "
            f"| 已结算 {signal.settled} | open/延迟中 {signal.open_count}"
        ),
        (
            f"- 扣费结果：胜率 {signal.win_rate_pct:.1f}% | 平均 {_fmt_pct(signal.mean_net_return_pct)} "
            f"| 中位 {_fmt_pct(signal.median_net_return_pct)} | 平均盈利 {_fmt_pct(signal.average_win_pct)} "
            f"| 平均亏损 {_fmt_pct(signal.average_loss_pct)} | 盈亏比 {_fmt_ratio(signal.profit_loss_ratio)} "
            f"| 最大单笔亏损 {_fmt_pct(signal.max_single_loss_pct)}"
        ),
        f"- 退出原因：{exit_reasons}",
        (
            f"- 组合层：纳入 {portfolio.selected} | 已结算 {portfolio.settled} "
            f"| 已实现净值贡献 {portfolio.realized_contribution:+.4f} "
            f"| 平均槽位使用率 {portfolio.average_slot_utilization_pct:.1f}% "
            f"| 期末 open {portfolio.open_positions}（exit_deferred {portfolio.deferred_positions}）"
        ),
        (
            f"- 容量跳过：每日上限 {portfolio.skipped_daily_limit} | 满仓 {portfolio.skipped_capacity} "
            f"| 同股重复 {portfolio.skipped_duplicate}"
        ),
        (
            f"- 行业集中度（仅展示）：{industry_text} | 最大行业 "
            f"{portfolio.max_industry or '无'} {portfolio.max_industry_weight_pct:.1f}% "
            f"| 未知行业 {portfolio.unknown_industry_positions}"
        ),
    ]


def _build_legacy_report(
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
            overnight = [item.overnight_return_pct for item in group_results]
            day = [item.day_return_pct for item in group_results]
            suffix = "（样本不足，仅供参考）" if len(group_results) < MIN_SAMPLE_SIZE else ""
            lines.append(
                f"\n【{group_name}】样本 {len(group_results)} 条{suffix}\n"
                f"- 隔夜(收盘→次日开盘)：胜率 {_rate(sum(value > 0 for value in overnight), len(overnight)):.0f}% "
                f"| 平均 {statistics.fmean(overnight):+.2f}%\n"
                f"- T+1 全天(收盘→次日收盘)：胜率 {_rate(sum(value > 0 for value in day), len(day)):.0f}% "
                f"| 平均 {statistics.fmean(day):+.2f}%"
            )
    if missing_count:
        lines.append(f"\n另有 {missing_count} 条信号缺少 T+1 行情（停牌/数据未出），未纳入统计。")
    return "\n".join(lines)


def _resolve_next_trade_days(client, signal_dates: list[str]) -> dict[str, str]:
    if not signal_dates:
        return {}
    end_date = (dt.date.today() + dt.timedelta(days=1)).strftime("%Y%m%d")
    try:
        calendar = client.trade_cal(
            exchange="", start_date=min(signal_dates), end_date=end_date, fields="cal_date,is_open"
        )
    except Exception:
        logger.exception("Tushare trade_cal query failed")
        return {}
    if calendar is None or calendar.empty:
        return {}
    open_days = sorted(
        str(cal_date)
        for cal_date, is_open in zip(calendar["cal_date"], calendar["is_open"])
        if _to_float(is_open) == 1
    )
    return {
        date_text: next((day for day in open_days if day > date_text), "")
        for date_text in signal_dates
    }


def _fetch_day_quotes(client, trade_date: str) -> dict[str, tuple[float, float]]:
    try:
        frame = client.daily(trade_date=trade_date, fields="ts_code,open,close")
    except Exception:
        logger.exception("Tushare daily query failed for %s", trade_date)
        return {}
    if frame is None or frame.empty:
        return {}
    return {
        str(row["ts_code"]): (_to_float(row["open"]), _to_float(row["close"]))
        for _, row in frame.iterrows()
        if _to_float(row["open"]) > 0 and _to_float(row["close"]) > 0
    }


def _parse_industry_weights(value: str) -> dict[str, float]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): _to_float(weight) for key, weight in parsed.items()}


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def _fmt_ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator * 100.0 if denominator else 0.0


def _parse_date(value: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(value).strip(), "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


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
