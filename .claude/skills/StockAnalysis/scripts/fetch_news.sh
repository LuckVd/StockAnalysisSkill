#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$($SCRIPT_DIR/ensure_venv.sh)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -f "$SKILL_DIR/.env" ]; then
  set -a
  . "$SKILL_DIR/.env"
  set +a
fi

if [ "$#" -lt 1 ]; then
  echo '{"error":"usage: fetch_news.sh SYMBOL [SYMBOL ...]"}'
  exit 1
fi

"$PYTHON_BIN" - "$@" <<'PY'
import json
import os
import random
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    import certifi
except Exception:
    certifi = None


RETRYABLE_HTTP_CODES = {401, 402, 403, 429, 430, 431, 432}


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def build_ssl_context():
    if certifi is not None:
        try:
            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass
    return ssl.create_default_context()


def fetch_json(url, timeout, method='GET', headers=None, body=None):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header('User-Agent', 'StockAnalysisSkill/0.1')
    req.add_header('Accept', 'application/json')
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    context = build_ssl_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        return json.loads(resp.read().decode('utf-8'))


def parse_date(value):
    """Parse ISO 8601 date string, compatible with Python 3.6+"""
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None

    # Handle common ISO 8601 formats manually for Python 3.6 compatibility
    # datetime.fromisoformat() was added in Python 3.7

    # Replace Z with +00:00 for UTC
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'

    # Remove ' UTC' suffix if present
    if value.endswith(' UTC'):
        value = value[:-4]

    # Try parsing with strptime for common formats
    formats = [
        '%Y-%m-%dT%H:%M:%S%z',           # 2023-01-01T12:00:00+08:00
        '%Y-%m-%dT%H:%M:%S.%f%z',         # 2023-01-01T12:00:00.123456+08:00
        '%Y-%m-%dT%H:%M:%S',              # 2023-01-01T12:00:00
        '%Y-%m-%dT%H:%M:%S.%f',           # 2023-01-01T12:00:00.123456
        '%Y-%m-%d %H:%M:%S',              # 2023-01-01 12:00:00
        '%Y-%m-%d',                       # 2023-01-01
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue

    return None


def within_days(dt, max_days):
    if dt is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
    return dt >= cutoff


def dedupe(items):
    seen = set()
    result = []
    for item in items:
        key = (
            (item.get('title') or '').strip().lower(),
            (item.get('source') or '').strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def split_csv_keys(*values):
    results = []
    for value in values:
        raw = (value or '').strip()
        if not raw:
            continue
        for part in raw.split(','):
            item = part.strip()
            if item and item not in results:
                results.append(item)
    return results


def provider_keys(provider):
    name = provider.strip().lower()
    if name == 'tavily':
        return split_csv_keys(os.getenv('TAVILY_API_KEY'), os.getenv('TAVILY_API_KEYS'))
    if name == 'serpapi':
        return split_csv_keys(os.getenv('SERPAPI_API_KEY'), os.getenv('SERPAPI_API_KEYS'))
    if name == 'brave':
        return split_csv_keys(os.getenv('BRAVE_API_KEY'), os.getenv('BRAVE_API_KEYS'))
    if name == 'bocha':
        return split_csv_keys(os.getenv('BOCHA_API_KEY'), os.getenv('BOCHA_API_KEYS'))
    return []


def mask_key(key):
    if not key:
        return 'empty'
    if len(key) <= 8:
        return key
    return key[:6] + '...' + key[-4:]


def format_http_error(exc):
    payload = ''
    try:
        payload = exc.read().decode('utf-8', errors='replace')[:300]
    except Exception:
        payload = ''
    message = f'http {exc.code}'
    if payload:
        message += f' {payload}'
    return message


def ordered_key_pool(provider, base_offset=0):
    keys = provider_keys(provider)
    if not keys:
        return []
    strategy = os.getenv('NEWS_KEY_POOL_STRATEGY', 'round_robin').strip().lower() or 'round_robin'
    indexed = list(enumerate(keys))
    if strategy == 'random':
        rng = random.SystemRandom()
        rng.shuffle(indexed)
        return indexed
    offset = base_offset % len(indexed)
    return indexed[offset:] + indexed[:offset]


def with_key_pool(provider, runner, base_offset=0):
    indexed_keys = ordered_key_pool(provider, base_offset)
    if not indexed_keys:
        raise RuntimeError(f'missing {provider.upper()}_API_KEY or {provider.upper()}_API_KEYS')
    errors = []
    for real_idx, key in indexed_keys:
        try:
            items = runner(key)
            return items, real_idx
        except urllib.error.HTTPError as exc:
            detail = format_http_error(exc)
            errors.append(f'key#{real_idx + 1}({mask_key(key)}): {detail}')
            if exc.code not in RETRYABLE_HTTP_CODES:
                break
        except Exception as exc:
            errors.append(f'key#{real_idx + 1}({mask_key(key)}): {exc}')
    raise RuntimeError('; '.join(errors))


def tavily_search(query, timeout, max_days, key_offset=0):
    def run(api_key):
        body = json.dumps({
            'api_key': api_key,
            'query': query,
            'topic': 'news',
            'days': max_days,
            'max_results': 6,
            'search_depth': 'basic',
            'include_answer': False,
            'include_images': False,
            'include_raw_content': False,
        }).encode('utf-8')
        payload = fetch_json(
            'https://api.tavily.com/search',
            timeout,
            method='POST',
            headers={'Content-Type': 'application/json'},
            body=body,
        )
        items = []
        for row in payload.get('results', []) or []:
            published = row.get('published_date') or row.get('published_at')
            dt = parse_date(published)
            if not within_days(dt, max_days):
                continue
            items.append({
                'title': row.get('title'),
                'source': row.get('source') or 'tavily',
                'published_at': published,
                'url': row.get('url'),
                'snippet': row.get('content'),
                'relevance_score': row.get('score'),
            })
        return dedupe(items)[:6]

    items, key_index = with_key_pool('tavily', run, key_offset)
    return items, key_index


def serpapi_search(query, timeout, max_days, key_offset=0):
    def run(api_key):
        params = urllib.parse.urlencode({
            'engine': 'google_news',
            'q': query,
            'api_key': api_key,
            'hl': 'en',
            'gl': 'us',
        })
        payload = fetch_json('https://serpapi.com/search.json?' + params, timeout)
        items = []
        for row in payload.get('news_results', []) or []:
            items.append({
                'title': row.get('title'),
                'source': (row.get('source') or {}).get('name') if isinstance(row.get('source'), dict) else row.get('source'),
                'published_at': row.get('date'),
                'url': row.get('link'),
                'snippet': row.get('snippet'),
                'relevance_score': None,
            })
        return dedupe(items)[:6]

    items, key_index = with_key_pool('serpapi', run, key_offset)
    return items, key_index


def brave_search(query, timeout, max_days, key_offset=0):
    def run(api_key):
        freshness = 'pd' if max_days <= 1 else 'pw' if max_days <= 7 else 'pm' if max_days <= 31 else 'py'
        params = urllib.parse.urlencode({
            'q': query,
            'count': 6,
            'search_lang': 'en',
            'country': 'US',
            'freshness': freshness,
        })
        payload = fetch_json(
            'https://api.search.brave.com/res/v1/news/search?' + params,
            timeout,
            headers={'X-Subscription-Token': api_key, 'Accept-Encoding': 'gzip'},
        )
        rows = payload.get('results') or payload.get('news') or []
        items = []
        for row in rows:
            meta_url = row.get('meta_url') if isinstance(row.get('meta_url'), dict) else {}
            published = row.get('page_age') or row.get('published') or row.get('published_at')
            dt = parse_date(published)
            if not within_days(dt, max_days):
                continue
            items.append({
                'title': row.get('title'),
                'source': meta_url.get('hostname') or row.get('source') or 'brave',
                'published_at': published,
                'url': row.get('url'),
                'snippet': row.get('description') or row.get('snippet'),
                'relevance_score': row.get('score'),
            })
        return dedupe(items)[:6]

    items, key_index = with_key_pool('brave', run, key_offset)
    return items, key_index


def bocha_search(query, timeout, max_days, key_offset=0):
    def run(api_key):
        freshness = 'oneDay' if max_days <= 1 else 'oneWeek' if max_days <= 7 else 'oneMonth' if max_days <= 31 else 'oneYear'
        body = json.dumps({
            'query': query,
            'freshness': freshness,
            'summary': True,
            'count': 6,
        }).encode('utf-8')
        payload = fetch_json(
            'https://api.bochaai.com/v1/web-search',
            timeout,
            method='POST',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            body=body,
        )
        rows = (((payload.get('data') or {}).get('webPages') or payload.get('webPages') or {}).get('value') or [])
        items = []
        for row in rows:
            published = row.get('publishedDate') or row.get('datePublished') or row.get('date')
            dt = parse_date(published)
            if not within_days(dt, max_days):
                continue
            items.append({
                'title': row.get('name') or row.get('title'),
                'source': row.get('siteName') or 'bocha',
                'published_at': published,
                'url': row.get('url'),
                'snippet': row.get('summary') or row.get('snippet') or row.get('description'),
                'relevance_score': row.get('score'),
            })
        return dedupe(items)[:6]

    items, key_index = with_key_pool('bocha', run, key_offset)
    return items, key_index


def try_provider(provider, query, timeout, max_days, key_offset=0):
    if provider == 'tavily':
        return tavily_search(query, timeout, max_days, key_offset)
    if provider == 'serpapi':
        return serpapi_search(query, timeout, max_days, key_offset)
    if provider == 'brave':
        return brave_search(query, timeout, max_days, key_offset)
    if provider == 'bocha':
        return bocha_search(query, timeout, max_days, key_offset)
    raise RuntimeError(f'provider {provider} is not implemented yet')


def split_symbol_name(raw):
    if '::' in raw:
        symbol, name = raw.split('::', 1)
        return symbol.strip(), name.strip()
    return raw.strip(), ''


def infer_market(symbol):
    upper = symbol.upper()
    if re.search(r'(^[0-9]{6}$)|\.(SS|SZ)$', upper):
        return 'cn'
    if re.search(r'(^HK[0-9]+$)|\.(HK)$|(^[0-9]{1,5}$)', upper):
        return 'hk'
    return 'us'


def build_dimensions(symbol, stock_name=''):
    market = infer_market(symbol)
    stock_name = (stock_name or '').strip()
    query_base = symbol if not stock_name or stock_name.lower() == symbol.lower() else f'{stock_name} {symbol}'
    if market in ('us', 'hk'):
        return [
            {'name': 'latest_news', 'desc': '最新消息', 'query': f'{query_base} stock latest news events'},
            {'name': 'market_analysis', 'desc': '机构分析', 'query': f'{query_base} analyst rating target price report'},
            {'name': 'risk_check', 'desc': '风险排查', 'query': f'{query_base} risk insider selling lawsuit litigation'},
            {'name': 'earnings', 'desc': '业绩预期', 'query': f'{query_base} earnings revenue profit growth forecast'},
            {'name': 'industry', 'desc': '行业分析', 'query': f'{query_base} industry competitors market share outlook'},
        ]
    # CN market: use shorter queries for better search relevance
    return [
        {'name': 'latest_news', 'desc': '最新消息', 'query': f'{query_base} 最新 新闻'},
        {'name': 'market_analysis', 'desc': '机构分析', 'query': f'{query_base} 研报 评级'},
        {'name': 'risk_check', 'desc': '风险排查', 'query': f'{query_base} 减持 风险'},
        {'name': 'earnings', 'desc': '业绩预期', 'query': f'{query_base} 业绩 财报'},
        {'name': 'industry', 'desc': '行业分析', 'query': f'{query_base} 行业 前景'},
    ]


def search_dimension(priority, dimension, timeout, max_days, start_index):
    all_errors = []
    for offset in range(len(priority)):
        provider = priority[(start_index + offset) % len(priority)]
        key_offset = start_index + offset + len(dimension['name'])
        try:
            items, key_index = try_provider(provider, dimension['query'], timeout, max_days, key_offset)
            return {
                'name': dimension['name'],
                'desc': dimension['desc'],
                'query': dimension['query'],
                'provider': provider,
                'provider_key_index': key_index,
                'items': items,
                'errors': all_errors,
            }
        except Exception as exc:
            all_errors.append(f'{provider}: {exc}')
    return {
        'name': dimension['name'],
        'desc': dimension['desc'],
        'query': dimension['query'],
        'provider': None,
        'provider_key_index': None,
        'items': [],
        'errors': all_errors or ['no provider available'],
    }


def main():
    priority = [p.strip() for p in os.getenv('NEWS_PROVIDER_PRIORITY', 'tavily,serpapi,brave,bocha').split(',') if p.strip()]
    timeout = float(os.getenv('REQUEST_TIMEOUT', '20'))
    max_days_cfg = max(1, int(os.getenv('NEWS_MAX_AGE_DAYS', '3')))
    now_weekday = datetime.now().weekday()
    if now_weekday == 0:
        weekday_days = 3
    elif now_weekday >= 5:
        weekday_days = 2
    else:
        weekday_days = 1
    max_days = min(weekday_days, max_days_cfg)
    max_dimensions = max(1, int(os.getenv('NEWS_MAX_DIMENSIONS', '5')))

    results = []
    used_providers = []
    used_provider_keys = []
    for index, raw_symbol in enumerate(sys.argv[1:]):
        symbol, stock_name = split_symbol_name(raw_symbol)
        dimensions = build_dimensions(symbol, stock_name)[:max_dimensions]
        dimension_results = {}
        aggregate_items = []
        aggregate_errors = []
        provider_cursor = index % len(priority) if priority else 0
        for dim in dimensions:
            dim_result = search_dimension(priority, dim, timeout, max_days, provider_cursor) if priority else {
                'name': dim['name'],
                'desc': dim['desc'],
                'query': dim['query'],
                'provider': None,
                'provider_key_index': None,
                'items': [],
                'errors': ['no provider configured'],
            }
            dimension_results[dim['name']] = dim_result
            if dim_result['provider']:
                used_providers.append(dim_result['provider'])
                used_provider_keys.append(f"{dim_result['provider']}#{(dim_result['provider_key_index'] or 0) + 1}")
                provider_cursor = (priority.index(dim_result['provider']) + 1) % len(priority)
            aggregate_items.extend(dim_result['items'])
            aggregate_errors.extend([f"{dim['name']}: {err}" for err in dim_result['errors']])
        results.append({
            'symbol': symbol,
            'name': stock_name or None,
            'items': dedupe(aggregate_items)[:12],
            'dimensions': dimension_results,
            'provider': ','.join(sorted({p for p in used_providers if p})) or None,
            'provider_keys': sorted({p for p in used_provider_keys if p}),
            'errors': aggregate_errors,
            'search_days': max_days,
        })

    payload = {
        'symbols': results,
        'provider': ','.join(sorted(set(p for p in used_providers if p))) or None,
        'provider_keys': sorted(set(p for p in used_provider_keys if p)),
        'fetched_at': utc_now(),
        'search_days': max_days,
        'mode': 'comprehensive_intel',
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
PY
