from __future__ import annotations

import pytest

import tradeeye.strategies.rules as rules_module
from tradeeye.strategies.rules import (
    DEFAULT_RULES_FILE,
    EtfMode,
    Rules,
    RulesValidationError,
    load_rules,
)


def test_defaults_expose_recommend_v2_and_disabled_etf_whitelist():
    rules = Rules()

    assert rules.analysis.status_bands.strong == 80
    assert rules.analysis.rules.ma_alignment.full_score == 18
    assert rules.recommender.strategy_version == "recommend_v2"
    assert rules.recommender.minimum_quality_score == 55
    assert rules.recommender.max_results == 5
    assert rules.recommender.hard_min is None
    assert rules.recommender.hard_max is None
    assert rules.recommender.preferred_price_max == 20
    assert rules.recommender.preferred_price_bonus == 3
    assert rules.recommender.entry_price_multiplier == 0.98
    assert rules.etf.enabled is False
    assert rules.etf.mode is EtfMode.WHITELIST
    assert rules.etf.codes == ()
    assert rules.etf.strategy_version == "etf_recommend_v1"


def test_load_rules_explicit_missing_file_raises(tmp_path):
    missing = tmp_path / "missing.yaml"

    with pytest.raises(RulesValidationError, match=r"Rules file does not exist: .*missing\.yaml"):
        load_rules(missing)


def test_load_rules_env_missing_file_raises(tmp_path, monkeypatch):
    missing = rules_module.RULES_ALLOWED_DIR / "missing-env.yaml"
    monkeypatch.setenv("TRADEEYE_RULES_FILE", str(missing))

    with pytest.raises(RulesValidationError, match=r"Rules file does not exist: .*missing-env\.yaml"):
        load_rules()


def test_load_rules_env_rejects_path_outside_strategy_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEEYE_RULES_FILE", str(tmp_path / "outside.yaml"))

    with pytest.raises(RulesValidationError, match="TRADEEYE_RULES_FILE"):
        load_rules()


def test_load_rules_missing_packaged_file_raises(tmp_path, monkeypatch):
    missing = tmp_path / "missing-packaged.yaml"
    monkeypatch.delenv("TRADEEYE_RULES_FILE", raising=False)
    monkeypatch.setattr(rules_module, "DEFAULT_RULES_FILE", missing)

    with pytest.raises(RulesValidationError, match=r"Rules file does not exist: .*missing-packaged\.yaml"):
        load_rules()


def test_load_rules_empty_yaml_returns_defaults(tmp_path):
    yaml_file = tmp_path / "empty.yaml"
    yaml_file.write_text("", encoding="utf-8")

    assert load_rules(yaml_file) == Rules()


def test_load_rules_strictly_supports_string_bool_list_enum_and_null(tmp_path):
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        "recommender:\n"
        "  strategy_version: recommend_v2_custom\n"
        "  hard_min: null\n"
        "  hard_max: 88\n"
        "  preferred_price_bonus: 2.5\n"
        "  momentum: {pct_chg_full: 7}\n"
        "etf:\n"
        "  enabled: true\n"
        "  mode: whitelist\n"
        "  codes: [510300.SH, 159915.SZ]\n",
        encoding="utf-8",
    )

    rules = load_rules(yaml_file)

    assert rules.recommender.strategy_version == "recommend_v2_custom"
    assert rules.recommender.hard_min is None
    assert rules.recommender.hard_max == 88.0
    assert rules.recommender.preferred_price_bonus == 2.5
    assert rules.recommender.momentum.pct_chg_full == 7.0
    assert rules.recommender.momentum.pct_chg_min == 0.0
    assert rules.etf.enabled is True
    assert rules.etf.mode is EtfMode.WHITELIST
    assert rules.etf.codes == ("510300.SH", "159915.SZ")


@pytest.mark.parametrize(
    "yaml_text, expected_path",
    [
        ("etf: {enabled: 'false'}\n", "rules.etf.enabled"),
        ("etf: {mode: 1}\n", "rules.etf.mode"),
        ("etf: {codes: 510300.SH}\n", "rules.etf.codes"),
        ("recommender: {strategy_version: 2}\n", "rules.recommender.strategy_version"),
        ("recommender: {hard_min: 'null'}\n", "rules.recommender.hard_min"),
    ],
)
def test_load_rules_rejects_wrong_scalar_types(tmp_path, yaml_text, expected_path):
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(RulesValidationError, match=expected_path):
        load_rules(yaml_file)


def test_load_rules_rejects_unknown_keys(tmp_path):
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text("recommender:\n  momentum:\n    typo_threshold: 3\n", encoding="utf-8")

    with pytest.raises(RulesValidationError, match=r"rules\.recommender\.momentum\.typo_threshold"):
        load_rules(yaml_file)


@pytest.mark.parametrize(
    "yaml_text, expected_message",
    [
        ("recommender: {hard_min: 30, hard_max: 20}\n", "hard_min cannot exceed hard_max"),
        ("recommender: {minimum_quality_score: 101}\n", "minimum_quality_score"),
        ("recommender: {max_results: 6}\n", "max_results"),
        ("recommender:\n  momentum: {pct_chg_min: 6, pct_chg_full: 6}\n", "pct_chg"),
        ("etf: {mode: all}\n", "must be one of"),
        ("etf: {codes: [510300.SH, BAD]}\n", "invalid ETF code"),
        ("etf: {codes: [510300.SH, 510300.SH]}\n", "duplicates"),
    ],
)
def test_load_rules_rejects_semantically_invalid_values(tmp_path, yaml_text, expected_message):
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(RulesValidationError, match=expected_message):
        load_rules(yaml_file)


def test_load_rules_invalid_yaml_raises_clear_error(tmp_path):
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text("analysis: [unclosed", encoding="utf-8")

    with pytest.raises(RulesValidationError, match="Cannot parse rules file"):
        load_rules(yaml_file)


def test_packaged_rules_yaml_exists_and_matches_defaults():
    assert DEFAULT_RULES_FILE.exists()
    assert load_rules(DEFAULT_RULES_FILE) == Rules()


def test_load_rules_env_override(tmp_path, monkeypatch):
    yaml_file = tmp_path / "custom.yaml"
    yaml_file.write_text("recommender: {minimum_quality_score: 60}\n", encoding="utf-8")
    monkeypatch.setattr(rules_module, "RULES_ALLOWED_DIR", tmp_path)
    monkeypatch.setenv("TRADEEYE_RULES_FILE", str(yaml_file))

    assert load_rules().recommender.minimum_quality_score == 60
