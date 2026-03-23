# StockAnalysisSkill

一个面向 Claude / Codex 场景的股票分析 skill，支持：

- 单股分析
- 多股对比
- A 股 / 港股 / 美股市场复盘
- 策略判断

当前主要实现位于 `.claude/skills/StockAnalysis`，通过本地脚本抓取行情、市场和新闻，再生成可直接复述的中文分析结果。

## 项目结构

- `main.py`：兼容入口，将旧式 `main.py market ...` / `main.py stock ...` 调用转发到 skill 主入口
- `.claude/skills/StockAnalysis/SKILL.md`：skill 说明
- `.claude/skills/StockAnalysis/scripts/run.sh`：统一入口脚本
- `.claude/skills/StockAnalysis/scripts/fetch_quotes.sh`：个股行情抓取
- `.claude/skills/StockAnalysis/scripts/fetch_market.sh`：市场指数抓取
- `.claude/skills/StockAnalysis/scripts/fetch_news.sh`：新闻抓取

## 运行时

项目默认使用 `uv` 管理虚拟环境：

- 虚拟环境目录：`.claude/skills/StockAnalysis/.venv`
- 依赖声明：`.claude/skills/StockAnalysis/pyproject.toml`
- 首次运行时会通过 `scripts/ensure_venv.sh` 自动创建并同步依赖

## 配置

复制并填写：

- `.claude/skills/StockAnalysis/.env.example`

至少配置一个新闻 provider key：

- `TAVILY_API_KEY`
- `SERPAPI_API_KEY`
- `BRAVE_API_KEY`
- `BOCHA_API_KEY`

注意：

- `.env`
- `.claude/settings.local.json`
- `.venv`

这些本地文件不会被提交。

## 用法

### 查看状态

```bash
python3 main.py status
python3 main.py status --doctor
```

### 市场复盘

```bash
python3 main.py market --market A
python3 main.py market --market cn
python3 main.py market --market us
```

### 单股分析

```bash
python3 main.py stock --symbol 002594 --market A
python3 main.py stock --symbol AAPL --market us
```

### 直接调用 skill 入口

```bash
bash .claude/skills/StockAnalysis/scripts/run.sh market cn
bash .claude/skills/StockAnalysis/scripts/run.sh stock 002594 cn
bash .claude/skills/StockAnalysis/scripts/run.sh stock AAPL us
```

## 数据源

### 个股

- A 股 / 港股：`eastmoney -> sina -> tencent -> yfinance`
- 美股：`yfinance`

### 市场指数

- A 股：`eastmoney -> akshare`
- 港股 / 美股：`yfinance`

### 新闻

按 `.env` 中的 `NEWS_PROVIDER_PRIORITY` 顺序尝试。

## 发布说明

推送仓库前请确认：

- 不要提交 `.env`
- 不要提交 `.claude/settings.local.json`
- 不要提交 `.venv`
- 不要提交任何包含真实 key 的本地配置
