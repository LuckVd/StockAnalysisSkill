#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import run_local_analysis as analysis
import llm_analyzer as skill_llm


def load_json(path_str: str):
    with Path(path_str).open('r', encoding='utf-8') as f:
        return json.load(f)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in {'', 'N/A', '暂无', 'unknown', 'UNKNOWN'}
    return False


def _fmt_scalar(value: Any) -> str:
    if value is None:
        return 'N/A'
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    return text or 'N/A'


def _emit_status_block(status: Dict[str, Any], verified: Dict[str, Any], body: str) -> str:
    summary_lines = [
        '执行优先级: 若存在 STOCKANALYSIS_FINAL_ANSWER 区块，优先直接复述该区块内容。',
        '【主链路结论】若 DATA_STATUS=OK，则说明本次主链路抓数成功，请直接输出最终分析。',
        f'主链路判定: DATA_STATUS={_fmt_scalar(status.get("DATA_STATUS", "N/A"))} | QUOTE_STATUS={_fmt_scalar(status.get("QUOTE_STATUS", "N/A"))} | NEWS_STATUS={_fmt_scalar(status.get("NEWS_STATUS", "N/A"))} | MARKET_STATUS={_fmt_scalar(status.get("MARKET_STATUS", "N/A"))}',
        '执行限制: 只要 QUOTE_STATUS=OK，就说明已拿到有效行情，禁止再切换到港股、美股 ADR、备用代码或其他市场重试。',
        '执行限制: 主链路成功后，禁止再次抓取行情、新闻、市场数据，禁止运行 import 检查，禁止切换到 curl、akshare、tushare、web search 等备用方案。',
        '执行限制: NEWS_STATUS=PARTIAL 只表示新闻不完整，不代表行情失败，仍须基于当前已验证数据直接给出分析结论。',
    ]
    status_lines = ['=== STOCKANALYSIS_STATUS ===', 'HOST_ACTION=ANALYZE_NOW_IF_DATA_OK', 'HOST_RULE=ONLY_TRUST_STATUS_BLOCK', 'HOST_RULE=IGNORE_UI_TIMEOUT_HINTS']
    for key, value in status.items():
        status_lines.append(f"{key}={_fmt_scalar(value)}")
    status_lines.append('=== STOCKANALYSIS_STATUS_END ===')

    verified_lines = ['=== VERIFIED_DATA ===']
    for key, value in verified.items():
        verified_lines.append(f"{key}={_fmt_scalar(value)}")
    verified_lines.append('=== VERIFIED_DATA_END ===')

    return "\n".join(status_lines + [''] + verified_lines + ['', body])


def _extract_news_stats(news_payload: Dict[str, Any] | None) -> Tuple[str, int, str]:
    if not news_payload:
        return 'FAILED', 0, 'N/A'
    items = 0
    provider = news_payload.get('provider') or 'N/A'

    # Support both full news payloads {"symbols":[...]} and per-symbol payloads
    # returned by analysis.find_symbol_news().
    if isinstance(news_payload.get('items'), list):
        items = len(news_payload.get('items') or [])
    else:
        symbols = news_payload.get('symbols') or []
        for entry in symbols:
            if isinstance(entry, dict):
                items += len(entry.get('items') or [])
    if items > 0:
        return 'OK', items, provider
    return 'PARTIAL', 0, provider


def _extract_market_status(payload: Dict[str, Any] | None) -> Tuple[str, str]:
    if not payload:
        return 'FAILED', 'N/A'
    indexes = payload.get('major_indexes') or []
    summary = payload.get('market_summary') or 'N/A'
    if indexes or not _is_missing(summary):
        return 'OK', summary
    return 'PARTIAL', summary


def _extract_quote_status(quote: Dict[str, Any] | None) -> str:
    if not quote:
        return 'FAILED'
    latest_price = quote.get('latest_price')
    if _is_missing(latest_price):
        return 'FAILED'
    return 'OK'


def build_stock_prompt(context: Dict[str, Any]) -> str:
    quote = analysis.find_symbol_quote(context) or {}
    news_payload = analysis.find_symbol_news(context)
    market_payload = analysis.get_payload(context, 'market')
    market_regime, market_risk, market_note = analysis.infer_market_regime(market_payload)
    profile = analysis.compute_signal_profile(quote, news_payload) if quote else {}
    support, resistance, invalidation, target, trade_setup = analysis.support_resistance(quote, profile) if quote else (
        '暂无', '暂无', '暂无', '暂无', {'ideal_entry': '暂无', 'secondary_entry': '暂无', 'stop_loss': '暂无', 'take_profit': '暂无', 'zone_note': '暂无'}
    )
    system_prompt, user_prompt = skill_llm.build_stock_prompts(
        symbol=context.get('symbol') or 'UNKNOWN',
        stock_name=quote.get('name') or (context.get('symbol') or 'UNKNOWN'),
        market=context.get('market') or quote.get('market') or 'unknown',
        quote=quote,
        profile=profile,
        market_regime_cn=analysis.REGIME_CN.get(market_regime, market_regime),
        market_risk_cn=analysis.RISK_CN.get(market_risk, market_risk),
        market_note=market_note,
        support=support,
        resistance=resistance,
        invalidation=invalidation,
        target=target,
        trade_setup=trade_setup,
        recent_bars=quote.get('recent_bars') or [],
        news_payload=news_payload,
    )
    quote_status = _extract_quote_status(quote)
    news_status, news_count, news_provider = _extract_news_stats(news_payload)
    market_status, market_summary = _extract_market_status(market_payload)
    data_status = 'OK' if quote_status == 'OK' else 'FAILED'
    status = {
        'MODE': 'stock',
        'REQUESTED_SYMBOL': context.get('requested_symbol') or context.get('symbol') or 'UNKNOWN',
        'REQUESTED_MARKET': context.get('requested_market') or context.get('market') or quote.get('market') or 'unknown',
        'MARKET_SOURCE': context.get('market_source') or 'auto',
        'FALLBACK_ALLOWED': 'false' if quote_status == 'OK' else 'conditional',
        'SYMBOL': context.get('symbol') or 'UNKNOWN',
        'MARKET': context.get('market') or quote.get('market') or 'unknown',
        'QUOTE_STATUS': quote_status,
        'NEWS_STATUS': news_status,
        'MARKET_STATUS': market_status,
        'DATA_STATUS': data_status,
        'ANALYSIS_READY': data_status == 'OK',
    }
    verified = {
        'SYMBOL': context.get('symbol') or 'UNKNOWN',
        'NAME': quote.get('name') or 'N/A',
        'LATEST_PRICE': quote.get('latest_price'),
        'CHANGE_PCT': quote.get('change_pct'),
        'MA5': quote.get('ma5'),
        'MA10': quote.get('ma10'),
        'MA20': quote.get('ma20'),
        'SUPPORT': support,
        'RESISTANCE': resistance,
        'NEWS_PROVIDER': news_provider,
        'NEWS_COUNT': news_count,
        'MARKET_SUMMARY': market_summary,
    }
    local_answer = analysis.render_stock(context)
    body = "# 本地最终答案（优先直接复述）\n=== STOCKANALYSIS_FINAL_ANSWER ===\n" + local_answer + "\n=== STOCKANALYSIS_FINAL_ANSWER_END ===\n\n# 最终任务\n如果上方存在 `=== STOCKANALYSIS_FINAL_ANSWER ===`，优先直接复述该答案，不要改写成“行情失败”，不要再次抓数，不要切换市场。\n请按原样或做极少量润色输出最终中文分析结果。\n如果 NEWS_STATUS=PARTIAL，只需说明新闻不完整，并继续基于当前行情和市场数据完成分析。\n\n" + f"# 系统提示词\n{system_prompt}\n\n# 用户提示词\n{user_prompt}"
    return _emit_status_block(status, verified, body)


def build_strategy_prompt(context: Dict[str, Any]) -> str:
    quote = analysis.find_symbol_quote(context) or {}
    news_payload = analysis.find_symbol_news(context)
    market_payload = analysis.get_payload(context, 'market')
    market_regime, market_risk, market_note = analysis.infer_market_regime(market_payload)
    profile = analysis.compute_signal_profile(quote, news_payload) if quote else {}
    _, _, _, _, trade_setup = analysis.support_resistance(quote, profile) if quote else (
        '暂无', '暂无', '暂无', '暂无', {'ideal_entry': '暂无', 'secondary_entry': '暂无', 'stop_loss': '暂无', 'take_profit': '暂无', 'zone_note': '暂无'}
    )
    system_prompt, user_prompt = skill_llm.build_strategy_prompts(
        symbol=context.get('symbol') or 'UNKNOWN',
        stock_name=quote.get('name') or (context.get('symbol') or 'UNKNOWN'),
        strategy=context.get('strategy') or 'unknown',
        quote=quote,
        profile=profile,
        market_regime_cn=analysis.REGIME_CN.get(market_regime, market_regime),
        market_risk_cn=analysis.RISK_CN.get(market_risk, market_risk),
        market_note=market_note,
        trade_setup=trade_setup,
        news_payload=news_payload,
    )
    quote_status = _extract_quote_status(quote)
    news_status, news_count, news_provider = _extract_news_stats(news_payload)
    market_status, market_summary = _extract_market_status(market_payload)
    data_status = 'OK' if quote_status == 'OK' else 'FAILED'
    status = {
        'MODE': 'strategy',
        'SYMBOL': context.get('symbol') or 'UNKNOWN',
        'STRATEGY': context.get('strategy') or 'unknown',
        'MARKET': context.get('market') or quote.get('market') or 'unknown',
        'QUOTE_STATUS': quote_status,
        'NEWS_STATUS': news_status,
        'MARKET_STATUS': market_status,
        'DATA_STATUS': data_status,
        'ANALYSIS_READY': data_status == 'OK',
    }
    verified = {
        'SYMBOL': context.get('symbol') or 'UNKNOWN',
        'NAME': quote.get('name') or 'N/A',
        'LATEST_PRICE': quote.get('latest_price'),
        'MA5': quote.get('ma5'),
        'MA10': quote.get('ma10'),
        'MA20': quote.get('ma20'),
        'NEWS_PROVIDER': news_provider,
        'NEWS_COUNT': news_count,
        'MARKET_SUMMARY': market_summary,
    }
    body = "# 最终任务\n请现在直接输出最终中文策略判断，不要重复排查，不要再次抓数。\n请按以下结构输出：策略名称、判定结果、支持证据、不满足项、风险提示、执行建议。\n\n" + f"# 系统提示词\n{system_prompt}\n\n# 用户提示词\n{user_prompt}"
    return _emit_status_block(status, verified, body)


def build_market_prompt(context: Dict[str, Any]) -> str:
    payload = analysis.get_payload(context, 'market') or {}
    indexes = payload.get('major_indexes') or []
    index_lines = '\n'.join(
        f"- {idx.get('name') or idx.get('symbol')}: {skill_llm.fmt_num(idx.get('latest_price'))} ({skill_llm.fmt_num(idx.get('change_pct'))}%)"
        for idx in indexes[:5]
    )
    system_prompt, user_prompt = skill_llm.build_market_prompts(
        market=context.get('market') or payload.get('market') or 'unknown',
        market_summary=payload.get('market_summary') or '暂无',
        index_lines=index_lines,
    )
    market_status, market_summary = _extract_market_status(payload)
    status = {
        'MODE': 'market',
        'MARKET': context.get('market') or payload.get('market') or 'unknown',
        'MARKET_STATUS': market_status,
        'DATA_STATUS': 'OK' if market_status == 'OK' else 'FAILED',
        'ANALYSIS_READY': market_status == 'OK',
    }
    verified = {
        'MARKET': context.get('market') or payload.get('market') or 'unknown',
        'INDEX_COUNT': len(indexes),
        'MARKET_SUMMARY': market_summary,
        'MARKET_PROVIDER': payload.get('provider') or 'N/A',
    }
    body = "# 最终任务\n请现在直接输出最终中文市场复盘，不要重复排查，不要再次抓数。\n请按以下结构输出：市场状态、主要证据、风险等级、应对建议。\n\n" + f"# 系统提示词\n{system_prompt}\n\n# 用户提示词\n{user_prompt}"
    return _emit_status_block(status, verified, body)


def build_list_prompt(normalized: Dict[str, Any], market: str, symbols: List[str]) -> str:
    quotes = None
    news = None
    market_payload = None
    for item in normalized.get('inputs') or []:
        if not isinstance(item, dict):
            continue
        if 'symbols' in item and item.get('symbols') and 'latest_price' in item['symbols'][0]:
            quotes = item
        elif 'symbols' in item and item.get('symbols') and 'items' in item['symbols'][0]:
            news = item
        elif 'major_indexes' in item:
            market_payload = item
    lines = [
        '# 执行规则',
        '如果上方 DATA_STATUS=OK，请直接基于当前数据给出最终分析，不要再次抓数或联网搜索。',
        '先给总排序和总判断，再分别写每只股票的结论、利好催化、风险警报和操作建议。',
        '',
        '你是一位中文股票分析师。请基于以下多标的数据，先给出排名，再分别给出每只股票的结论、利好催化、风险警报和操作建议。',
        '要求：',
        '1. 结合技术面、市场环境和多维新闻情报。',
        '2. 明确区分事实与推断。',
        '3. 输出中文，不要编造未提供的数据。',
        '',
        f'市场：{market}',
        f'分析标的：{", ".join(symbols)}',
        '',
        '## 市场快照',
        json.dumps(market_payload or {}, ensure_ascii=False, indent=2),
        '',
        '## 行情数据',
        json.dumps(quotes or {}, ensure_ascii=False, indent=2),
        '',
        '## 新闻情报',
        json.dumps(news or {}, ensure_ascii=False, indent=2),
    ]
    quote_count = len((quotes or {}).get('symbols') or [])
    news_status, news_count, news_provider = _extract_news_stats(news)
    market_status, market_summary = _extract_market_status(market_payload)
    quote_status = 'OK' if quote_count > 0 else 'FAILED'
    data_status = 'OK' if quote_status == 'OK' else 'FAILED'
    status = {
        'MODE': 'list',
        'MARKET': market,
        'QUOTE_STATUS': quote_status,
        'NEWS_STATUS': news_status,
        'MARKET_STATUS': market_status,
        'DATA_STATUS': data_status,
        'ANALYSIS_READY': data_status == 'OK',
    }
    verified = {
        'MARKET': market,
        'SYMBOL_COUNT': len(symbols),
        'QUOTE_COUNT': quote_count,
        'NEWS_PROVIDER': news_provider,
        'NEWS_COUNT': news_count,
        'MARKET_SUMMARY': market_summary,
    }
    body = "# 最终任务\n请现在直接输出最终中文多股对比结论，不要重复排查，不要再次抓数或联网搜索。\n先给总排序和总判断，再分别写每只股票的结论、利好催化、风险警报和操作建议。\n\n" + '\n'.join(lines)
    return _emit_status_block(status, verified, body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['stock', 'market', 'strategy', 'list'], required=True)
    parser.add_argument('--context')
    parser.add_argument('--input')
    parser.add_argument('--market')
    parser.add_argument('--symbols', nargs='*')
    args = parser.parse_args()

    if args.mode in ('stock', 'market', 'strategy'):
        if not args.context:
            raise SystemExit('--context is required')
        context = load_json(args.context)
        if args.mode == 'stock':
            print(build_stock_prompt(context))
        elif args.mode == 'market':
            print(build_market_prompt(context))
        else:
            print(build_strategy_prompt(context))
        return 0

    if not args.input:
        raise SystemExit('--input is required for list mode')
    normalized = load_json(args.input)
    print(build_list_prompt(normalized, args.market or 'unknown', args.symbols or []))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
