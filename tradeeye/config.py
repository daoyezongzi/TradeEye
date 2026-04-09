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
)


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
        )


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """缓存配置，避免单次运行中重复读取环境变量。"""
    return Settings.from_env()
