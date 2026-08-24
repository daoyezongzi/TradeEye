from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable, Mapping

from tradeeye.config import Settings, load_settings
from tradeeye.logging_utils import configure_logging
from tradeeye.services.notifier import send_report
from tradeeye.services.signal_store import append_etf_recommend_signals, append_recommend_signals
from tradeeye.time_utils import market_today
from tradeeye.strategies.stock_recommender import (
    ETF_STATUS_DISABLED,
    STOCK_CANDIDATES_KEY,
    build_etf_recommendation_brief,
    build_recommendation_brief,
    recommend_top_etfs,
    recommend_top_stocks,
)

logger = logging.getLogger(__name__)

Recommender = Callable[[Settings, int], Mapping[str, Any]]
EtfRecommender = Callable[..., Mapping[str, Any]]
Notifier = Callable[[str, Settings], bool]
SignalRecorder = Callable[[list[dict[str, Any]]], bool]


def build_recommendation_content(
    recommendations: Mapping[str, Any] | list[dict[str, Any]],
    report_date: dt.date | None = None,
    etf_recommendations: Mapping[str, Any] | None = None,
) -> str:
    """Build the deterministic local stock report plus an isolated ETF section."""
    date_text = (report_date or market_today()).strftime("%Y-%m-%d")
    sections = [build_recommendation_brief(recommendations)]
    if etf_recommendations is not None:
        etf_brief = build_etf_recommendation_brief(etf_recommendations)
        if etf_brief:
            sections.append(etf_brief)
    return f"{date_text} 每日好股推荐\n\n" + "\n\n".join(sections)


def main(
    settings: Settings | None = None,
    recommender: Recommender = recommend_top_stocks,
    notifier: Notifier = send_report,
    top_n: int = 5,
    signal_recorder: SignalRecorder = append_recommend_signals,
    etf_recommender: EtfRecommender = recommend_top_etfs,
    etf_signal_recorder: SignalRecorder = append_etf_recommend_signals,
) -> int:
    settings = settings or load_settings()
    configure_logging(settings.debug_mode)
    if not settings.tushare_token:
        logger.error("Recommendation workflow requires TUSHARE_TOKEN")
        return 1

    stock_result = recommender(settings, top_n)
    stock_candidates = _get_candidates(stock_result)
    trade_date = _get_trade_date(stock_result, stock_candidates)

    # ETF uses the same morning task, but its availability, ranking, report, and
    # persistence are isolated from the stock Top5 and stock signal stream.
    etf_result = etf_recommender(settings, trade_date=trade_date or None, top_n=None)
    etf_candidates = _get_candidates(etf_result)

    persistence_ok = True
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    stock_rows = _build_signal_rows(stock_result, generated_at=generated_at)
    if stock_rows and not signal_recorder(stock_rows):
        logger.error("Failed to persist stock recommendation signals")
        persistence_ok = False

    etf_rows = _build_etf_signal_rows(etf_result, generated_at=generated_at)
    if etf_rows and not etf_signal_recorder(etf_rows):
        logger.error("Failed to persist ETF recommendation signals")
        persistence_ok = False

    if not stock_candidates:
        logger.warning("No stock recommendation candidates generated")
    if str(etf_result.get("status", "")) not in (ETF_STATUS_DISABLED, "available"):
        logger.warning("ETF recommendation branch degraded: %s", etf_result.get("message", "unknown status"))
    elif str(etf_result.get("status", "")) == "available" and not etf_candidates:
        logger.info("ETF recommendation branch produced no candidates")

    content = build_recommendation_content(stock_result, etf_recommendations=etf_result)
    notification_ok = notifier(content, settings)
    if not notification_ok:
        logger.error("Recommendation workflow finished with notification failure")
    return 0 if persistence_ok and notification_ok else 1


def _get_candidates(result: Mapping[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return list(result)
    if STOCK_CANDIDATES_KEY in result:
        return list(result.get(STOCK_CANDIDATES_KEY, []))
    # Legacy inputs remain readable during the on-disk migration only.
    return list(result.get("low_price_group", [])) + list(result.get("mid_price_group", []))


def _get_trade_date(
    result: Mapping[str, Any] | list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str:
    value = result.get("trade_date") if isinstance(result, Mapping) else ""
    if value:
        return str(value)
    for item in candidates:
        if item.get("trade_date"):
            return str(item["trade_date"])
    return ""


def _build_signal_rows(
    recommendations: Mapping[str, Any] | list[dict[str, Any]],
    *,
    generated_at: str = "",
) -> list[dict[str, Any]]:
    result = recommendations if isinstance(recommendations, Mapping) else {}
    default_version = str(result.get("strategy_version") or "recommend_v2")
    default_fingerprint = str(result.get("rules_fingerprint") or "")
    rows: list[dict[str, Any]] = []
    for selection_rank, item in enumerate(_get_candidates(recommendations), start=1):
        trade_date = item.get("trade_date") or result.get("trade_date", "")
        rows.append(
            {
                "strategy_version": item.get("strategy_version", default_version),
                "generated_at": generated_at,
                "rules_fingerprint": item.get("rules_fingerprint", default_fingerprint),
                "trade_date": trade_date,
                "date": trade_date,
                "ts_code": item.get("ts_code", ""),
                "name": item.get("name", ""),
                "industry": item.get("industry") or "未知",
                "momentum_score": item.get("momentum_score", ""),
                "close_quality_score": item.get("close_quality_score", ""),
                "volume_funds_score": item.get("volume_funds_score", ""),
                "quality_score": item.get("quality_score", item.get("total_score", "")),
                "total_score": item.get("total_score", item.get("quality_score", "")),
                "risk_level": item.get("risk_level", "normal"),
                "risk_flags": "|".join(item.get("risk_flags", [])),
                "planned_entry_price": item.get("planned_entry_price", ""),
                "close": item.get("close", ""),
                "price_preference": "preferred" if item.get("price_preference_applied") else "none",
                "selection_rank": selection_rank,
                "price_group": "unified",
                "dimensions": "|".join(item.get("dimensions", [])),
            }
        )
    return rows


def _build_etf_signal_rows(
    recommendations: Mapping[str, Any],
    *,
    generated_at: str = "",
) -> list[dict[str, Any]]:
    default_version = str(recommendations.get("strategy_version") or "etf_recommend_v1")
    default_fingerprint = str(recommendations.get("rules_fingerprint") or "")
    rows: list[dict[str, Any]] = []
    for selection_rank, item in enumerate(_get_candidates(recommendations), start=1):
        trade_date = item.get("trade_date") or recommendations.get("trade_date", "")
        rows.append(
            {
                "strategy_version": item.get("strategy_version", default_version),
                "generated_at": generated_at,
                "rules_fingerprint": item.get("rules_fingerprint", default_fingerprint),
                "trade_date": trade_date,
                "date": trade_date,
                "ts_code": item.get("ts_code", ""),
                "name": item.get("name", ""),
                "fund_type": item.get("fund_type", "未知"),
                "momentum_score": item.get("momentum_score", ""),
                "close_quality_score": item.get("close_quality_score", ""),
                "liquidity_score": item.get("liquidity_score", ""),
                "quality_score": item.get("quality_score", item.get("total_score", "")),
                "risk_level": "independent_etf",
                "risk_flags": "",
                "planned_entry_price": item.get("planned_entry_price", ""),
                "close": item.get("close", ""),
                "price_preference": "not_applicable",
                "selection_rank": selection_rank,
                "dimensions": "|".join(item.get("dimensions", [])),
            }
        )
    return rows
