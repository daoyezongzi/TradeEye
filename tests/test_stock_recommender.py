from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import pytest

from tradeeye.config import Settings
from tradeeye.strategies.rules import EtfRules, RecommenderRules
from tradeeye.strategies.stock_recommender import (
    ETF_STATUS_AVAILABLE,
    ETF_STATUS_DISABLED,
    ETF_STATUS_EMPTY_WHITELIST,
    ETF_STATUS_UNAVAILABLE,
    build_etf_recommendation_brief,
    build_recommendation_brief,
    rank_market_candidates,
    recommendations_to_json,
    recommend_top_etfs,
)


def make_settings() -> Settings:
    return Settings(
        tushare_token="token",
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


def stock_row(code: str, *, close: float = 12.0, **overrides) -> dict:
    pre_close = close / 1.04
    row = {
        "ts_code": code,
        "name": f"Stock {code[:6]}",
        "industry": "Power",
        "trade_date": "20260822",
        "open": pre_close,
        "high": close * 1.01,
        "low": close * 0.95,
        "close": close,
        "pre_close": pre_close,
        "pct_chg": 4.0,
        "pct_chg_rank": 0.9,
        "turnover_rate": 8.0,
        "volume_ratio": 2.5,
        "amount": 500_000.0,
        "amount_pct_rank": 0.9,
        "net_mf_ratio_pct": 3.0,
        "large_order_net_pct": 2.0,
        "close_strength": 0.9,
        "upper_shadow_pct": 0.4,
        "total_mv": 3_000_000.0,
        "pe": 12.0,
        "pe_ttm": 10.0,
    }
    row.update(overrides)
    return row


def candidates(rows: list[dict], rules: RecommenderRules | None = None, **kwargs) -> list[dict]:
    result = rank_market_candidates(
        pd.DataFrame(rows),
        allowed_exchanges=("SH", "SZ"),
        trade_date="20260822",
        rules=rules,
        **kwargs,
    )
    return result["candidates"]


def test_rank_market_candidates_returns_one_pool_capped_at_five():
    rows = [stock_row(f"60000{index}.SH", close=12 + index * 4) for index in range(1, 8)]
    rows.extend(
        [
            stock_row("600101.SH", name="*ST Risk"),
            stock_row("600102.SH", name="退市风险"),
            stock_row("830001.BJ"),
        ]
    )

    result = rank_market_candidates(
        pd.DataFrame(rows),
        allowed_exchanges=("SH", "SZ"),
        recommender_industries=("Not Power",),
        top_n_each_group=99,
    )

    assert set(result) == {"strategy_version", "rules_fingerprint", "trade_date", "candidates", "message"}
    assert result["strategy_version"] == "recommend_v2"
    assert len(result["candidates"]) == 5
    assert any(item["close"] > 20 for item in result["candidates"])
    assert all(item["asset_type"] == "stock" for item in result["candidates"])
    assert "600101.SH" not in {item["ts_code"] for item in result["candidates"]}
    assert "600102.SH" not in {item["ts_code"] for item in result["candidates"]}
    assert all(not item["ts_code"].endswith(".BJ") for item in result["candidates"])


def test_three_positive_dimensions_are_capped_and_sum_to_quality_score():
    item = candidates([stock_row("600001.SH", close=10.0)])[0]

    assert 0 <= item["momentum_score"] <= 40
    assert 0 <= item["close_quality_score"] <= 35
    assert 0 <= item["volume_funds_score"] <= 25
    assert item["quality_score"] == pytest.approx(
        item["momentum_score"] + item["close_quality_score"] + item["volume_funds_score"],
        abs=0.01,
    )
    assert 0 <= item["quality_score"] <= 100
    assert item["total_score"] == item["quality_score"]
    assert item["strategy_version"] == "recommend_v2"
    assert item["planned_entry_price"] == pytest.approx(item["close"] * 0.98, abs=0.01)


def test_missing_optional_daily_basic_and_moneyflow_features_degrade_to_zero_points():
    row = stock_row(
        "600009.SH",
        pct_chg=6.0,
        pct_chg_rank=1.0,
        close_strength=0.95,
        upper_shadow_pct=0.2,
    )
    for optional_column in (
        "turnover_rate",
        "volume_ratio",
        "amount_pct_rank",
        "net_mf_ratio_pct",
        "large_order_net_pct",
    ):
        row.pop(optional_column)

    selected = candidates([row])

    assert len(selected) == 1
    assert selected[0]["quality_score"] >= 55
    assert 0 <= selected[0]["volume_funds_score"] <= 25


def test_invalid_or_missing_primary_ohlc_is_rejected():
    rows = [
        stock_row("600011.SH", high=None),
        stock_row("600012.SH", low=13.0, close=12.0),
        stock_row("600013.SH"),
    ]

    selected = candidates(rows, rules=replace(RecommenderRules(), minimum_quality_score=0))

    assert [item["ts_code"] for item in selected] == ["600013.SH"]


def test_risk_gate_hard_rejects_weak_close_long_shadow():
    rows = [
        stock_row("600001.SH", close_strength=0.44, upper_shadow_pct=2.51),
        stock_row("600002.SH", close_strength=0.45, upper_shadow_pct=2.5),
    ]

    selected = candidates(rows, rules=replace(RecommenderRules(), minimum_quality_score=0))

    assert [item["ts_code"] for item in selected] == ["600002.SH"]


def test_overheat_gate_rejects_two_flags_and_orders_one_flag_after_normal():
    rules = replace(RecommenderRules(), minimum_quality_score=0)
    rows = [
        stock_row(
            "600001.SH",
            pct_chg=2.0,
            pct_chg_rank=0.55,
            turnover_rate=2.0,
            volume_ratio=1.0,
            net_mf_ratio_pct=0.1,
            large_order_net_pct=0.1,
        ),
        stock_row("600002.SH", pct_chg=8.01),
        stock_row("600003.SH", pct_chg=8.01, turnover_rate=18.01),
        stock_row("600004.SH", pct_chg=8.01, turnover_rate=18.01, volume_ratio=4.01),
    ]

    selected = candidates(rows, rules=rules)

    assert [item["ts_code"] for item in selected] == ["600001.SH", "600002.SH"]
    assert selected[0]["risk_level"] == "normal"
    assert selected[1]["risk_level"] == "overheat_watch"
    assert selected[1]["risk_flags"] == ["pct_chg_hot"]


def test_configured_overheat_threshold_three_keeps_all_subthreshold_flags_in_watch_layer():
    base_rules = RecommenderRules()
    rules = replace(
        base_rules,
        minimum_quality_score=0,
        risk_gate=replace(base_rules.risk_gate, reject_overheat_count=3),
    )
    rows = [
        stock_row("600010.SH", pct_chg=2.0, turnover_rate=2.0, volume_ratio=1.0),
        stock_row("600011.SH", pct_chg=8.01),
        stock_row("600012.SH", pct_chg=8.01, turnover_rate=18.01),
        stock_row("600013.SH", pct_chg=8.01, turnover_rate=18.01, volume_ratio=4.01),
    ]

    result = rank_market_candidates(
        pd.DataFrame(rows),
        allowed_exchanges=("SH", "SZ"),
        trade_date="20260822",
        rules=rules,
    )
    selected = result["candidates"]

    assert selected[0]["ts_code"] == "600010.SH"
    watched = {item["ts_code"]: item for item in selected[1:]}
    assert set(watched) == {"600011.SH", "600012.SH"}
    assert all(item["risk_level"] == "overheat_watch" for item in watched.values())
    assert watched["600012.SH"]["risk_flags"] == ["pct_chg_hot", "turnover_hot"]
    assert "过热观察（涨幅过热、换手过热），排在普通候选后" in build_recommendation_brief(result)


def test_low_price_preference_changes_ranking_but_not_quality_score():
    rows = [
        stock_row("600001.SH", close=25.0),
        stock_row("600002.SH", close=15.0),
    ]

    selected = candidates(rows)

    assert [item["ts_code"] for item in selected] == ["600002.SH", "600001.SH"]
    assert selected[0]["quality_score"] == selected[1]["quality_score"]
    assert selected[0]["ranking_score"] == selected[0]["quality_score"] + 3
    assert selected[1]["ranking_score"] == selected[1]["quality_score"]


def test_optional_hard_price_bounds_and_configured_quality_gate():
    bounded = replace(RecommenderRules(), hard_min=10.0, hard_max=20.0, minimum_quality_score=0)
    rows = [
        stock_row("600001.SH", close=8.0),
        stock_row("600002.SH", close=15.0),
        stock_row("600003.SH", close=30.0),
    ]

    assert [item["ts_code"] for item in candidates(rows, rules=bounded)] == ["600002.SH"]

    too_strict = replace(RecommenderRules(), minimum_quality_score=100.0)
    assert candidates([stock_row("600010.SH")], rules=too_strict) == []


def test_valuation_and_industry_do_not_change_short_term_quality_score():
    rows = [
        stock_row("600001.SH", pe=3, pe_ttm=2, total_mv=999_999_999, industry="Power"),
        stock_row("600002.SH", pe=300, pe_ttm=250, total_mv=10, industry="Other"),
    ]

    selected = candidates(rows)

    assert selected[0]["quality_score"] == selected[1]["quality_score"]
    assert {item["industry"] for item in selected} == {"Power", "Other"}


def test_unknown_industry_is_normalized_and_json_emits_no_legacy_groups():
    result = rank_market_candidates(
        pd.DataFrame([stock_row("600001.SH", industry=None)]),
        allowed_exchanges=("SH",),
    )

    parsed = json.loads(recommendations_to_json(result))

    assert "low_price_group" not in parsed
    assert "mid_price_group" not in parsed
    assert parsed["candidates"][0]["industry"] == "未知"


def test_local_report_is_deterministic_and_contains_v2_plan():
    result = rank_market_candidates(
        pd.DataFrame([stock_row("600001.SH")]),
        allowed_exchanges=("SH",),
    )

    first = build_recommendation_brief(result)
    second = build_recommendation_brief(result)

    assert first == second
    assert "短线动能" in first
    assert "收盘质量" in first
    assert "量能资金" in first
    assert "D+1" in first
    assert "LLM" not in first


class CountingEtfClient:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.basic_calls = 0
        self.daily_calls = 0

    def etf_basic(self, **kwargs):
        self.basic_calls += 1
        if self.fail:
            raise PermissionError("no ETF permission")
        return pd.DataFrame(
            [
                {"ts_code": "510300.SH", "csname": "沪深300ETF", "fund_type": "股票型"},
                {"ts_code": "159915.SZ", "csname": "创业板ETF", "fund_type": "股票型"},
                {"ts_code": "513100.SH", "csname": "非白名单ETF", "fund_type": "QDII"},
            ]
        )

    def fund_daily(self, **kwargs):
        self.daily_calls += 1
        return pd.DataFrame(
            [
                {
                    "ts_code": "510300.SH",
                    "trade_date": "20260822",
                    "open": 4.0,
                    "high": 4.25,
                    "low": 3.98,
                    "close": 4.2,
                    "pre_close": 4.0,
                    "pct_chg": 5.0,
                    "amount": 600_000,
                },
                {
                    "ts_code": "513100.SH",
                    "trade_date": "20260822",
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.99,
                    "close": 1.09,
                    "pre_close": 1.0,
                    "pct_chg": 9.0,
                    "amount": 900_000,
                },
            ]
        )


def test_etf_disabled_and_empty_whitelist_make_zero_api_calls():
    client = CountingEtfClient()

    disabled = recommend_top_etfs(make_settings(), trade_date="20260822", pro_client=client)
    empty = recommend_top_etfs(
        make_settings(),
        trade_date="20260822",
        pro_client=client,
        rules=EtfRules(enabled=True, codes=()),
    )

    assert disabled["status"] == ETF_STATUS_DISABLED
    assert empty["status"] == ETF_STATUS_EMPTY_WHITELIST
    assert client.basic_calls == 0
    assert client.daily_calls == 0


def test_etf_whitelist_uses_independent_45_35_20_scoring():
    client = CountingEtfClient()
    rules = EtfRules(enabled=True, codes=("510300.SH", "159915.SZ"), minimum_quality_score=0)

    result = recommend_top_etfs(
        make_settings(),
        trade_date="20260822",
        pro_client=client,
        rules=rules,
    )

    assert result["status"] == ETF_STATUS_AVAILABLE
    assert result["strategy_version"] == "etf_recommend_v1"
    assert [item["ts_code"] for item in result["candidates"]] == ["510300.SH"]
    item = result["candidates"][0]
    assert 0 <= item["momentum_score"] <= 45
    assert 0 <= item["close_quality_score"] <= 35
    assert 0 <= item["liquidity_score"] <= 20
    assert item["quality_score"] == pytest.approx(
        item["momentum_score"] + item["close_quality_score"] + item["liquidity_score"],
        abs=0.01,
    )
    assert item["asset_type"] == "etf"
    assert client.basic_calls == 1
    assert client.daily_calls == 1
    assert "独立评分" in build_etf_recommendation_brief(result)


def test_etf_permission_failure_is_clear_isolated_downgrade():
    client = CountingEtfClient(fail=True)
    rules = EtfRules(enabled=True, codes=("510300.SH",))

    result = recommend_top_etfs(
        make_settings(),
        trade_date="20260822",
        pro_client=client,
        rules=rules,
    )

    assert result["status"] == ETF_STATUS_UNAVAILABLE
    assert result["candidates"] == []
    assert "股票荐股不受影响" in result["message"]
    assert "PermissionError" in result["message"]
