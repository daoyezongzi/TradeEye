from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Callable

from tradeeye.config import Settings, load_settings
from tradeeye.logging_utils import configure_logging
from tradeeye.services.notifier import send_text
from tradeeye.services.rss import NewsItem, collect_news

logger = logging.getLogger(__name__)

Collector = Callable[[Settings], list[NewsItem]]
Notifier = Callable[[str, Settings, str], bool]

_DEFAULT_TEMPLATE = "{date} 财经新闻简报\n\n共 {count} 条要闻：\n\n{items_block}"
_EMPTY_MESSAGE = "今日无符合条件的财经新闻。"


def build_news_content(
    news_items: list[NewsItem],
    settings: Settings,
    report_date: dt.date | None = None,
    template_text: str | None = None,
) -> str:
    date_text = (report_date or dt.date.today()).strftime("%Y-%m-%d")
    items_block = _build_items_block(news_items)
    template = template_text or _load_template_text(settings)

    try:
        return template.format(
            date=date_text,
            count=len(news_items),
            items_block=items_block,
        )
    except KeyError:
        logger.exception("Invalid NEWS_TEMPLATE_FILE placeholders, fallback to default template")
        return _DEFAULT_TEMPLATE.format(
            date=date_text,
            count=len(news_items),
            items_block=items_block,
        )


def main(
    settings: Settings | None = None,
    collector: Collector = collect_news,
    notifier: Notifier | None = None,
) -> int:
    settings = settings or load_settings()
    configure_logging(settings.debug_mode)

    news_items = collector(settings)
    if not news_items and not settings.news_push_when_empty:
        logger.info("No news matched filters and NEWS_PUSH_WHEN_EMPTY=false, skip sending")
        return 0

    content = build_news_content(news_items, settings=settings)
    title = f"{dt.date.today():%Y-%m-%d} 财经新闻简报"
    notifier = notifier or _send_news
    if not notifier(content, settings, title):
        logger.error("News workflow finished with notification failure")
        return 1
    return 0


def _send_news(content: str, settings: Settings, title: str) -> bool:
    return send_text(
        content=content,
        settings=settings,
        title=title,
        icon="\U0001f4f0",
    )


def _build_items_block(news_items: list[NewsItem]) -> str:
    if not news_items:
        return _EMPTY_MESSAGE

    lines: list[str] = []
    for index, item in enumerate(news_items, start=1):
        local_time = _as_china_time(item.published_at).strftime("%m-%d %H:%M")
        lines.append(f"{index}. [{item.source}] {local_time} {item.title}")
        if item.link:
            lines.append(f"   {item.link}")
    return "\n".join(lines)


def _load_template_text(settings: Settings) -> str:
    template_path = Path(settings.news_template_file)
    if not template_path.exists():
        logger.warning("Template file does not exist: %s", settings.news_template_file)
        return _DEFAULT_TEMPLATE

    text = template_path.read_text(encoding="utf-8").strip()
    return text or _DEFAULT_TEMPLATE


def _as_china_time(value: dt.datetime) -> dt.datetime:
    china_tz = dt.timezone(dt.timedelta(hours=8))
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(china_tz)
