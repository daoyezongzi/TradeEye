import csv

from tradeeye.services.signal_store import (
    ANALYSIS_FIELDS,
    append_analysis_signals,
    append_recommend_signals,
)


def _read_rows(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_append_creates_file_and_dirs_with_header(tmp_path):
    target = tmp_path / "data" / "signals" / "analysis.csv"
    ok = append_analysis_signals(
        [{"date": "20260724", "ts_code": "600001.SH", "name": "Alpha", "score": 82,
          "status": "【强候选】尾盘隔夜", "close": 9.8, "called_llm": True}],
        path=target,
    )
    assert ok is True
    rows = _read_rows(target)
    assert len(rows) == 1
    assert rows[0]["ts_code"] == "600001.SH"
    assert list(rows[0].keys()) == ANALYSIS_FIELDS


def test_append_dedupes_same_day_same_code_keeps_latest(tmp_path):
    target = tmp_path / "analysis.csv"
    append_analysis_signals(
        [{"date": "20260724", "ts_code": "600001.SH", "name": "Alpha", "score": 60,
          "status": "old", "close": 9.0, "called_llm": False}],
        path=target,
    )
    append_analysis_signals(
        [{"date": "20260724", "ts_code": "600001.SH", "name": "Alpha", "score": 82,
          "status": "new", "close": 9.8, "called_llm": True}],
        path=target,
    )
    rows = _read_rows(target)
    assert len(rows) == 1
    assert rows[0]["score"] == "82"
    assert rows[0]["status"] == "new"


def test_append_accumulates_across_days_and_codes(tmp_path):
    target = tmp_path / "recommend.csv"
    append_recommend_signals(
        [{"date": "20260723", "ts_code": "600001.SH", "name": "A", "price_group": "low_price_group",
          "total_score": 70.5, "dimensions": "short_burst|t_active", "close": 9.8}],
        path=target,
    )
    append_recommend_signals(
        [{"date": "20260724", "ts_code": "600002.SH", "name": "B", "price_group": "mid_price_group",
          "total_score": 66.0, "dimensions": "t_active", "close": 15.2}],
        path=target,
    )
    rows = _read_rows(target)
    assert len(rows) == 2
    assert {row["date"] for row in rows} == {"20260723", "20260724"}


def test_append_returns_false_on_io_error(tmp_path):
    # 传一个目录路径触发 IO 异常，不应抛出
    ok = append_analysis_signals(
        [{"date": "20260724", "ts_code": "600001.SH", "name": "A", "score": 1,
          "status": "s", "close": 1.0, "called_llm": False}],
        path=tmp_path,
    )
    assert ok is False
