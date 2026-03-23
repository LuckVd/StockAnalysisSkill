#!/usr/bin/env python3
import argparse
import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_PATH = SCRIPT_DIR / 'run_local_analysis.py'

spec = importlib.util.spec_from_file_location('stockanalysis_engine', ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
sys.modules['stockanalysis_engine'] = engine
spec.loader.exec_module(engine)


def load_json(path_str: str):
    with Path(path_str).open('r', encoding='utf-8') as f:
        return json.load(f)


def build_context(normalized, symbol: str, market: str):
    payloads = {'quotes': None, 'news': None, 'market': None}
    for item in normalized.get('inputs') or []:
        if not isinstance(item, dict):
            continue
        if payloads['market'] is None and 'major_indexes' in item:
            payloads['market'] = item
        elif payloads['quotes'] is None and 'symbols' in item and item.get('symbols') and 'latest_price' in item['symbols'][0]:
            payloads['quotes'] = item
        elif payloads['news'] is None and 'symbols' in item and item.get('symbols') and 'items' in item['symbols'][0]:
            payloads['news'] = item
    return {
        'mode': 'stock',
        'symbol': symbol,
        'market': market,
        'strategy': None,
        'normalized_payload': normalized,
        'payloads': payloads,
        'input_summaries': [],
        'instructions': [],
    }


def summarize_symbol(context):
    quote = engine.find_symbol_quote(context)
    news_payload = engine.find_symbol_news(context)
    market_payload = engine.get_payload(context, 'market')
    symbol = context['symbol']
    if not quote:
        return {
            'symbol': symbol,
            'score': -1,
            'decision': '观望',
            'trend': '未知',
            'report': f'结论：观望（{symbol}） | 置信度 低\n评分：暂无\n趋势：未知，原因是没有找到该标的的行情数据',
        }
    market_regime, market_risk, market_note = engine.infer_market_regime(market_payload)
    profile = engine.compute_signal_profile(quote, news_payload)
    score, reasons, risks = engine.calculate_score(quote, market_regime, news_payload, profile)
    decision, confidence = engine.classify_decision(profile, market_regime, score)
    report = engine.render_stock(context)
    return {
        'symbol': symbol,
        'score': score,
        'decision': engine.DECISION_CN[decision],
        'trend': engine.TREND_CN[profile['trend_status']],
        'confidence': confidence,
        'market_regime': engine.REGIME_CN[market_regime],
        'report': report,
        'latest_price': quote.get('latest_price'),
        'facts': profile.get('facts', []),
        'market_note': market_note,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--symbols', nargs='+', required=True)
    parser.add_argument('--market', required=True)
    args = parser.parse_args()

    normalized = load_json(args.input)
    results = [summarize_symbol(build_context(normalized, symbol, args.market)) for symbol in args.symbols]
    results.sort(key=lambda item: item['score'], reverse=True)

    buy_count = sum(1 for item in results if item['decision'] == '买入')
    watch_count = sum(1 for item in results if item['decision'] == '观望')
    avoid_count = sum(1 for item in results if item['decision'] == '回避')
    print(f'批量结论：共分析 {len(results)} 只股票 | 买入 {buy_count} | 观望 {watch_count} | 回避 {avoid_count}')
    print('排名摘要：')
    for idx, item in enumerate(results, start=1):
        price_text = '暂无价格' if item.get('latest_price') is None else f"现价 {item['latest_price']:.2f}"
        print(f"{idx}. {item['symbol']} | {item['decision']} | 评分 {item['score']}/100 | {item['trend']} | {price_text}")

    print('\n===== 个股详情 =====')
    for item in results:
        print(item['report'])
        print('')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
