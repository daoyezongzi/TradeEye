from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
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
DEFAULT_NEWS_LOOKBACK_HOURS = 24
DEFAULT_NEWS_MAX_ITEMS = 15
DEFAULT_NEWS_PUSH_WHEN_EMPTY = False
PROJECT_ROOT = Path(__file__).resolve().parent.parent
NEWS_RESOURCES_DIR = PROJECT_ROOT / "tradeeye" / "resources"
STRATEGIES_DIR = PROJECT_ROOT / "tradeeye" / "strategies"
DEFAULT_NEWS_FEEDS_FILE = "tradeeye/resources/news_feeds.txt"
DEFAULT_NEWS_TEMPLATE_FILE = "tradeeye/resources/news_template.txt"
DEFAULT_NEWS_RSS_ALLOWED_HOSTS = (
    "in-en.com",
    "www.in-en.com",
    "chinanews.com.cn",
    "www.chinanews.com.cn",
)
DEFAULT_BACKTEST_LOOKBACK_DAYS = 45
STOCK_CODE_PATTERN = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")

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

    normalized_value = value.replace("，", ",")
    stocks = [item.strip().upper() for item in normalized_value.split(",") if item.strip()]
    invalid = [stock for stock in stocks if not STOCK_CODE_PATTERN.fullmatch(stock)]
    if invalid:
        raise ValueError(f"MY_STOCKS contains invalid stock codes: {', '.join(invalid)}")
    if not stocks:
        raise ValueError("MY_STOCKS must contain at least one valid stock code")
    return list(dict.fromkeys(stocks))


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


def resolve_repo_path(value: str | Path, allowed_dir: str | Path, setting_name: str) -> Path:
    """Resolve a configuration-controlled file and keep it under ``allowed_dir``.

    Relative paths are interpreted from the repository root rather than the
    process working directory. ``Path.resolve`` also follows existing
    symlinks, so a link from an allowed directory to an external file is not
    accepted.
    """
    raw_value = str(value).strip()
    if not raw_value:
        raise ValueError(f"{setting_name} must not be empty")

    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate

    try:
        resolved = candidate.resolve(strict=False)
        allowed = Path(allowed_dir).resolve(strict=True)
        resolved.relative_to(allowed)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"{setting_name} must point to a file inside {allowed_dir}"
        ) from exc

    if resolved == allowed:
        raise ValueError(f"{setting_name} must point to a file inside {allowed_dir}")
    return resolved


def parse_exchange_list(
    value: str | None,
    default: Iterable[str] = DEFAULT_ALLOWED_EXCHANGES,
) -> tuple[str, ...]:
    if not value:
        return tuple(default)

    normalized_value = value.replace("，", ",").replace(" ", ",")
    tokens = [item.strip() for item in normalized_value.split(",") if item.strip()]
    exchanges: list[str] = []
    invalid_tokens: list[str] = []

    for token in tokens:
        expanded = _expand_exchange_token(token)
        if not expanded:
            invalid_tokens.append(token)
            continue
        for exchange in expanded:
            if exchange not in exchanges:
                exchanges.append(exchange)

    if invalid_tokens:
        raise ValueError(f"ALLOWED_EXCHANGES contains invalid values: {', '.join(invalid_tokens)}")
    if not exchanges:
        raise ValueError("ALLOWED_EXCHANGES must contain at least one supported exchange")
    return tuple(exchanges)


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
    news_rss_feeds: tuple[str, ...] = ()
    news_rss_feeds_file: str = DEFAULT_NEWS_FEEDS_FILE
    news_lookback_hours: int = DEFAULT_NEWS_LOOKBACK_HOURS
    news_max_items: int = DEFAULT_NEWS_MAX_ITEMS
    news_include_keywords: tuple[str, ...] = ()
    news_exclude_keywords: tuple[str, ...] = ()
    news_push_when_empty: bool = DEFAULT_NEWS_PUSH_WHEN_EMPTY
    news_template_file: str = DEFAULT_NEWS_TEMPLATE_FILE
    backtest_lookback_days: int = DEFAULT_BACKTEST_LOOKBACK_DAYS
    news_rss_allowed_hosts: tuple[str, ...] = DEFAULT_NEWS_RSS_ALLOWED_HOSTS

    def __post_init__(self) -> None:
        invalid_stocks = [
            stock for stock in self.my_stocks if not STOCK_CODE_PATTERN.fullmatch(str(stock).upper())
        ]
        if invalid_stocks:
            raise ValueError(f"Invalid stock codes: {', '.join(invalid_stocks)}")

        invalid_exchanges = [
            exchange for exchange in self.allowed_exchanges if exchange.upper() not in DEFAULT_ALLOWED_EXCHANGES
        ]
        if invalid_exchanges or not self.allowed_exchanges:
            details = ", ".join(invalid_exchanges) or "empty list"
            raise ValueError(f"Invalid allowed exchanges: {details}")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            tushare_token=os.getenv("TUSHARE_TOKEN", "").strip(),
            feishu_webhook=os.getenv("FEISHU_WEBHOOK", "").strip(),
            debug_mode=parse_bool(os.getenv("DEBUG_MODE"), default=False),
            my_stocks=parse_stock_list(os.getenv("MY_STOCKS")),
            allowed_exchanges=parse_exchange_list(os.getenv("ALLOWED_EXCHANGES")),
            news_rss_feeds=parse_csv_list(os.getenv("NEWS_RSS_FEEDS")),
            news_rss_feeds_file=(
                os.getenv("NEWS_RSS_FEEDS_FILE", DEFAULT_NEWS_FEEDS_FILE).strip() or DEFAULT_NEWS_FEEDS_FILE
            ),
            news_rss_allowed_hosts=parse_csv_list(
                os.getenv("NEWS_RSS_ALLOWED_HOSTS"),
                default=DEFAULT_NEWS_RSS_ALLOWED_HOSTS,
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
            backtest_lookback_days=parse_int(
                os.getenv("BACKTEST_LOOKBACK_DAYS"),
                default=DEFAULT_BACKTEST_LOOKBACK_DAYS,
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
