from pathlib import Path

import pytest

from tradeeye.services.portfolio import (
    CLOSED,
    ENTRY_UNAVAILABLE,
    EXPIRED_UNFILLED,
    SKIPPED_CAPACITY,
    SKIPPED_DAILY_LIMIT,
    SKIPPED_DUPLICATE,
    read_nav_rows,
    read_trade_records,
    settle_recommend_portfolio,
)
from tradeeye.services import portfolio as portfolio_service
from tradeeye.services.signal_store import append_recommend_signals
from tradeeye.services.trading import DailyMarketData, MarketDataUnavailable, MarketQuote


DAYS = ["20260803", "20260804", "20260805", "20260806", "20260807"]


def q(day, code, open_, high, low, close, *, down_limit=None, locked=False):
    return MarketQuote(
        trade_date=day,
        ts_code=code,
        open=open_,
        high=high,
        low=low,
        close=close,
        down_limit=down_limit,
        one_price_down_limit=locked,
    )


class FakeProvider:
    def __init__(self, markets, fail_day=None):
        self.markets = markets
        self.fail_day = fail_day
        self.calendar_calls = []
        self.daily_calls = []

    def get_trade_days(self, start_date, end_date):
        self.calendar_calls.append((start_date, end_date))
        return DAYS

    def get_daily_market(self, trade_date):
        self.daily_calls.append(trade_date)
        if trade_date == self.fail_day:
            raise MarketDataUnavailable("supplier failed")
        return DailyMarketData(trade_date, self.markets.get(trade_date, {}), complete=True)


def signal(code="600001.SH", *, day=DAYS[0], rank=1, industry="Power", version="recommend_v2"):
    return {
        "trade_date": day,
        "ts_code": code,
        "name": code,
        "industry": industry,
        "strategy_version": version,
        "quality_score": 90 - rank,
        "selection_rank": rank,
        "close": 10.0,
    }


def paths(tmp_path):
    return (
        tmp_path / "signals.csv",
        tmp_path / "trades.csv",
        tmp_path / "nav.csv",
    )


def settle(tmp_path, rows, provider, as_of):
    signal_path, trade_path, nav_path = paths(tmp_path)
    assert append_recommend_signals(rows, path=signal_path)
    result = settle_recommend_portfolio(
        provider,
        as_of=as_of,
        signal_path=signal_path,
        trade_path=trade_path,
        nav_path=nav_path,
    )
    return result, trade_path, nav_path


def test_entry_t_plus_one_exit_t_plus_two_cost_nav_and_idempotence(tmp_path):
    code = "600001.SH"
    markets = {
        DAYS[0]: {},
        DAYS[1]: {code: q(DAYS[1], code, 9.7, 10.8, 9.6, 9.9)},
        DAYS[2]: {code: q(DAYS[2], code, 9.9, 10.2, 9.8, 10.0)},
    }
    provider = FakeProvider(markets)
    result, trade_path, nav_path = settle(tmp_path, [signal(code)], provider, DAYS[2])
    assert provider.daily_calls == [DAYS[1], DAYS[2]]
    trade = read_trade_records(trade_path)[0]
    assert result.trade_count == 1
    assert trade.entry_date == DAYS[1]
    assert trade.entry_price == pytest.approx(9.7)
    assert trade.actual_exit_date == DAYS[2]
    assert trade.exit_reason == "take_profit"
    assert trade.gross_return_pct == pytest.approx(4.0)
    assert trade.net_return_pct == pytest.approx(3.85)
    assert trade.portfolio_status == CLOSED
    assert float(read_nav_rows(nav_path)[-1]["nav"]) == pytest.approx(1.0077)

    first_trade_bytes = trade_path.read_bytes()
    first_nav_bytes = nav_path.read_bytes()
    rerun_provider = FakeProvider(markets)
    settle_recommend_portfolio(
        rerun_provider,
        as_of=DAYS[2],
        signal_path=paths(tmp_path)[0],
        trade_path=trade_path,
        nav_path=nav_path,
    )
    assert trade_path.read_bytes() == first_trade_bytes
    assert nav_path.read_bytes() == first_nav_bytes
    assert rerun_provider.calendar_calls == []
    assert rerun_provider.daily_calls == []


def test_new_as_of_fetches_only_the_new_trade_day(tmp_path):
    code = "600001.SH"
    markets = {
        DAYS[1]: {code: q(DAYS[1], code, 9.8, 10.0, 9.7, 9.9)},
        DAYS[2]: {code: q(DAYS[2], code, 9.9, 10.0, 9.8, 9.9)},
    }
    _, trade_path, nav_path = settle(
        tmp_path, [signal(code)], FakeProvider(markets), DAYS[1]
    )
    provider = FakeProvider(markets)
    settle_recommend_portfolio(
        provider,
        as_of=DAYS[2],
        signal_path=paths(tmp_path)[0],
        trade_path=trade_path,
        nav_path=nav_path,
    )
    assert provider.daily_calls == [DAYS[2]]
    assert [row["trade_date"] for row in read_nav_rows(nav_path)] == DAYS[:3]


def test_non_trading_as_of_watermark_makes_exact_rerun_provider_free(tmp_path):
    code = "600001.SH"
    markets = {
        DAYS[1]: {code: q(DAYS[1], code, 10.0, 10.2, 9.9, 10.1)},
    }
    _, trade_path, nav_path = settle(
        tmp_path,
        [signal(code)],
        FakeProvider(markets),
        DAYS[-1],
    )
    saturday = "20260808"
    first_weekend_provider = FakeProvider(markets)

    settle_recommend_portfolio(
        first_weekend_provider,
        as_of=saturday,
        signal_path=paths(tmp_path)[0],
        trade_path=trade_path,
        nav_path=nav_path,
    )

    assert first_weekend_provider.calendar_calls
    assert first_weekend_provider.daily_calls == []
    assert read_nav_rows(nav_path)[-1]["settled_through"] == saturday
    trade_bytes = trade_path.read_bytes()
    nav_bytes = nav_path.read_bytes()
    exact_rerun_provider = FakeProvider({})

    settle_recommend_portfolio(
        exact_rerun_provider,
        as_of=saturday,
        signal_path=paths(tmp_path)[0],
        trade_path=trade_path,
        nav_path=nav_path,
    )

    assert exact_rerun_provider.calendar_calls == []
    assert exact_rerun_provider.daily_calls == []
    assert trade_path.read_bytes() == trade_bytes
    assert nav_path.read_bytes() == nav_bytes


def test_new_strategy_version_starts_independent_nav_without_history_refetch(tmp_path):
    code_v2 = "600001.SH"
    code_v3 = "600002.SH"
    markets = {
        DAYS[1]: {code_v2: q(DAYS[1], code_v2, 9.8, 10.0, 9.7, 9.9)},
        DAYS[2]: {
            code_v2: q(DAYS[2], code_v2, 9.9, 10.0, 9.8, 9.9),
            code_v3: q(DAYS[2], code_v3, 9.8, 10.0, 9.7, 9.9),
        },
    }
    _, trade_path, nav_path = settle(
        tmp_path, [signal(code_v2, version="recommend_v2")], FakeProvider(markets), DAYS[1]
    )
    assert append_recommend_signals(
        [signal(code_v3, day=DAYS[1], version="recommend_v3")],
        path=paths(tmp_path)[0],
    )
    provider = FakeProvider(markets)
    settle_recommend_portfolio(
        provider,
        as_of=DAYS[2],
        signal_path=paths(tmp_path)[0],
        trade_path=trade_path,
        nav_path=nav_path,
    )
    assert provider.daily_calls == [DAYS[2]]
    nav_dates = {}
    for row in read_nav_rows(nav_path):
        nav_dates.setdefault(row["strategy_version"], []).append(row["trade_date"])
    assert nav_dates["recommend_v2"] == DAYS[:3]
    assert nav_dates["recommend_v3"] == DAYS[1:3]


def test_retired_closed_version_stops_extending_cash_nav_when_new_version_starts(tmp_path):
    code_v2 = "600001.SH"
    code_v3 = "600002.SH"
    initial_markets = {
        DAYS[1]: {code_v2: q(DAYS[1], code_v2, 9.8, 10.8, 9.7, 9.9)},
        DAYS[2]: {code_v2: q(DAYS[2], code_v2, 9.9, 10.3, 9.8, 10.0)},
    }
    _, trade_path, nav_path = settle(
        tmp_path,
        [signal(code_v2, version="recommend_v2")],
        FakeProvider(initial_markets),
        DAYS[2],
    )
    assert read_trade_records(trade_path)[0].status == CLOSED
    assert append_recommend_signals(
        [signal(code_v3, day=DAYS[2], version="recommend_v3")],
        path=paths(tmp_path)[0],
    )
    provider = FakeProvider(
        {DAYS[3]: {code_v3: q(DAYS[3], code_v3, 9.8, 10.0, 9.7, 9.9)}}
    )
    settle_recommend_portfolio(
        provider,
        as_of=DAYS[3],
        signal_path=paths(tmp_path)[0],
        trade_path=trade_path,
        nav_path=nav_path,
    )
    assert provider.daily_calls == [DAYS[3]]
    nav_dates = {}
    for row in read_nav_rows(nav_path):
        nav_dates.setdefault(row["strategy_version"], []).append(row["trade_date"])
    assert nav_dates["recommend_v2"] == DAYS[:3]
    assert nav_dates["recommend_v3"] == DAYS[2:4]

    trade_bytes = trade_path.read_bytes()
    nav_bytes = nav_path.read_bytes()
    rerun_provider = FakeProvider({})
    settle_recommend_portfolio(
        rerun_provider,
        as_of=DAYS[3],
        signal_path=paths(tmp_path)[0],
        trade_path=trade_path,
        nav_path=nav_path,
    )
    assert rerun_provider.calendar_calls == []
    assert rerun_provider.daily_calls == []
    assert trade_path.read_bytes() == trade_bytes
    assert nav_path.read_bytes() == nav_bytes


@pytest.mark.parametrize("targets_exist", [True, False])
def test_atomic_csv_pair_replace_rolls_back_both_targets_on_second_failure(
    tmp_path, monkeypatch, targets_exist
):
    first_target = tmp_path / "trades.csv"
    second_target = tmp_path / "nav.csv"
    if targets_exist:
        first_target.write_bytes(b"original trades\r\n")
        second_target.write_bytes(b"original nav\r\n")
    before = {
        first_target: first_target.read_bytes() if first_target.exists() else None,
        second_target: second_target.read_bytes() if second_target.exists() else None,
    }
    real_replace = portfolio_service.os.replace
    failed = False

    def fail_second_install(source, target):
        nonlocal failed
        source_path = Path(source)
        target_path = Path(target)
        if not failed and source_path.suffix == ".tmp" and target_path == second_target:
            failed = True
            raise OSError("injected second replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(portfolio_service.os, "replace", fail_second_install)

    with pytest.raises(OSError, match="injected second replace failure"):
        portfolio_service._atomic_replace_csv_pair(
            (first_target, ["value"], [{"value": "new trades"}]),
            (second_target, ["value"], [{"value": "new nav"}]),
        )

    for target, original in before.items():
        if original is None:
            assert not target.exists()
        else:
            assert target.read_bytes() == original


def test_entry_unavailable_unfilled_and_daily_two_entry_limit(tmp_path):
    codes = [f"60000{i}.SH" for i in range(1, 6)]
    markets = {
        DAYS[0]: {},
        DAYS[1]: {
            codes[0]: q(DAYS[1], codes[0], 9.8, 10.0, 9.7, 9.9),
            codes[1]: q(DAYS[1], codes[1], 9.8, 10.0, 9.7, 9.9),
            codes[2]: q(DAYS[1], codes[2], 9.8, 10.0, 9.7, 9.9),
            codes[3]: q(DAYS[1], codes[3], 10.0, 10.2, 9.9, 10.1),
            # codes[4] intentionally absent from an otherwise complete batch.
        },
    }
    _, trade_path, _ = settle(
        tmp_path,
        [signal(code, rank=index + 1) for index, code in enumerate(codes)],
        FakeProvider(markets),
        DAYS[1],
    )
    by_code = {record.ts_code: record for record in read_trade_records(trade_path)}
    assert by_code[codes[4]].status == ENTRY_UNAVAILABLE
    assert by_code[codes[3]].status == EXPIRED_UNFILLED
    selected = [record for record in by_code.values() if record.slot_id]
    assert len(selected) == 2
    assert by_code[codes[2]].portfolio_status == SKIPPED_DAILY_LIMIT


def test_same_day_exit_does_not_retroactively_free_a_premarket_slot(tmp_path):
    first = ["600001.SH", "600002.SH"]
    second = ["600003.SH", "600004.SH"]
    third = ["600005.SH", "600006.SH"]
    all_codes = first + second + third
    markets = {
        DAYS[1]: {code: q(DAYS[1], code, 9.8, 10.0, 9.7, 9.9) for code in first},
        DAYS[2]: {
            **{code: q(DAYS[2], code, 9.9, 10.1, 9.8, 10.0) for code in first},
            **{code: q(DAYS[2], code, 9.8, 10.0, 9.7, 9.9) for code in second},
        },
        DAYS[3]: {
            **{code: q(DAYS[3], code, 10.0, 10.1, 9.9, 10.0) for code in first},
            **{code: q(DAYS[3], code, 9.9, 10.1, 9.8, 10.0) for code in second},
            **{code: q(DAYS[3], code, 9.8, 10.0, 9.7, 9.9) for code in third},
        },
    }
    signals = [
        *[signal(code, day=DAYS[0], rank=index + 1) for index, code in enumerate(first)],
        *[signal(code, day=DAYS[1], rank=index + 1) for index, code in enumerate(second)],
        *[signal(code, day=DAYS[2], rank=index + 1) for index, code in enumerate(third)],
    ]

    _, trade_path, _ = settle(
        tmp_path,
        signals,
        FakeProvider(markets),
        DAYS[3],
    )

    by_code = {record.ts_code: record for record in read_trade_records(trade_path)}
    assert [by_code[code].slot_id > 0 for code in third] == [True, False]
    assert by_code[third[1]].portfolio_status == SKIPPED_CAPACITY
    assert all(by_code[code].status == CLOSED for code in first)
    assert set(by_code) == set(all_codes)


def test_overlapping_same_stock_signal_is_retained_but_skipped_by_portfolio(tmp_path):
    code = "600001.SH"
    markets = {
        DAYS[0]: {},
        DAYS[1]: {code: q(DAYS[1], code, 9.8, 10.0, 9.7, 9.9)},
        DAYS[2]: {code: q(DAYS[2], code, 9.8, 10.0, 9.7, 9.9)},
    }
    _, trade_path, _ = settle(
        tmp_path,
        [signal(code, day=DAYS[0]), signal(code, day=DAYS[1])],
        FakeProvider(markets),
        DAYS[2],
    )
    records = sorted(read_trade_records(trade_path), key=lambda item: item.signal_date)
    assert len(records) == 2
    assert records[0].slot_id == 1
    assert records[1].status == "open"
    assert records[1].portfolio_status == SKIPPED_DUPLICATE


def test_d2_missing_quote_stays_open_and_d3_valid_quote_uses_timeout_close(tmp_path):
    code = "600001.SH"
    markets = {
        DAYS[1]: {code: q(DAYS[1], code, 9.8, 10.0, 9.7, 9.9)},
        DAYS[2]: {},
        DAYS[3]: {code: q(DAYS[3], code, 10.0, 10.1, 9.9, 10.05)},
    }
    _, trade_path, nav_path = settle(
        tmp_path, [signal(code)], FakeProvider(markets), DAYS[3]
    )
    trade = read_trade_records(trade_path)[0]
    assert trade.status == CLOSED
    assert trade.planned_exit_date == DAYS[3]
    assert trade.actual_exit_date == DAYS[3]
    assert trade.exit_reason == "timeout_close"
    assert trade.stale_valuation_days == 1
    nav_by_day = {row["trade_date"]: row for row in read_nav_rows(nav_path)}
    assert nav_by_day[DAYS[2]]["stale_price_codes"] == code


def test_d3_missing_quote_defers_timeout_until_first_tradable_open(tmp_path):
    code = "600001.SH"
    markets = {
        DAYS[1]: {code: q(DAYS[1], code, 9.8, 10.0, 9.7, 9.9)},
        DAYS[2]: {},
        DAYS[3]: {},
        DAYS[4]: {code: q(DAYS[4], code, 9.1, 9.3, 9.0, 9.2)},
    }
    _, trade_path, nav_path = settle(
        tmp_path, [signal(code)], FakeProvider(markets), DAYS[4]
    )
    trade = read_trade_records(trade_path)[0]
    assert trade.status == CLOSED
    assert trade.planned_exit_date == DAYS[3]
    assert trade.actual_exit_date == DAYS[4]
    assert trade.exit_price == pytest.approx(9.1)
    assert trade.exit_reason == "deferred_open"
    assert trade.delay_trade_days == 1
    assert trade.deferred_reason == "no_quote"
    assert trade.stale_valuation_days == 2
    nav_by_day = {row["trade_date"]: row for row in read_nav_rows(nav_path)}
    assert nav_by_day[DAYS[2]]["stale_price_codes"] == code
    assert nav_by_day[DAYS[3]]["occupied_slots"] == "1"


def test_d3_locked_down_limit_defers_then_exits_next_open(tmp_path):
    code = "600001.SH"
    markets = {
        DAYS[1]: {code: q(DAYS[1], code, 9.8, 10.0, 9.7, 9.9)},
        DAYS[2]: {},
        DAYS[3]: {code: q(DAYS[3], code, 8.8, 8.8, 8.8, 8.8, down_limit=8.8)},
        DAYS[4]: {code: q(DAYS[4], code, 8.9, 9.2, 8.8, 9.0)},
    }
    _, trade_path, nav_path = settle(
        tmp_path, [signal(code)], FakeProvider(markets), DAYS[4]
    )
    trade = read_trade_records(trade_path)[0]
    assert trade.status == CLOSED
    assert trade.planned_exit_date == DAYS[3]
    assert trade.actual_exit_date == DAYS[4]
    assert trade.exit_price == pytest.approx(8.9)
    assert trade.exit_reason == "deferred_open"
    assert trade.delay_trade_days == 1
    assert trade.deferred_reason == "one_price_down_limit"
    assert trade.stale_valuation_days == 1
    nav_by_day = {row["trade_date"]: row for row in read_nav_rows(nav_path)}
    assert nav_by_day[DAYS[2]]["stale_price_codes"] == code
    assert nav_by_day[DAYS[2]]["occupied_slots"] == "1"
    assert nav_by_day[DAYS[3]]["occupied_slots"] == "1"


def test_supplier_failure_does_not_replace_existing_ledger(tmp_path):
    signal_path, trade_path, nav_path = paths(tmp_path)
    assert append_recommend_signals([signal()], path=signal_path)
    trade_path.write_text("original-trades", encoding="utf-8")
    nav_path.write_text("original-nav", encoding="utf-8")
    provider = FakeProvider({DAYS[0]: {}, DAYS[1]: {}}, fail_day=DAYS[1])
    with pytest.raises(MarketDataUnavailable):
        settle_recommend_portfolio(
            provider,
            as_of=DAYS[1],
            signal_path=signal_path,
            trade_path=trade_path,
            nav_path=nav_path,
        )
    assert trade_path.read_text(encoding="utf-8") == "original-trades"
    assert nav_path.read_text(encoding="utf-8") == "original-nav"


def test_incremental_supplier_failure_keeps_last_successful_watermark(tmp_path):
    code = "600001.SH"
    markets = {DAYS[1]: {code: q(DAYS[1], code, 9.8, 10.0, 9.7, 9.9)}}
    _, trade_path, nav_path = settle(
        tmp_path, [signal(code)], FakeProvider(markets), DAYS[1]
    )
    trade_bytes = trade_path.read_bytes()
    nav_bytes = nav_path.read_bytes()
    provider = FakeProvider(markets, fail_day=DAYS[2])

    with pytest.raises(MarketDataUnavailable):
        settle_recommend_portfolio(
            provider,
            as_of=DAYS[2],
            signal_path=paths(tmp_path)[0],
            trade_path=trade_path,
            nav_path=nav_path,
        )
    assert provider.daily_calls == [DAYS[2]]
    assert trade_path.read_bytes() == trade_bytes
    assert nav_path.read_bytes() == nav_bytes
