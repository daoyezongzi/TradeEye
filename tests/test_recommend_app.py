from tradeeye.config import Settings
from tradeeye.recommend_app import build_recommendation_content, main


def make_settings(debug_mode: bool = True) -> Settings:
    return Settings(
        tushare_token="token",
        dify_api_key="api",
        feishu_webhook="https://example.com",
        dify_base_url="https://api.dify.ai/v1",
        debug_mode=debug_mode,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


def test_build_recommendation_content_includes_ai_section():
    recommendations = {
        "low_price_group": [{"ts_code": "600001.SH", "name": "Alpha", "close": 9.8, "total_score": 88.5, "dimensions": []}],
        "mid_price_group": [],
    }
    content = build_recommendation_content(recommendations, ai_analysis="AI summary")

    assert "每日好股推荐" in content
    assert "600001.SH" in content
    assert "AI summary" in content


def test_recommend_main_runs_end_to_end_with_injected_services():
    calls: list[str] = []

    grouped = {
        "low_price_group": [{"ts_code": "600001.SH", "name": "Alpha", "close": 9.8, "total_score": 88.5, "dimensions": []}],
        "mid_price_group": [{"ts_code": "000001.SZ", "name": "Beta", "close": 15.2, "total_score": 77.0, "dimensions": []}],
    }

    def fake_recommender(settings, top_n):
        calls.append(f"recommend:{top_n}")
        return grouped

    def fake_analyzer(recommendations_json, settings):
        calls.append("analyze")
        assert "low_price_group" in recommendations_json
        assert "mid_price_group" in recommendations_json
        return "AI summary"

    def fake_notifier(content, settings):
        calls.append("notify")
        assert "AI summary" in content
        return True

    exit_code = main(
        settings=make_settings(),
        recommender=fake_recommender,
        analyzer=fake_analyzer,
        notifier=fake_notifier,
        top_n=5,
    )

    assert exit_code == 0
    assert calls == ["recommend:5", "analyze", "notify"]
