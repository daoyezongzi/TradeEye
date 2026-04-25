import json

from tradeeye.config import Settings
from tradeeye.services.analysis import _run_dify_workflow, get_dify_analysis, get_dify_recommendation_analysis


class _DummyResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _DummyHttpClient:
    def __init__(self):
        self.last_request = None

    def post(self, url, headers, json, timeout):
        self.last_request = {
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
        }
        return _DummyResponse({"data": {"outputs": {"text": "workflow-ok"}}})


def make_settings() -> Settings:
    return Settings(
        tushare_token="token",
        dify_api_key="api",
        feishu_webhook="https://example.com",
        dify_base_url="https://api.dify.ai/v1",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


def test_get_dify_recommendation_analysis_sends_prefixed_query():
    settings = make_settings()
    http_client = _DummyHttpClient()
    raw_json = json.dumps(
        {
            "low_price_group": [{"ts_code": "600001.SH"}],
            "mid_price_group": [{"ts_code": "000001.SZ"}],
        },
        ensure_ascii=False,
    )

    result = get_dify_recommendation_analysis(
        recommendations_json=raw_json,
        settings=settings,
        input_key="daily_candidates",  # ignored for compatibility
        http_client=http_client,
    )

    assert result == "workflow-ok"
    assert http_client.last_request is not None
    query = http_client.last_request["json"]["inputs"]["query"]
    assert query.startswith("[REC]")
    parsed = json.loads(query[len("[REC]") :])
    assert set(parsed.keys()) == {"low_price_group", "mid_price_group"}


def test_get_dify_analysis_sends_prefixed_query():
    settings = make_settings()
    http_client = _DummyHttpClient()

    stock_data = {
        "name": "Alpha Corp",
        "trade_date": "20260425",
        "latest": {"close": 10.5, "pct_chg": 3.1, "ma5": 10.1, "ma10": 9.8, "ma20": 9.6, "high": 10.8, "low": 10.0},
        "prev": {"low": 9.9},
        "market_regime": {"up_ratio_pct": 55, "strong_ratio_pct": 8},
    }
    tech_result = {
        "status": "candidate",
        "score": 82,
        "close_strength": 0.85,
        "vol_ratio": 2.2,
        "turnover_rate": 8.1,
        "amount_ratio_5d": 1.6,
        "net_mf_ratio_pct": 3.2,
        "large_order_net_pct": 1.5,
        "up_limit_room_pct": 4.3,
        "breakout_pct": 1.1,
        "market_bias": "strong",
        "detail": "tail strong",
        "risk": "none",
        "action_plan": "observe",
    }

    result = get_dify_analysis(
        stock_data=stock_data,
        tech_result=tech_result,
        stock_code="600001.SH",
        settings=settings,
        http_client=http_client,
    )

    assert result == "workflow-ok"
    assert http_client.last_request is not None
    query = http_client.last_request["json"]["inputs"]["query"]
    assert query.startswith("[STK]")
    assert "600001.SH" in query


def test_run_dify_workflow_accepts_legacy_mapping_input():
    settings = make_settings()
    http_client = _DummyHttpClient()

    result = _run_dify_workflow(
        query={"stock_data": "legacy-content"},
        settings=settings,
        http_client=http_client,
        log_key="legacy",
    )

    assert result == "workflow-ok"
    assert http_client.last_request is not None
    assert http_client.last_request["json"]["inputs"]["query"] == "legacy-content"
