from __future__ import annotations

import pytest

from tradeeye.config import Settings
from tradeeye.services.notifier import build_payload, send_text


def _settings(*, debug: bool = False, webhook: str = "https://example.test/hook") -> Settings:
    return Settings(
        tushare_token="token",
        feishu_webhook=webhook,
        debug_mode=debug,
        my_stocks=["600000.SH"],
        allowed_exchanges=("SH",),
    )


def test_build_payload_keeps_title_and_content():
    assert build_payload("body", title="Title", icon="!") == {
        "msg_type": "text",
        "content": {"text": "! Title:\n\nbody"},
    }


def test_debug_notification_does_not_call_http(capsys):
    class UnexpectedClient:
        def post(self, *_args, **_kwargs):
            raise AssertionError("HTTP must not be called in debug mode")

    assert send_text("preview", _settings(debug=True), "Report", http_client=UnexpectedClient()) is True
    assert "preview" in capsys.readouterr().out


def test_missing_webhook_is_a_failure():
    assert send_text("body", _settings(webhook=""), "Report") is False


@pytest.mark.parametrize(
    ("raises", "payload", "expected"),
    [
        (False, {"code": 0, "msg": "success"}, True),
        (False, {"StatusCode": 0, "StatusMessage": "success"}, True),
        (False, {"code": 19002, "msg": "rejected"}, False),
        (True, {"code": 0}, False),
    ],
)
def test_http_result_is_reflected_in_return_code(raises, payload, expected):
    class Response:
        def raise_for_status(self):
            if raises:
                raise RuntimeError("bad response")

        def json(self):
            return payload

    class Client:
        def post(self, url, *, json, timeout):
            assert url == "https://example.test/hook"
            assert json["content"]["text"].endswith("body")
            assert timeout == 10
            return Response()

    assert send_text("body", _settings(), "Report", http_client=Client()) is expected


def test_non_json_success_response_is_a_failure():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("not json")

    class Client:
        def post(self, *_args, **_kwargs):
            return Response()

    assert send_text("body", _settings(), "Report", http_client=Client()) is False
