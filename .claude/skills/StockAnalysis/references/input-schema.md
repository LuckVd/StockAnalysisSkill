# Input Schema

All scripts should emit UTF-8 JSON to stdout.

## Quote payload

```json
{
  "symbols": [
    {
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "market": "us",
      "currency": "USD",
      "latest_price": 0,
      "change_pct": 0,
      "open": 0,
      "high": 0,
      "low": 0,
      "volume": 0,
      "turnover": null,
      "ma5": null,
      "ma10": null,
      "ma20": null,
      "recent_bars": []
    }
  ],
  "provider": "yfinance",
  "fetched_at": "2026-01-01T00:00:00Z"
}
```

## News payload

The skill now uses a comprehensive-intelligence structure modeled on the original project.
The flat `items` list is kept for compatibility, while `dimensions` carries the real analysis context.

```json
{
  "symbols": [
    {
      "symbol": "AAPL",
      "items": [
        {
          "title": "",
          "source": "",
          "published_at": "",
          "url": "",
          "snippet": "",
          "relevance_score": null
        }
      ],
      "dimensions": {
        "latest_news": {
          "name": "latest_news",
          "desc": "最新消息",
          "query": "AAPL stock latest news events",
          "provider": "tavily",
          "items": [],
          "errors": []
        },
        "market_analysis": {
          "name": "market_analysis",
          "desc": "机构分析",
          "query": "AAPL analyst rating target price report",
          "provider": "serpapi",
          "items": [],
          "errors": []
        },
        "risk_check": {
          "name": "risk_check",
          "desc": "风险排查",
          "query": "AAPL risk insider selling lawsuit litigation",
          "provider": "brave",
          "items": [],
          "errors": []
        },
        "earnings": {
          "name": "earnings",
          "desc": "业绩预期",
          "query": "AAPL earnings revenue profit growth forecast",
          "provider": "bocha",
          "items": [],
          "errors": []
        }
      },
      "provider": "tavily,serpapi",
      "errors": [],
      "search_days": 3
    }
  ],
  "provider": "tavily,serpapi,brave,bocha",
  "fetched_at": "2026-01-01T00:00:00Z",
  "search_days": 3,
  "mode": "comprehensive_intel"
}
```

## Market payload

```json
{
  "market": "us",
  "major_indexes": [],
  "breadth": null,
  "leaders_laggards": [],
  "market_summary": "",
  "provider": "yfinance",
  "fetched_at": "2026-01-01T00:00:00Z"
}
```
