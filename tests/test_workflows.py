from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_core_workflow_uses_completed_daily_data_and_settles_before_analysis():
    content = (WORKFLOWS / "TradeEye-1.0.0.yml").read_text(encoding="utf-8")
    workflow = _load("TradeEye-1.0.0.yml")
    crons = {item["cron"] for item in workflow["on"]["schedule"]}

    assert crons == {"0 22 * * 0-4", "0 10 * * 1-5"}
    assert workflow["run-name"].startswith("TradeEye core ")
    assert content.index("python portfolio_main.py") < content.index("python main.py")
    assert "LLM_" not in content
    assert "requirements-dev.txt" not in content
    assert "data/trades/" in content
    assert "data/portfolio/" in content
    assert workflow["concurrency"]["group"] == "tradeeye-data-writer"


def test_weekly_report_runs_after_friday_evening_batch():
    workflow = _load("TradeEye-backtest-1.0.0.yml")
    content = (WORKFLOWS / "TradeEye-backtest-1.0.0.yml").read_text(encoding="utf-8")

    assert workflow["on"]["schedule"] == [{"cron": "30 11 * * 5"}]
    assert "concurrency" not in workflow
    assert workflow["permissions"]["actions"] == "read"
    assert "TradeEye-1.0.0.yml/runs" in content
    assert "TradeEye core 0 10 * * 1-5" in content
    assert "for attempt in {1..10}" in content
    assert "No successful Friday evening core batch" in content
    assert "requirements-dev.txt" not in content


def test_tests_are_kept_in_dedicated_ci_workflow():
    ci = (WORKFLOWS / "TradeEye-ci.yml").read_text(encoding="utf-8")
    assert "python -m pytest" in ci
    assert "python -m compileall -q tradeeye" in ci


def test_runtime_configuration_has_no_llm_and_persists_new_csv_paths():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "LLM_" not in env_example
    assert "TRADEEYE_RULES_FILE=" in env_example
    assert "!data/trades/*.csv" in gitignore
    assert "!data/portfolio/*.csv" in gitignore
