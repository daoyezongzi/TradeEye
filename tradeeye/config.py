from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from dotenv import load_dotenv

load_dotenv()

DEFAULT_STOCKS = (
    "601880.SH",
    "600157.SH",
    "603010.SH",
    "002372.SZ",
    "600905.SH",
    "600009.SH",
)


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


@dataclass(frozen=True)
class Settings:
    tushare_token: str
    dify_api_key: str
    feishu_webhook: str
    dify_base_url: str
    debug_mode: bool
    my_stocks: list[str]

    @property
    def dify_workflow_url(self) -> str:
        return f"{self.dify_base_url.rstrip('/')}/workflows/run"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            tushare_token=os.getenv("TUSHARE_TOKEN", "").strip(),
            dify_api_key=os.getenv("DIFY_API_KEY", "").strip(),
            feishu_webhook=os.getenv("FEISHU_WEBHOOK", "").strip(),
            dify_base_url=os.getenv("DIFY_BASE_URL", "https://api.dify.ai/v1").strip() or "https://api.dify.ai/v1",
            debug_mode=parse_bool(os.getenv("DEBUG_MODE"), default=False),
            my_stocks=parse_stock_list(os.getenv("MY_STOCKS")),
        )


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    return Settings.from_env()
