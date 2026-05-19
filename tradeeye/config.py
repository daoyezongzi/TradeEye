from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from dotenv import load_dotenv

load_dotenv()

DEFAULT_STOCKS = (
    "600370.SH",
    "600157.SH",
    "603010.SH",
    "002372.SZ",
    "600905.SH",
    "600009.SH",
    "600010.SH",
)
DEFAULT_ALLOWED_EXCHANGES = ("SH", "SZ", "BJ")
DEFAULT_RECOMMENDER_INDUSTRIES: tuple[str, ...] = ()
DEFAULT_NEWS_LOOKBACK_HOURS = 24
DEFAULT_NEWS_MAX_ITEMS = 15
DEFAULT_NEWS_PUSH_WHEN_EMPTY = False
DEFAULT_NEWS_FEEDS_FILE = "tradeeye/resources/news_feeds.txt"
DEFAULT_NEWS_TEMPLATE_FILE = "tradeeye/resources/news_template.txt"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"
DEFAULT_LLM_TIMEOUT_SEC = 60
PRICE_RANGES = {"low": [0, 10], "mid": [10, 20]}

EXCHANGE_ALIASES = {
    "SH": {"SH", "SSE", "沪", "沪市", "上海", "上交所", "上海证券交易所"},
    "SZ": {"SZ", "SZSE", "深", "深市", "深圳", "深交所", "深圳证券交易所"},
    "BJ": {"BJ", "BSE", "北", "北市", "北京", "北交所", "北京证券交易所"},
}
COMBINED_EXCHANGE_ALIASES = {
    "ALL": DEFAULT_ALLOWED_EXCHANGES,
    "ALL_MARKETS": DEFAULT_ALLOWED_EXCHANGES,
    "A股": DEFAULT_ALLOWED_EXCHANGES,
    "全市场": DEFAULT_ALLOWED_EXCHANGES,
    "全部": DEFAULT_ALLOWED_EXCHANGES,
    "沪深": ("SH", "SZ"),
    "沪深交易所": ("SH", "SZ"),
}


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def parse_stock_list(value: str | None, default: Iterable[str] = DEFAULT_STOCKS) -> list[str]:
    if not value:
        return list(default)

    stocks = [item.strip() for item in value.split(",")]
    return [item for item in stocks if item] or list(default)


def parse_csv_list(value: str | None, default: Iterable[str] = ()) -> tuple[str, ...]:
    if not value:
        return tuple(default)

    normalized_value = value.replace("，", ",")
    tokens = [item.strip() for item in normalized_value.split(",") if item.strip()]
    return tuple(dict.fromkeys(tokens)) or tuple(default)


def parse_int(value: str | None, default: int, minimum: int = 0) -> int:
    if value is None:
        return default

    try:
        parsed = int(value.strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def parse_exchange_list(
    value: str | None,
    default: Iterable[str] = DEFAULT_ALLOWED_EXCHANGES,
) -> tuple[str, ...]:
    if not value:
        return tuple(default)

    normalized_value = value.replace("，", ",").replace(" ", ",")
    tokens = [item.strip() for item in normalized_value.split(",") if item.strip()]
    exchanges: list[str] = []

    for token in tokens:
        for exchange in _expand_exchange_token(token):
            if exchange not in exchanges:
                exchanges.append(exchange)

    return tuple(exchanges or tuple(default))


def parse_industry_list(
    value: str | None,
    default: Iterable[str] = DEFAULT_RECOMMENDER_INDUSTRIES,
) -> tuple[str, ...]:
    if not value:
        return tuple(default)

    normalized_value = value.replace("，", ",")
    tokens = [item.strip() for item in normalized_value.split(",") if item.strip()]
    return tuple(dict.fromkeys(tokens)) or tuple(default)


def extract_exchange(code: str) -> str:
    if not code or "." not in code:
        return ""
    return code.rsplit(".", maxsplit=1)[-1].upper()


def split_stocks_by_exchange(
    stocks: Iterable[str],
    allowed_exchanges: Iterable[str],
) -> tuple[list[str], list[str]]:
    allowed_set = {exchange.upper() for exchange in allowed_exchanges}
    included: list[str] = []
    excluded: list[str] = []

    for stock in stocks:
        if extract_exchange(stock) in allowed_set:
            included.append(stock)
        else:
            excluded.append(stock)

    return included, excluded


@dataclass(frozen=True)
class Settings:
    tushare_token: str
    feishu_webhook: str
    debug_mode: bool
    my_stocks: list[str]
    allowed_exchanges: tuple[str, ...]
    recommender_industries: tuple[str, ...] = DEFAULT_RECOMMENDER_INDUSTRIES
    news_rss_feeds: tuple[str, ...] = ()
    news_rss_feeds_file: str = DEFAULT_NEWS_FEEDS_FILE
    news_lookback_hours: int = DEFAULT_NEWS_LOOKBACK_HOURS
    news_max_items: int = DEFAULT_NEWS_MAX_ITEMS
    news_include_keywords: tuple[str, ...] = ()
    news_exclude_keywords: tuple[str, ...] = ()
    news_push_when_empty: bool = DEFAULT_NEWS_PUSH_WHEN_EMPTY
    news_template_file: str = DEFAULT_NEWS_TEMPLATE_FILE
    llm_api_key: str = ""
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_timeout_sec: int = DEFAULT_LLM_TIMEOUT_SEC

    @property
    def llm_chat_completions_url(self) -> str:
        return f"{self.llm_base_url.rstrip('/')}/chat/completions"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            tushare_token=os.getenv("TUSHARE_TOKEN", "").strip(),
            feishu_webhook=os.getenv("FEISHU_WEBHOOK", "").strip(),
            debug_mode=parse_bool(os.getenv("DEBUG_MODE"), default=False),
            my_stocks=parse_stock_list(os.getenv("MY_STOCKS")),
            allowed_exchanges=parse_exchange_list(os.getenv("ALLOWED_EXCHANGES")),
            recommender_industries=parse_industry_list(os.getenv("RECOMMENDER_INDUSTRIES")),
            news_rss_feeds=parse_csv_list(os.getenv("NEWS_RSS_FEEDS")),
            news_rss_feeds_file=(
                os.getenv("NEWS_RSS_FEEDS_FILE", DEFAULT_NEWS_FEEDS_FILE).strip() or DEFAULT_NEWS_FEEDS_FILE
            ),
            news_lookback_hours=parse_int(
                os.getenv("NEWS_LOOKBACK_HOURS"),
                default=DEFAULT_NEWS_LOOKBACK_HOURS,
                minimum=1,
            ),
            news_max_items=parse_int(
                os.getenv("NEWS_MAX_ITEMS"),
                default=DEFAULT_NEWS_MAX_ITEMS,
                minimum=1,
            ),
            news_include_keywords=parse_csv_list(os.getenv("NEWS_INCLUDE_KEYWORDS")),
            news_exclude_keywords=parse_csv_list(os.getenv("NEWS_EXCLUDE_KEYWORDS")),
            news_push_when_empty=parse_bool(
                os.getenv("NEWS_PUSH_WHEN_EMPTY"),
                default=DEFAULT_NEWS_PUSH_WHEN_EMPTY,
            ),
            news_template_file=(
                os.getenv("NEWS_TEMPLATE_FILE", DEFAULT_NEWS_TEMPLATE_FILE).strip() or DEFAULT_NEWS_TEMPLATE_FILE
            ),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_base_url=(os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL).strip() or DEFAULT_LLM_BASE_URL),
            llm_model=(os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL),
            llm_timeout_sec=parse_int(
                os.getenv("LLM_TIMEOUT_SEC"),
                default=DEFAULT_LLM_TIMEOUT_SEC,
                minimum=1,
            ),
        )


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    return Settings.from_env()


def _expand_exchange_token(token: str) -> tuple[str, ...]:
    raw_token = token.strip()
    upper_token = raw_token.upper()

    if upper_token in COMBINED_EXCHANGE_ALIASES:
        return tuple(COMBINED_EXCHANGE_ALIASES[upper_token])
    if raw_token in COMBINED_EXCHANGE_ALIASES:
        return tuple(COMBINED_EXCHANGE_ALIASES[raw_token])

    for exchange, aliases in EXCHANGE_ALIASES.items():
        if upper_token in aliases or raw_token in aliases:
            return (exchange,)

    return ()
