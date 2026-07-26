from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, fields, is_dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

logger = logging.getLogger(__name__)

RULES_FILE_ENV = "TRADEEYE_RULES_FILE"
DEFAULT_RULES_FILE = Path(__file__).with_name("rules.yaml")


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
    llm_score_threshold: float = 70.0
    status_bands: StatusBands = field(default_factory=StatusBands)
    rules: AnalysisRuleSet = field(default_factory=AnalysisRuleSet)


@dataclass(frozen=True)
class ShortBurstRule:
    volume_ratio_min: float = 2.0
    turnover_min: float = 5.0
    turnover_max: float = 15.0
    pct_chg_min: float = 2.0


@dataclass(frozen=True)
class TActiveRule:
    amplitude_min: float = 4.5
    amount_min: float = 500_000.0


@dataclass(frozen=True)
class LongValueRule:
    pe_rank_max: float = 0.4
    mv_rank_min: float = 0.8


@dataclass(frozen=True)
class RecommenderWeights:
    short_burst: float = 0.4
    t_active: float = 0.3
    long_value: float = 0.3
    multi_dim_bonus: float = 4.0


@dataclass(frozen=True)
class PriceRanges:
    low: tuple[float, float] = (0.0, 10.0)
    mid: tuple[float, float] = (10.0, 20.0)

    @property
    def max_price(self) -> float:
        return max(self.low[1], self.mid[1])


@dataclass(frozen=True)
class RecommenderRules:
    short_burst: ShortBurstRule = field(default_factory=ShortBurstRule)
    t_active: TActiveRule = field(default_factory=TActiveRule)
    long_value: LongValueRule = field(default_factory=LongValueRule)
    weights: RecommenderWeights = field(default_factory=RecommenderWeights)
    price_ranges: PriceRanges = field(default_factory=PriceRanges)


@dataclass(frozen=True)
class Rules:
    analysis: AnalysisRules = field(default_factory=AnalysisRules)
    recommender: RecommenderRules = field(default_factory=RecommenderRules)


def load_rules(path: str | Path | None = None) -> Rules:
    defaults = Rules()
    env_path = os.getenv(RULES_FILE_ENV, "").strip()
    rules_path = Path(path or env_path or DEFAULT_RULES_FILE)
    if not rules_path.exists():
        return defaults

    try:
        raw = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to parse rules file %s, falling back to defaults", rules_path, exc_info=True)
        return defaults

    if not isinstance(raw, Mapping):
        if raw is not None:
            logger.warning("Rules file %s is not a mapping, falling back to defaults", rules_path)
        return defaults

    return _merge_dataclass(defaults, raw)


@lru_cache(maxsize=1)
def get_rules() -> Rules:
    return load_rules()


def _merge_dataclass(instance: Any, data: Mapping[str, Any]) -> Any:
    updates: dict[str, Any] = {}
    for f in fields(instance):
        if f.name not in data:
            continue
        current = getattr(instance, f.name)
        incoming = data[f.name]
        if is_dataclass(current):
            if isinstance(incoming, Mapping):
                updates[f.name] = _merge_dataclass(current, incoming)
            else:
                logger.warning("Ignoring rules key %s: expected mapping", f.name)
        elif isinstance(current, tuple):
            if isinstance(incoming, (list, tuple)) and len(incoming) == len(current):
                try:
                    updates[f.name] = tuple(float(item) for item in incoming)
                except (TypeError, ValueError):
                    logger.warning("Ignoring rules key %s: expected numbers", f.name)
            else:
                logger.warning("Ignoring rules key %s: expected list of %d numbers", f.name, len(current))
        elif isinstance(incoming, (int, float)) and not isinstance(incoming, bool):
            updates[f.name] = type(current)(incoming)
        else:
            logger.warning("Ignoring rules key %s: expected number", f.name)
    return replace(instance, **updates)
