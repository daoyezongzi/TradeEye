from __future__ import annotations

import datetime as dt

from tradeeye.config import Settings
from tradeeye.recommend_app import build_recommendation_content, main


def make_settings(debug_mode: bool = True) -> Settings:
    return Settings(
        tushare_token="token",
        feishu_webhook="https://example.com",
        debug_mode=debug_mode,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


def stock_item(code: str = "600001.SH") -> dict:
    return {
        "asset_type": "stock",
        "strategy_version": "recommend_v2",
        "rules_fingerprint": "abc123",
        "trade_date": "20260822",
        "ts_code": code,
        "name": "Alpha",
        "industry": "Power",
        "close": 10.0,
        "momentum_score": 30.0,
        "close_quality_score": 28.0,
        "volume_funds_score": 18.0,
        "quality_score": 76.0,
        "total_score": 76.0,
        "risk_level": "normal",
        "risk_flags": [],
        "price_preference_applied": True,
        "planned_entry_price": 9.8,
        "entry_plan": "D+1 触及 9.80 元时计划入场。",
        "local_reason": "确定性本地三维说明。",
        "dimensions": ["short_momentum", "close_quality", "volume_funds"],
    }


def etf_item() -> dict:
    return {
        "asset_type": "etf",
        "strategy_version": "etf_recommend_v1",
        "rules_fingerprint": "etf123",
        "trade_date": "20260822",
        "ts_code": "510300.SH",
        "name": "沪深300ETF",
        "fund_type": "股票型",
        "close": 4.2,
        "momentum_score": 38.0,
        "close_quality_score": 30.0,
        "liquidity_score": 20.0,
        "quality_score": 88.0,
        "planned_entry_price": 4.116,
        "entry_plan": "D+1 触及 4.116 元时计划入场。",
        "local_reason": "ETF 独立确定性说明。",
        "dimensions": ["etf_momentum", "close_quality", "liquidity"],
    }


def stock_result(items: list[dict] | None = None) -> dict:
    return {
        "strategy_version": "recommend_v2",
        "rules_fingerprint": "abc123",
        "trade_date": "20260822",
        "candidates": list(items if items is not None else [stock_item()]),
        "message": "",
    }


def disabled_etf_result() -> dict:
    return {
        "strategy_version": "etf_recommend_v1",
        "rules_fingerprint": "etf123",
        "status": "disabled",
        "trade_date": "20260822",
        "candidates": [],
        "message": "ETF 推荐未启用。",
    }


def test_build_recommendation_content_is_local_and_can_add_independent_etf_section():
    etf_result = {
        "strategy_version": "etf_recommend_v1",
        "status": "available",
        "trade_date": "20260822",
        "candidates": [etf_item()],
        "message": "",
    }

    content = build_recommendation_content(
        stock_result(),
        report_date=dt.date(2026, 8, 23),
        etf_recommendations=etf_result,
    )

    assert "2026-08-23 每日好股推荐" in content
    assert "股票统一候选池" in content
    assert "600001.SH" in content
    assert "短线动能 30.0/40" in content
    assert "ETF 白名单推荐" in content
    assert "510300.SH" in content
    assert "LLM" not in content
    assert "AI 分析" not in content


def test_recommend_main_runs_one_morning_batch_without_analyzer():
    calls: list[str] = []
    stock_rows: list[dict] = []
    etf_rows: list[dict] = []

    def fake_recommender(settings, top_n):
        calls.append(f"stock:{top_n}")
        return stock_result()

    def fake_etf_recommender(settings, trade_date, top_n):
        calls.append(f"etf:{trade_date}:{top_n}")
        return {
            "strategy_version": "etf_recommend_v1",
            "rules_fingerprint": "etf123",
            "status": "available",
            "trade_date": trade_date,
            "candidates": [etf_item()],
            "message": "",
        }

    def fake_stock_writer(rows):
        calls.append("stock_write")
        stock_rows.extend(rows)
        return True

    def fake_etf_writer(rows):
        calls.append("etf_write")
        etf_rows.extend(rows)
        return True

    def fake_notifier(content, settings):
        calls.append("notify")
        assert "确定性本地三维说明" in content
        assert "ETF 独立确定性说明" in content
        return True

    exit_code = main(
        settings=make_settings(),
        recommender=fake_recommender,
        etf_recommender=fake_etf_recommender,
        notifier=fake_notifier,
        top_n=5,
        signal_recorder=fake_stock_writer,
        etf_signal_recorder=fake_etf_writer,
    )

    assert exit_code == 0
    assert calls == ["stock:5", "etf:20260822:None", "stock_write", "etf_write", "notify"]
    assert stock_rows[0]["strategy_version"] == "recommend_v2"
    assert stock_rows[0]["momentum_score"] == 30.0
    assert stock_rows[0]["planned_entry_price"] == 9.8
    assert stock_rows[0]["selection_rank"] == 1
    assert stock_rows[0]["price_group"] == "unified"
    assert etf_rows[0]["strategy_version"] == "etf_recommend_v1"
    assert etf_rows[0]["liquidity_score"] == 20.0
    assert etf_rows[0]["selection_rank"] == 1


def test_etf_failure_is_reported_but_does_not_block_stock_recommendation():
    stock_rows: list[dict] = []
    notified: list[str] = []

    result = main(
        settings=make_settings(),
        recommender=lambda settings, top_n: stock_result(),
        etf_recommender=lambda settings, trade_date, top_n: {
            "strategy_version": "etf_recommend_v1",
            "status": "unavailable",
            "trade_date": trade_date,
            "candidates": [],
            "message": "ETF 接口不可用，股票荐股不受影响。",
        },
        notifier=lambda content, settings: notified.append(content) or True,
        signal_recorder=lambda rows: stock_rows.extend(rows) or True,
        etf_signal_recorder=lambda rows: (_ for _ in ()).throw(AssertionError("ETF writer must not run")),
    )

    assert result == 0
    assert len(stock_rows) == 1
    assert "ETF 接口不可用" in notified[0]
    assert "600001.SH" in notified[0]


def test_disabled_etf_is_not_written_or_shown():
    notified: list[str] = []

    result = main(
        settings=make_settings(),
        recommender=lambda settings, top_n: stock_result([]),
        etf_recommender=lambda settings, trade_date, top_n: disabled_etf_result(),
        notifier=lambda content, settings: notified.append(content) or True,
        signal_recorder=lambda rows: True,
        etf_signal_recorder=lambda rows: (_ for _ in ()).throw(AssertionError("ETF writer must not run")),
    )

    assert result == 0
    assert "今日无满足质量与风险门" in notified[0]
    assert "ETF 白名单推荐" not in notified[0]


def test_signal_persistence_failure_returns_failure_after_notification():
    notifications: list[str] = []

    result = main(
        settings=make_settings(),
        recommender=lambda settings, top_n: stock_result(),
        etf_recommender=lambda settings, trade_date, top_n: disabled_etf_result(),
        notifier=lambda content, settings: notifications.append(content) or True,
        signal_recorder=lambda rows: False,
        etf_signal_recorder=lambda rows: True,
    )

    assert result == 1
    assert len(notifications) == 1


def test_recommend_main_fails_fast_without_tushare_token():
    settings = make_settings()
    settings = Settings(
        tushare_token="",
        feishu_webhook=settings.feishu_webhook,
        debug_mode=settings.debug_mode,
        my_stocks=settings.my_stocks,
        allowed_exchanges=settings.allowed_exchanges,
    )

    result = main(
        settings=settings,
        recommender=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recommender must not run")
        ),
    )

    assert result == 1
