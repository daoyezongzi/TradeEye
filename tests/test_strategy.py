from tradeeye.strategies.strategy import check_signals


def test_check_signals_returns_high_score_for_shrink_pullback():
    result = check_signals(
        {
            "latest": {"vol": 60, "pct_chg": 1, "close": 10.1, "open": 9.8, "ma20": 10, "ma5": 10.5},
            "prev": {"vol": 100},
        }
    )

    assert result["score"] == 80
    assert result["vol_ratio"] == 0.6


def test_check_signals_handles_missing_payload():
    result = check_signals({})
    assert result["score"] == 0
