from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from dotenv import load_dotenv

load_dotenv()

# 默认关注股票列表：当未配置 MY_STOCKS 或配置为空时使用。
DEFAULT_STOCKS = (
    "601880.SH",
    "600157.SH",
    "603010.SH",
    "002372.SZ",
    "600905.SH",
    "600009.SH",
    "600010.SH",
)
DEFAULT_ALLOWED_EXCHANGES = ("SH", "SZ", "BJ")

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
    """解析布尔型环境变量，支持常见真值/假值写法。"""
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def parse_stock_list(value: str | None, default: Iterable[str] = DEFAULT_STOCKS) -> list[str]:
    """解析股票代码列表，格式为 `000001.SZ,600000.SH`。"""
    if not value:
        return list(default)

    stocks = [item.strip() for item in value.split(",")]
    return [item for item in stocks if item] or list(default)


def parse_exchange_list(
    value: str | None,
    default: Iterable[str] = DEFAULT_ALLOWED_EXCHANGES,
) -> tuple[str, ...]:
    """解析交易所过滤配置，支持 `SH,SZ`、`沪深`、`北交所` 等写法。"""
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


def extract_exchange(code: str) -> str:
    """从股票代码提取交易所后缀，如 `600000.SH` -> `SH`。"""
    if not code or "." not in code:
        return ""
    return code.rsplit(".", maxsplit=1)[-1].upper()


def split_stocks_by_exchange(
    stocks: Iterable[str],
    allowed_exchanges: Iterable[str],
) -> tuple[list[str], list[str]]:
    """按允许的交易所拆分股票列表。"""
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
    """运行时配置。

    所有字段均从环境变量读取，便于本地 `.env` 和 CI secrets 共用同一套入口。
    """

    # Tushare 访问令牌，用于拉取股票基础信息和日线数据。
    tushare_token: str
    # Dify 工作流 API Key，用于生成 AI 复盘内容。
    dify_api_key: str
    # 飞书机器人 Webhook 地址，用于发送最终通知。
    feishu_webhook: str
    # Dify API 基础地址；私有化部署时可改为自建服务地址。
    dify_base_url: str
    # 调试模式：开启后打印报告并落盘调试 CSV，不发送飞书消息。
    debug_mode: bool
    # 需要分析的股票列表，支持逗号分隔配置多个标的。
    my_stocks: list[str]
    # 允许纳入分析和市场横向比较的交易所列表，如 SH/SZ/BJ。
    allowed_exchanges: tuple[str, ...]

    @property
    def dify_workflow_url(self) -> str:
        """根据基础地址拼出 Dify 工作流执行地址。"""
        return f"{self.dify_base_url.rstrip('/')}/workflows/run"

    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量构造配置对象。"""
        return cls(
            tushare_token=os.getenv("TUSHARE_TOKEN", "").strip(),
            dify_api_key=os.getenv("DIFY_API_KEY", "").strip(),
            feishu_webhook=os.getenv("FEISHU_WEBHOOK", "").strip(),
            dify_base_url=os.getenv("DIFY_BASE_URL", "https://api.dify.ai/v1").strip() or "https://api.dify.ai/v1",
            debug_mode=parse_bool(os.getenv("DEBUG_MODE"), default=False),
            my_stocks=parse_stock_list(os.getenv("MY_STOCKS")),
            allowed_exchanges=parse_exchange_list(os.getenv("ALLOWED_EXCHANGES")),
        )


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """缓存配置，避免单次运行中重复读取环境变量。"""
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
