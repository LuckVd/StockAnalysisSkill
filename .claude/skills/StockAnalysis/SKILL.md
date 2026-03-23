---
name: StockAnalysis
description: 当用户需要股票分析、市场复盘、多股票对比、策略问股，或需要通过对话完成这个 skill 的配置时使用。这个 skill 通过本地脚本抓取行情和新闻、构建分析上下文，再由当前宿主智能体本身完成最终分析，支持 A 股、港股和美股。
---

# StockAnalysis

这是一个单入口 skill。宿主里通常只会显示一个命令：`StockAnalysis`。
不要把它当成多个 slash command 的集合。首次触发时，优先做配置检查和对话式引导；配置满足后，再进入分析流程。

## 何时使用

适用场景：
- 用户要分析单只股票
- 用户要对比多只股票并排序
- 用户要做 CN / HK / US 市场复盘
- 用户要按策略判断一只股票
- 用户要配置这个 skill，或询问当前缺了哪些配置、现在能做什么

不适用场景：
- 只聊泛化投资常识
- 当前环境无法执行本地 shell 或 Python 脚本
- 用户要求严格实时结论，但当前环境无网络且无任何可用 provider

## 路径约定

Python 解释器优先级：
- 如果 `.env` 中设置了 `STOCK_ANALYSIS_PYTHON`，优先使用它
- 如果该路径不存在或不可执行，自动回退到较新的系统 Python，例如 `python3.12`、`python3.11`、`python3`

Claude Code 在这个项目里通常会从项目根目录 `/opt/projects/StockAnalysis` 执行命令，而不是从 skill 目录执行。
因此这里所有 shell 命令都必须写项目根相对路径，例如：
- `python3 .claude/skills/StockAnalysis/scripts/skill_status.py`
- `bash .claude/skills/StockAnalysis/scripts/run.sh stock AAPL`

## 运行时

这个 skill 现在默认使用 `uv` 管理自己的虚拟环境。
- 分析相关脚本会优先使用 `.claude/skills/StockAnalysis/.venv/bin/python`
- 如果虚拟环境不存在，会自动通过 `uv` 创建并安装依赖
- 如果 `.env` 中设置了 `STOCK_ANALYSIS_PYTHON` 且该路径可用，则优先使用该解释器，不强制走 `.venv`

## 单入口原则

每次触发 `StockAnalysis`，先做这一步：
1. 运行 `python3 .claude/skills/StockAnalysis/scripts/skill_status.py`
2. 读取当前状态 JSON
3. 如果必要配置未满足，先进入对话式配置，不要直接分析
4. 如果用户只是问怎么用、缺什么、现在能做什么，也先基于状态回答
5. 只有在配置已足够时，才进入 stock / market / strategy / list 分析流程

## 对话式配置

当 `skill_status.py` 返回的 `missing_required` 非空时，先配置，不要分析。

配置时必须遵守：
- 全程中文
- 每次只问一个最关键问题
- 默认最小可用配置是：至少一个新闻搜索 Key
- 默认不要求用户配置 `OPENAI_API_KEY`，因为最终分析由宿主模型完成
- 用户一旦给出配置值，立即写入 `.env`，不要让用户手工编辑文件

写配置使用：
- `python3 .claude/skills/StockAnalysis/scripts/set_env.py --set KEY=VALUE`
- 一次可写多个，例如：
  - `python3 .claude/skills/StockAnalysis/scripts/set_env.py --set BRAVE_API_KEY=xxx --set NEWS_PROVIDER_PRIORITY=brave,tavily`

推荐配置优先级：
1. 先补任意一个新闻 provider Key：`TAVILY_API_KEY` / `SERPAPI_API_KEY` / `BRAVE_API_KEY` / `BOCHA_API_KEY`
2. 再按需补 `TUSHARE_TOKEN`
3. 如需强制指定解释器，可补 `STOCK_ANALYSIS_PYTHON=/path/to/python`
4. 默认运行时是 `uv` 虚拟环境，可通过 `uv` 自动安装依赖
5. 只有用户明确要求保留 skill 内部 LLM 回退时，才补 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`

如果用户说“帮我配置”或“这个 skill 现在怎么用不了”，你的行为应该是：
1. 先汇总当前状态
2. 明确现在最小可用能力和缺失项
3. 只问下一项最关键配置
4. 用户答复后，直接用 `set_env.py` 写入
5. 再告诉用户现在已经解锁了哪些能力

## 状态和帮助

如果用户问“怎么使用”“现在能做什么”“还缺什么配置”，先运行：
- `python3 .claude/skills/StockAnalysis/scripts/skill_status.py`

然后用中文简洁说明：
- 当前状态：`ready` / `partial` / `unavailable`
- 已配置的新闻 provider
- 还缺哪些必要配置
- 还缺哪些可选配置
- 现在能做什么：单股、批量、市场、策略、新闻增强是否可用

## 分析流程

只有在必要配置满足时，才进入分析。

执行约束：
- 行情抓取入口只有 `bash .claude/skills/StockAnalysis/scripts/fetch_quotes.sh ...`
- 新闻抓取入口只有 `bash .claude/skills/StockAnalysis/scripts/fetch_news.sh ...`
- 不要自行假设存在 `fetch_quotes.py`、`fetch_news.py`、`fetch_market.py` 这类文件
- 默认优先使用 `bash .claude/skills/StockAnalysis/scripts/run.sh ...`，而不是跳过包装脚本手工拼调用链

### 单股分析

适用于：
- 分析 `AAPL`
- 看一下 `600519`
- `TSLA` 现在值不值得继续观察

执行：
- `bash .claude/skills/StockAnalysis/scripts/run.sh stock SYMBOL [MARKET]`

内部流程：
1. `bash .claude/skills/StockAnalysis/scripts/fetch_quotes.sh SYMBOL`
2. `bash .claude/skills/StockAnalysis/scripts/fetch_news.sh SYMBOL`
3. `bash .claude/skills/StockAnalysis/scripts/fetch_market.sh MARKET`
4. `python3 .claude/skills/StockAnalysis/scripts/normalize_data.py`
5. `python3 .claude/skills/StockAnalysis/scripts/build_analysis_context.py --mode stock`
6. `python3 .claude/skills/StockAnalysis/scripts/build_host_prompt.py --mode stock`
7. 由当前宿主智能体基于输出的提示词直接生成最终中文分析

### 多股分析

执行：
- `bash .claude/skills/StockAnalysis/scripts/run.sh list MARKET SYMBOL1 SYMBOL2 ...`

先给排序，再给逐股分析。

### 市场复盘

执行：
- `bash .claude/skills/StockAnalysis/scripts/run.sh market MARKET`

### 策略判断

执行：
- `bash .claude/skills/StockAnalysis/scripts/run.sh strategy SYMBOL STRATEGY [MARKET]`

当前内置策略：
- `ma_golden_cross`
- `shrink_pullback`
- `bull_trend`
- `box_oscillation`

详细规则见：
- `.claude/skills/StockAnalysis/references/strategies.md`

## 输出纪律

始终遵守：
- 只要看到了 `=== STOCKANALYSIS_STATUS ===` 状态区块，就只能按该区块里的字段判定成功或失败，禁止凭界面上的 `(timeout 2m)`、命令折叠、省略显示或主观猜测下结论
- 如果 `DATA_STATUS=OK` 或 `QUOTE_STATUS=OK`，必须立即停止一切 fallback 思路，直接基于当前数据输出分析
- 禁止把 Claude Code 界面里的 `(timeout 2m)` 文字当成脚本执行失败信号；它不是业务状态字段
- 先读取输出最顶部的状态区块和已验证数据区块；如果 DATA_STATUS=OK，就直接进入分析，不要再做二次抓数或旁路排障
- 如果 `bash .claude/skills/StockAnalysis/scripts/run.sh stock ...` 或同类命令已经输出了明确的价格、均线、市场说明、新闻摘要，则视为主链路抓数成功，不要再声称“行情未获取”或“新闻未获取”
- 不要在主链路成功后再自行运行 `python3 -c "import yfinance"` 这类旁路检查来否定已有结果
- 不要因为某个备用排障命令失败，就覆盖主链路已经拿到的有效数据结论
- 对 list 模式也一样：只要 DATA_STATUS=OK，就必须直接完成多股排序和逐股分析，禁止再调用 web search 或其他备用行情源
- 区分事实与推断
- 不要把缺失数据说成实时数据
- 如果 NEWS_STATUS=PARTIAL，要明确说明新闻不完整，但这不等于行情失败，也不允许触发二次抓数。
- 新闻失败时要明确说明新闻不可用
- 行情缺失时不提供精确买卖点
- 除非用户要求，不要直接倾倒原始 JSON
- 最终分析默认由宿主模型完成，不要优先走 skill 内部独立 LLM

## 手工命令

如果你需要直接调用脚本，可用这些命令：
- `bash .claude/skills/StockAnalysis/scripts/run.sh doctor`
- `bash .claude/skills/StockAnalysis/scripts/run.sh set-env KEY=VALUE [KEY=VALUE ...]`
- `bash .claude/skills/StockAnalysis/scripts/run.sh stock AAPL`
- `bash .claude/skills/StockAnalysis/scripts/run.sh stock 600519`
- `bash .claude/skills/StockAnalysis/scripts/run.sh market us`
- `bash .claude/skills/StockAnalysis/scripts/run.sh strategy AAPL ma_golden_cross us`
- `bash .claude/skills/StockAnalysis/scripts/run.sh list us AAPL TSLA MSFT`
