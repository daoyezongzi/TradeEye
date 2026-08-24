import csv

from tradeeye.services.signal_store import (
    ETF_RECOMMEND_FIELDS,
    LEGACY_SCHEMA_VERSION,
    RECOMMEND_FIELDS,
    RECOMMEND_SCHEMA_VERSION,
    append_analysis_signals,
    append_etf_recommend_signals,
    append_recommend_signals,
    read_recommend_signals,
)


def _read_rows(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _recommend(code="600001.SH", score=82, **overrides):
    row = {
        "trade_date": "20260724",
        "ts_code": code,
        "name": "Alpha",
        "industry": "Power",
        "strategy_version": "recommend_v2",
        "momentum_score": 34,
        "close_quality_score": 29,
        "volume_funds_score": 19,
        "quality_score": score,
        "risk_level": "normal",
        "risk_flags": "",
        "planned_entry_price": 9.604,
        "close": 9.8,
        "price_preference": 3,
        "selection_rank": 1,
        "rules_fingerprint": "rules-abc",
    }
    row.update(overrides)
    return row


def test_append_writes_versioned_schema_and_first_write_wins(tmp_path):
    target = tmp_path / "data" / "signals" / "recommend.csv"
    assert append_recommend_signals([_recommend()], path=target) is True
    first = _read_rows(target)[0]
    assert list(first) == RECOMMEND_FIELDS
    assert first["schema_version"] == RECOMMEND_SCHEMA_VERSION
    assert first["trade_date"] == first["date"] == "20260724"
    assert first["signal_id"].startswith("sig_")

    assert append_recommend_signals([_recommend(score=85)], path=target) is True
    second_rows = _read_rows(target)
    assert len(second_rows) == 1
    assert second_rows[0]["signal_id"] == first["signal_id"]
    assert second_rows[0]["quality_score"] == "82"


def test_legacy_csv_is_read_as_legacy_v1_with_stable_id(tmp_path):
    target = tmp_path / "recommend.csv"
    target.write_text(
        "date,ts_code,name,price_group,total_score,dimensions,close\n"
        "20260723,600005.SH,Rec,low_price_group,66,t_active,9.5\n",
        encoding="utf-8",
    )
    first = read_recommend_signals(target)[0]
    second = read_recommend_signals(target)[0]
    assert first["schema_version"] == LEGACY_SCHEMA_VERSION
    assert first["strategy_version"] == LEGACY_SCHEMA_VERSION
    assert first["trade_date"] == "20260723"
    assert first["signal_id"] == second["signal_id"]


def test_append_migrates_legacy_rows_without_losing_them(tmp_path):
    target = tmp_path / "recommend.csv"
    target.write_text(
        "date,ts_code,name,price_group,total_score,dimensions,close\n"
        "20260723,600005.SH,Rec,low_price_group,66,t_active,9.5\n",
        encoding="utf-8",
    )
    assert append_recommend_signals([_recommend()], path=target)
    rows = _read_rows(target)
    assert len(rows) == 2
    assert {row["schema_version"] for row in rows} == {LEGACY_SCHEMA_VERSION, RECOMMEND_SCHEMA_VERSION}


def test_etf_signals_have_separate_schema_and_strategy(tmp_path):
    stock_path = tmp_path / "recommend.csv"
    etf_path = tmp_path / "etf_recommend.csv"
    assert append_recommend_signals([_recommend()], path=stock_path)
    assert append_etf_recommend_signals(
        [
            {
                "trade_date": "20260724",
                "ts_code": "510300.SH",
                "name": "ETF",
                "strategy_version": "etf_v1",
                "momentum_score": 40,
                "close_quality_score": 30,
                "liquidity_score": 18,
                "quality_score": 88,
                "close": 4.0,
            }
        ],
        path=etf_path,
    )
    etf = _read_rows(etf_path)[0]
    assert list(etf) == ETF_RECOMMEND_FIELDS
    assert etf["strategy_version"] == "etf_v1"
    assert etf["signal_id"] != _read_rows(stock_path)[0]["signal_id"]
    assert len(_read_rows(stock_path)) == 1


def test_append_returns_false_on_io_error(tmp_path):
    ok = append_analysis_signals(
        [{"date": "20260724", "ts_code": "600001.SH", "close": 1.0}],
        path=tmp_path,
    )
    assert ok is False


def test_append_does_not_overwrite_history_when_existing_csv_cannot_be_parsed(tmp_path):
    target = tmp_path / "recommend.csv"
    original = b"\xff\xfe\x00broken-history"
    target.write_bytes(original)

    assert append_recommend_signals([_recommend()], path=target) is False
    assert target.read_bytes() == original
