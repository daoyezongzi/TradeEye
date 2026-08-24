import datetime as dt

from tradeeye.time_utils import market_today


def test_market_today_uses_asia_shanghai_for_morning_utc_runs():
    sunday_utc = dt.datetime(2026, 8, 23, 22, 0, tzinfo=dt.timezone.utc)

    assert market_today(sunday_utc) == dt.date(2026, 8, 24)
