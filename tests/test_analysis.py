from tradeeye.services.analysis import build_analysis_report
from tradeeye.strategies.strategy import DIMENSION_CAPS


def test_build_analysis_report_contains_required_diagnostic_sections():
    result = {
        "raw_score": 100,
        "risk_level": "低风险",
        "final_status": "强",
        "dimensions": dict(DIMENSION_CAPS),
        "reasons": ["收盘位于多头排列上方", "资金净流入为正"],
        "risk": "未发现主要风险",
        "next_day_watch": ["观察次日收盘能否守住 MA5", "观察量能是否保持常态"],
    }

    report = build_analysis_report(
        {"name": "Alpha Corp", "trade_date": "20260822"},
        result,
        "600001.SH",
    )

    assert "【Alpha Corp (600001.SH)】" in report
    assert "趋势结构：30/30" in report
    assert "收盘与价格行为：25/25" in report
    assert "量能与流动性：20/20" in report
    assert "资金确认：15/15" in report
    assert "市场环境：10/10" in report
    assert "原始总分：100/100" in report
    assert "风险等级：低风险" in report
    assert "最终状态：强" in report
    assert "主要依据：" in report
    assert "次日观察点：" in report


def test_build_analysis_report_marks_missing_data_as_unscored():
    result = {
        "raw_score": None,
        "risk_level": "无法判定",
        "final_status": "数据不足",
        "dimensions": {name: None for name in DIMENSION_CAPS},
        "reasons": ["缺少关键数据：latest.ma20"],
        "risk": "关键数据缺失，无法判定风险等级",
        "next_day_watch": ["补齐完整盘后行情后再观察结构变化"],
    }

    report = build_analysis_report({}, result, "600001.SH")

    assert "趋势结构：不评分/30" in report
    assert "原始总分：不评分" in report
    assert "最终状态：数据不足" in report
    assert "latest.ma20" in report


def test_build_analysis_report_is_deterministic_and_contains_no_trade_instruction():
    result = {
        "raw_score": 72,
        "risk_level": "中风险",
        "final_status": "观察",
        "dimensions": {
            "趋势结构": 24,
            "收盘与价格行为": 18,
            "量能与流动性": 14,
            "资金确认": 9,
            "市场环境": 7,
        },
        "reasons": ["结构保持稳定"],
        "risk": "上市时间较短",
        "next_day_watch": ["观察结构是否保持稳定"],
    }
    stock = {"name": "Beta", "trade_date": "20260822"}

    first = build_analysis_report(stock, result, "000001.SZ")
    second = build_analysis_report(stock, result, "000001.SZ")

    assert first == second
    assert "LLM" not in first
    for forbidden in ("买入", "加仓", "卖出", "止盈", "轻仓"):
        assert forbidden not in first
