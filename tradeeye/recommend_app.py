from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable

from tradeeye.config import Settings, load_settings
from tradeeye.logging_utils import configure_logging
from tradeeye.services.analysis import get_dify_recommendation_analysis
from tradeeye.services.notifier import send_report
from tradeeye.strategies.stock_recommender import (
    build_recommendation_brief,
    recommendations_to_json,
    recommend_top_stocks,
)

logger = logging.getLogger(__name__)

Recommender = Callable[[Settings, int], dict[str, list[dict[str, Any]]]]
Analyzer = Callable[[str, Settings], str]
Notifier = Callable[[str, Settings], bool]


def build_recommendation_content(
    recommendations: dict[str, list[dict[str, Any]]],
    ai_analysis: str,
    report_date: dt.date | None = None,
) -> str:
    date_text = (report_date or dt.date.today()).strftime("%Y-%m-%d")
    brief = build_recommendation_brief(recommendations)
    return f"{date_text} 每日好股推荐\n\n{brief}\n\nDify 分析：\n{ai_analysis}"


def main(
    settings: Settings | None = None,
    recommender: Recommender = recommend_top_stocks,
    analyzer: Analyzer = get_dify_recommendation_analysis,
    notifier: Notifier = send_report,
    top_n: int = 5,
) -> int:
    settings = settings or load_settings()
    configure_logging(settings.debug_mode)

    recommendations = recommender(settings, top_n)
    if not _has_recommendations(recommendations):
        logger.warning("No recommendation candidates generated")
        content = build_recommendation_content(
            recommendations=recommendations,
            ai_analysis="今日未命中推荐条件。",
        )
        return 0 if notifier(content, settings) else 1

    recommendations_json = recommendations_to_json(recommendations)
    ai_analysis = analyzer(recommendations_json, settings)
    content = build_recommendation_content(recommendations, ai_analysis=ai_analysis)

    if not notifier(content, settings):
        logger.error("Recommendation workflow finished with notification failure")
        return 1
    return 0


def _has_recommendations(recommendations: dict[str, list[dict[str, Any]]]) -> bool:
    return bool(recommendations.get("low_price_group") or recommendations.get("mid_price_group"))
