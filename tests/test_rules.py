from tradeeye.strategies.rules import Rules, load_rules


def test_defaults_match_current_hardcoded_values():
    rules = Rules()
    assert rules.analysis.llm_score_threshold == 70
    assert rules.analysis.status_bands.strong == 80
    assert rules.analysis.status_bands.candidate == 65
    assert rules.analysis.status_bands.watch == 50
    assert rules.analysis.rules.ma_alignment.full_score == 18
    assert rules.analysis.rules.close_strength.strong_min == 0.8
    assert rules.analysis.rules.pct_chg.sweet_max == 6.5
    assert rules.analysis.rules.penalties.st_penalty == -40
    assert rules.analysis.rules.penalties.new_stock_age_days == 120
    assert rules.recommender.short_burst.volume_ratio_min == 2.0
    assert rules.recommender.t_active.amount_min == 500_000
    assert rules.recommender.long_value.pe_rank_max == 0.4
    assert rules.recommender.weights.short_burst == 0.4
    assert rules.recommender.weights.multi_dim_bonus == 4.0
    assert rules.recommender.price_ranges.low == (0.0, 10.0)
    assert rules.recommender.price_ranges.mid == (10.0, 20.0)
    assert rules.recommender.price_ranges.max_price == 20.0


def test_load_rules_missing_file_returns_defaults(tmp_path):
    assert load_rules(tmp_path / "missing.yaml") == Rules()


def test_load_rules_overrides_and_keeps_unset_fields(tmp_path):
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        "analysis:\n"
        "  llm_score_threshold: 55\n"
        "  rules:\n"
        "    turnover: {sweet_min: 3}\n"
        "recommender:\n"
        "  weights: {short_burst: 0.5}\n"
        "  price_ranges: {low: [0, 8]}\n",
        encoding="utf-8",
    )
    rules = load_rules(yaml_file)
    assert rules.analysis.llm_score_threshold == 55
    assert rules.analysis.rules.turnover.sweet_min == 3
    assert rules.analysis.rules.turnover.sweet_max == 12  # 未覆盖字段保持默认
    assert rules.recommender.weights.short_burst == 0.5
    assert rules.recommender.price_ranges.low == (0.0, 8.0)
    assert rules.recommender.price_ranges.mid == (10.0, 20.0)


def test_load_rules_invalid_yaml_falls_back(tmp_path):
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text("analysis: [unclosed", encoding="utf-8")
    assert load_rules(yaml_file) == Rules()


def test_load_rules_invalid_value_type_ignored(tmp_path):
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text("analysis:\n  llm_score_threshold: not-a-number\n", encoding="utf-8")
    assert load_rules(yaml_file) == Rules()


def test_load_rules_env_override(tmp_path, monkeypatch):
    yaml_file = tmp_path / "custom.yaml"
    yaml_file.write_text("analysis: {llm_score_threshold: 60}\n", encoding="utf-8")
    monkeypatch.setenv("TRADEEYE_RULES_FILE", str(yaml_file))
    assert load_rules().analysis.llm_score_threshold == 60
