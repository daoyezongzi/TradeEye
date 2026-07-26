# 设计文档：打分规则外置 yaml + 信号落地与胜率追踪

日期：2026-07-26
状态：已获用户批准

## 背景与目标

TradeEye 现有三条工作流（analysis / recommend / news），跑在 GitHub Actions 上。两个痛点：

1. 打分与选股的所有阈值硬编码在 Python 里（`tradeeye/strategies/strategy.py`、`tradeeye/strategies/stock_recommender.py`），调参必须改代码。
2. 每日信号无落地、无胜率闭环，无法知道信号历史准确率，调参全靠拍脑袋。

本设计做两件事：

- **A. 规则外置**：两套策略的阈值/分值/权重 + LLM 调用门槛全部外置到 yaml，缺省回退硬编码默认值，纯重构不改行为。
- **B. 胜率追踪**：每日信号以 CSV 落地并由 Actions 自动提交回仓库；新增每周五的第四条工作流回测近期信号胜率并推飞书。

## A. 规则外置 yaml

### 新文件

- `tradeeye/strategies/rules.yaml` — 规则参数（提交进仓库，作为默认配置）
- `tradeeye/strategies/rules.py` — 加载模块

### rules.py 设计

- 定义 frozen dataclass 层级：`Rules` → `AnalysisRules` + `RecommenderRules`，字段默认值 = 当前硬编码值。
- `load_rules(path: str | Path | None = None) -> Rules`：读 yaml 并覆盖默认值；**yaml 文件不存在、区块缺失、字段缺失时一律用默认值**；解析失败记 warning 并整体回退默认值。
- 用 `lru_cache` 缓存（与 `load_settings` 同风格）。
- 环境变量 `TRADEEYE_RULES_FILE` 可覆盖 yaml 路径（便于多套参数实验），不设则用包内默认路径。
- 删除 `strategy.py` 中现有的死代码 `load_yaml_config`（其查找的 `shrink_pullback.yaml` 从不存在），由 `rules.py` 取代。

### yaml 结构（键与默认值与现行代码一一对应）

```yaml
analysis:
  llm_score_threshold: 70          # 原 app.py LLM_SCORE_THRESHOLD
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
    up_limit_room: {sweet_min: 2, sweet_max: 7, sweet_score: 6,
                    near_max: 1.2, near_penalty: -10}
    ranks: {turnover_rank_min: 0.75, turnover_rank_score: 4,
            net_mf_rank_min: 0.8, net_mf_rank_score: 4,
            large_order_rank_min: 0.8, large_order_rank_score: 4}
    penalties: {st_penalty: -40, new_stock_age_days: 120, new_stock_penalty: -25,
                bj_penalty: -20}
recommender:
  short_burst: {volume_ratio_min: 2.0, turnover_min: 5.0, turnover_max: 15.0, pct_chg_min: 2.0}
  t_active: {amplitude_min: 4.5, amount_min: 500000}
  long_value: {pe_rank_max: 0.4, mv_rank_min: 0.8}
  weights: {short_burst: 0.4, t_active: 0.3, long_value: 0.3, multi_dim_bonus: 4}
  price_ranges: {low: [0, 10], mid: [10, 20]}
```

### 范围界定

- **外置**：阈值、加减分值、权重、分档边界、LLM 门槛、价格分组。
- **不外置**（保留在代码中）：规则的结构与判断逻辑、评分曲线公式（如 short_burst 的 55+... 插值式）、action_plan/status 文案、reasons/risks 文案。不做通用规则引擎。

### 改造点

- `strategy.py::check_signals` 增加可选参数 `rules: AnalysisRules | None = None`（None 时 `load_rules()`），所有魔法数字改引用 rules 字段。
- `stock_recommender.py` 同理引用 `RecommenderRules`；`PRICE_RANGES` 的读取来源从 `tradeeye/config.py` 迁移到 rules，`config.PRICE_RANGES` 删除（同步更新其引用与相关测试）。
- `app.py` 的 `LLM_SCORE_THRESHOLD` 常量改为从 rules 读取。

## B. 信号落地与胜率追踪

### B1. 每日信号落地

新模块 `tradeeye/services/signal_store.py`：

- `append_analysis_signals(rows, path="data/signals/analysis.csv")`
- `append_recommend_signals(rows, path="data/signals/recommend.csv")`
- 追加写入；写入前按 `(date, ts_code)` 去重（同日重跑覆盖旧行，保留最新）；文件不存在则连同目录一起创建并写表头；UTF-8。

CSV 列：

```
analysis.csv:  date, ts_code, name, score, status, close, called_llm
recommend.csv: date, ts_code, name, price_group, total_score, dimensions, close
```

- `date` = 信号对应交易日（YYYYMMDD）；`dimensions` 用 `|` 连接（如 `short_burst|t_active`）。
- `app.py`：对每只成功取数并打分的股票记录一行（无论分数高低），`called_llm` 标记是否触发了 LLM。
- `recommend_app.py`：记录当日两组全部入选标的。
- 落地失败（IO 异常）只记 error 日志，不影响工作流退出码——信号落地是旁路，不能阻断推送主链路。

### B2. Actions 自动提交回仓库

现有 `TradeEye-1.0.0.yml` 是单 job（`trade_eye_job`）+ 条件 step 结构（recommend 与 analysis 各一个条件 step）。在两个 run step 之后追加一个提交步骤：

```
git add data/signals/
若有变更: git commit -m "chore: record signals YYYY-MM-DD [skip ci]" && git push
```

- 使用 `github-actions[bot]` 身份；workflow 需声明 `permissions: contents: write`。
- 无变更（周末手动触发等）时静默跳过。
- push 前先 `git pull --rebase` 防冲突（recommend 与 analysis 定时错开，但调度随机延迟最长 30 分钟，存在小概率重叠），失败重试一次。

### B3. 每周胜率回测工作流

新增第四条工作流：

- 入口壳 `backtest_main.py`（3 行，风格同 `main.py`）
- 编排 `tradeeye/backtest_app.py::main(settings, loader, fetcher, notifier)` — 依赖注入风格与其余三条工作流一致，返回 0/1
- 核心 `tradeeye/services/backtest.py`：
  - `load_signals(path, lookback_days)` — 读 CSV，取最近 N 个自然日（默认 45，覆盖约 30 个交易日）内的信号
  - `evaluate_signals(signals, settings, pro_client)` — 对每个 `(date, ts_code)` 用 Tushare `daily` 拉信号日之后 10 个自然日内的行情，取信号日的下一交易日：
    - **隔夜收益** = 次日开盘 / 信号日收盘 − 1（对应"尾盘买、次日早盘卖"玩法）
    - **T+1 全天收益** = 次日收盘 / 信号日收盘 − 1
    - 取不到 T+1 行情（停牌/数据未出/新信号）→ 跳过并计入 `missing_count`
  - `build_backtest_report(results)` — 分组统计胜率（收益>0 占比）、平均收益、样本数：
    - analysis 信号按分数段：≥80（强候选）、65–79（候选）、<65
    - recommend 信号按 low_price_group / mid_price_group
    - 样本 <5 的分组标注"样本不足，仅供参考"
    - 两个收益口径都展示
- 推送复用 `services/notifier.py::send_text`，标题"策略胜率周报"
- 无信号文件或窗口内无信号 → 推送"暂无历史信号数据"并返回 0
- 新 workflow `.github/workflows/TradeEye-backtest-1.0.0.yml`：cron `30 10 * * 5`（北京周五 18:30）+ `workflow_dispatch`；secrets 同现有（TUSHARE_TOKEN、FEISHU_WEBHOOK）
- `Settings` 新增 `backtest_lookback_days`（环境变量 `BACKTEST_LOOKBACK_DAYS`，默认 45，最小 1）

## 测试策略

沿用现有 pytest + 依赖注入 mock 风格：

1. `tests/test_rules.py`：默认值等于现行硬编码值；yaml 覆盖生效；文件缺失/字段缺失/解析失败回退默认；`TRADEEYE_RULES_FILE` 生效。
2. 现有 `test_strategy.py`、`test_stock_recommender.py`、`test_app.py` 不改断言即全绿（验证纯重构）。
3. `tests/test_signal_store.py`：首写建目录建表头；追加；同键去重保留最新；IO 异常不抛出。
4. `tests/test_backtest.py`：构造信号+行情数据验证两个收益口径、胜率分组、样本不足标注、缺 T+1 数据计数、空信号路径。
5. `tests/test_backtest_app.py`：mock loader/fetcher/notifier 验证编排与退出码。

## 交付物清单

| 类型 | 路径 |
|---|---|
| 新增 | `tradeeye/strategies/rules.yaml`、`tradeeye/strategies/rules.py` |
| 新增 | `tradeeye/services/signal_store.py`、`tradeeye/services/backtest.py`、`tradeeye/backtest_app.py`、`backtest_main.py` |
| 新增 | `.github/workflows/TradeEye-backtest-1.0.0.yml` |
| 修改 | `strategy.py`、`stock_recommender.py`、`app.py`、`recommend_app.py`、`config.py`、`.github/workflows/TradeEye-1.0.0.yml` |
| 新增测试 | `test_rules.py`、`test_signal_store.py`、`test_backtest.py`、`test_backtest_app.py` |

## 明确不做（YAGNI）

- 通用规则引擎 / DSL
- 信号存 SQLite 或外部数据库
- T+3 / T+5 多周期回测（先跑通 T+1 闭环，后续按需加）
- news 工作流的任何改动
