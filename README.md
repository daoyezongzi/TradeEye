# TradeEye

TradeEye 是一个面向 A 股的确定性盘后研究与虚拟组合跟踪项目。它按每天 2 次核心 GitHub Actions 批处理运行：早晨生成每日荐股，完整日线就绪后推进三日交易状态与净值，再生成自选股盘后诊断。项目不连接券商、不自动下单，也不调用 LLM。

## 已有功能

| 功能 | 当前能力 | 主要输出 |
| --- | --- | --- |
| 每日荐股 `recommend` | 全市场统一股票池、三维质量评分、独立风险门、低价软偏好，每日最多 5 只且允许少推或不推 | 飞书确定性报告；`data/signals/recommend.csv` |
| ETF 研究接口 | 默认关闭；启用后仅分析配置白名单，使用独立评分、版本、报告和信号文件 | 报告独立分栏；`data/signals/etf_recommend.csv` |
| 虚拟组合 `settle` | 按 D+1 回踩、最长 D+3、止盈止损、5 槽位和每日最多 2 笔规则增量推进 | `data/trades/recommend_trades.csv`；`data/portfolio/recommend_nav.csv` |
| 盘后诊断 `analysis` | 对 `MY_STOCKS` 做五维结构评分、数据质量检查、风险矩阵和次日观察点 | 飞书盘后诊断，不进入荐股组合或交易周报 |
| 交易周报 `backtest` | 仅评价 `recommend`，并列本周与滚动窗口的信号层、组合层表现 | 飞书荐股交易周报 |
| 主题简报 `news` | 独立的 RSS/Atom 聚合、关键词过滤、去重、时间窗和模板接口 | 可选飞书单向简报 |
| 自动化与可靠性 | 业务调度、push/PR CI、数据写入串行化、原子 CSV、严格规则校验、主/辅行情失败分类 | GitHub Actions 运行记录和版本化研究数据 |

## 快速开始

需要 Python 3.11+；GitHub Actions 当前使用 Python 3.13。

```powershell
git clone https://github.com/daoyezongzi/TradeEye.git
cd TradeEye
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

至少配置：

```dotenv
TUSHARE_TOKEN=your_tushare_token
FEISHU_WEBHOOK=your_feishu_webhook
DEBUG_MODE=false
MY_STOCKS=600370.SH,600157.SH,603010.SH
ALLOWED_EXCHANGES=SH,SZ,BJ
BACKTEST_LOOKBACK_DAYS=45
```

本地入口：

```powershell
python recommend_main.py  # 生成股票荐股；ETF 启用时同批运行
python portfolio_main.py  # 推进交易状态和日度净值
python main.py            # 自选股盘后诊断
python backtest_main.py   # 生成荐股交易周报
python news_main.py       # 可选主题简报
```

Windows 也可使用：

```powershell
.\run_tradeeye.bat recommend
.\run_tradeeye.bat settle
.\run_tradeeye.bat analysis
.\run_tradeeye.bat evening  # 依次 settle + analysis
.\run_tradeeye.bat backtest
.\run_tradeeye.bat news
```

BAT 会把工作目录锚定到仓库根目录；未创建 `.venv` 时回退到系统 `python`。

## 每日荐股规则

股票评分为三个只加分且分别封顶的维度，总质量分始终等于三维之和：

| 维度 | 上限 | 主要输入 |
| --- | ---: | --- |
| 短线动能 | 40 | 当日涨幅、全市场涨幅排名 |
| 收盘质量 | 35 | 收盘位置、阳线实体、上影线 |
| 量能与资金 | 25 | 换手、量比、成交额排名、资金与大单净流向 |

默认最低质量分为 55，这只是待历史样本验证的研究基线，不代表最优参数。风险不从质量分里倒扣，而是在总分之外单独处理：

- `close_strength < 0.45` 且上影线 `> 2.5%`：硬剔除。
- 涨幅 `> 8%`、换手率 `> 18%`、量比 `> 4`：命中 2 项及以上硬剔除。
- 只命中 1 项：保留为单项过热候选，但排在所有普通候选之后。
- 先过风险门和绝对质量门，再按风险层、质量分与价格偏好排序；每日最多发布 5 条，不为凑数递补。

股票不再按 `0-10 / 10-20` 元硬分组。默认对 20 元及以下股票增加 3 分排序偏好，但这 3 分不写入质量分，也不改变三维评价。行业只保存和展示，不做第一版持仓硬上限。

### 规则配置

版本化策略参数位于 [rules.yaml](tradeeye/strategies/rules.yaml)。加载器严格校验未知键、类型、枚举、ETF 代码和参数边界；错误配置会直接让任务失败，不会静默扩大股票池。

```yaml
recommender:
  strategy_version: recommend_v2
  minimum_quality_score: 55
  max_results: 5
  hard_min: null
  hard_max: null
  preferred_price_max: 20
  preferred_price_bonus: 3
  entry_price_multiplier: 0.98

etf:
  enabled: false
  mode: whitelist
  codes: []
  strategy_version: etf_recommend_v1
  minimum_quality_score: 50
  max_results: 5
```

- `hard_min / hard_max: null` 表示不做硬价格过滤；需要限定价格范围时再填写正数。
- 修改策略语义时应同时升级 `strategy_version`，避免不同规则被拼进同一净值序列。
- 本地或 Actions 可用 `TRADEEYE_RULES_FILE` 临时指向仓库中的另一份 YAML 做参数实验；显式路径不存在时任务会失败。
- ETF 默认零接口调用。启用后使用动能 45、收盘质量 35、流动性 20 的独立评分，不读取股票资金流，也不竞争股票 Top 5 或股票组合槽位。

ETF 行情使用 Tushare [ETF 基础信息](https://tushare.pro/document/2?doc_id=385) 和 [公募基金日线行情](https://tushare.pro/document/2?doc_id=127)。接口权限或白名单行情不可用时，只降级 ETF 分支，股票荐股继续运行。

## 三日交易与组合口径

荐股只是研究信号；以下规则用于虚拟账本和周报，不会发出真实订单。

| 日期 | 状态推进 |
| --- | --- |
| D | 记录信号，计划入场价为 D 收盘价 × 98% |
| D+1 | 最低价触及计划价才模拟成交；成交价取 `min(开盘价, 计划价)`，未触及即过期 |
| D+2 | 遵守 T+1 后开始判断 `+4%` 止盈和 `-3%` 止损 |
| D+3 | 继续判断止盈止损；都未触发时按收盘价超时退出 |

其他成交假设：

- 跳空越过止盈/止损线时按开盘价；同一日同时触发时按止损优先。
- 每笔退出统一扣除 0.15 个百分点往返成本，同时保存毛收益与净收益。
- 使用 5 个等权归一化槽位，每日最多新开 2 笔；没有足够质量的信号时现金槽位留给以后。
- 容量按开盘前已有空槽判断；当日稍后退出释放的槽位从下一批次起才可使用。
- 同一股票已在组合中时不重复占槽；被容量、每日上限或重复持仓跳过的信号仍保留信号层模拟结果。
- 第一版不设置行业持仓硬上限，但保存行业分布、最大行业占比和未知行业数量。

### 停牌、缺行情和失败分类

- 主行情、交易日历或完整市场批次失败：本次结算返回失败且不推进任何状态。
- 市场批次完整，但 D+1 单只股票没有有效 OHLC：记为 `entry_unavailable`，不进入触发率或胜率分母。
- D+2 个股无报价：保持 `open`，使用最后有效收盘价做陈旧估值。
- 到 D+3 应退出但无报价或一字跌停：记为 `exit_deferred`，继续占槽；首个可交易日按开盘价退出。
- 账本同时记录计划退出日、实际退出日、延期交易日数和原因。

结算按已有交易/NAV 水位增量推进：同一日期重跑不会重复请求行情或改写数据；新增一天只获取新增交易日行情。

## 盘后诊断

`analysis` 只解释完整日线后的自选股结构，不产生荐股、自动仓位或交易收益。

| 维度 | 上限 |
| --- | ---: |
| 趋势结构 | 30 |
| 收盘与价格行为 | 25 |
| 量能与流动性 | 20 |
| 资金确认 | 15 |
| 市场环境 | 10 |

原始分档为：80-100 强、65-79 较强、50-64 中性、0-49 弱。风险等级与原始分分开：

| 原始结构 | 低风险 | 中风险 | 高风险 |
| --- | --- | --- | --- |
| 强 | 强 | 观察 | 高风险 |
| 较强 | 较强 | 观察 | 高风险 |
| 中性 | 中性 | 谨慎 | 高风险 |
| 弱 | 弱 | 弱 | 高风险 |

关键字段、个股辅助行情或上游数据源缺失时直接显示“数据不足”，不把缺失值当作 0 分。报告固定展示五维分、原始总分、风险、最终状态、依据和次日观察点，不含买卖指令。

## 周报与数据文件

周报只读取荐股交易账本，不把 `analysis` 当成买入信号。每个策略版本分别展示本周和 `BACKTEST_LOOKBACK_DAYS`（默认 45 个日历日）：

- 信号层：推荐数、可用分母、触发率、实际结算周的扣费胜率、均值、中位数、平均盈利/亏损、盈亏比、最大亏损和退出原因。
- 组合层：实际纳入数、已实现贡献、平均槽位使用率、期末开放/延期持仓、容量跳过和行业集中度。
- 开放交易不进入胜率；跨周退出按实际退出日计入结算周，不会永远漏掉。

| 文件 | 作用 |
| --- | --- |
| `data/signals/recommend.csv` | 不可变股票荐股信号、三维分、风险、规则指纹和计划价 |
| `data/signals/etf_recommend.csv` | 独立 ETF 研究信号 |
| `data/trades/recommend_trades.csv` | 信号层与组合层交易状态、成交、成本和退出结果 |
| `data/portfolio/recommend_nav.csv` | 每个策略版本的日度净值、日收益、现金/持仓槽位、陈旧估值和结算水位 |

CSV 使用稳定 ID、版本化表头、首次写入不覆盖和同目录临时文件原子替换。旧版荐股 CSV 仍能作为 `legacy_v1` 读取，但不会与 `recommend_v2` 合并成同一净值序列。

当前周报不展示年化、夏普或完整回撤；连续净值和交易明细已经为未来计算年化收益、波动率、最大回撤与净值曲线保留输入。样本不足时不应展示容易误导的年化值。

## GitHub Actions

| 工作流 | 北京时间 | 内容 |
| --- | --- | --- |
| `TradeEye-1.0.0.yml` | 工作日 06:00 | 每日股票荐股；ETF 启用时同批运行 |
| `TradeEye-1.0.0.yml` | 工作日 18:00 | 先推进交易/NAV，再做盘后诊断 |
| `TradeEye-backtest-1.0.0.yml` | 周五 19:30 | 读取最新账本并发送周报 |
| `TradeEye-news-1.0.0.yml` | 工作日 07:30 | 独立可选主题简报 |
| `TradeEye-ci.yml` | push / pull request | 完整测试与 Python 编译检查 |

需要在仓库设置：

- Secrets：`TUSHARE_TOKEN`、`FEISHU_WEBHOOK`
- Variables：`MY_STOCKS`、`ALLOWED_EXCHANGES`、`BACKTEST_LOOKBACK_DAYS`，可选 `TRADEEYE_RULES_FILE`，以及需要时的新闻变量

业务工作流只安装运行依赖，不重复跑完整测试；写数据的任务共享同一并发组，提交 `data/signals/`、`data/trades/` 和 `data/portfolio/`。周五周报在发送前还会确认当天晚间核心批次已经成功完成，避免调度延迟时读取旧账本。项目不再需要任何 LLM Secret、模型地址或超时变量，旧的相关 GitHub 配置可手动删除。

## News 边界

`news` 暂时保持为独立、低优先级的单向资讯接口，不参与评分、交易或周报。它支持多个 RSS/Atom 源、包含/排除关键词、回看时间窗、去重、条数上限、自定义模板和无结果是否推送；全部已配置来源均失败时任务返回失败，不把故障伪装成正常空结果。跨批次持久去重、逐来源健康汇总与未知发布时间处理保留在 TODO。

## 验证

```powershell
python -m pytest
python -m compileall -q tradeeye
git diff --check
```

本项目是研究与自动化记录工具，不构成投资建议。日线无法还原完整盘中成交顺序，费用、滑点、涨跌停可成交性与真实账户约束都可能不同；任何收益指标都必须结合样本量、策略版本和模型假设阅读。
