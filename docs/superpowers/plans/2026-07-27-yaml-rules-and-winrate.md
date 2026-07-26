# 打分规则外置 + 胜率追踪 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把两套策略的阈值/分值外置到 rules.yaml（纯重构不改行为），并建立每日信号 CSV 落地 + 每周胜率回测推飞书的闭环。

**Architecture:** 新增 `tradeeye/strategies/rules.py`（frozen dataclass 默认值 = 现行硬编码值，yaml 覆盖，缺失回退）；新增 `tradeeye/services/signal_store.py`（CSV 追加+去重）与 `tradeeye/services/backtest.py`（T+1 胜率计算）；第四条工作流 backtest 每周五推飞书。所有编排层沿用现有依赖注入风格。

**Tech Stack:** Python 3.13, dataclasses, PyYAML（已在 requirements）, pandas, tushare, pytest。

**Spec:** `docs/superpowers/specs/2026-07-26-yaml-rules-and-winrate-design.md`

**约定：** 每个 Task 完成后必须 `python -m pytest -q` 全绿再 commit。仓库 `.gitignore` 有 `*.csv` 全局忽略，Task 7 会加 `!data/signals/*.csv` 例外——不加这条，Actions 提交信号会静默失败。

## 文件结构

| 动作 | 路径 | 职责 |
|---|---|---|
| 新增 | `tradeeye/strategies/rules.py` | 规则 dataclass + yaml 加载/合并/回退 |
| 新增 | `tradeeye/strategies/rules.yaml` | 默认规则参数（与 dataclass 默认值一致） |
| 新增 | `tradeeye/services/signal_store.py` | 信号 CSV 追加写入与去重 |
| 新增 | `tradeeye/services/backtest.py` | 信号加载、T+1 收益计算、周报文本 |
| 新增 | `tradeeye/backtest_app.py` + `backtest_main.py` | 回测编排 + 入口壳 |
| 新增 | `.github/workflows/TradeEye-backtest-1.0.0.yml` | 每周五回测工作流 |
| 修改 | `tradeeye/strategies/strategy.py` | 魔法数字 → rules 字段；删 `load_yaml_config` |
| 修改 | `tradeeye/strategies/stock_recommender.py` | 常量 → rules 字段 |
| 修改 | `tradeeye/app.py`、`tradeeye/recommend_app.py` | LLM 门槛读 rules；接入信号落地 |
| 修改 | `tradeeye/config.py` | 删 `PRICE_RANGES`；加 `backtest_lookback_days` |
| 修改 | `strategies/strategy.py`、`strategies/__init__.py`、`tradeeye/strategies/__init__.py` | 移除 `load_yaml_config` re-export |
| 修改 | `.github/workflows/TradeEye-1.0.0.yml`、`.gitignore`、`README.md` | 信号提交步骤、CSV 白名单、文档 |

---

### Task 1: rules.py — 规则 dataclass 与加载器

**Files:**
- Create: `tradeeye/strategies/rules.py`
- Test: `tests/test_rules.py`

- [ ] **Step 1: 写失败测试**

`tests/test_rules.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_rules.py -q`
Expected: FAIL（ModuleNotFoundError: tradeeye.strategies.rules）

- [ ] **Step 3: 实现 rules.py**

`tradeeye/strategies/rules.py` 完整内容：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_rules.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add tradeeye/strategies/rules.py tests/test_rules.py
git commit -m "feat: 新增规则 dataclass 与 yaml 加载器"
```

---

### Task 2: rules.yaml — 打包默认规则文件

**Files:**
- Create: `tradeeye/strategies/rules.yaml`
- Test: `tests/test_rules.py`（追加）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_rules.py`）

```python
def test_packaged_rules_yaml_exists_and_matches_defaults():
    from tradeeye.strategies.rules import DEFAULT_RULES_FILE

    assert DEFAULT_RULES_FILE.exists()
    assert load_rules(DEFAULT_RULES_FILE) == Rules()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_rules.py::test_packaged_rules_yaml_exists_and_matches_defaults -q`
Expected: FAIL（文件不存在）

- [ ] **Step 3: 创建 rules.yaml**

`tradeeye/strategies/rules.yaml` 完整内容（数值与 dataclass 默认值一一对应）：

```yaml
# TradeEye 策略规则参数。改这里即可调参，不用改代码。
# 缺失的键自动回退代码内默认值。可用环境变量 TRADEEYE_RULES_FILE 指向其他文件做参数实验。
analysis:
  llm_score_threshold: 70          # 本地得分 >= 此值才调用 LLM
  status_bands: {strong: 80, candidate: 65, watch: 50}
  rules:
    market_regime: {strong_min: 15, strong_score: 10, weak_max: -15, weak_penalty: -15}
    ma_alignment: {full_score: 18, mid_score: 12, weak_score: 6, fail_penalty: -10}
    ma5_slope: {up_min: 0.2, up_score: 4, down_max: -0.2, down_penalty: -4}
    close_strength: {strong_min: 0.8, strong_score: 18, mid_min: 0.68, mid_score: 10,
                     weak_max: 0.45, weak_penalty: -15}
    pct_chg: {sweet_min: 1.2, sweet_max: 6.5, sweet_score: 12, mild_score: 5,
              weak_max: -1.5, weak_penalty: -18, hot_min: 8, hot_penalty: -12}
    candle_body: {bull_score: 8, bear_penalty: -4}
    upper_shadow: {short_max: 1.2, short_score: 6, long_min: 2.5, long_penalty: -10}
    turnover: {sweet_min: 2, sweet_max: 12, sweet_score: 10, ok_min: 0.8, ok_score: 4,
               hot_min: 18, hot_penalty: -8, cold_penalty: -8}
    amount_ratio_5d: {sweet_min: 1.2, sweet_max: 3, sweet_score: 10,
                      hot_min: 4, hot_penalty: -6, cold_max: 0.8, cold_penalty: -6}
    volume_ratio: {sweet_min: 1, sweet_max: 2.5, sweet_score: 8,
                   hot_min: 4, hot_penalty: -4, cold_max: 0.6, cold_penalty: -4}
    net_mf: {strong_min: 3, strong_score: 14, ok_min: 1, ok_score: 8,
             weak_max: -2, weak_penalty: -14}
    large_order: {strong_min: 2, strong_score: 12, ok_min: 0.5, ok_score: 6,
                  weak_max: -1, weak_penalty: -12}
    breakout: {sweet_min: -1, sweet_max: 2.5, sweet_score: 8, far_max: -3, far_penalty: -8}
    up_limit_room: {sweet_min: 2, sweet_max: 7, sweet_score: 6, near_max: 1.2, near_penalty: -10}
    ranks: {turnover_rank_min: 0.75, turnover_rank_score: 4,
            net_mf_rank_min: 0.8, net_mf_rank_score: 4,
            large_order_rank_min: 0.8, large_order_rank_score: 4}
    penalties: {st_penalty: -40, new_stock_age_days: 120, new_stock_penalty: -25, bj_penalty: -20}
recommender:
  short_burst: {volume_ratio_min: 2.0, turnover_min: 5.0, turnover_max: 15.0, pct_chg_min: 2.0}
  t_active: {amplitude_min: 4.5, amount_min: 500000}
  long_value: {pe_rank_max: 0.4, mv_rank_min: 0.8}
  weights: {short_burst: 0.4, t_active: 0.3, long_value: 0.3, multi_dim_bonus: 4}
  price_ranges: {low: [0, 10], mid: [10, 20]}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_rules.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add tradeeye/strategies/rules.yaml tests/test_rules.py
git commit -m "feat: 打包默认 rules.yaml"
```

---
### Task 3: strategy.py 改用 rules（纯重构）

**Files:**
- Modify: `tradeeye/strategies/strategy.py`（整文件替换）
- Modify: `tradeeye/strategies/__init__.py`、`strategies/strategy.py`、`strategies/__init__.py`（移除 load_yaml_config re-export）
- Test: 现有 `tests/test_strategy.py` 不改动，必须保持全绿（这就是"纯重构"的验证）

- [ ] **Step 1: 整文件替换 `tradeeye/strategies/strategy.py`**

```python
from __future__ import annotations

from typing import Any

from tradeeye.strategies.rules import AnalysisRules, get_rules


def check_signals(data: dict[str, Any], rules: AnalysisRules | None = None) -> dict[str, Any]:
    if not data or "latest" not in data or "prev" not in data:
        return {
            "score": 0,
            "status": "【数据缺失】",
            "detail": "无法获取隔夜策略所需行情",
            "risk": "数据不足",
            "vol_ratio": 0.0,
            "turnover_rate": 0.0,
            "amount_ratio_5d": 0.0,
            "net_mf_ratio_pct": 0.0,
            "large_order_net_pct": 0.0,
            "up_limit_room_pct": 0.0,
            "close_strength": 0.0,
            "breakout_pct": 0.0,
            "market_bias": "未知",
            "action_plan": "跳过本次分析。",
        }

    rules = rules or get_rules().analysis
    r = rules.rules

    latest = data["latest"]
    prev = data["prev"]
    market_regime = data.get("market_regime", {})

    close = _to_float(latest.get("close"))
    open_price = _to_float(latest.get("open"))
    pct_chg = _to_float(latest.get("pct_chg"))
    turnover_rate = _to_float(latest.get("turnover_rate"))
    volume_ratio = _pick_first_float(latest.get("volume_ratio"), latest.get("day_vol_ratio"))
    amount_ratio_5d = _to_float(latest.get("amount_ratio_5d"))
    net_mf_ratio_pct = _to_float(latest.get("net_mf_ratio_pct"))
    large_order_net_pct = _to_float(latest.get("large_order_net_pct"))
    up_limit_room_pct = _to_float(latest.get("up_limit_room_pct"))
    close_strength = _to_float(latest.get("close_strength"))
    upper_shadow_pct = _to_float(latest.get("upper_shadow_pct"))
    breakout_pct = _to_float(latest.get("breakout_10_pct"))
    ma5 = _to_float(latest.get("ma5"))
    ma10 = _to_float(latest.get("ma10"))
    ma20 = _to_float(latest.get("ma20"))
    ma5_slope_pct = _to_float(latest.get("ma5_slope_pct"))
    turnover_pct_rank = _to_float(latest.get("turnover_pct_rank"))
    net_mf_ratio_rank = _to_float(latest.get("net_mf_ratio_rank"))
    large_order_net_rank = _to_float(latest.get("large_order_net_rank"))
    list_age_days = int(_to_float(latest.get("list_age_days")))
    market_score = _to_float(market_regime.get("score"))
    market_bias = str(market_regime.get("status", "未知"))
    stock_name = str(data.get("name") or latest.get("name") or "")
    ts_code = str(latest.get("ts_code") or "")
    board_name = str(latest.get("market") or "")

    score = 0.0
    reasons: list[str] = []
    risks: list[str] = []

    if market_score >= r.market_regime.strong_min:
        score += r.market_regime.strong_score
        reasons.append("市场收盘情绪偏强")
    elif market_score <= r.market_regime.weak_max:
        score += r.market_regime.weak_penalty
        risks.append("全市场收盘偏弱，隔夜溢价容易被压缩")

    if close > ma5 > ma10 > ma20 and ma20 > 0:
        score += r.ma_alignment.full_score
        reasons.append("收盘位于多头均线之上")
    elif close > ma5 > ma10 and ma10 > 0:
        score += r.ma_alignment.mid_score
        reasons.append("短线均线保持上拐")
    elif close > ma5 and ma5 > 0:
        score += r.ma_alignment.weak_score
        reasons.append("收盘仍守住短均线")
    else:
        score += r.ma_alignment.fail_penalty
        risks.append("收盘失守短均线")

    if ma5_slope_pct > r.ma5_slope.up_min:
        score += r.ma5_slope.up_score
        reasons.append("MA5 继续抬升")
    elif ma5_slope_pct < r.ma5_slope.down_max:
        score += r.ma5_slope.down_penalty
        risks.append("MA5 走平转弱")

    if close_strength >= r.close_strength.strong_min:
        score += r.close_strength.strong_score
        reasons.append("收盘靠近日内高位，尾盘承接较强")
    elif close_strength >= r.close_strength.mid_min:
        score += r.close_strength.mid_score
        reasons.append("收盘位置偏强")
    elif close_strength < r.close_strength.weak_max:
        score += r.close_strength.weak_penalty
        risks.append("收盘位置偏低，尾盘不够强")

    if r.pct_chg.sweet_min <= pct_chg <= r.pct_chg.sweet_max:
        score += r.pct_chg.sweet_score
        reasons.append("涨幅适中，兼顾动能和次日空间")
    elif 0 < pct_chg < r.pct_chg.sweet_min:
        score += r.pct_chg.mild_score
        reasons.append("日内温和走强")
    elif pct_chg < r.pct_chg.weak_max:
        score += r.pct_chg.weak_penalty
        risks.append("收盘偏弱，不适合做隔夜")
    elif pct_chg > r.pct_chg.hot_min:
        score += r.pct_chg.hot_penalty
        risks.append("涨幅过大，次日追高风险高")

    if close > open_price:
        score += r.candle_body.bull_score
        reasons.append("实体收阳")
    else:
        score += r.candle_body.bear_penalty
        risks.append("收盘未能站上开盘价")

    if upper_shadow_pct <= r.upper_shadow.short_max:
        score += r.upper_shadow.short_score
        reasons.append("上影线短，抛压可控")
    elif upper_shadow_pct > r.upper_shadow.long_min:
        score += r.upper_shadow.long_penalty
        risks.append("上影较长，尾盘抛压偏重")

    if r.turnover.sweet_min <= turnover_rate <= r.turnover.sweet_max:
        score += r.turnover.sweet_score
        reasons.append("换手处于短线舒适区间")
    elif r.turnover.ok_min <= turnover_rate < r.turnover.sweet_min:
        score += r.turnover.ok_score
        reasons.append("换手合格但不算活跃")
    elif turnover_rate > r.turnover.hot_min:
        score += r.turnover.hot_penalty
        risks.append("换手过热，隔夜一致性风险升高")
    else:
        score += r.turnover.cold_penalty
        risks.append("换手不足，次日兑现流动性偏弱")

    if r.amount_ratio_5d.sweet_min <= amount_ratio_5d <= r.amount_ratio_5d.sweet_max:
        score += r.amount_ratio_5d.sweet_score
        reasons.append("成交额较近五日明显放大")
    elif amount_ratio_5d > r.amount_ratio_5d.hot_min:
        score += r.amount_ratio_5d.hot_penalty
        risks.append("放量过猛，容易透支次日空间")
    elif 0 < amount_ratio_5d < r.amount_ratio_5d.cold_max:
        score += r.amount_ratio_5d.cold_penalty
        risks.append("成交额未放大，尾盘跟风不足")

    if r.volume_ratio.sweet_min <= volume_ratio <= r.volume_ratio.sweet_max:
        score += r.volume_ratio.sweet_score
        reasons.append("量比配合合理")
    elif volume_ratio > r.volume_ratio.hot_min:
        score += r.volume_ratio.hot_penalty
        risks.append("量比过高，波动容易失真")
    elif 0 < volume_ratio < r.volume_ratio.cold_max:
        score += r.volume_ratio.cold_penalty
        risks.append("量比偏低，主动资金不明显")

    if net_mf_ratio_pct >= r.net_mf.strong_min:
        score += r.net_mf.strong_score
        reasons.append("资金净流入占成交额较高")
    elif net_mf_ratio_pct >= r.net_mf.ok_min:
        score += r.net_mf.ok_score
        reasons.append("资金净流入为正")
    elif net_mf_ratio_pct <= r.net_mf.weak_max:
        score += r.net_mf.weak_penalty
        risks.append("资金净流出明显")

    if large_order_net_pct >= r.large_order.strong_min:
        score += r.large_order.strong_score
        reasons.append("大单承接占优")
    elif large_order_net_pct >= r.large_order.ok_min:
        score += r.large_order.ok_score
        reasons.append("大单净额为正")
    elif large_order_net_pct <= r.large_order.weak_max:
        score += r.large_order.weak_penalty
        risks.append("大单流出，次日承接需谨慎")

    if r.breakout.sweet_min <= breakout_pct <= r.breakout.sweet_max:
        score += r.breakout.sweet_score
        reasons.append("接近或小幅突破近十日高点")
    elif breakout_pct < r.breakout.far_max:
        score += r.breakout.far_penalty
        risks.append("距离近十日高点偏远，动能不足")

    if r.up_limit_room.sweet_min <= up_limit_room_pct <= r.up_limit_room.sweet_max:
        score += r.up_limit_room.sweet_score
        reasons.append("距离涨停仍有合理空间")
    elif 0 < up_limit_room_pct < r.up_limit_room.near_max:
        score += r.up_limit_room.near_penalty
        risks.append("离涨停过近，但无竞价/封单权限确认强度")

    if turnover_pct_rank >= r.ranks.turnover_rank_min:
        score += r.ranks.turnover_rank_score
        reasons.append("换手位于市场前列")
    if net_mf_ratio_rank >= r.ranks.net_mf_rank_min:
        score += r.ranks.net_mf_rank_score
        reasons.append("资金净流入强于多数个股")
    if large_order_net_rank >= r.ranks.large_order_rank_min:
        score += r.ranks.large_order_rank_score
        reasons.append("大单承接强于多数个股")

    if "ST" in stock_name.upper():
        score += r.penalties.st_penalty
        risks.append("ST 标的隔夜波动不可控")
    if list_age_days and list_age_days < r.penalties.new_stock_age_days:
        score += r.penalties.new_stock_penalty
        risks.append(f"上市未满 {r.penalties.new_stock_age_days} 天，历史样本不足")
    if ts_code.endswith(".BJ") or "北交所" in board_name:
        score += r.penalties.bj_penalty
        risks.append("北交所标的次日流动性与滑点风险偏大")

    final_score = int(round(max(0.0, min(100.0, score))))
    risk_text = "；".join(dict.fromkeys(risks)) if risks else "无显著额外风险"
    detail_text = " + ".join(dict.fromkeys(reasons)) if reasons else "缺少足够的尾盘强势信号"

    if final_score >= rules.status_bands.strong:
        status = "【强候选】尾盘隔夜"
    elif final_score >= rules.status_bands.candidate:
        status = "【候选】可跟踪"
    elif final_score >= rules.status_bands.watch:
        status = "【观察】等待更优确认"
    else:
        status = "【回避】"

    action_plan = _build_action_plan(final_score, market_score, up_limit_room_pct, pct_chg, rules)

    return {
        "score": final_score,
        "status": status,
        "detail": detail_text,
        "risk": risk_text,
        "vol_ratio": round(volume_ratio, 2),
        "turnover_rate": round(turnover_rate, 2),
        "amount_ratio_5d": round(amount_ratio_5d, 2),
        "net_mf_ratio_pct": round(net_mf_ratio_pct, 2),
        "large_order_net_pct": round(large_order_net_pct, 2),
        "up_limit_room_pct": round(up_limit_room_pct, 2),
        "close_strength": round(close_strength, 2),
        "breakout_pct": round(breakout_pct, 2),
        "market_bias": market_bias,
        "action_plan": action_plan,
    }


def _build_action_plan(
    score: int,
    market_score: float,
    up_limit_room_pct: float,
    pct_chg: float,
    rules: AnalysisRules,
) -> str:
    r = rules.rules
    if score >= rules.status_bands.strong:
        base = "轻仓参与隔夜，不追临近涨停的尾盘拉板；次日若高开 2% 到 4% 优先分批兑现。"
    elif score >= rules.status_bands.candidate:
        base = "仅列入尾盘观察名单，必须确认尾盘强势未衰减再考虑；次日优先快进快出。"
    elif score >= rules.status_bands.watch:
        base = "只观察，不建议机械买入。"
    else:
        return "放弃本次隔夜交易，等待更强的收盘结构与资金确认。"

    if market_score <= r.market_regime.weak_max:
        base += " 市场环境偏弱，仓位需要再降一档。"
    if 0 < up_limit_room_pct < r.up_limit_room.near_max or pct_chg > r.pct_chg.hot_min:
        base += " 该股过于贴近涨停，因缺少竞价与封单权限，不宜重仓。"

    base += " 若次日开盘弱于昨收约 1.5%，优先止损，不做日内扛单。"
    return base


def _pick_first_float(*values: Any) -> float:
    for value in values:
        candidate = _to_float(value)
        if candidate != 0:
            return candidate
    return 0.0


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
```

注意：原文件的 `load_yaml_config`、`import yaml`、`from pathlib import Path` 已删除。原 ST/次新股风险文案中 `120` 改为 f-string 引用规则值，默认值下输出文本不变。

- [ ] **Step 2: 更新三个 re-export 文件**

`tradeeye/strategies/__init__.py` 整文件替换：

```python
from .strategy import check_signals

__all__ = [
    "check_signals",
]
```

`strategies/strategy.py`（根目录兼容壳）整文件替换：

```python
from tradeeye.strategies.strategy import check_signals

__all__ = ["check_signals"]
```

`strategies/__init__.py`（根目录兼容壳）整文件替换：

```python
from .strategy import check_signals

__all__ = ["check_signals"]
```

- [ ] **Step 3: 跑全量测试验证纯重构**

Run: `python -m pytest -q`
Expected: 全部通过，`tests/test_strategy.py` 零改动全绿

- [ ] **Step 4: 验证 yaml 覆盖真的生效**（追加到 `tests/test_rules.py`）

```python
def test_check_signals_respects_rule_overrides(tmp_path):
    from tradeeye.strategies.rules import AnalysisRules, StatusBands
    from tradeeye.strategies.strategy import check_signals
    from dataclasses import replace

    data = {
        "name": "Test Co",
        "market_regime": {"status": "中性", "score": 0},
        "latest": {"close": 10.5, "open": 10.0, "ma5": 10.2, "ma10": 10.0, "ma20": 9.8,
                   "pct_chg": 2.0, "close_strength": 0.9, "list_age_days": 600},
        "prev": {"low": 9.7},
    }
    default_result = check_signals(data, rules=AnalysisRules())
    # 把强候选门槛降到 1 分，status 应变为强候选
    lowered = replace(AnalysisRules(), status_bands=StatusBands(strong=1, candidate=0, watch=0))
    lowered_result = check_signals(data, rules=lowered)
    assert default_result["status"] != lowered_result["status"]
    assert lowered_result["status"] == "【强候选】尾盘隔夜"
```

Run: `python -m pytest tests/test_rules.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add tradeeye/strategies/strategy.py tradeeye/strategies/__init__.py strategies/ tests/test_rules.py
git commit -m "refactor: 复盘打分阈值改读 rules，删除死代码 load_yaml_config"
```

---
### Task 4: stock_recommender.py 改用 rules，删除 config.PRICE_RANGES

**Files:**
- Modify: `tradeeye/strategies/stock_recommender.py`
- Modify: `tradeeye/config.py:31`（删 `PRICE_RANGES`）
- Modify: `tests/test_config.py:8,72-73`（删 PRICE_RANGES 断言）
- Test: 现有 `tests/test_stock_recommender.py` 不改动保持全绿

- [ ] **Step 1: 修改 stock_recommender.py**

(a) 头部 import 与常量区（原 9-27 行）替换为：

```python
from tradeeye.config import Settings, extract_exchange
from tradeeye.services.data import build_pro_client, get_market_snapshot
from tradeeye.strategies.rules import RecommenderRules, get_rules

logger = logging.getLogger(__name__)

LOW_PRICE_GROUP_KEY = "low_price_group"
MID_PRICE_GROUP_KEY = "mid_price_group"
DEFAULT_TOP_N_PER_GROUP = 5
```

（`SHORT_BURST_*`、`T_ACTIVE_*`、`LONG_VALUE_*` 常量全部删除；`PRICE_RANGES` import 删除）

(b) `recommend_top_stocks` 增加 `rules` 参数并传递：

```python
def recommend_top_stocks(
    settings: Settings,
    top_n: int = DEFAULT_TOP_N_PER_GROUP,
    pro_client=None,
    rules: RecommenderRules | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch market snapshot via existing data service and return grouped recommendations."""
    if not settings.tushare_token:
        logger.error("Stock recommender skipped: missing TUSHARE_TOKEN")
        return _empty_grouped_result()

    client = pro_client or build_pro_client(settings)
    snapshot = get_market_snapshot(settings, pro_client=client)
    if snapshot.market_df.empty:
        return _empty_grouped_result()

    return rank_market_candidates(
        market_df=snapshot.market_df,
        allowed_exchanges=settings.allowed_exchanges,
        recommender_industries=settings.recommender_industries,
        trade_date=snapshot.trade_date,
        top_n_each_group=top_n,
        rules=rules,
    )
```

(c) `rank_market_candidates` 增加 `rules` 参数，价格分组改读 rules：

```python
def rank_market_candidates(
    market_df: pd.DataFrame,
    allowed_exchanges: tuple[str, ...],
    recommender_industries: tuple[str, ...] = (),
    trade_date: str | None = None,
    top_n_each_group: int = DEFAULT_TOP_N_PER_GROUP,
    rules: RecommenderRules | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if market_df.empty:
        return _empty_grouped_result()

    rules = rules or get_rules().recommender
    ranked_df = _build_scored_market_frame(market_df, allowed_exchanges, recommender_industries, rules)
    if ranked_df.empty:
        return _empty_grouped_result()

    date_value = trade_date or _resolve_trade_date_from_frame(ranked_df)
    low_min, low_max = rules.price_ranges.low
    mid_min, mid_max = rules.price_ranges.mid
```

（函数其余部分不变）

(d) `_build_scored_market_frame` 增加 `rules` 参数；函数内四处改动：

```python
def _build_scored_market_frame(
    market_df: pd.DataFrame,
    allowed_exchanges: tuple[str, ...],
    recommender_industries: tuple[str, ...],
    rules: RecommenderRules,
) -> pd.DataFrame:
```

价格上限（原 169 行）：

```python
    max_price = rules.price_ranges.max_price
```

short_burst 段（原 192-204 行）：

```python
    sb = rules.short_burst
    short_mask = (
        (frame["volume_ratio"] > sb.volume_ratio_min)
        & (frame["turnover_rate"] >= sb.turnover_min)
        & (frame["turnover_rate"] <= sb.turnover_max)
        & (frame["pct_chg"] > sb.pct_chg_min)
    )
    frame["short_burst_score"] = 0.0
    frame.loc[short_mask, "short_burst_score"] = (
        55
        + ((frame.loc[short_mask, "volume_ratio"] - sb.volume_ratio_min).clip(lower=0, upper=5) / 5) * 20
        + (1 - ((frame.loc[short_mask, "turnover_rate"] - 10).abs().clip(upper=5) / 5)) * 15
        + ((frame.loc[short_mask, "pct_chg"] - sb.pct_chg_min).clip(lower=0, upper=8) / 8) * 10
    ).clip(lower=0, upper=100)
```

t_active 段（原 206-212 行）：

```python
    ta = rules.t_active
    t_mask = (frame["intraday_amplitude_pct"] > ta.amplitude_min) & (frame["amount"] > ta.amount_min)
    frame["t_active_score"] = 0.0
    frame.loc[t_mask, "t_active_score"] = (
        50
        + ((frame.loc[t_mask, "intraday_amplitude_pct"] - ta.amplitude_min).clip(lower=0, upper=8) / 8) * 25
        + ((frame.loc[t_mask, "amount"] - ta.amount_min).clip(lower=0, upper=1_000_000) / 1_000_000) * 25
    ).clip(lower=0, upper=100)
```

long_value 段（原 220-229 行，`LONG_VALUE_*` 换成 `lv.*`）：

```python
    lv = rules.long_value
    if not long_df.empty:
        long_df["pe_rank"] = long_df.groupby("industry")["pe_value"].rank(pct=True, ascending=True)
        long_df["mv_rank"] = long_df.groupby("industry")["total_mv"].rank(pct=True, ascending=True)
        long_mask = (long_df["pe_rank"] <= lv.pe_rank_max) & (long_df["mv_rank"] >= lv.mv_rank_min)
        long_df.loc[long_mask, "long_value_score"] = (
            50
            + ((lv.pe_rank_max - long_df.loc[long_mask, "pe_rank"]) / lv.pe_rank_max) * 25
            + ((long_df.loc[long_mask, "mv_rank"] - lv.mv_rank_min) / (1 - lv.mv_rank_min)) * 25
        ).clip(lower=0, upper=100)
        frame.loc[long_df.index, "long_value_score"] = long_df["long_value_score"]
```

total_score 段（原 240-245 行）：

```python
    w = rules.weights
    frame["total_score"] = (
        frame["short_burst_score"] * w.short_burst
        + frame["t_active_score"] * w.t_active
        + frame["long_value_score"] * w.long_value
        + (frame["dimension_hits"] - 1).clip(lower=0) * w.multi_dim_bonus
    ).clip(lower=0, upper=100)
```

(e) 删除函数 `_get_price_range`（原 309-313 行，已无调用方）。

- [ ] **Step 2: 删除 config.PRICE_RANGES 及其测试断言**

`tradeeye/config.py`：删除第 31 行 `PRICE_RANGES = {"low": [0, 10], "mid": [10, 20]}`。

`tests/test_config.py`：从 import 列表删除 `PRICE_RANGES`，删除这两行断言：

```python
    assert PRICE_RANGES["low"] == [0, 10]
    assert PRICE_RANGES["mid"] == [10, 20]
```

- [ ] **Step 3: 跑全量测试**

Run: `python -m pytest -q`
Expected: 全绿，`tests/test_stock_recommender.py` 零改动通过

- [ ] **Step 4: Commit**

```bash
git add tradeeye/strategies/stock_recommender.py tradeeye/config.py tests/test_config.py
git commit -m "refactor: 选股阈值与价格分组改读 rules，移除 config.PRICE_RANGES"
```

---

### Task 5: app.py 的 LLM 门槛改读 rules

**Files:**
- Modify: `tradeeye/app.py:19,80,92`
- Test: `tests/test_app.py`（现有测试不改；追加一个门槛覆盖测试）

- [ ] **Step 1: 修改 app.py**

删除第 19 行 `LLM_SCORE_THRESHOLD = 70`，import 区加：

```python
from tradeeye.strategies.rules import get_rules
```

`main()` 内、进入 for 循环之前加一行，并替换两处引用：

```python
    llm_score_threshold = get_rules().analysis.llm_score_threshold
```

原 `if score >= LLM_SCORE_THRESHOLD:` → `if score >= llm_score_threshold:`
原日志参数 `LLM_SCORE_THRESHOLD,` → `llm_score_threshold,`

- [ ] **Step 2: 追加测试**（`tests/test_app.py` 末尾）

```python
def test_main_llm_threshold_from_rules(monkeypatch, tmp_path):
    """把门槛改到 101 分时，任何股票都不应触发 LLM。"""
    from tradeeye.strategies import rules as rules_module

    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text("analysis: {llm_score_threshold: 101}\n", encoding="utf-8")
    monkeypatch.setenv("TRADEEYE_RULES_FILE", str(yaml_file))
    rules_module.get_rules.cache_clear()

    analyzer_calls = []

    def fake_fetcher(code, settings):
        return make_strong_payload()

    def fake_analyzer(data, tech_result, code, settings):
        analyzer_calls.append(code)
        return "AI report"

    result = main(
        settings=make_settings(),
        data_fetcher=fake_fetcher,
        analyzer=fake_analyzer,
        notifier=lambda content, settings: True,
    )

    rules_module.get_rules.cache_clear()
    assert result == 0
    assert analyzer_calls == []
```

注意：`get_rules` 有 lru_cache，测试前后必须 `cache_clear()`。若 Task 7 已并入信号落地参数，此测试还需传 `signal_recorder=lambda rows: True`。

- [ ] **Step 3: 跑全量测试**

Run: `python -m pytest -q`
Expected: 全绿

- [ ] **Step 4: Commit**

```bash
git add tradeeye/app.py tests/test_app.py
git commit -m "refactor: LLM 调用门槛改读 rules.yaml"
```

---
### Task 6: signal_store.py — 信号 CSV 落地

**Files:**
- Create: `tradeeye/services/signal_store.py`
- Test: `tests/test_signal_store.py`

- [ ] **Step 1: 写失败测试**

`tests/test_signal_store.py`：

```python
import csv

from tradeeye.services.signal_store import (
    ANALYSIS_FIELDS,
    append_analysis_signals,
    append_recommend_signals,
)


def _read_rows(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_append_creates_file_and_dirs_with_header(tmp_path):
    target = tmp_path / "data" / "signals" / "analysis.csv"
    ok = append_analysis_signals(
        [{"date": "20260724", "ts_code": "600001.SH", "name": "Alpha", "score": 82,
          "status": "【强候选】尾盘隔夜", "close": 9.8, "called_llm": True}],
        path=target,
    )
    assert ok is True
    rows = _read_rows(target)
    assert len(rows) == 1
    assert rows[0]["ts_code"] == "600001.SH"
    assert list(rows[0].keys()) == ANALYSIS_FIELDS


def test_append_dedupes_same_day_same_code_keeps_latest(tmp_path):
    target = tmp_path / "analysis.csv"
    append_analysis_signals(
        [{"date": "20260724", "ts_code": "600001.SH", "name": "Alpha", "score": 60,
          "status": "old", "close": 9.0, "called_llm": False}],
        path=target,
    )
    append_analysis_signals(
        [{"date": "20260724", "ts_code": "600001.SH", "name": "Alpha", "score": 82,
          "status": "new", "close": 9.8, "called_llm": True}],
        path=target,
    )
    rows = _read_rows(target)
    assert len(rows) == 1
    assert rows[0]["score"] == "82"
    assert rows[0]["status"] == "new"


def test_append_accumulates_across_days_and_codes(tmp_path):
    target = tmp_path / "recommend.csv"
    append_recommend_signals(
        [{"date": "20260723", "ts_code": "600001.SH", "name": "A", "price_group": "low_price_group",
          "total_score": 70.5, "dimensions": "short_burst|t_active", "close": 9.8}],
        path=target,
    )
    append_recommend_signals(
        [{"date": "20260724", "ts_code": "600002.SH", "name": "B", "price_group": "mid_price_group",
          "total_score": 66.0, "dimensions": "t_active", "close": 15.2}],
        path=target,
    )
    rows = _read_rows(target)
    assert len(rows) == 2
    assert {row["date"] for row in rows} == {"20260723", "20260724"}


def test_append_returns_false_on_io_error(tmp_path):
    # 传一个目录路径触发 IO 异常，不应抛出
    ok = append_analysis_signals(
        [{"date": "20260724", "ts_code": "600001.SH", "name": "A", "score": 1,
          "status": "s", "close": 1.0, "called_llm": False}],
        path=tmp_path,
    )
    assert ok is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_signal_store.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 signal_store.py**

`tradeeye/services/signal_store.py` 完整内容：

```python
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

ANALYSIS_SIGNALS_FILE = Path("data/signals/analysis.csv")
RECOMMEND_SIGNALS_FILE = Path("data/signals/recommend.csv")
ANALYSIS_FIELDS = ["date", "ts_code", "name", "score", "status", "close", "called_llm"]
RECOMMEND_FIELDS = ["date", "ts_code", "name", "price_group", "total_score", "dimensions", "close"]


def append_analysis_signals(rows: Iterable[dict[str, Any]], path: str | Path = ANALYSIS_SIGNALS_FILE) -> bool:
    return _append_signals(rows, Path(path), ANALYSIS_FIELDS)


def append_recommend_signals(rows: Iterable[dict[str, Any]], path: str | Path = RECOMMEND_SIGNALS_FILE) -> bool:
    return _append_signals(rows, Path(path), RECOMMEND_FIELDS)


def _append_signals(rows: Iterable[dict[str, Any]], path: Path, fieldnames: list[str]) -> bool:
    """追加信号并按 (date, ts_code) 去重，后写覆盖先写。信号落地是旁路，失败只记日志。"""
    try:
        existing: dict[tuple[str, str], dict[str, str]] = {}
        if path.exists():
            with path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    existing[(row.get("date", ""), row.get("ts_code", ""))] = {
                        key: row.get(key, "") for key in fieldnames
                    }

        for row in rows:
            normalized = {key: _to_cell(row.get(key)) for key in fieldnames}
            existing[(normalized["date"], normalized["ts_code"])] = normalized

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for key in sorted(existing):
                writer.writerow(existing[key])
        return True
    except Exception:
        logger.exception("Failed to append signals to %s", path)
        return False


def _to_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_signal_store.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add tradeeye/services/signal_store.py tests/test_signal_store.py
git commit -m "feat: 信号 CSV 落地模块（追加+按日去重）"
```

---

### Task 7: 两条工作流接入信号落地 + .gitignore 白名单

**Files:**
- Modify: `tradeeye/app.py`（main 循环内收集信号行）
- Modify: `tradeeye/recommend_app.py`
- Modify: `.gitignore`
- Test: `tests/test_app.py`、`tests/test_recommend_app.py`（各追加一个测试）

- [ ] **Step 1: 写失败测试**

`tests/test_app.py` 追加：

```python
def test_main_records_signals_for_scored_stocks():
    recorded = []

    result = main(
        settings=make_settings(),
        data_fetcher=lambda code, settings: make_strong_payload() | {"trade_date": "20260724"},
        analyzer=lambda data, tech_result, code, settings: "AI report",
        notifier=lambda content, settings: True,
        signal_recorder=lambda rows: recorded.extend(rows) or True,
    )

    assert result == 0
    assert len(recorded) == 1
    row = recorded[0]
    assert row["date"] == "20260724"
    assert row["ts_code"] == "000001.SZ"
    assert row["close"] == 10.4
    assert isinstance(row["score"], int)
    assert isinstance(row["called_llm"], bool)
```

`tests/test_recommend_app.py` 追加（沿用该文件现有的 make_settings/推荐样例结构；若无则按下面写）：

```python
def test_main_records_recommend_signals():
    recorded = []
    recommendations = {
        "low_price_group": [
            {"trade_date": "20260724", "ts_code": "600001.SH", "name": "Alpha", "close": 9.8,
             "total_score": 70.5, "dimensions": ["short_burst", "t_active"]},
        ],
        "mid_price_group": [
            {"trade_date": "20260724", "ts_code": "600002.SH", "name": "Beta", "close": 15.2,
             "total_score": 66.0, "dimensions": ["t_active"]},
        ],
    }

    result = main(
        settings=make_settings(),
        recommender=lambda settings, top_n: recommendations,
        analyzer=lambda payload, settings: "AI analysis",
        notifier=lambda content, settings: True,
        signal_recorder=lambda rows: recorded.extend(rows) or True,
    )

    assert result == 0
    assert len(recorded) == 2
    assert recorded[0]["price_group"] == "low_price_group"
    assert recorded[0]["dimensions"] == "short_burst|t_active"
    assert recorded[1]["ts_code"] == "600002.SH"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_app.py tests/test_recommend_app.py -q`
Expected: FAIL（main() 无 signal_recorder 参数）

- [ ] **Step 3: 修改 app.py**

import 区加：

```python
from tradeeye.services.signal_store import append_analysis_signals
```

`main()` 签名加参数：

```python
def main(
    settings: Settings | None = None,
    data_fetcher: DataFetcher = get_clean_data,
    analyzer: Analyzer = get_llm_analysis,
    notifier: Notifier = send_report,
    signal_recorder: Callable[[list[dict[str, Any]]], bool] = append_analysis_signals,
) -> int:
```

循环前初始化 `signal_rows: list[dict[str, Any]] = []`。循环内 `tech_result = check_signals(data)`、`score = _safe_score(...)` 之后（进入 LLM 分支判断之前）加：

```python
        signal_rows.append(
            {
                "date": data.get("trade_date", ""),
                "ts_code": code,
                "name": data.get("name", ""),
                "score": score,
                "status": tech_result.get("status", ""),
                "close": data.get("latest", {}).get("close", ""),
                "called_llm": score >= llm_score_threshold,
            }
        )
```

for 循环结束后、构建 final_content 之前加：

```python
    if signal_rows:
        signal_recorder(signal_rows)
```

- [ ] **Step 4: 修改 recommend_app.py**

import 区加：

```python
from tradeeye.services.signal_store import append_recommend_signals
```

`main()` 签名加参数 `signal_recorder: Callable[[list[dict[str, Any]]], bool] = append_recommend_signals`。

在 `recommendations = recommender(settings, top_n)` 之后加：

```python
    signal_rows = _build_signal_rows(recommendations)
    if signal_rows:
        signal_recorder(signal_rows)
```

文件末尾加：

```python
def _build_signal_rows(recommendations: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_key in ("low_price_group", "mid_price_group"):
        for item in recommendations.get(group_key, []):
            rows.append(
                {
                    "date": item.get("trade_date", ""),
                    "ts_code": item.get("ts_code", ""),
                    "name": item.get("name", ""),
                    "price_group": group_key,
                    "total_score": item.get("total_score", ""),
                    "dimensions": "|".join(item.get("dimensions", [])),
                    "close": item.get("close", ""),
                }
            )
    return rows
```

- [ ] **Step 5: .gitignore 加白名单**

在 `*.csv` 行之后加一行：

```
!data/signals/*.csv
```

- [ ] **Step 6: 给现有测试补 no-op recorder（防止测试写真实 CSV）**

`tests/test_app.py` 与 `tests/test_recommend_app.py` 中所有直接调用 `main(...)` 的既有测试（含 Task 5 新增的 `test_main_llm_threshold_from_rules`），统一补传：

```python
        signal_recorder=lambda rows: True,
```

否则这些测试会走默认 `append_analysis_signals`，在仓库里写出真实的 `data/signals/*.csv`。

- [ ] **Step 7: 跑全量测试**

Run: `python -m pytest -q`
Expected: 全绿。另验证两点：
- `git check-ignore data/signals/analysis.csv; echo $?` 输出 1（未被忽略）
- `git status` 不出现 data/signals/（确认测试没写真实文件）

- [ ] **Step 8: Commit**

```bash
git add tradeeye/app.py tradeeye/recommend_app.py tests/test_app.py tests/test_recommend_app.py .gitignore
git commit -m "feat: 复盘与荐股工作流每日信号落地 data/signals/"
```

---
### Task 8: Settings 增加 backtest_lookback_days

**Files:**
- Modify: `tradeeye/config.py`
- Test: `tests/test_config.py`（追加）

- [ ] **Step 1: 写失败测试**（`tests/test_config.py` 追加）

```python
def test_backtest_lookback_days_default(monkeypatch):
    monkeypatch.delenv("BACKTEST_LOOKBACK_DAYS", raising=False)
    assert Settings.from_env().backtest_lookback_days == 45


def test_backtest_lookback_days_env(monkeypatch):
    monkeypatch.setenv("BACKTEST_LOOKBACK_DAYS", "30")
    assert Settings.from_env().backtest_lookback_days == 30


def test_backtest_lookback_days_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("BACKTEST_LOOKBACK_DAYS", "0")
    assert Settings.from_env().backtest_lookback_days == 45
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL（Settings 无该字段）

- [ ] **Step 3: 实现**

`tradeeye/config.py` 常量区加：

```python
DEFAULT_BACKTEST_LOOKBACK_DAYS = 45
```

`Settings` dataclass 加字段（放在 `llm_timeout_sec` 之后）：

```python
    backtest_lookback_days: int = DEFAULT_BACKTEST_LOOKBACK_DAYS
```

`from_env()` 末尾加：

```python
            backtest_lookback_days=parse_int(
                os.getenv("BACKTEST_LOOKBACK_DAYS"),
                default=DEFAULT_BACKTEST_LOOKBACK_DAYS,
                minimum=1,
            ),
```

- [ ] **Step 4: 跑测试确认通过并 Commit**

Run: `python -m pytest tests/test_config.py -q` → 全绿

```bash
git add tradeeye/config.py tests/test_config.py
git commit -m "feat: 配置项 BACKTEST_LOOKBACK_DAYS（默认 45 天）"
```

---

### Task 9: backtest.py — 信号加载、T+1 收益、周报文本

**Files:**
- Create: `tradeeye/services/backtest.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: 写失败测试**

`tests/test_backtest.py`：

```python
import datetime as dt

import pandas as pd

from tradeeye.config import Settings
from tradeeye.services.backtest import (
    SignalRecord,
    build_backtest_report,
    evaluate_signals,
    load_signals,
)


def make_settings() -> Settings:
    return Settings(
        tushare_token="token",
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


class FakeClient:
    """信号日 20260723，下一交易日 20260724。"""

    def trade_cal(self, **kwargs):
        return pd.DataFrame(
            {"cal_date": ["20260723", "20260724", "20260725"], "is_open": [1, 1, 0]}
        )

    def daily(self, trade_date="", **kwargs):
        if trade_date == "20260724":
            return pd.DataFrame(
                [
                    {"ts_code": "600001.SH", "open": 10.2, "close": 9.9},
                    {"ts_code": "600002.SH", "open": 14.8, "close": 15.5},
                ]
            )
        return pd.DataFrame()


def _record(ts_code: str, close: float, group: str = "复盘 强候选(≥80)") -> SignalRecord:
    return SignalRecord(
        date="20260723", ts_code=ts_code, name="X", kind="analysis", group=group, close=close
    )


def test_load_signals_filters_by_lookback_and_groups(tmp_path):
    analysis = tmp_path / "analysis.csv"
    analysis.write_text(
        "date,ts_code,name,score,status,close,called_llm\n"
        "20260101,600009.SH,Old,90,s,10.0,True\n"      # 超出回看窗口
        "20260723,600001.SH,Strong,85,s,10.0,True\n"
        "20260723,600002.SH,Mid,70,s,15.0,True\n"
        "20260723,600003.SH,Low,40,s,5.0,False\n"
        "20260723,600004.SH,BadClose,85,s,0,False\n",  # close<=0 跳过
        encoding="utf-8",
    )
    recommend = tmp_path / "recommend.csv"
    recommend.write_text(
        "date,ts_code,name,price_group,total_score,dimensions,close\n"
        "20260723,600005.SH,Rec,low_price_group,66.0,t_active,9.5\n",
        encoding="utf-8",
    )

    records = load_signals(
        analysis_path=analysis,
        recommend_path=recommend,
        lookback_days=45,
        today=dt.date(2026, 7, 27),
    )

    assert len(records) == 4
    groups = {record.ts_code: record.group for record in records}
    assert "强候选" in groups["600001.SH"]
    assert "候选" in groups["600002.SH"] and "强" not in groups["600002.SH"]
    assert "低分" in groups["600003.SH"]
    assert "低价组" in groups["600005.SH"]


def test_load_signals_missing_files_returns_empty(tmp_path):
    records = load_signals(
        analysis_path=tmp_path / "none1.csv",
        recommend_path=tmp_path / "none2.csv",
        lookback_days=45,
    )
    assert records == []


def test_evaluate_signals_computes_two_return_metrics():
    records = [_record("600001.SH", close=10.0), _record("600002.SH", close=16.0)]
    results, missing = evaluate_signals(records, make_settings(), pro_client=FakeClient())

    assert missing == 0
    assert len(results) == 2
    first = next(r for r in results if r.record.ts_code == "600001.SH")
    # 隔夜: 10.2/10.0-1 = +2%；全天: 9.9/10.0-1 = -1%
    assert round(first.overnight_return_pct, 2) == 2.0
    assert round(first.day_return_pct, 2) == -1.0


def test_evaluate_signals_counts_missing_quotes():
    records = [_record("999999.SH", close=10.0)]
    results, missing = evaluate_signals(records, make_settings(), pro_client=FakeClient())
    assert results == []
    assert missing == 1


def test_build_backtest_report_groups_and_flags_small_samples():
    records = [_record("600001.SH", close=10.0)]
    results, missing = evaluate_signals(records, make_settings(), pro_client=FakeClient())
    report = build_backtest_report(results, missing_count=2, lookback_days=45)

    assert "强候选" in report
    assert "样本不足" in report          # 样本 1 < 5
    assert "胜率 100%" in report          # 隔夜 +2% 为赢
    assert "2 条信号缺少 T+1 行情" in report
    assert "45" in report


def test_build_backtest_report_empty_results():
    report = build_backtest_report([], missing_count=0, lookback_days=45)
    assert "窗口内无可评估信号" in report
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_backtest.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 backtest.py**

`tradeeye/services/backtest.py` 完整内容：

```python
from __future__ import annotations

import csv
import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

from tradeeye.config import Settings
from tradeeye.services.data import build_pro_client
from tradeeye.strategies.rules import get_rules

logger = logging.getLogger(__name__)

ANALYSIS_SIGNALS_FILE = Path("data/signals/analysis.csv")
RECOMMEND_SIGNALS_FILE = Path("data/signals/recommend.csv")
MIN_SAMPLE_SIZE = 5


@dataclass(frozen=True)
class SignalRecord:
    date: str
    ts_code: str
    name: str
    kind: str
    group: str
    close: float


@dataclass(frozen=True)
class SignalResult:
    record: SignalRecord
    overnight_return_pct: float
    day_return_pct: float


def load_signals(
    analysis_path: str | Path = ANALYSIS_SIGNALS_FILE,
    recommend_path: str | Path = RECOMMEND_SIGNALS_FILE,
    lookback_days: int = 45,
    today: dt.date | None = None,
) -> list[SignalRecord]:
    cutoff = (today or dt.date.today()) - dt.timedelta(days=lookback_days)
    records = _load_analysis_signals(Path(analysis_path), cutoff)
    records.extend(_load_recommend_signals(Path(recommend_path), cutoff))
    return records


def evaluate_signals(
    records: list[SignalRecord],
    settings: Settings,
    pro_client=None,
) -> tuple[list[SignalResult], int]:
    if not records:
        return [], 0

    client = pro_client or build_pro_client(settings)
    signal_dates = sorted({record.date for record in records})
    next_day_map = _resolve_next_trade_days(client, signal_dates)

    quotes: dict[str, dict[str, tuple[float, float]]] = {}
    for next_day in sorted(set(next_day_map.values())):
        quotes[next_day] = _fetch_day_quotes(client, next_day)

    results: list[SignalResult] = []
    missing = 0
    for record in records:
        next_day = next_day_map.get(record.date)
        quote = quotes.get(next_day, {}).get(record.ts_code) if next_day else None
        if not quote or quote[0] <= 0 or quote[1] <= 0 or record.close <= 0:
            missing += 1
            continue
        next_open, next_close = quote
        results.append(
            SignalResult(
                record=record,
                overnight_return_pct=(next_open / record.close - 1) * 100,
                day_return_pct=(next_close / record.close - 1) * 100,
            )
        )
    return results, missing


def build_backtest_report(
    results: list[SignalResult],
    missing_count: int,
    lookback_days: int,
) -> str:
    lines = [f"回看窗口：近 {lookback_days} 天"]

    if not results:
        lines.append("窗口内无可评估信号。")
    else:
        groups: dict[str, list[SignalResult]] = {}
        for result in results:
            groups.setdefault(result.record.group, []).append(result)

        for group_name in sorted(groups):
            group_results = groups[group_name]
            sample_size = len(group_results)
            overnight = [item.overnight_return_pct for item in group_results]
            day = [item.day_return_pct for item in group_results]
            suffix = "（样本不足，仅供参考）" if sample_size < MIN_SAMPLE_SIZE else ""
            lines.append(
                f"\n【{group_name}】样本 {sample_size} 条{suffix}\n"
                f"- 隔夜(收盘→次日开盘)：胜率 {_win_rate_pct(overnight):.0f}% | 平均 {_mean(overnight):+.2f}%\n"
                f"- T+1 全天(收盘→次日收盘)：胜率 {_win_rate_pct(day):.0f}% | 平均 {_mean(day):+.2f}%"
            )

    if missing_count:
        lines.append(f"\n另有 {missing_count} 条信号缺少 T+1 行情（停牌/数据未出），未纳入统计。")
    return "\n".join(lines)


def _load_analysis_signals(path: Path, cutoff: dt.date) -> list[SignalRecord]:
    bands = get_rules().analysis.status_bands
    records: list[SignalRecord] = []
    for row in _read_csv_rows(path):
        signal_date = _parse_date(row.get("date", ""))
        close = _to_float(row.get("close"))
        if signal_date is None or signal_date < cutoff or close <= 0:
            continue
        score = _to_float(row.get("score"))
        if score >= bands.strong:
            group = f"复盘 强候选(≥{bands.strong:g})"
        elif score >= bands.candidate:
            group = f"复盘 候选({bands.candidate:g}-{bands.strong:g})"
        else:
            group = f"复盘 低分(<{bands.candidate:g})"
        records.append(
            SignalRecord(
                date=row.get("date", ""),
                ts_code=row.get("ts_code", ""),
                name=row.get("name", ""),
                kind="analysis",
                group=group,
                close=close,
            )
        )
    return records


def _load_recommend_signals(path: Path, cutoff: dt.date) -> list[SignalRecord]:
    group_labels = {
        "low_price_group": "荐股 低价组",
        "mid_price_group": "荐股 中价组",
    }
    records: list[SignalRecord] = []
    for row in _read_csv_rows(path):
        signal_date = _parse_date(row.get("date", ""))
        close = _to_float(row.get("close"))
        if signal_date is None or signal_date < cutoff or close <= 0:
            continue
        group = group_labels.get(row.get("price_group", ""), "荐股 其他")
        records.append(
            SignalRecord(
                date=row.get("date", ""),
                ts_code=row.get("ts_code", ""),
                name=row.get("name", ""),
                kind="recommend",
                group=group,
                close=close,
            )
        )
    return records


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        logger.exception("Failed to read signals file %s", path)
        return []


def _resolve_next_trade_days(client, signal_dates: list[str]) -> dict[str, str]:
    if not signal_dates:
        return {}
    end_date = (dt.date.today() + dt.timedelta(days=1)).strftime("%Y%m%d")
    try:
        calendar_df = client.trade_cal(
            exchange="", start_date=min(signal_dates), end_date=end_date, fields="cal_date,is_open"
        )
    except Exception:
        logger.exception("Tushare trade_cal query failed")
        return {}
    if calendar_df is None or calendar_df.empty:
        return {}

    open_days = sorted(
        str(cal_date)
        for cal_date, is_open in zip(calendar_df["cal_date"], calendar_df["is_open"])
        if _to_float(is_open) == 1
    )
    mapping: dict[str, str] = {}
    for date_text in signal_dates:
        next_day = next((day for day in open_days if day > date_text), None)
        if next_day:
            mapping[date_text] = next_day
    return mapping


def _fetch_day_quotes(client, trade_date: str) -> dict[str, tuple[float, float]]:
    try:
        df = client.daily(trade_date=trade_date, fields="ts_code,open,close")
    except Exception:
        logger.exception("Tushare daily query failed for %s", trade_date)
        return {}
    if df is None or df.empty:
        return {}
    return {
        str(row["ts_code"]): (_to_float(row["open"]), _to_float(row["close"]))
        for _, row in df.iterrows()
    }


def _parse_date(value: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(value).strip(), "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def _win_rate_pct(values: list[float]) -> float:
    return sum(1 for value in values if value > 0) / len(values) * 100


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _to_float(value) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_backtest.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add tradeeye/services/backtest.py tests/test_backtest.py
git commit -m "feat: T+1 胜率回测核心（信号加载/收益计算/周报文本）"
```

---
### Task 10: backtest_app.py 编排 + 入口壳

**Files:**
- Create: `tradeeye/backtest_app.py`、`backtest_main.py`
- Test: `tests/test_backtest_app.py`

- [ ] **Step 1: 写失败测试**

`tests/test_backtest_app.py`：

```python
from tradeeye.backtest_app import main
from tradeeye.config import Settings
from tradeeye.services.backtest import SignalRecord, SignalResult


def make_settings(token: str = "token") -> Settings:
    return Settings(
        tushare_token=token,
        feishu_webhook="https://example.com",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


def _record() -> SignalRecord:
    return SignalRecord(
        date="20260723", ts_code="600001.SH", name="X",
        kind="analysis", group="复盘 强候选(≥80)", close=10.0,
    )


def test_main_no_signals_sends_empty_notice():
    sent = []
    result = main(
        settings=make_settings(),
        loader=lambda lookback_days: [],
        evaluator=lambda records, settings: ([], 0),
        notifier=lambda content, settings: sent.append(content) or True,
    )
    assert result == 0
    assert "暂无历史信号数据" in sent[0]


def test_main_with_signals_sends_report():
    sent = []
    results = [SignalResult(record=_record(), overnight_return_pct=2.0, day_return_pct=-1.0)]
    result = main(
        settings=make_settings(),
        loader=lambda lookback_days: [_record()],
        evaluator=lambda records, settings: (results, 0),
        notifier=lambda content, settings: sent.append(content) or True,
    )
    assert result == 0
    assert "强候选" in sent[0]
    assert "胜率" in sent[0]


def test_main_missing_token_with_signals_fails():
    result = main(
        settings=make_settings(token=""),
        loader=lambda lookback_days: [_record()],
        notifier=lambda content, settings: True,
    )
    assert result == 1


def test_main_notifier_failure_returns_error():
    result = main(
        settings=make_settings(),
        loader=lambda lookback_days: [],
        notifier=lambda content, settings: False,
    )
    assert result == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_backtest_app.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现**

`tradeeye/backtest_app.py` 完整内容：

```python
from __future__ import annotations

import logging
from typing import Callable

from tradeeye.config import Settings, load_settings
from tradeeye.logging_utils import configure_logging
from tradeeye.services.backtest import (
    SignalRecord,
    SignalResult,
    build_backtest_report,
    evaluate_signals,
    load_signals,
)
from tradeeye.services.notifier import send_text

logger = logging.getLogger(__name__)

Loader = Callable[..., list[SignalRecord]]
Evaluator = Callable[[list[SignalRecord], Settings], tuple[list[SignalResult], int]]
Notifier = Callable[[str, Settings], bool]

_EMPTY_MESSAGE = "暂无历史信号数据，先让每日工作流积累几天信号再来看周报。"


def main(
    settings: Settings | None = None,
    loader: Loader | None = None,
    evaluator: Evaluator = evaluate_signals,
    notifier: Notifier | None = None,
) -> int:
    settings = settings or load_settings()
    configure_logging(settings.debug_mode)

    loader = loader or load_signals
    records = loader(lookback_days=settings.backtest_lookback_days)

    if not records:
        logger.info("No signals found within lookback window")
        content = _EMPTY_MESSAGE
    else:
        if not settings.tushare_token:
            logger.error("Backtest cannot fetch market data: missing TUSHARE_TOKEN")
            return 1
        results, missing_count = evaluator(records, settings)
        content = build_backtest_report(results, missing_count, settings.backtest_lookback_days)

    notifier = notifier or _send_report
    if not notifier(content, settings):
        logger.error("Backtest workflow finished with notification failure")
        return 1
    return 0


def _send_report(content: str, settings: Settings) -> bool:
    return send_text(content=content, settings=settings, title="策略胜率周报", icon="\U0001f4c8")
```

`backtest_main.py`（仓库根目录）完整内容：

```python
from tradeeye.backtest_app import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_backtest_app.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add tradeeye/backtest_app.py backtest_main.py tests/test_backtest_app.py
git commit -m "feat: 胜率回测编排层与入口 backtest_main.py"
```

---

### Task 11: GitHub Actions 工作流 + README

**Files:**
- Modify: `.github/workflows/TradeEye-1.0.0.yml`
- Create: `.github/workflows/TradeEye-backtest-1.0.0.yml`
- Modify: `README.md`

- [ ] **Step 1: 修改 TradeEye-1.0.0.yml**

在 `jobs:` 之前（`on:` 块之后）加：

```yaml
permissions:
  contents: write
```

在 `trade_eye_job` 的最后一个 step（`Run stock review analysis (STK)`）之后追加：

```yaml
      - name: Commit signal data
        shell: bash
        run: |
          if [ -z "$(git status --porcelain data/signals/ 2>/dev/null)" ]; then
            echo "No signal changes to commit."
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/signals/
          git commit -m "chore: record signals $(date -u +%Y-%m-%d) [skip ci]"
          git pull --rebase origin main
          git push origin HEAD:main || (git pull --rebase origin main && git push origin HEAD:main)
```

- [ ] **Step 2: 创建 TradeEye-backtest-1.0.0.yml**

`.github/workflows/TradeEye-backtest-1.0.0.yml` 完整内容：

```yaml
name: TradeEye Weekly Backtest

on:
  schedule:
    - cron: "30 10 * * 5"   # 北京时间周五 18:30，当日收盘数据已就绪
  workflow_dispatch:

jobs:
  backtest_job:
    runs-on: ubuntu-latest
    env:
      TUSHARE_TOKEN: ${{ secrets.TUSHARE_TOKEN }}
      FEISHU_WEBHOOK: ${{ secrets.FEISHU_WEBHOOK }}
      BACKTEST_LOOKBACK_DAYS: ${{ vars.BACKTEST_LOOKBACK_DAYS || '45' }}
      DEBUG_MODE: "false"

    steps:
      - name: Checkout repository
        uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd # v5

      - name: Set up Python
        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6
        with:
          python-version: "3.13"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -r requirements-dev.txt

      - name: Run tests
        run: python -m pytest

      - name: Run weekly backtest
        run: python backtest_main.py
```

- [ ] **Step 3: 更新 README.md**

(a) 三个工作流列表处（`- \`news\`: RSS finance digest -> Feishu push` 之后）加：

```markdown
- `backtest`: weekly win-rate report of recorded signals -> Feishu push
```

(b) `## GitHub Actions Deployment` 的 workflow 文件列表加：

```markdown
- `.github/workflows/TradeEye-backtest-1.0.0.yml` for weekly `backtest`
```

(c) `### Built-in schedules` 列表加：

```markdown
- `backtest`: `30 10 * * 5` (UTC), around China Friday `18:30`
```

(d) `## Environment Variables` 列表加两行：

```markdown
- `BACKTEST_LOOKBACK_DAYS`
- `TRADEEYE_RULES_FILE`
```

(e) `## Current Analysis Logic` 节末尾加一段：

```markdown
Scoring thresholds and weights live in `tradeeye/strategies/rules.yaml`.
Daily signals are appended to `data/signals/*.csv` by CI for the weekly backtest.
```

- [ ] **Step 4: 验证 workflow 语法**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/TradeEye-backtest-1.0.0.yml', encoding='utf-8')); yaml.safe_load(open('.github/workflows/TradeEye-1.0.0.yml', encoding='utf-8')); print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ README.md
git commit -m "ci: 信号自动提交回仓库 + 每周胜率回测工作流"
```

---

### Task 12: 收尾验证

- [ ] **Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿（新增约 20 个测试）

- [ ] **Step 2: 三个入口冒烟（debug 模式，不推飞书）**

Run: `DEBUG_MODE=true python backtest_main.py`
Expected: 控制台打印 "暂无历史信号数据…"（首次无信号文件），退出码 0

- [ ] **Step 3: 检查无遗漏**

Run: `git status`
Expected: 干净（所有变更已按 Task 提交）

---

## 完成定义

1. `python -m pytest -q` 全绿；现有测试（strategy/recommender/app）零改动通过 = 外置是纯重构。
2. `rules.yaml` 改数字 → 打分行为变化（test_check_signals_respects_rule_overrides 证明）。
3. 每日工作流跑完 `data/signals/*.csv` 有当日行，重跑不重复。
4. `backtest_main.py` 在 debug 模式可产出周报文本或空数据提示。

