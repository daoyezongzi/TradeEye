from tradeeye.strategies.strategy import check_signals


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


def test_check_signals_returns_high_score_for_strong_overnight_setup():
    result = check_signals(make_strong_payload())

    assert result["score"] == 100
    assert result["status"] == "【强候选】尾盘隔夜"
    assert result["vol_ratio"] == 1.8
    assert "尾盘承接较强" in result["detail"]


def test_check_signals_penalizes_weak_and_high_risk_setup():
    result = check_signals(make_weak_payload())

    assert result["score"] == 0
    assert result["status"] == "【回避】"
    assert "ST" in result["risk"]
    assert "放弃本次隔夜交易" in result["action_plan"]


def test_check_signals_handles_missing_payload():
    result = check_signals({})

    assert result["score"] == 0
    assert result["status"] == "【数据缺失】"
