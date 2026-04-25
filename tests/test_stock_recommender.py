import json

import pandas as pd

from tradeeye.strategies.stock_recommender import rank_market_candidates, recommendations_to_json


def test_rank_market_candidates_returns_two_price_groups():
    market_df = pd.DataFrame(
        [
            {
                "ts_code": "600001.SH",
                "name": "Alpha Power",
                "industry": "Power",
                "trade_date": "20260425",
                "close": 9.8,
                "pct_chg": 3.5,
                "turnover_rate": 9.0,
                "volume_ratio": 2.8,
                "high": 10.2,
                "low": 9.5,
                "pre_close": 9.6,
                "amount": 900000,
                "total_mv": 3000000,
                "pe": 12.0,
                "pe_ttm": 10.0,
            },
            {
                "ts_code": "600002.SH",
                "name": "Beta Power",
                "industry": "Power",
                "trade_date": "20260425",
                "close": 15.2,
                "pct_chg": 2.6,
                "turnover_rate": 7.0,
                "volume_ratio": 2.2,
                "high": 15.9,
                "low": 14.8,
                "pre_close": 14.9,
                "amount": 620000,
                "total_mv": 2500000,
                "pe": 25.0,
                "pe_ttm": 24.0,
            },
            {
                "ts_code": "600003.SH",
                "name": "*ST Risk",
                "industry": "Power",
                "trade_date": "20260425",
                "close": 7.0,
                "pct_chg": 4.0,
                "turnover_rate": 8.0,
                "volume_ratio": 3.0,
                "high": 7.3,
                "low": 6.8,
                "pre_close": 6.9,
                "amount": 700000,
                "total_mv": 2200000,
                "pe": 18.0,
                "pe_ttm": 17.5,
            },
            {
                "ts_code": "600004.SH",
                "name": "Gamma退",
                "industry": "Power",
                "trade_date": "20260425",
                "close": 8.5,
                "pct_chg": 4.2,
                "turnover_rate": 8.5,
                "volume_ratio": 3.1,
                "high": 8.8,
                "low": 8.1,
                "pre_close": 8.2,
                "amount": 750000,
                "total_mv": 2100000,
                "pe": 16.0,
                "pe_ttm": 15.0,
            },
            {
                "ts_code": "600005.SH",
                "name": "Over20",
                "industry": "Power",
                "trade_date": "20260425",
                "close": 21.0,
                "pct_chg": 5.0,
                "turnover_rate": 9.5,
                "volume_ratio": 3.2,
                "high": 21.5,
                "low": 20.5,
                "pre_close": 20.6,
                "amount": 820000,
                "total_mv": 2800000,
                "pe": 14.0,
                "pe_ttm": 13.0,
            },
        ]
    )

    grouped = rank_market_candidates(
        market_df=market_df,
        allowed_exchanges=("SH", "SZ"),
        recommender_industries=("Power",),
        trade_date="20260425",
        top_n_each_group=5,
    )

    assert set(grouped.keys()) == {"low_price_group", "mid_price_group"}
    assert all(item["close"] <= 10 for item in grouped["low_price_group"])
    assert all(10 < item["close"] <= 20 for item in grouped["mid_price_group"])
    assert all("ST" not in item["name"].upper() for item in grouped["low_price_group"] + grouped["mid_price_group"])
    assert all("退" not in item["name"] for item in grouped["low_price_group"] + grouped["mid_price_group"])
    assert all(item["close"] <= 20 for item in grouped["low_price_group"] + grouped["mid_price_group"])
    assert len(grouped["low_price_group"]) <= 5
    assert len(grouped["mid_price_group"]) <= 5


def test_recommendations_to_json_contains_required_keys():
    payload = {
        "low_price_group": [{"ts_code": "600001.SH"}],
        "mid_price_group": [{"ts_code": "000001.SZ"}],
    }

    as_json = recommendations_to_json(payload)
    parsed = json.loads(as_json)

    assert set(parsed.keys()) == {"low_price_group", "mid_price_group"}
    assert parsed["low_price_group"][0]["ts_code"] == "600001.SH"
