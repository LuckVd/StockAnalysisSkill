# Providers

## Quotes

Preferred order:
- `yfinance` as the default quote source
- automatic fallback to `eastmoney` for A-share when `yfinance` fails or is rate-limited
- `tushare` remains optional for future A-share expansion

Required normalized fields:
- `symbol`
- `name`
- `market`
- `currency`
- `latest_price`
- `change_pct`
- `high`
- `low`
- `open`
- `volume`
- `turnover` when available
- `ma5`
- `ma10`
- `ma20`
- `recent_bars`

## News

Priority is controlled by `NEWS_PROVIDER_PRIORITY`.

Supported providers:
- `tavily`
- `serpapi`
- `brave`
- `bocha`

Each provider supports both a single key and a key pool:
- `TAVILY_API_KEY` or `TAVILY_API_KEYS`
- `SERPAPI_API_KEY` or `SERPAPI_API_KEYS`
- `BRAVE_API_KEY` or `BRAVE_API_KEYS`
- `BOCHA_API_KEY` or `BOCHA_API_KEYS`

`*_API_KEYS` uses comma-separated values. Example:
- `TAVILY_API_KEYS=key1,key2,key3`
- `BRAVE_API_KEYS=keyA,keyB`

The skill follows the original project's idea of `comprehensive_intel` instead of a single flat news query.
Each symbol is searched across dimensions:
- `latest_news`
- `market_analysis`
- `risk_check`
- `earnings`
- `industry`

Required article fields:
- `title`
- `source`
- `published_at`
- `url`
- `snippet`
- `relevance_score` when available

Required per-symbol news fields:
- `symbol`
- `items`
- `dimensions`
- `provider`
- `provider_keys`
- `errors`
- `search_days`

Rules:
- discard items older than `NEWS_MAX_AGE_DAYS`
- dynamically clamp the search window by weekday, matching the original project's logic
- deduplicate by title and source
- rotate providers across dimensions when possible
- within a provider, automatically rotate across key pools when a key fails or reaches quota
- key pool strategy is controlled by `NEWS_KEY_POOL_STRATEGY`, supporting `round_robin` and `random`
- keep both aggregated `items` and per-dimension `dimensions.*.items`

## Market

For CN, HK, and US market review, fetch representative indexes and a compact snapshot.

Required normalized fields:
- `market`
- `major_indexes`
- `breadth` when available
- `leaders_laggards` when available
- `market_summary`

实现说明：
- Brave 新闻搜索使用官方 News Search API，认证头为 `X-Subscription-Token`。
- Bocha 搜索使用官方 `POST /v1/web-search` 接口，认证头为 `Authorization: Bearer <KEY>`。
- 新闻搜索不是只搜一次，而是按维度拆分查询，再聚合成情报上下文。
- 当某个 provider 缺少 Key 或请求失败时，脚本会自动尝试下一个 provider。
- 当某个 provider 配了多个 key 时，脚本会在同一 provider 内自动轮换 key，并记录实际使用的是第几个 key。
