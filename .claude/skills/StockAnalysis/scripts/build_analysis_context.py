#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


EXPECTED_KEYS = ('symbols', 'market', 'provider', 'fetched_at')


def load_json(path_str: str):
    with Path(path_str).open('r', encoding='utf-8') as f:
        return json.load(f)


def classify_payload(payload: Dict[str, Any]) -> str:
    if 'major_indexes' in payload and 'market_summary' in payload:
        return 'market'
    if 'symbols' in payload:
        symbols = payload.get('symbols') or []
        if symbols and isinstance(symbols[0], dict):
            first = symbols[0]
            if 'items' in first:
                return 'news'
            if 'latest_price' in first or 'recent_bars' in first:
                return 'quotes'
    return 'unknown'


def summarize_payload(payload_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload_type == 'quotes':
        return {
            'type': 'quotes',
            'count': len(payload.get('symbols') or []),
            'provider': payload.get('provider'),
            'fetched_at': payload.get('fetched_at'),
        }
    if payload_type == 'news':
        symbols = payload.get('symbols') or []
        return {
            'type': 'news',
            'count': len(symbols),
            'articles': sum(len((item or {}).get('items') or []) for item in symbols),
            'provider': payload.get('provider'),
            'fetched_at': payload.get('fetched_at'),
        }
    if payload_type == 'market':
        return {
            'type': 'market',
            'market': payload.get('market'),
            'indexes': len(payload.get('major_indexes') or []),
            'provider': payload.get('provider'),
            'fetched_at': payload.get('fetched_at'),
        }
    return {'type': 'unknown'}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['stock', 'market', 'strategy'], required=True)
    parser.add_argument('--input', required=True)
    parser.add_argument('--symbol')
    parser.add_argument('--market')
    parser.add_argument('--requested-market')
    parser.add_argument('--market-source', choices=['explicit', 'auto'], default='auto')
    parser.add_argument('--strategy')
    args = parser.parse_args()

    normalized = load_json(args.input)
    inputs: List[Dict[str, Any]] = normalized.get('inputs') or []
    payloads = {'quotes': None, 'news': None, 'market': None}
    summaries = []

    for item in inputs:
        if not isinstance(item, dict):
            continue
        payload_type = classify_payload(item)
        if payload_type in payloads and payloads[payload_type] is None:
            payloads[payload_type] = item
        summaries.append(summarize_payload(payload_type, item))

    context = {
        'mode': args.mode,
        'symbol': args.symbol,
        'market': args.market,
        'requested_symbol': args.symbol,
        'requested_market': args.requested_market or args.market,
        'market_source': args.market_source,
        'fallback_allowed': False,
        'strategy': args.strategy,
        'normalized_payload': normalized,
        'payloads': payloads,
        'input_summaries': summaries,
        'instructions': [
            'Use fetched data only.',
            'Separate facts from inference.',
            'Downgrade confidence when quote or news data is incomplete.',
        ],
    }
    print(json.dumps(context, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
