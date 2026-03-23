#!/usr/bin/env python3
import json
import os
import shutil
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / '.env'
ENV_EXAMPLE = ROOT / '.env.example'


def parse_env_file(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        data[key.strip()] = value.strip()
    return data


def first_nonempty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ''


def split_csv_values(*values: str):
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


def command_ok(name: str) -> bool:
    return shutil.which(name) is not None


def build_status() -> Dict[str, object]:
    file_env = parse_env_file(ENV_FILE)
    os_env = dict(os.environ)

    def get(name: str, default: str = '') -> str:
        return first_nonempty(os_env.get(name, ''), file_env.get(name, ''), default)

    tavily_keys = split_csv_values(get('TAVILY_API_KEY'), get('TAVILY_API_KEYS'))
    serpapi_keys = split_csv_values(get('SERPAPI_API_KEY'), get('SERPAPI_API_KEYS'))
    brave_keys = split_csv_values(get('BRAVE_API_KEY'), get('BRAVE_API_KEYS'))
    bocha_keys = split_csv_values(get('BOCHA_API_KEY'), get('BOCHA_API_KEYS'))

    news_ready = any([tavily_keys, serpapi_keys, brave_keys, bocha_keys])
    shell_ready = all(command_ok(name) for name in ('bash', 'python3', 'curl'))

    configured_news = []
    if tavily_keys:
        configured_news.append(f'tavily({len(tavily_keys)})')
    if serpapi_keys:
        configured_news.append(f'serpapi({len(serpapi_keys)})')
    if brave_keys:
        configured_news.append(f'brave({len(brave_keys)})')
    if bocha_keys:
        configured_news.append(f'bocha({len(bocha_keys)})')

    missing_required = []
    if not news_ready:
        missing_required.append('至少一个新闻搜索 Key（TAVILY_API_KEY/TAVILY_API_KEYS、SERPAPI_API_KEY/SERPAPI_API_KEYS、BRAVE_API_KEY/BRAVE_API_KEYS、BOCHA_API_KEY/BOCHA_API_KEYS）')

    missing_optional = []
    if not get('OPENAI_API_KEY'):
        missing_optional.append('OPENAI_API_KEY（仅在你想启用 skill 内部 LLM 回退时需要）')
    if not get('TUSHARE_TOKEN'):
        missing_optional.append('TUSHARE_TOKEN（A 股扩展数据，可选）')

    capabilities = {
        'quotes_market': shell_ready,
        'news_search': news_ready,
        'single_stock': shell_ready,
        'market_review': shell_ready,
        'strategy_judgment': shell_ready,
        'batch_review': shell_ready,
        'host_model_analysis': shell_ready,
        'internal_llm_fallback': bool(get('OPENAI_API_KEY')),
    }

    ready_level = 'unavailable'
    if shell_ready and news_ready:
        ready_level = 'ready'
    elif shell_ready:
        ready_level = 'partial'

    return {
        'env_file_exists': ENV_FILE.exists(),
        'env_file': str(ENV_FILE),
        'env_example': str(ENV_EXAMPLE),
        'shell_ready': shell_ready,
        'news_ready': news_ready,
        'ready_level': ready_level,
        'commands': {
            'bash': command_ok('bash'),
            'python3': command_ok('python3'),
            'curl': command_ok('curl'),
        },
        'providers': {
            'quote': get('QUOTE_PROVIDER', 'multi'),
            'market': get('MARKET_PROVIDER', 'yfinance'),
            'news_priority': get('NEWS_PROVIDER_PRIORITY', 'tavily,serpapi,brave,bocha'),
        },
        'defaults': {
            'market': get('DEFAULT_MARKET', 'cn'),
            'strategies': get('DEFAULT_STRATEGIES', 'ma_golden_cross,shrink_pullback,bull_trend,box_oscillation'),
            'news_max_age_days': get('NEWS_MAX_AGE_DAYS', '3'),
            'request_timeout': get('REQUEST_TIMEOUT', '20'),
        },
        'configured': {
            'news_providers': configured_news,
            'tavily_key_count': len(tavily_keys),
            'serpapi_key_count': len(serpapi_keys),
            'brave_key_count': len(brave_keys),
            'bocha_key_count': len(bocha_keys),
            'openai_api_key': bool(get('OPENAI_API_KEY')),
            'openai_base_url': get('OPENAI_BASE_URL'),
            'openai_model': get('OPENAI_MODEL', 'gpt-4o-mini'),
            'tushare_token': bool(get('TUSHARE_TOKEN')),
        },
        'missing_required': missing_required,
        'missing_optional': missing_optional,
        'capabilities': capabilities,
    }


if __name__ == '__main__':
    print(json.dumps(build_status(), ensure_ascii=False, indent=2))
