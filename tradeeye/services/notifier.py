from __future__ import annotations

import logging

import requests

from tradeeye.config import Settings

logger = logging.getLogger(__name__)


def build_payload(
    content: str,
    title: str = "个股盘后复盘报告",
    icon: str = "\U0001f4ca",
) -> dict[str, object]:
    return {
        "msg_type": "text",
        "content": {"text": f"{icon} {title}:\n\n{content}"},
    }


def send_text(
    content: str,
    settings: Settings,
    title: str,
    icon: str = "\U0001f4ca",
    http_client=requests,
) -> bool:
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
            json=build_payload(content, title=title, icon=icon),
            timeout=10,
        )
        response.raise_for_status()
        _validate_feishu_response(response)
        return True
    except Exception:
        logger.exception("Feishu notification failed")
        return False


def send_report(content: str, settings: Settings, http_client=requests) -> bool:
    return send_text(
        content=content,
        settings=settings,
        title="个股盘后复盘报告",
        icon="\U0001f4ca",
        http_client=http_client,
    )


def _validate_feishu_response(response) -> None:
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("Feishu webhook returned a non-JSON response") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Feishu webhook returned an invalid response payload")

    code = payload.get("code", payload.get("StatusCode"))
    if code not in (0, "0"):
        message = payload.get("msg", payload.get("StatusMessage", "unknown error"))
        raise RuntimeError(f"Feishu webhook rejected the message: code={code}, message={message}")
