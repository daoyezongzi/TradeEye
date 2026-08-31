from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import UnionType
from typing import Any, Mapping, Union, get_args, get_origin, get_type_hints

import yaml

from tradeeye.config import STRATEGIES_DIR, resolve_repo_path

RULES_FILE_ENV = "TRADEEYE_RULES_FILE"
DEFAULT_RULES_FILE = Path(__file__).with_name("rules.yaml")
RULES_ALLOWED_DIR = STRATEGIES_DIR.resolve()


@dataclass(frozen=True)
class MarketRegimeRule:
    strong_min: float = 15.0
    strong_score: float = 10.0
    weak_max: float = -15.0
    weak_penalty: float = -15.0


@dataclass(frozen=True)
class MaAlignmentRule:
    full_score: float = 18.0
    mid_score: float = 12.0
    weak_score: float = 6.0
    fail_penalty: float = -10.0


@dataclass(frozen=True)
class Ma5SlopeRule:
    up_min: float = 0.2
    up_score: float = 4.0
    down_max: float = -0.2
    down_penalty: float = -4.0


@dataclass(frozen=True)
class CloseStrengthRule:
    strong_min: float = 0.8
    strong_score: float = 18.0
    mid_min: float = 0.68
    mid_score: float = 10.0
    weak_max: float = 0.45
    weak_penalty: float = -15.0


@dataclass(frozen=True)
class PctChgRule:
    sweet_min: float = 1.2
    sweet_max: float = 6.5
    sweet_score: float = 12.0
    mild_score: float = 5.0
    weak_max: float = -1.5
    weak_penalty: float = -18.0
    hot_min: float = 8.0
    hot_penalty: float = -12.0


@dataclass(frozen=True)
class CandleBodyRule:
    bull_score: float = 8.0
    bear_penalty: float = -4.0


@dataclass(frozen=True)
class UpperShadowRule:
    short_max: float = 1.2
    short_score: float = 6.0
    long_min: float = 2.5
    long_penalty: float = -10.0


@dataclass(frozen=True)
class TurnoverRule:
    sweet_min: float = 2.0
    sweet_max: float = 12.0
    sweet_score: float = 10.0
    ok_min: float = 0.8
    ok_score: float = 4.0
    hot_min: float = 18.0
    hot_penalty: float = -8.0
    cold_penalty: float = -8.0


@dataclass(frozen=True)
class AmountRatioRule:
    sweet_min: float = 1.2
    sweet_max: float = 3.0
    sweet_score: float = 10.0
    hot_min: float = 4.0
    hot_penalty: float = -6.0
    cold_max: float = 0.8
    cold_penalty: float = -6.0


@dataclass(frozen=True)
class VolumeRatioRule:
    sweet_min: float = 1.0
    sweet_max: float = 2.5
    sweet_score: float = 8.0
    hot_min: float = 4.0
    hot_penalty: float = -4.0
    cold_max: float = 0.6
    cold_penalty: float = -4.0


@dataclass(frozen=True)
class NetMfRule:
    strong_min: float = 3.0
    strong_score: float = 14.0
    ok_min: float = 1.0
    ok_score: float = 8.0
    weak_max: float = -2.0
    weak_penalty: float = -14.0


@dataclass(frozen=True)
class LargeOrderRule:
    strong_min: float = 2.0
    strong_score: float = 12.0
    ok_min: float = 0.5
    ok_score: float = 6.0
    weak_max: float = -1.0
    weak_penalty: float = -12.0


@dataclass(frozen=True)
class BreakoutRule:
    sweet_min: float = -1.0
    sweet_max: float = 2.5
    sweet_score: float = 8.0
    far_max: float = -3.0
    far_penalty: float = -8.0


@dataclass(frozen=True)
class UpLimitRoomRule:
    sweet_min: float = 2.0
    sweet_max: float = 7.0
    sweet_score: float = 6.0
    near_max: float = 1.2
    near_penalty: float = -10.0


@dataclass(frozen=True)
class RanksRule:
    turnover_rank_min: float = 0.75
    turnover_rank_score: float = 4.0
    net_mf_rank_min: float = 0.8
    net_mf_rank_score: float = 4.0
    large_order_rank_min: float = 0.8
    large_order_rank_score: float = 4.0


@dataclass(frozen=True)
class PenaltiesRule:
    st_penalty: float = -40.0
    new_stock_age_days: int = 120
    new_stock_penalty: float = -25.0
    bj_penalty: float = -20.0


@dataclass(frozen=True)
class AnalysisRuleSet:
    market_regime: MarketRegimeRule = field(default_factory=MarketRegimeRule)
    ma_alignment: MaAlignmentRule = field(default_factory=MaAlignmentRule)
    ma5_slope: Ma5SlopeRule = field(default_factory=Ma5SlopeRule)
    close_strength: CloseStrengthRule = field(default_factory=CloseStrengthRule)
    pct_chg: PctChgRule = field(default_factory=PctChgRule)
    candle_body: CandleBodyRule = field(default_factory=CandleBodyRule)
    upper_shadow: UpperShadowRule = field(default_factory=UpperShadowRule)
    turnover: TurnoverRule = field(default_factory=TurnoverRule)
    amount_ratio_5d: AmountRatioRule = field(default_factory=AmountRatioRule)
    volume_ratio: VolumeRatioRule = field(default_factory=VolumeRatioRule)
    net_mf: NetMfRule = field(default_factory=NetMfRule)
    large_order: LargeOrderRule = field(default_factory=LargeOrderRule)
    breakout: BreakoutRule = field(default_factory=BreakoutRule)
    up_limit_room: UpLimitRoomRule = field(default_factory=UpLimitRoomRule)
    ranks: RanksRule = field(default_factory=RanksRule)
    penalties: PenaltiesRule = field(default_factory=PenaltiesRule)


@dataclass(frozen=True)
class StatusBands:
    strong: float = 80.0
    candidate: float = 65.0
    watch: float = 50.0


@dataclass(frozen=True)
class AnalysisRules:
    status_bands: StatusBands = field(default_factory=StatusBands)
    rules: AnalysisRuleSet = field(default_factory=AnalysisRuleSet)


@dataclass(frozen=True)
class MomentumRule:
    pct_chg_min: float = 0.0
    pct_chg_full: float = 6.0
    pct_rank_min: float = 0.5
    pct_rank_full: float = 0.95


@dataclass(frozen=True)
class RecommendationCloseQualityRule:
    close_strength_min: float = 0.45
    close_strength_full: float = 0.9
    body_pct_min: float = 0.0
    body_pct_full: float = 4.0
    upper_shadow_full: float = 0.5
    upper_shadow_zero: float = 2.5


@dataclass(frozen=True)
class VolumeFundsRule:
    turnover_min: float = 0.8
    turnover_full: float = 12.0
    volume_ratio_min: float = 0.6
    volume_ratio_full: float = 2.5
    amount_rank_min: float = 0.5
    amount_rank_full: float = 0.95
    net_mf_ratio_min: float = 0.0
    net_mf_ratio_full: float = 3.0
    large_order_net_min: float = 0.0
    large_order_net_full: float = 2.0


@dataclass(frozen=True)
class RecommendationRiskGateRule:
    weak_close_max: float = 0.45
    long_upper_shadow_min: float = 2.5
    pct_chg_hot: float = 8.0
    turnover_hot: float = 18.0
    volume_ratio_hot: float = 4.0
    reject_overheat_count: int = 2


@dataclass(frozen=True)
class RecommenderRules:
    strategy_version: str = "recommend_v2"
    minimum_quality_score: float = 55.0
    max_results: int = 5
    hard_min: float | None = None
    hard_max: float | None = None
    preferred_price_max: float = 20.0
    preferred_price_bonus: float = 3.0
    entry_price_multiplier: float = 0.98
    momentum: MomentumRule = field(default_factory=MomentumRule)
    close_quality: RecommendationCloseQualityRule = field(default_factory=RecommendationCloseQualityRule)
    volume_funds: VolumeFundsRule = field(default_factory=VolumeFundsRule)
    risk_gate: RecommendationRiskGateRule = field(default_factory=RecommendationRiskGateRule)


class EtfMode(str, Enum):
    WHITELIST = "whitelist"


@dataclass(frozen=True)
class EtfMomentumRule:
    pct_chg_min: float = 0.0
    pct_chg_full: float = 5.0
    pct_rank_min: float = 0.5
    pct_rank_full: float = 0.95


@dataclass(frozen=True)
class EtfLiquidityRule:
    amount_min: float = 20_000.0
    amount_full: float = 500_000.0
    amount_rank_min: float = 0.5
    amount_rank_full: float = 0.95


@dataclass(frozen=True)
class EtfRules:
    enabled: bool = False
    mode: EtfMode = EtfMode.WHITELIST
    codes: tuple[str, ...] = ()
    strategy_version: str = "etf_recommend_v1"
    minimum_quality_score: float = 50.0
    max_results: int = 5
    entry_price_multiplier: float = 0.98
    momentum: EtfMomentumRule = field(default_factory=EtfMomentumRule)
    close_quality: RecommendationCloseQualityRule = field(default_factory=RecommendationCloseQualityRule)
    liquidity: EtfLiquidityRule = field(default_factory=EtfLiquidityRule)


@dataclass(frozen=True)
class Rules:
    analysis: AnalysisRules = field(default_factory=AnalysisRules)
    recommender: RecommenderRules = field(default_factory=RecommenderRules)
    etf: EtfRules = field(default_factory=EtfRules)


class RulesValidationError(ValueError):
    """Raised when a rules file does not match the versioned schema."""


def load_rules(path: str | Path | None = None) -> Rules:
    defaults = Rules()
    env_path = os.getenv(RULES_FILE_ENV, "").strip()
    if path is not None:
        # Explicit callers may provide an isolated test/configuration path.
        # The environment-controlled production override is scoped below.
        rules_path = Path(path)
    elif env_path:
        try:
            rules_path = resolve_repo_path(env_path, RULES_ALLOWED_DIR, RULES_FILE_ENV)
        except ValueError as exc:
            raise RulesValidationError(str(exc)) from exc
    else:
        rules_path = DEFAULT_RULES_FILE
    if not rules_path.exists():
        raise RulesValidationError(f"Rules file does not exist: {rules_path}")

    try:
        raw = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RulesValidationError(f"Cannot parse rules file {rules_path}: {exc}") from exc

    if raw is None:
        return defaults
    if not isinstance(raw, Mapping):
        raise RulesValidationError(f"Rules file {rules_path} must contain a mapping")

    merged = _merge_dataclass(defaults, raw)
    _validate_rules(merged)
    return merged


@lru_cache(maxsize=1)
def get_rules() -> Rules:
    return load_rules()


def _merge_dataclass(instance: Any, data: Mapping[str, Any], path: str = "rules") -> Any:
    known_fields = {item.name for item in fields(instance)}
    unknown_fields = sorted(set(data) - known_fields, key=str)
    if unknown_fields:
        unknown_text = ", ".join(f"{path}.{name}" for name in unknown_fields)
        raise RulesValidationError(f"Unknown rules key(s): {unknown_text}")

    type_hints = get_type_hints(type(instance))
    updates: dict[str, Any] = {}
    for f in fields(instance):
        if f.name not in data:
            continue
        current = getattr(instance, f.name)
        incoming = data[f.name]
        field_path = f"{path}.{f.name}"
        updates[f.name] = _coerce_rule_value(incoming, type_hints[f.name], current, field_path)
    return replace(instance, **updates)


def _coerce_rule_value(incoming: Any, annotation: Any, current: Any, path: str) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in (Union, UnionType):
        none_allowed = type(None) in args
        if incoming is None:
            if none_allowed:
                return None
            raise RulesValidationError(f"{path} does not allow null")
        non_null = [item for item in args if item is not type(None)]
        if len(non_null) == 1:
            return _coerce_rule_value(incoming, non_null[0], current, path)

    if incoming is None:
        raise RulesValidationError(f"{path} does not allow null")

    if is_dataclass(current):
        if not isinstance(incoming, Mapping):
            raise RulesValidationError(f"{path} must be a mapping")
        return _merge_dataclass(current, incoming, path)

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        if type(incoming) is not str:
            raise RulesValidationError(f"{path} must be a string enum value")
        try:
            return annotation(incoming)
        except ValueError as exc:
            allowed = ", ".join(str(item.value) for item in annotation)
            raise RulesValidationError(f"{path} must be one of: {allowed}") from exc

    if annotation is bool:
        if type(incoming) is not bool:
            raise RulesValidationError(f"{path} must be a boolean")
        return incoming

    if annotation is str:
        if type(incoming) is not str:
            raise RulesValidationError(f"{path} must be a string")
        return incoming

    if annotation is float:
        if not isinstance(incoming, (int, float)) or isinstance(incoming, bool):
            raise RulesValidationError(f"{path} must be a number")
        return float(incoming)

    if annotation is int:
        if type(incoming) is not int:
            raise RulesValidationError(f"{path} must be an integer")
        return incoming

    if origin in (tuple, list):
        if type(incoming) is not list:
            raise RulesValidationError(f"{path} must be a list")
        item_type = args[0] if args else Any
        converted = [_coerce_rule_value(item, item_type, None, f"{path}[{index}]") for index, item in enumerate(incoming)]
        return tuple(converted) if origin is tuple else converted

    if annotation is Any:
        return incoming
    raise RulesValidationError(f"{path} has unsupported schema type {annotation!r}")


def _validate_rules(rules: Rules) -> None:
    bands = rules.analysis.status_bands
    if not 0 <= bands.watch <= bands.candidate <= bands.strong <= 100:
        raise RulesValidationError("rules.analysis.status_bands must satisfy 0 <= watch <= candidate <= strong <= 100")
    rec = rules.recommender
    _require_strategy_version("rules.recommender.strategy_version", rec.strategy_version)
    _require_between("rules.recommender.minimum_quality_score", rec.minimum_quality_score, 0, 100)
    if not 1 <= rec.max_results <= 5:
        raise RulesValidationError("rules.recommender.max_results must be between 1 and 5")
    for name, value in (("hard_min", rec.hard_min), ("hard_max", rec.hard_max)):
        if value is not None and value <= 0:
            raise RulesValidationError(f"rules.recommender.{name} must be positive or null")
    if rec.hard_min is not None and rec.hard_max is not None and rec.hard_min > rec.hard_max:
        raise RulesValidationError("rules.recommender.hard_min cannot exceed hard_max")
    if rec.preferred_price_max <= 0:
        raise RulesValidationError("rules.recommender.preferred_price_max must be positive")
    _require_between("rules.recommender.preferred_price_bonus", rec.preferred_price_bonus, 0, 10)
    _require_between("rules.recommender.entry_price_multiplier", rec.entry_price_multiplier, 0.01, 1.0)
    _validate_linear_rule("rules.recommender.momentum.pct_chg", rec.momentum.pct_chg_min, rec.momentum.pct_chg_full)
    _validate_rank_rule("rules.recommender.momentum.pct_rank", rec.momentum.pct_rank_min, rec.momentum.pct_rank_full)
    _validate_close_quality("rules.recommender.close_quality", rec.close_quality)
    volume = rec.volume_funds
    _validate_linear_rule("rules.recommender.volume_funds.turnover", volume.turnover_min, volume.turnover_full)
    _validate_linear_rule("rules.recommender.volume_funds.volume_ratio", volume.volume_ratio_min, volume.volume_ratio_full)
    _validate_rank_rule("rules.recommender.volume_funds.amount_rank", volume.amount_rank_min, volume.amount_rank_full)
    _validate_linear_rule("rules.recommender.volume_funds.net_mf_ratio", volume.net_mf_ratio_min, volume.net_mf_ratio_full)
    _validate_linear_rule(
        "rules.recommender.volume_funds.large_order_net",
        volume.large_order_net_min,
        volume.large_order_net_full,
    )
    risk = rec.risk_gate
    _require_between("rules.recommender.risk_gate.weak_close_max", risk.weak_close_max, 0, 1)
    if min(risk.long_upper_shadow_min, risk.pct_chg_hot, risk.turnover_hot, risk.volume_ratio_hot) <= 0:
        raise RulesValidationError("rules.recommender.risk_gate thresholds must be positive")
    if not 1 <= risk.reject_overheat_count <= 3:
        raise RulesValidationError("rules.recommender.risk_gate.reject_overheat_count must be between 1 and 3")

    etf = rules.etf
    _require_strategy_version("rules.etf.strategy_version", etf.strategy_version)
    _require_between("rules.etf.minimum_quality_score", etf.minimum_quality_score, 0, 100)
    if not 1 <= etf.max_results <= 20:
        raise RulesValidationError("rules.etf.max_results must be between 1 and 20")
    _require_between("rules.etf.entry_price_multiplier", etf.entry_price_multiplier, 0.01, 1.0)
    if len(set(etf.codes)) != len(etf.codes):
        raise RulesValidationError("rules.etf.codes must not contain duplicates")
    for code in etf.codes:
        if not re.fullmatch(r"\d{6}\.(?:SH|SZ)", code):
            raise RulesValidationError(f"rules.etf.codes contains invalid ETF code: {code!r}")
    _validate_linear_rule("rules.etf.momentum.pct_chg", etf.momentum.pct_chg_min, etf.momentum.pct_chg_full)
    _validate_rank_rule("rules.etf.momentum.pct_rank", etf.momentum.pct_rank_min, etf.momentum.pct_rank_full)
    _validate_close_quality("rules.etf.close_quality", etf.close_quality)
    _validate_linear_rule("rules.etf.liquidity.amount", etf.liquidity.amount_min, etf.liquidity.amount_full)
    _validate_rank_rule("rules.etf.liquidity.amount_rank", etf.liquidity.amount_rank_min, etf.liquidity.amount_rank_full)


def _validate_close_quality(path: str, rule: RecommendationCloseQualityRule) -> None:
    _validate_rank_rule(f"{path}.close_strength", rule.close_strength_min, rule.close_strength_full)
    _validate_linear_rule(f"{path}.body_pct", rule.body_pct_min, rule.body_pct_full)
    if not 0 <= rule.upper_shadow_full < rule.upper_shadow_zero:
        raise RulesValidationError(f"{path} must satisfy 0 <= upper_shadow_full < upper_shadow_zero")


def _validate_linear_rule(path: str, minimum: float, full: float) -> None:
    if minimum >= full:
        raise RulesValidationError(f"{path}_min must be lower than {path}_full")


def _validate_rank_rule(path: str, minimum: float, full: float) -> None:
    if not 0 <= minimum < full <= 1:
        raise RulesValidationError(f"{path} must satisfy 0 <= min < full <= 1")


def _require_strategy_version(path: str, value: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise RulesValidationError(f"{path} must use lowercase letters, digits, and underscores")


def _require_between(path: str, value: float, minimum: float, maximum: float) -> None:
    if not minimum <= value <= maximum:
        raise RulesValidationError(f"{path} must be between {minimum} and {maximum}")
