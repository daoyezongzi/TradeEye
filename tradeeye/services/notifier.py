from __future__ import annotations

import logging

import requests

from tradeeye.config import Settings

logger = logging.getLogger(__name__)


def build_payload(content: str) -> dict[str, object]:
    return {
        "msg_type": "text",
        "content": {"text": f"\U0001f4ca \u4e2a\u80a1\u76d8\u540e\u590d\u76d8\u62a5\u544a:\n\n{content}"},
    }


def send_report(content: str, settings: Settings, http_client=requests) -> bool:
    if settings.debug_mode:
        print("\n" + "=" * 20 + " DEBUG REPORT " + "=" * 20)
        print(content)
        print("=" * 54 + "\n")
        return True

    if not settings.feishu_webhook:
        logger.error("Feishu notification skipped: missing FEISHU_WEBHOOK")
        return False

    try:
        response = http_client.post(
            settings.feishu_webhook,
            json=build_payload(content),
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.exception("Feishu notification failed")
        return False
