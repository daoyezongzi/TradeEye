from copy import deepcopy

from tradeeye.strategies.strategy import DIMENSION_CAPS, check_signals


def make_strong_payload():
    return {
        "name": "Momentum Corp",
        "market_regime": {"status": "偏强", "score": 20},
        "latest": {
            "ts_code": "000001.SZ",
            "close": 10.4,
            "open": 10.0,
            "pct_chg": 3.5,
            "turnover_rate": 6.0,
            "volume_ratio": 1.8,
            "amount_ratio_5d": 1.6,
            "net_mf_ratio_pct": 4.2,
            "large_order_net_pct": 2.6,
            "up_limit_room_pct": 5.3,
            "close_strength": 0.88,
            "upper_shadow_pct": 0.4,
            "breakout_10_pct": 0.8,
            "ma5": 10.1,
            "ma10": 9.9,
            "ma20": 9.6,
            "ma5_slope_pct": 0.6,
            "turnover_pct_rank": 0.82,
            "net_mf_ratio_rank": 0.87,
            "large_order_net_rank": 0.83,
            "list_age_days": 600,
            "market": "主板",
        },
        "prev": {"vol": 100, "low": 9.7},
    }


def make_weak_payload():
    return {
        "name": "*ST Risky",
        "market_regime": {"status": "偏弱", "score": -20},
        "latest": {
            "ts_code": "430001.BJ",
            "close": 9.5,
            "open": 10.1,
            "pct_chg": -2.8,
            "turnover_rate": 0.3,
            "volume_ratio": 0.4,
            "amount_ratio_5d": 0.6,
            "net_mf_ratio_pct": -3.5,
            "large_order_net_pct": -2.2,
            "up_limit_room_pct": 0.6,
            "close_strength": 0.2,
            "upper_shadow_pct": 3.2,
            "breakout_10_pct": -5.2,
            "ma5": 9.8,
            "ma10": 10.1,
            "ma20": 10.4,
            "ma5_slope_pct": -0.5,
            "turnover_pct_rank": 0.1,
            "net_mf_ratio_rank": 0.1,
            "large_order_net_rank": 0.1,
            "list_age_days": 30,
            "market": "北交所",
        },
        "prev": {"vol": 100, "low": 9.6},
    }


def test_check_signals_scores_five_capped_dimensions():
    result = check_signals(make_strong_payload())

    assert result["dimensions"] == DIMENSION_CAPS
    assert sum(result["dimensions"].values()) == result["raw_score"] == 100
    assert result["raw_band"] == "强"
    assert result["risk_level"] == "低风险"
    assert result["final_status"] == result["status"] == "强"
    assert "买入" not in result["action_plan"]


def test_check_signals_keeps_raw_score_when_hard_risk_overrides_status():
    result = check_signals(make_weak_payload())

    assert result["raw_score"] == 0
    assert result["raw_band"] == "弱"
    assert result["risk_level"] == "高风险"
    assert result["final_status"] == "高风险"
    assert set(result["dimensions"]) == set(DIMENSION_CAPS)
    assert "ST" in result["risk"]


def test_medium_risk_caps_strong_structure_at_watch():
    payload = deepcopy(make_strong_payload())
    payload["latest"]["list_age_days"] = 60

    result = check_signals(payload)

    assert result["raw_score"] == 100
    assert result["raw_band"] == "强"
    assert result["risk_level"] == "中风险"
    assert result["final_status"] == "观察"


def test_missing_key_data_is_not_scored():
    payload = deepcopy(make_strong_payload())
    del payload["latest"]["net_mf_ratio_pct"]

    result = check_signals(payload)

    assert result["score"] is None
    assert result["raw_score"] is None
    assert result["status"] == "数据不足"
    assert result["data_quality"] == "数据不足"
    assert "latest.net_mf_ratio_pct" in result["missing_fields"]
    assert all(value is None for value in result["dimensions"].values())


def test_degraded_upstream_source_is_not_scored_as_zero():
    payload = make_strong_payload()
    payload["degraded_sources"] = ["moneyflow"]

    result = check_signals(payload)

    assert result["raw_score"] is None
    assert result["status"] == "数据不足"
    assert "data_source.moneyflow" in result["missing_fields"]


def test_stock_specific_auxiliary_gap_is_not_treated_as_real_zero():
    payload = make_strong_payload()
    payload["latest"]["moneyflow_available"] = False

    result = check_signals(payload)

    assert result["raw_score"] is None
    assert "data_source.moneyflow.000001.SZ" in result["missing_fields"]


def test_check_signals_handles_missing_payload_without_pseudo_score():
    result = check_signals({})

    assert result["score"] is None
    assert result["status"] == "数据不足"
    assert result["missing_fields"] == ["latest"]
