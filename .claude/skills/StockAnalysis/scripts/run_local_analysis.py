#!/usr/bin/env python3
import argparse
import json
import math
import os
import urllib.request
import urllib.error
import llm_analyzer as skill_llm
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


TREND_CN = {
    'strong_bull': '强势看多',
    'bull': '看多',
    'weak_bull': '偏多',
    'neutral': '中性',
    'weak_bear': '偏空',
    'bear': '看空',
    'strong_bear': '强势看空',
}

REGIME_CN = {
    'risk-on': '进攻',
    'constructive': '偏进攻',
    'neutral': '均衡',
    'defensive': '防守',
    'risk-off': '防御',
    'unknown': '未知',
}

RISK_CN = {
    'low': '低',
    'medium': '中',
    'high': '高',
    'unknown': '未知',
}

DECISION_CN = {
    'strong_buy': '强势买入',
    'buy': '买入',
    'hold': '持有',
    'watch': '观望',
    'avoid': '回避',
    'sell': '卖出',
}

STRATEGY_RESULT_CN = {
    'met': '满足',
    'partially met': '部分满足',
    'not met': '不满足',
}

ACTION_BIAS_CN = {
    'actionable': '可执行',
    'watchlist': '加入观察',
    'avoid for now': '暂不参与',
}

NEWS_CATEGORY_RULES = [
    {
        'name': '业绩超预期',
        'polarity': 'positive',
        'score': 4,
        'keywords': ['beat', 'beats', 'earnings beat', 'record profit', 'profit jumps', '预增', '超预期', '业绩增长', '净利润增长', '盈利增长', '创新高'],
        'summary': '业绩或盈利表现超预期，基本面形成支撑',
    },
    {
        'name': '订单合作',
        'polarity': 'positive',
        'score': 3,
        'keywords': ['partnership', 'deal', 'contract', 'order', 'orders', 'signs', '签约', '中标', '订单', '合作', '合同'],
        'summary': '订单、合作或中标催化有助于提升后续预期',
    },
    {
        'name': '产品获批',
        'polarity': 'positive',
        'score': 3,
        'keywords': ['approval', 'approved', 'launch', 'license', '获批', '获准', '上市申请', '新产品', '新药'],
        'summary': '产品获批或新业务推进带来新增催化',
    },
    {
        'name': '分析师上调',
        'polarity': 'positive',
        'score': 2,
        'keywords': ['upgrade', 'raised target', 'target raised', 'buy rating', 'overweight', '上调评级', '上调目标价', '增持评级'],
        'summary': '机构评级或目标价上修，情绪面偏正向',
    },
    {
        'name': '回购增持',
        'polarity': 'positive',
        'score': 2,
        'keywords': ['buyback', 'repurchase', 'insider buy', '增持', '回购', '高管增持'],
        'summary': '回购或增持通常有助于稳定市场预期',
    },
    {
        'name': '业绩不及预期',
        'polarity': 'negative',
        'score': -4,
        'keywords': ['miss', 'misses', 'warning', 'guidance cut', 'profit warning', '亏损', '预亏', '不及预期', '下滑', '业绩承压'],
        'summary': '业绩或指引偏弱，可能压制估值和风险偏好',
    },
    {
        'name': '评级下调',
        'polarity': 'negative',
        'score': -2,
        'keywords': ['downgrade', 'cut target', 'underperform', 'sell rating', '下调评级', '下调目标价', '减持评级'],
        'summary': '外部评级转弱，短线情绪承压',
    },
    {
        'name': '监管诉讼',
        'polarity': 'negative',
        'score': -4,
        'keywords': ['lawsuit', 'probe', 'investigation', 'fraud', 'sec', '诉讼', '调查', '立案', '处罚', '造假', '违规'],
        'summary': '监管、诉讼或合规问题会放大尾部风险',
    },
    {
        'name': '事故召回',
        'polarity': 'negative',
        'score': -3,
        'keywords': ['recall', 'accident', 'fire', 'defect', '召回', '事故', '停产', '故障', '起火'],
        'summary': '事故、召回或停产会压制需求预期',
    },
    {
        'name': '减持与资金压力',
        'polarity': 'negative',
        'score': -3,
        'keywords': ['share sale', 'offering', 'dilution', 'insider sell', '减持', '套现', '再融资', '违约', '质押风险'],
        'summary': '减持、融资或资金压力会影响筹码与预期',
    },
]

NEWS_DIMENSION_LABELS = {
    'latest_news': '最新消息',
    'market_analysis': '机构分析',
    'risk_check': '风险排查',
    'earnings': '业绩预期',
    'industry': '行业分析',
}

def load_json(path_str: str):
    with Path(path_str).open('r', encoding='utf-8') as f:
        return json.load(f)


def get_payload(context: Dict[str, Any], payload_type: str) -> Optional[Dict[str, Any]]:
    payloads = context.get('payloads') or {}
    payload = payloads.get(payload_type)
    if payload:
        return payload
    normalized = context.get('normalized_payload') or {}
    for item in normalized.get('inputs') or []:
        if not isinstance(item, dict):
            continue
        if payload_type == 'quotes' and 'symbols' in item and item.get('symbols') and 'latest_price' in item['symbols'][0]:
            return item
        if payload_type == 'news' and 'symbols' in item and item.get('symbols') and 'items' in item['symbols'][0]:
            return item
        if payload_type == 'market' and 'major_indexes' in item:
            return item
    return None


def find_symbol_quote(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = (context.get('symbol') or '').strip().lower()
    quotes = get_payload(context, 'quotes') or {}
    for item in quotes.get('symbols') or []:
        if (item.get('symbol') or '').strip().lower() == symbol:
            return item
    return None


def find_symbol_news(context: Dict[str, Any]) -> Dict[str, Any]:
    symbol = (context.get('symbol') or '').strip().lower()
    news = get_payload(context, 'news') or {}
    for item in news.get('symbols') or []:
        if (item.get('symbol') or '').strip().lower() == symbol:
            return item
    return {'symbol': context.get('symbol'), 'items': [], 'errors': ['未找到该标的对应的新闻结果']}


def infer_market_regime(market_payload: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
    if not market_payload:
        return 'neutral', 'unknown', '未提供市场快照，市场环境按中性处理。'
    indexes = [idx for idx in (market_payload.get('major_indexes') or []) if idx.get('change_pct') is not None]
    if not indexes:
        return 'neutral', 'unknown', market_payload.get('market_summary') or '市场数据不可用。'
    avg_change = sum(idx['change_pct'] for idx in indexes) / len(indexes)
    if avg_change > 1:
        return 'risk-on', 'low', f'主要指数平均涨幅约 {avg_change:.2f}%，市场风险偏好较强。'
    if avg_change > 0.2:
        return 'constructive', 'medium', f'主要指数平均涨幅约 {avg_change:.2f}%，市场环境偏正面。'
    if avg_change < -1:
        return 'risk-off', 'high', f'主要指数平均跌幅约 {abs(avg_change):.2f}%，市场承压明显。'
    if avg_change < -0.2:
        return 'defensive', 'medium', f'主要指数平均跌幅约 {abs(avg_change):.2f}%，市场偏谨慎。'
    return 'neutral', 'medium', f'主要指数平均变动约 {avg_change:.2f}%，市场偏震荡。'


def ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * k + result[-1] * (1 - k))
    return result


def compute_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) <= period:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def classify_news_item(item: Dict[str, Any]) -> Tuple[int, str, Optional[str], str]:
    title = (item.get('title') or '').strip()
    snippet = (item.get('snippet') or '').strip()
    if not title:
        return 0, 'neutral', None, ''
    text_blob = f"{title} {snippet}".lower()
    best_rule = None
    best_hits = 0
    for rule in NEWS_CATEGORY_RULES:
        hits = sum(1 for kw in rule['keywords'] if kw.lower() in text_blob)
        if hits > best_hits:
            best_hits = hits
            best_rule = rule
    if not best_rule or best_hits <= 0:
        return 0, 'neutral', None, ''
    score = best_rule['score']
    if best_hits >= 2:
        score += 1 if score > 0 else -1
    score = max(-5, min(5, score))
    return score, best_rule['polarity'], best_rule['name'], best_rule['summary']


def summarize_news_dimension(name: str, payload: Dict[str, Any]) -> Tuple[int, List[str], List[str], List[str], List[str], List[Dict[str, Any]]]:
    items = payload.get('items') or []
    positives: List[str] = []
    negatives: List[str] = []
    positive_summaries: List[str] = []
    negative_summaries: List[str] = []
    events: List[Dict[str, Any]] = []
    score = 0

    for item in items[:4]:
        item_score, polarity, category, summary = classify_news_item(item)
        title = (item.get('title') or '').strip()
        if item_score == 0 and name == 'risk_check' and title:
            item_score = -2
            polarity = 'negative'
            category = '风险排查'
            summary = '风险排查维度检索到潜在异常事项，需要重点复核'
        elif item_score == 0 and name == 'earnings' and title:
            summary = '业绩预期维度已有更新，需结合财报与指引确认兑现度'
        elif item_score == 0 and name == 'market_analysis' and title:
            summary = '机构分析维度已有研报或评级信息，可作为情绪和预期参考'
        elif item_score == 0 and name == 'industry' and title:
            summary = '行业维度有新信息，可辅助判断景气度与竞争格局'
        elif item_score == 0 and name == 'latest_news' and title:
            summary = '最新消息维度已有近期动态，建议与技术面交叉验证'

        score += item_score
        if summary:
            event = {
                'dimension': name,
                'title': title,
                'polarity': polarity,
                'category': category,
                'summary': summary,
                'score': item_score,
            }
            events.append(event)
            if polarity == 'positive':
                positives.append(title)
                positive_summaries.append(summary)
            elif polarity == 'negative':
                negatives.append(title)
                negative_summaries.append(summary)

    return score, positives, negatives, positive_summaries, negative_summaries, events


def analyze_news_signal(news_payload: Dict[str, Any]) -> Dict[str, Any]:
    dimensions = news_payload.get('dimensions') or {}
    items = news_payload.get('items') or []
    score = 0
    positive_titles: List[str] = []
    negative_titles: List[str] = []
    positive_summaries: List[str] = []
    negative_summaries: List[str] = []
    all_events: List[Dict[str, Any]] = []
    dimension_notes: List[str] = []
    dimension_counts: Dict[str, int] = {}

    if dimensions:
        for name in ['latest_news', 'market_analysis', 'risk_check', 'earnings', 'industry']:
            payload = dimensions.get(name)
            if not payload:
                continue
            dim_items = payload.get('items') or []
            dimension_counts[name] = len(dim_items)
            dim_score, pos_titles, neg_titles, pos_summaries, neg_summaries, events = summarize_news_dimension(name, payload)
            score += dim_score
            positive_titles.extend(pos_titles)
            negative_titles.extend(neg_titles)
            positive_summaries.extend(pos_summaries)
            negative_summaries.extend(neg_summaries)
            all_events.extend(events)
            if dim_items:
                label = NEWS_DIMENSION_LABELS.get(name, name)
                if name == 'risk_check':
                    dimension_notes.append(f'{label}命中 {len(dim_items)} 条，需要重点核实潜在利空')
                elif name == 'earnings':
                    dimension_notes.append(f'{label}命中 {len(dim_items)} 条，可辅助判断财报兑现度')
                elif name == 'market_analysis':
                    dimension_notes.append(f'{label}命中 {len(dim_items)} 条，可观察机构预期变化')
                else:
                    dimension_notes.append(f'{label}命中 {len(dim_items)} 条，说明近期信息流较活跃')
    else:
        fallback_payload = {'items': items}
        dim_score, pos_titles, neg_titles, pos_summaries, neg_summaries, events = summarize_news_dimension('latest_news', fallback_payload)
        score += dim_score
        positive_titles.extend(pos_titles)
        negative_titles.extend(neg_titles)
        positive_summaries.extend(pos_summaries)
        negative_summaries.extend(neg_summaries)
        all_events.extend(events)
        if items:
            dimension_notes.append(f'最新消息命中 {len(items[:4])} 条，可作为情绪面参考')

    if news_payload.get('errors') and not items and not dimensions:
        score -= 3

    def dedupe(seq: List[str]) -> List[str]:
        return list(dict.fromkeys([x for x in seq if x]))

    return {
        'score': max(-12, min(12, score)),
        'positive_titles': dedupe(positive_titles)[:3],
        'negative_titles': dedupe(negative_titles)[:3],
        'positive_summaries': dedupe(positive_summaries)[:3],
        'negative_summaries': dedupe(negative_summaries)[:3],
        'dimension_notes': dedupe(dimension_notes)[:4],
        'dimension_counts': dimension_counts,
        'events': all_events[:8],
    }


def compute_signal_profile(quote: Dict[str, Any], news_payload: Dict[str, Any]) -> Dict[str, Any]:
    latest = quote.get('latest_price')
    ma5 = quote.get('ma5')
    ma10 = quote.get('ma10')
    ma20 = quote.get('ma20')
    change_pct = quote.get('change_pct')
    recent_bars = quote.get('recent_bars') or []
    closes = [b.get('close') for b in recent_bars if b.get('close') is not None]
    highs = [b.get('high') for b in recent_bars if b.get('high') is not None]
    lows = [b.get('low') for b in recent_bars if b.get('low') is not None]
    volumes = [b.get('volume') for b in recent_bars if b.get('volume') is not None]

    facts: List[str] = []
    if latest is not None:
        facts.append(f'最新价 {latest:.2f}')
    if change_pct is not None:
        facts.append(f'日涨跌幅 {change_pct:.2f}%')
    if None not in (ma5, ma10, ma20):
        facts.append(f'MA5/M10/M20 = {ma5:.2f}/{ma10:.2f}/{ma20:.2f}')

    trend_status = 'neutral'
    trend_strength = 50
    ma_alignment = '均线缠绕，趋势不明'
    if None not in (ma5, ma10, ma20):
        curr_spread = (ma5 - ma20) / ma20 * 100 if ma20 else 0.0
        prev_spread = 0.0
        if len(closes) >= 5 and ma20:
            prev_close = closes[-5]
            prev_spread = curr_spread if prev_close == 0 else curr_spread
        if ma5 > ma10 > ma20:
            if curr_spread > 5:
                trend_status = 'strong_bull'
                trend_strength = 90
                ma_alignment = '强势多头排列，均线发散上行'
            else:
                trend_status = 'bull'
                trend_strength = 75
                ma_alignment = '多头排列 MA5>MA10>MA20'
        elif ma5 > ma10 and ma10 <= ma20:
            trend_status = 'weak_bull'
            trend_strength = 55
            ma_alignment = '弱势多头，MA5>MA10 但 MA10<=MA20'
        elif ma5 < ma10 < ma20:
            bear_spread = (ma20 - ma5) / ma5 * 100 if ma5 else 0.0
            if bear_spread > 5:
                trend_status = 'strong_bear'
                trend_strength = 10
                ma_alignment = '强势空头排列，均线发散下行'
            else:
                trend_status = 'bear'
                trend_strength = 25
                ma_alignment = '空头排列 MA5<MA10<MA20'
        elif ma5 < ma10 and ma10 >= ma20:
            trend_status = 'weak_bear'
            trend_strength = 40
            ma_alignment = '弱势空头，MA5<MA10 但 MA10>=MA20'

    bias_ma5 = ((latest - ma5) / ma5 * 100) if latest not in (None,) and ma5 not in (None, 0) else None
    bias_ma10 = ((latest - ma10) / ma10 * 100) if latest not in (None,) and ma10 not in (None, 0) else None
    bias_ma20 = ((latest - ma20) / ma20 * 100) if latest not in (None,) and ma20 not in (None, 0) else None

    volume_ratio = None
    volume_status = 'normal'
    volume_trend = '量能正常'
    if len(volumes) >= 6 and closes:
        avg_vol = sum(volumes[-6:-1]) / 5 if len(volumes[-6:-1]) == 5 else None
        if avg_vol:
            volume_ratio = volumes[-1] / avg_vol
            price_change = ((closes[-1] - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 and closes[-2] else 0.0
            if volume_ratio >= 1.5:
                if price_change > 0:
                    volume_status = 'heavy_up'
                    volume_trend = '放量上涨，多头力量较强'
                else:
                    volume_status = 'heavy_down'
                    volume_trend = '放量下跌，需警惕资金出逃'
            elif volume_ratio <= 0.7:
                if price_change > 0:
                    volume_status = 'shrink_up'
                    volume_trend = '缩量上涨，上攻动能一般'
                else:
                    volume_status = 'shrink_down'
                    volume_trend = '缩量回调，偏洗盘特征'

    support_ma5 = False
    support_ma10 = False
    if latest is not None and ma5 not in (None, 0):
        dist = abs(latest - ma5) / ma5
        if dist <= 0.015 and latest >= ma5:
            support_ma5 = True
    if latest is not None and ma10 not in (None, 0):
        dist = abs(latest - ma10) / ma10
        if dist <= 0.02 and latest >= ma10:
            support_ma10 = True

    macd_status = 'neutral'
    macd_signal = 'MACD 中性'
    if len(closes) >= 26:
        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        dif = [a - b for a, b in zip(ema12, ema26)]
        dea = ema(dif, 9)
        hist = [d - e for d, e in zip(dif, dea)]
        if len(dif) >= 2 and len(dea) >= 2:
            prev_dif, curr_dif = dif[-2], dif[-1]
            prev_dea, curr_dea = dea[-2], dea[-1]
            if curr_dif > curr_dea and prev_dif <= prev_dea and curr_dif > 0:
                macd_status = 'golden_cross_zero'
                macd_signal = '零轴上金叉，多头信号最强'
            elif curr_dif > curr_dea and prev_dif <= prev_dea:
                macd_status = 'golden_cross'
                macd_signal = 'MACD 金叉，趋势有修复迹象'
            elif curr_dif > 0 and prev_dif <= 0:
                macd_status = 'crossing_up'
                macd_signal = 'DIF 上穿零轴，趋势正在转强'
            elif curr_dif < curr_dea and prev_dif >= prev_dea:
                macd_status = 'death_cross'
                macd_signal = 'MACD 死叉，趋势走弱'
            elif curr_dif < 0 and prev_dif >= 0:
                macd_status = 'crossing_down'
                macd_signal = 'DIF 下穿零轴，空头压力增强'
            elif curr_dif > curr_dea:
                macd_status = 'bullish'
                macd_signal = 'MACD 多头结构仍在'
            elif curr_dif < curr_dea:
                macd_status = 'bearish'
                macd_signal = 'MACD 空头结构占优'

    rsi_value = compute_rsi(closes, 14) if len(closes) >= 15 else None
    rsi_status = 'neutral'
    rsi_signal = 'RSI 中性'
    if rsi_value is not None:
        if rsi_value < 30:
            rsi_status = 'oversold'
            rsi_signal = f'RSI 超卖（{rsi_value:.1f}），存在反弹条件'
        elif rsi_value < 45:
            rsi_status = 'weak'
            rsi_signal = f'RSI 偏弱（{rsi_value:.1f}），动能不足'
        elif rsi_value <= 70:
            rsi_status = 'strong_buy'
            rsi_signal = f'RSI 偏强（{rsi_value:.1f}），多头动能尚可'
        else:
            rsi_status = 'overbought'
            rsi_signal = f'RSI 超买（{rsi_value:.1f}），短线回撤风险上升'

    news_signal = analyze_news_signal(news_payload)
    return {
        'facts': facts,
        'trend_status': trend_status,
        'trend_strength': trend_strength,
        'ma_alignment': ma_alignment,
        'bias_ma5': bias_ma5,
        'bias_ma10': bias_ma10,
        'bias_ma20': bias_ma20,
        'volume_ratio': volume_ratio,
        'volume_status': volume_status,
        'volume_trend': volume_trend,
        'support_ma5': support_ma5,
        'support_ma10': support_ma10,
        'macd_status': macd_status,
        'macd_signal': macd_signal,
        'rsi_status': rsi_status,
        'rsi_signal': rsi_signal,
        'rsi_value': rsi_value,
        'news_score': news_signal['score'],
        'positive_news': news_signal['positive_titles'],
        'negative_news': news_signal['negative_titles'],
        'positive_news_summaries': news_signal['positive_summaries'],
        'negative_news_summaries': news_signal['negative_summaries'],
        'news_dimension_notes': news_signal['dimension_notes'],
        'news_dimension_counts': news_signal['dimension_counts'],
        'news_events': news_signal['events'],
    }


def calculate_score(quote: Dict[str, Any], market_regime: str, news_payload: Dict[str, Any], profile: Dict[str, Any]) -> Tuple[int, List[str], List[str]]:
    score = 0
    reasons: List[str] = []
    risks: List[str] = []

    trend_scores = {
        'strong_bull': 30,
        'bull': 26,
        'weak_bull': 18,
        'neutral': 12,
        'weak_bear': 8,
        'bear': 4,
        'strong_bear': 0,
    }
    score += trend_scores.get(profile['trend_status'], 12)
    if profile['trend_status'] in ('strong_bull', 'bull'):
        reasons.append(f"{profile['ma_alignment']}，顺势方向清晰")
    elif profile['trend_status'] in ('bear', 'strong_bear'):
        risks.append(f"{profile['ma_alignment']}，逆势做多胜率偏低")

    bias = profile['bias_ma5'] if profile['bias_ma5'] is not None else 0.0
    base_threshold = float(os.getenv('BIAS_THRESHOLD', '5'))
    is_strong_trend = profile['trend_status'] == 'strong_bull' and profile['trend_strength'] >= 70
    effective_threshold = base_threshold * 1.5 if is_strong_trend else base_threshold
    if bias < 0:
        if bias > -3:
            score += 20
            reasons.append(f'价格略低于 MA5（{bias:.1f}%），更像回踩买点')
        elif bias > -5:
            score += 16
            reasons.append(f'价格回踩 MA5（{bias:.1f}%），可继续观察支撑')
        else:
            score += 8
            risks.append(f'乖离率过大（{bias:.1f}%），可能已经演变成走弱')
    elif bias < 2:
        score += 18
        reasons.append(f'价格贴近 MA5（{bias:.1f}%），位置不算差')
    elif bias < base_threshold:
        score += 14
        reasons.append(f'价格略高于 MA5（{bias:.1f}%），允许小仓跟踪')
    elif bias > effective_threshold:
        score += 4
        risks.append(f'乖离率过高（{bias:.1f}% > {effective_threshold:.1f}%），不适合追高')
    elif bias > base_threshold and is_strong_trend:
        score += 10
        reasons.append(f'强势趋势中乖离偏高（{bias:.1f}%），只能轻仓追踪')
    else:
        score += 4
        risks.append(f'乖离率偏高（{bias:.1f}%），盈亏比一般')

    volume_scores = {
        'shrink_down': 15,
        'heavy_up': 12,
        'normal': 10,
        'shrink_up': 6,
        'heavy_down': 0,
    }
    score += volume_scores.get(profile['volume_status'], 8)
    if profile['volume_status'] == 'shrink_down':
        reasons.append('缩量回调，偏洗盘而非恐慌砸盘')
    elif profile['volume_status'] == 'heavy_up':
        reasons.append('放量上涨，说明多头参与度较高')
    elif profile['volume_status'] == 'heavy_down':
        risks.append('放量下跌，短线抛压明显')

    if profile['support_ma5']:
        score += 5
        reasons.append('MA5 附近支撑有效')
    if profile['support_ma10']:
        score += 5
        reasons.append('MA10 附近支撑有效')

    macd_scores = {
        'golden_cross_zero': 15,
        'golden_cross': 12,
        'crossing_up': 10,
        'bullish': 8,
        'bearish': 2,
        'crossing_down': 0,
        'death_cross': 0,
        'neutral': 5,
    }
    score += macd_scores.get(profile['macd_status'], 5)
    if profile['macd_status'] in ('golden_cross_zero', 'golden_cross', 'crossing_up'):
        reasons.append(profile['macd_signal'])
    elif profile['macd_status'] in ('death_cross', 'crossing_down', 'bearish'):
        risks.append(profile['macd_signal'])
    else:
        reasons.append(profile['macd_signal'])

    rsi_scores = {
        'oversold': 10,
        'strong_buy': 8,
        'neutral': 5,
        'weak': 3,
        'overbought': 0,
    }
    score += rsi_scores.get(profile['rsi_status'], 5)
    if profile['rsi_status'] in ('oversold', 'strong_buy'):
        reasons.append(profile['rsi_signal'])
    elif profile['rsi_status'] == 'overbought':
        risks.append(profile['rsi_signal'])
    else:
        reasons.append(profile['rsi_signal'])

    if market_regime == 'risk-on':
        score += 6
        reasons.append('市场处于偏进攻环境，对个股有额外加成')
    elif market_regime == 'constructive':
        score += 3
    elif market_regime == 'defensive':
        score -= 4
        risks.append('市场偏防守，强趋势股之外的标的难度更高')
    elif market_regime == 'risk-off':
        score -= 8
        risks.append('市场风险偏好较差，开仓容错率下降')

    score += profile['news_score']
    reasons.extend([f'新闻催化：{summary}' for summary in profile.get('positive_news_summaries', [])[:2]])
    reasons.extend([f'新闻覆盖：{note}' for note in profile.get('news_dimension_notes', [])[:1]])
    risks.extend([f'新闻风险：{summary}' for summary in profile.get('negative_news_summaries', [])[:2]])
    if news_payload.get('errors') and not news_payload.get('items') and not news_payload.get('dimensions'):
        risks.append('近期新闻未成功抓取，催化和风险覆盖不完整')

    return max(0, min(100, int(round(score)))), reasons[:6], risks[:6]


def classify_decision(profile: Dict[str, Any], market_regime: str, score: int) -> Tuple[str, str]:
    trend_status = profile['trend_status']
    bias = profile['bias_ma5']
    threshold = float(os.getenv('BIAS_THRESHOLD', '5'))
    if score >= 78 and trend_status in ('strong_bull', 'bull') and market_regime in ('risk-on', 'constructive') and not (bias is not None and bias > threshold):
        return 'strong_buy', 'high'
    if score >= 62 and trend_status in ('strong_bull', 'bull', 'weak_bull'):
        return 'buy', 'medium' if score < 75 else 'high'
    if score >= 45:
        return 'hold', 'medium'
    if score >= 30:
        return 'watch', 'low' if trend_status in ('bear', 'strong_bear') else 'medium'
    if trend_status in ('bear', 'strong_bear'):
        return 'sell', 'high' if score < 20 else 'medium'
    return 'avoid', 'low'


def support_resistance(quote: Dict[str, Any], profile: Dict[str, Any]) -> Tuple[str, str, str, str, Dict[str, Any]]:
    latest = quote.get('latest_price')
    ma5 = quote.get('ma5')
    ma10 = quote.get('ma10')
    ma20 = quote.get('ma20')
    recent_bars = quote.get('recent_bars') or []
    lows = [b.get('low') for b in recent_bars if b.get('low') is not None]
    highs = [b.get('high') for b in recent_bars if b.get('high') is not None]
    box_bottom = min(lows[-10:]) if len(lows) >= 5 else (min(lows) if lows else None)
    box_top = max(highs[-10:]) if len(highs) >= 5 else (max(highs) if highs else None)

    if profile['trend_status'] in ('strong_bull', 'bull', 'weak_bull'):
        support = ma5 or ma10 or (min(lows[-5:]) if lows else None)
        invalidation = ma20 or (min(lows[-3:]) if len(lows) >= 3 else support)
    else:
        support = ma10 or (min(lows[-5:]) if lows else None)
        invalidation = min(lows[-3:]) if len(lows) >= 3 else support
    resistance = max(highs[-5:]) if highs else None
    target = None
    if latest is not None and resistance is not None and support is not None:
        distance = max(resistance - support, 0)
        target = latest + distance * (1.2 if profile['trend_status'] in ('strong_bull', 'bull') else 0.8)

    trade_setup = compute_trade_setup(
        latest=latest,
        support=support,
        resistance=resistance,
        invalidation=invalidation,
        target=target,
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        box_bottom=box_bottom,
        box_top=box_top,
        profile=profile,
    )
    return fmt_level(support), fmt_level(resistance), fmt_level(invalidation), fmt_level(target), trade_setup


def fmt_level(value: Optional[float]) -> str:
    return '暂无' if value is None else f'{value:.2f}'


def compute_trade_setup(
    latest: Optional[float],
    support: Optional[float],
    resistance: Optional[float],
    invalidation: Optional[float],
    target: Optional[float],
    ma5: Optional[float],
    ma10: Optional[float],
    ma20: Optional[float],
    box_bottom: Optional[float],
    box_top: Optional[float],
    profile: Dict[str, Any],
) -> Dict[str, str]:
    ideal_entry = None
    secondary_entry = None
    stop_loss = invalidation
    take_profit = target
    zone_note = '位置一般，优先等待更好的盈亏比。'

    trend_status = profile['trend_status']
    volume_status = profile['volume_status']
    macd_status = profile['macd_status']
    latest_val = latest if latest is not None else None

    if trend_status in ('strong_bull', 'bull'):
        ideal_entry = ma5 or support
        secondary_entry = ma10 or support
        stop_loss = ma20 or invalidation
        if latest_val is not None and ma5 not in (None, 0) and abs(latest_val - ma5) / ma5 <= 0.02:
            zone_note = '当前更接近 MA5，属于偏理想的趋势低吸区。'
        elif latest_val is not None and ma10 not in (None, 0) and abs(latest_val - ma10) / ma10 <= 0.03:
            zone_note = '当前更接近 MA10，属于次优回踩区。'
        elif profile['bias_ma5'] is not None and profile['bias_ma5'] > float(os.getenv('BIAS_THRESHOLD', '5')):
            zone_note = '当前价格距离短均线偏远，属于不宜追高区。'
        elif volume_status == 'heavy_up' and resistance not in (None,) and latest_val is not None and latest_val >= resistance * 0.98:
            zone_note = '当前接近放量突破区，若有效站上压力可转为突破跟随。'
    elif trend_status == 'weak_bull':
        ideal_entry = ma10 or support
        secondary_entry = support
        stop_loss = ma20 or invalidation
        zone_note = '趋势仍偏多，但更适合靠近 MA10 再考虑低吸。'
    elif trend_status in ('neutral', 'weak_bear') and box_bottom not in (None,) and box_top not in (None,) and latest_val not in (None,):
        ideal_entry = box_bottom
        secondary_entry = support or ma10
        stop_loss = box_bottom * 0.97 if box_bottom else invalidation
        take_profit = box_top
        if box_bottom and (latest_val - box_bottom) / box_bottom <= 0.05:
            zone_note = '当前接近箱底区域，适合按箱体思路低吸。'
        elif box_top and (box_top - latest_val) / box_top <= 0.05:
            zone_note = '当前接近箱顶区域，更偏减仓/兑现而不是追买。'
        else:
            zone_note = '当前位于箱体中部，更适合等待靠近边界再动作。'
    else:
        ideal_entry = support or ma10
        secondary_entry = None
        stop_loss = invalidation or ma20
        zone_note = '当前趋势偏弱，不适合主动寻找买点。'

    if macd_status in ('golden_cross_zero', 'golden_cross') and ideal_entry is not None:
        zone_note += ' MACD 已出现偏强确认，可提高执行优先级。'
    elif macd_status in ('death_cross', 'crossing_down'):
        zone_note += ' MACD 尚未修复，执行上应更保守。'

    return {
        'ideal_entry': fmt_level(ideal_entry),
        'secondary_entry': fmt_level(secondary_entry),
        'stop_loss': fmt_level(stop_loss),
        'take_profit': fmt_level(take_profit),
        'zone_note': zone_note,
        'box_bottom': fmt_level(box_bottom),
        'box_top': fmt_level(box_top),
    }


def build_catalysts(profile: Dict[str, Any], market_regime: str) -> List[str]:
    catalysts = []
    catalysts.extend(profile.get('positive_news_summaries', [])[:2])
    catalysts.extend(profile['positive_news'][:1])
    if profile.get('news_dimension_notes'):
        catalysts.append(profile['news_dimension_notes'][0])
    if profile['trend_status'] in ('strong_bull', 'bull'):
        catalysts.append(profile['ma_alignment'])
    if profile['volume_status'] == 'heavy_up':
        catalysts.append('量能放大且价格同步走强，多头参与度提升')
    elif profile['volume_status'] == 'shrink_down':
        catalysts.append('回调时量能收缩，更像整理而不是趋势破坏')
    if market_regime in ('risk-on', 'constructive'):
        catalysts.append('市场整体环境偏正面，对趋势延续有帮助')
    return list(dict.fromkeys(catalysts))[:4]


def build_risks(profile: Dict[str, Any], market_regime: str) -> List[str]:
    risks = []
    risks.extend(profile.get('negative_news_summaries', [])[:2])
    risks.extend(profile['negative_news'][:1])
    if profile['bias_ma5'] is not None and profile['bias_ma5'] > float(os.getenv('BIAS_THRESHOLD', '5')):
        risks.append(f'价格相对 MA5 偏离 {profile["bias_ma5"]:.1f}%，追高风险较大')
    if profile['rsi_status'] == 'overbought':
        risks.append(profile['rsi_signal'])
    if profile['macd_status'] in ('death_cross', 'crossing_down'):
        risks.append('MACD 仍未出现修复，趋势反转信号不足')
    if profile.get('news_dimension_counts', {}).get('risk_check'):
        risks.append('风险排查维度已有命中结果，需核实减持、处罚或诉讼类信息')
    if market_regime in ('defensive', 'risk-off'):
        risks.append('市场风险偏好不足，个股即使有形态也容易打折兑现')
    return list(dict.fromkeys(risks))[:4]


def build_news_brief(profile: Dict[str, Any]) -> str:
    notes = profile.get('news_dimension_notes') or []
    if notes:
        return '；'.join(notes[:3])
    if profile.get('positive_news_summaries'):
        return '；'.join(profile['positive_news_summaries'][:2])
    if profile.get('negative_news_summaries'):
        return '；'.join(profile['negative_news_summaries'][:2])
    return '近期未形成可用的新闻情报摘要'


def build_action_plan(decision: str, profile: Dict[str, Any], support: str, invalidation: str) -> str:
    if decision in ('strong_buy', 'buy'):
        return f'操作计划：优先等靠近支撑位再分批介入，若后续有效跌破 {invalidation} 应严格止损；若放量突破再上，可考虑顺势跟踪。'
    if decision == 'hold':
        return f'操作计划：更适合持有观察或等待二次确认，重点看支撑 {support} 是否持续有效。'
    if decision in ('sell', 'avoid'):
        return '操作计划：当前不适合激进参与，先等趋势、量能和市场环境至少有两项同步改善。'
    return f'操作计划：暂以观察为主，若重新站稳 {support} 并出现量价共振，再考虑跟进。'


def strategy_trade_plan(strategy: str, quote: Dict[str, Any], profile: Dict[str, Any], trade_setup: Dict[str, str]) -> Tuple[str, str, str, str]:
    ma5 = quote.get('ma5')
    ma10 = quote.get('ma10')
    ma20 = quote.get('ma20')
    latest = quote.get('latest_price')
    bars = quote.get('recent_bars') or []
    lows = [b.get('low') for b in bars if b.get('low') is not None]
    highs = [b.get('high') for b in bars if b.get('high') is not None]

    entry = trade_setup['ideal_entry']
    stop = trade_setup['stop_loss']
    target = trade_setup['take_profit']
    note = trade_setup['zone_note']

    if strategy == 'ma_golden_cross':
        entry = fmt_level(ma5 or ma10)
        stop = fmt_level(ma10 or ma20)
        target_val = max(highs[-5:]) if highs else None
        if latest is not None and target_val is not None and latest >= target_val * 0.98:
            target_val = latest * 1.05
        target = fmt_level(target_val)
        note = '均线金叉更适合在交叉均线附近参与，远离均线时不追。'
    elif strategy == 'shrink_pullback':
        entry = fmt_level(ma5 or ma10)
        secondary = fmt_level(ma10)
        stop = fmt_level(ma20 or (min(lows[-3:]) if len(lows) >= 3 else None))
        target = fmt_level(max(highs[-5:]) if highs else None)
        note = '缩量回踩策略优先等 MA5 附近低吸，次优是 MA10，跌破 MA20 视为形态破坏。'
        return entry, secondary, stop, target, note
    elif strategy == 'bull_trend':
        entry = fmt_level(ma5 or ma10)
        stop = fmt_level(ma20 or (min(lows[-3:]) if len(lows) >= 3 else None))
        target_val = max(highs[-5:]) if highs else None
        if latest is not None and target_val is not None and latest >= target_val * 0.99:
            target_val = latest * 1.06
        target = fmt_level(target_val)
        note = '多头趋势策略优先做回踩不破，止损以 MA20 或结构低点为主。'
    elif strategy == 'box_oscillation':
        box_bottom = trade_setup.get('box_bottom', '暂无')
        box_top = trade_setup.get('box_top', '暂无')
        entry = box_bottom
        stop = fmt_level((min(lows[-10:]) * 0.97) if len(lows) >= 5 else None)
        target = box_top
        note = '箱体策略更强调贴近箱底低吸、接近箱顶兑现，中段位置不主动出手。'

    return entry, trade_setup['secondary_entry'], stop, target, note


def render_stock(context: Dict[str, Any]) -> str:
    quote = find_symbol_quote(context)
    news_payload = find_symbol_news(context)
    market_payload = get_payload(context, 'market')
    symbol = context.get('symbol') or 'UNKNOWN'
    if not quote:
        return '\n'.join([
            f'结论：观望（{symbol}） | 置信度 低',
            '评分：暂无',
            '趋势：未知，原因是没有找到该标的的行情数据',
            '关键价位：暂无',
            '利好催化：暂无',
            '风险警报：缺少行情输入，当前分析不可用于交易判断',
            '操作计划：先补齐行情数据后再运行分析',
        ])

    market_regime, market_risk, market_note = infer_market_regime(market_payload)
    profile = compute_signal_profile(quote, news_payload)
    score, reasons, risks_core = calculate_score(quote, market_regime, news_payload, profile)
    decision, confidence = classify_decision(profile, market_regime, score)
    support, resistance, invalidation, target, trade_setup = support_resistance(quote, profile)
    catalysts = build_catalysts(profile, market_regime)
    risks = []
    for item in risks_core + build_risks(profile, market_regime):
        if item not in risks:
            risks.append(item)
    facts = profile['facts'] + [profile['volume_trend'], profile['macd_signal']]

    trend_line = f'趋势：{TREND_CN[profile["trend_status"]]} | ' + '；'.join(facts[:5])
    news_line = '新闻情报：' + build_news_brief(profile)
    key_levels = f'关键价位：支撑 {support} | 压力 {resistance} | 失效位 {invalidation} | 参考目标 {target}'
    trade_line = (
        f"交易计划：理想买点 {trade_setup['ideal_entry']} | 次优买点 {trade_setup['secondary_entry']} | "
        f"止损位 {trade_setup['stop_loss']} | 止盈参考 {trade_setup['take_profit']}"
    )
    zone_line = f"位置判断：{trade_setup['zone_note']}"
    catalyst_line = '利好催化：' + ('；'.join(catalysts) if catalysts else '当前输入中未捕捉到高置信度利好催化')
    reason_line = '加分依据：' + ('；'.join(reasons) if reasons else '暂无明显加分项')
    risk_line = '风险警报：' + ('；'.join(risks[:5]) if risks else '当前未发现突出的新增风险项')
    action = build_action_plan(decision, profile, support, invalidation)

    lines = [
        f'结论：{DECISION_CN[decision]}（{symbol}） | 置信度 {"高" if confidence == "high" else "中" if confidence == "medium" else "低"}',
        f'评分：{score}/100',
        trend_line,
        f'市场环境：{REGIME_CN[market_regime]} | 风险等级 {RISK_CN[market_risk]} | {market_note}',
        news_line,
        catalyst_line,
        reason_line,
        key_levels,
        trade_line,
        zone_line,
        risk_line,
        action,
    ]
    return '\n'.join(lines)


def render_market(context: Dict[str, Any]) -> str:
    payload = get_payload(context, 'market')
    market = context.get('market') or (payload or {}).get('market') or 'unknown'
    regime, risk, note = infer_market_regime(payload)
    indexes = (payload or {}).get('major_indexes') or []
    evidence = []
    for idx in indexes[:3]:
        name = idx.get('name') or idx.get('symbol')
        cp = idx.get('change_pct')
        lp = idx.get('latest_price')
        if cp is not None and lp is not None:
            evidence.append(f'{name} {lp:.2f}（{cp:.2f}%）')
    if not evidence:
        evidence.append('指数实时数据不可用')
    posture = '进攻' if regime == 'risk-on' else '均衡' if regime in ('constructive', 'neutral') else '防守'
    return '\n'.join([
        f'市场结论：{REGIME_CN[regime]}（{market}）',
        '市场证据：' + '；'.join(evidence),
        f'风险等级：{RISK_CN[risk]}',
        f'建议姿态：{posture}',
        f'说明：{note}',
    ])


def evaluate_strategy(strategy: str, quote: Dict[str, Any], market_regime: str, profile: Dict[str, Any]) -> Tuple[str, List[str], List[str], str]:
    latest = quote.get('latest_price')
    ma5 = quote.get('ma5')
    ma10 = quote.get('ma10')
    ma20 = quote.get('ma20')
    recent_bars = quote.get('recent_bars') or []
    evidence: List[str] = []
    failed: List[str] = []
    action = 'watchlist'

    if strategy == 'ma_golden_cross':
        if None not in (ma5, ma10) and ma5 >= ma10:
            evidence.append('MA5 已经高于或贴近 MA10')
        else:
            failed.append('MA5 仍未站上 MA10')
        if profile['macd_status'] in ('golden_cross_zero', 'golden_cross', 'crossing_up'):
            evidence.append(profile['macd_signal'])
        else:
            failed.append('MACD 尚未给出同步转强信号')
        if latest is not None and ma5 is not None and latest >= ma5:
            evidence.append('股价仍能维持在 MA5 附近或上方')
        else:
            failed.append('股价没有站稳 MA5')
    elif strategy == 'shrink_pullback':
        if profile['trend_status'] in ('strong_bull', 'bull'):
            evidence.append('趋势主方向仍然向上')
        else:
            failed.append('趋势主方向不够强')
        if profile['volume_status'] == 'shrink_down':
            evidence.append('最近回调量能收缩，符合缩量回踩特征')
        else:
            failed.append('回踩时量能没有明显收缩')
        if None not in (latest, ma5, ma10) and (abs(latest - ma5) / ma5 <= 0.03 or abs(latest - ma10) / ma10 <= 0.03):
            evidence.append('价格靠近关键均线，位置更合理')
        else:
            failed.append('价格距离关键均线不够近')
    elif strategy == 'bull_trend':
        if profile['trend_status'] in ('strong_bull', 'bull'):
            evidence.append(profile['ma_alignment'])
        else:
            failed.append('均线未形成清晰多头结构')
        highs = [b.get('high') for b in recent_bars[-5:] if b.get('high') is not None]
        lows = [b.get('low') for b in recent_bars[-5:] if b.get('low') is not None]
        if len(highs) >= 2 and len(lows) >= 2 and highs[-1] >= highs[0] and lows[-1] >= lows[0]:
            evidence.append('近期高低点没有明显走坏')
        else:
            failed.append('近期高低点不支持延续上升趋势')
    elif strategy == 'box_oscillation':
        highs = [b.get('high') for b in recent_bars[-10:] if b.get('high') is not None]
        lows = [b.get('low') for b in recent_bars[-10:] if b.get('low') is not None]
        if highs and lows and latest not in (None, 0):
            spread = max(highs) - min(lows)
            if spread / latest < 0.12:
                evidence.append('最近区间振幅可控，存在箱体震荡特征')
                box_bottom = min(lows)
                if (latest - box_bottom) / box_bottom <= 0.05:
                    evidence.append('价格靠近箱底区域，位置相对有利')
                else:
                    failed.append('当前不在理想箱底区域')
            else:
                failed.append('区间振幅偏大，不像标准箱体')
        else:
            failed.append('区间数据不足，无法判断箱体')
    else:
        failed.append(f'暂未实现策略 {strategy} 的专用判定')

    if market_regime in ('risk-off', 'defensive'):
        failed.append('当前市场环境偏防守，不利于策略执行')

    if evidence and not failed:
        result = 'met'
        action = 'actionable'
    elif evidence:
        result = 'partially met'
    else:
        result = 'not met'
        action = 'avoid for now'
    return result, evidence[:5], failed[:5], action


def render_strategy(context: Dict[str, Any]) -> str:
    symbol = context.get('symbol') or 'UNKNOWN'
    strategy = context.get('strategy') or 'unknown'
    quote = find_symbol_quote(context)
    if not quote:
        return '\n'.join([
            f'策略名称：{strategy}',
            '判定结果：不满足',
            '支持证据：暂无，因为缺少行情数据',
            '不满足项：未找到该标的对应的行情数据',
            '风险提示：缺少价格输入时，策略判断不可靠',
            '执行建议：暂不参与',
        ])
    market_regime, _, _ = infer_market_regime(get_payload(context, 'market'))
    profile = compute_signal_profile(quote, find_symbol_news(context))
    _, _, _, _, trade_setup = support_resistance(quote, profile)
    result, evidence, failed, action = evaluate_strategy(strategy, quote, market_regime, profile)
    risks = build_risks(profile, market_regime)
    entry, secondary, stop, target, note = strategy_trade_plan(strategy, quote, profile, trade_setup)
    return '\n'.join([
        f'策略名称：{strategy}',
        f'判定结果：{STRATEGY_RESULT_CN[result]}（{symbol}）',
        '支持证据：' + ('；'.join(evidence) if evidence else '暂无'),
        '不满足项：' + ('；'.join(failed) if failed else '无'),
        f'策略买点：理想买点 {entry} | 次优买点 {secondary}',
        f'策略风控：止损位 {stop} | 目标位 {target}',
        f'位置判断：{note}',
        '风险提示：' + ('；'.join(risks[:4]) if risks else '暂无明显新增风险'),
        f'执行建议：{ACTION_BIAS_CN[action]}',
    ])


def llm_is_configured() -> bool:
    return bool(os.getenv('OPENAI_API_KEY', '').strip() and os.getenv('OPENAI_MODEL', '').strip())


def extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if '```json' in cleaned:
        cleaned = cleaned.replace('```json', '').replace('```', '')
    elif '```' in cleaned:
        cleaned = cleaned.replace('```', '')
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('LLM response does not contain a JSON object')
    return json.loads(cleaned[start:end + 1])


def call_openai_chat(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    model = os.getenv('OPENAI_MODEL', '').strip()
    base_url = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1').strip().rstrip('/')
    timeout = float(os.getenv('REQUEST_TIMEOUT', '30'))
    temperature = float(os.getenv('OPENAI_TEMPERATURE', '0.2'))
    if not api_key or not model:
        raise RuntimeError('missing OPENAI_API_KEY or OPENAI_MODEL')

    payload = {
        'model': model,
        'temperature': temperature,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'response_format': {'type': 'json_object'},
    }
    req = urllib.request.Request(
        base_url + '/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'StockAnalysisSkill/0.1',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'LLM request failed: HTTP {exc.code} {body[:300]}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'LLM request failed: {exc}') from exc

    choices = data.get('choices') or []
    if not choices:
        raise RuntimeError('LLM response missing choices')
    content = (((choices[0] or {}).get('message') or {}).get('content') or '').strip()
    if not content:
        raise RuntimeError('LLM response content is empty')
    return extract_json_object(content)


def format_news_context(news_payload: Dict[str, Any]) -> str:
    dimensions = news_payload.get('dimensions') or {}
    if not dimensions and not (news_payload.get('items') or []):
        return '未搜索到相关新闻。'
    lines = []
    order = ['latest_news', 'market_analysis', 'risk_check', 'earnings', 'industry']
    for name in order:
        payload = dimensions.get(name)
        if not payload:
            continue
        label = NEWS_DIMENSION_LABELS.get(name, name)
        provider = payload.get('provider') or '未命中'
        lines.append(f'## {label}（来源：{provider}）')
        items = payload.get('items') or []
        if items:
            for idx, item in enumerate(items[:3], 1):
                title = item.get('title') or '无标题'
                snippet = (item.get('snippet') or '').strip()
                published = item.get('published_at') or '未知时间'
                lines.append(f'{idx}. {title} [{published}]')
                if snippet:
                    lines.append(f'   {snippet[:180]}')
        else:
            lines.append('1. 未找到相关信息')
    if not lines:
        for idx, item in enumerate((news_payload.get('items') or [])[:5], 1):
            lines.append(f"{idx}. {item.get('title') or '无标题'}")
            if item.get('snippet'):
                lines.append(f"   {(item.get('snippet') or '')[:180]}")
    return '\n'.join(lines)


def fmt_num(value: Optional[float], digits: int = 2) -> str:
    return 'N/A' if value is None else f'{value:.{digits}f}'


def build_stock_analysis_prompt(context: Dict[str, Any]) -> Tuple[str, str]:
    symbol = context.get('symbol') or 'UNKNOWN'
    quote = find_symbol_quote(context) or {}
    news_payload = find_symbol_news(context)
    market_payload = get_payload(context, 'market')
    market_regime, market_risk, market_note = infer_market_regime(market_payload)
    profile = compute_signal_profile(quote, news_payload) if quote else {}
    support, resistance, invalidation, target, trade_setup = support_resistance(quote, profile) if quote else ('暂无', '暂无', '暂无', '暂无', {'ideal_entry': '暂无', 'secondary_entry': '暂无', 'stop_loss': '暂无', 'take_profit': '暂无', 'zone_note': '暂无'})

    stock_name = quote.get('name') or symbol
    recent_bars = quote.get('recent_bars') or []
    bar_lines = []
    for bar in recent_bars[-5:]:
        bar_lines.append(
            f"- {bar.get('date', '未知')} O:{fmt_num(bar.get('open'))} H:{fmt_num(bar.get('high'))} L:{fmt_num(bar.get('low'))} C:{fmt_num(bar.get('close'))} V:{bar.get('volume', 'N/A')}"
        )

    system_prompt = """你是一位中文股票分析师。你的任务不是复述数据，而是像原始 daily_stock_analysis 项目一样，综合技术面、市场环境和多维新闻情报，生成面向交易决策的中文分析。必须严格区分事实与推断，不得编造未提供的信息。如果新闻为空，要明确说明新闻情报不足。请仅输出 JSON。"""

    user_prompt = f"""请基于以下输入，为 {stock_name}({symbol}) 生成中文股票分析 JSON。

输出 JSON 字段必须包含：
- conclusion
- score
- confidence
- trend
- market_environment
- news_summary
- catalysts
- risks
- key_levels
- trade_plan
- position_judgment
- action_plan
- reasoning

字段要求：
- conclusion: 例如“买入/观望/回避（AAPL） | 置信度 中”
- score: 0-100 整数
- confidence: 高/中/低
- trend: 一句话描述趋势和技术状态
- market_environment: 一句话总结市场环境
- news_summary: 一句话总结多维新闻情报，若缺失明确写“新闻情报不足”
- catalysts: 字符串数组，最多4条
- risks: 字符串数组，最多5条
- key_levels: 对象，包含 support/resistance/invalidation/target
- trade_plan: 对象，包含 ideal_entry/secondary_entry/stop_loss/take_profit
- position_judgment: 一句话说明当前位置是否适合参与
- action_plan: 一句话给出执行建议
- reasoning: 字符串数组，列出3-6条核心依据

【股票基础】
- 代码: {symbol}
- 名称: {stock_name}
- 市场: {context.get('market') or quote.get('market') or 'unknown'}
- 最新价: {fmt_num(quote.get('latest_price'))}
- 日涨跌幅: {fmt_num(quote.get('change_pct'))}%
- MA5/MA10/MA20: {fmt_num(quote.get('ma5'))}/{fmt_num(quote.get('ma10'))}/{fmt_num(quote.get('ma20'))}

【技术状态】
- 趋势状态: {profile.get('trend_status', 'unknown')}
- 趋势描述: {profile.get('ma_alignment', '暂无')}
- 量能状态: {profile.get('volume_trend', '暂无')}
- MACD: {profile.get('macd_signal', '暂无')}
- RSI: {profile.get('rsi_signal', '暂无')}
- MA5 乖离率: {fmt_num(profile.get('bias_ma5'))}%
- MA10 乖离率: {fmt_num(profile.get('bias_ma10'))}%
- MA20 乖离率: {fmt_num(profile.get('bias_ma20'))}%

【关键价位】
- 支撑: {support}
- 压力: {resistance}
- 失效位: {invalidation}
- 参考目标: {target}
- 理想买点: {trade_setup.get('ideal_entry', '暂无')}
- 次优买点: {trade_setup.get('secondary_entry', '暂无')}
- 止损位: {trade_setup.get('stop_loss', '暂无')}
- 止盈参考: {trade_setup.get('take_profit', '暂无')}
- 位置判断参考: {trade_setup.get('zone_note', '暂无')}

【最近K线摘要】
{chr(10).join(bar_lines) if bar_lines else '- 无'}

【市场环境】
- 市场阶段: {REGIME_CN.get(market_regime, market_regime)}
- 风险等级: {RISK_CN.get(market_risk, market_risk)}
- 市场说明: {market_note}

【多维新闻情报】
{format_news_context(news_payload)}

分析要求：
1. 新闻分析必须优先识别 风险排查、业绩预期、机构分析、最新消息 里的关键信号。
2. 如果新闻和技术面冲突，必须指出冲突。
3. 不要机械看多或看空，要结合当前位置、乖离率和市场环境给交易建议。
4. 输出必须是中文，且只能输出 JSON。"""
    return system_prompt, user_prompt


def build_strategy_prompt(context: Dict[str, Any]) -> Tuple[str, str]:
    symbol = context.get('symbol') or 'UNKNOWN'
    strategy = context.get('strategy') or 'unknown'
    quote = find_symbol_quote(context) or {}
    news_payload = find_symbol_news(context)
    market_payload = get_payload(context, 'market')
    market_regime, market_risk, market_note = infer_market_regime(market_payload)
    profile = compute_signal_profile(quote, news_payload) if quote else {}
    _, _, _, _, trade_setup = support_resistance(quote, profile) if quote else ('暂无', '暂无', '暂无', '暂无', {'ideal_entry': '暂无', 'secondary_entry': '暂无', 'stop_loss': '暂无', 'take_profit': '暂无', 'zone_note': '暂无'})
    stock_name = quote.get('name') or symbol

    system_prompt = "你是一位中文策略交易分析师。请结合技术面、多维新闻情报和市场环境，对给定策略做严格判定。只输出 JSON。"
    user_prompt = f"""请按策略 {strategy} 分析 {stock_name}({symbol})，并仅输出 JSON。

输出 JSON 字段必须包含：
- strategy_name
- result
- evidence
- failed_checks
- strategy_buy_points
- strategy_risk_control
- position_judgment
- risks
- action_bias

字段要求：
- result: 满足/部分满足/不满足
- evidence: 字符串数组，2-5条
- failed_checks: 字符串数组
- strategy_buy_points: 对象，包含 ideal_entry/secondary_entry
- strategy_risk_control: 对象，包含 stop_loss/target
- position_judgment: 一句话
- risks: 字符串数组
- action_bias: 可执行/加入观察/暂不参与

【标的与技术】
- 代码: {symbol}
- 名称: {stock_name}
- 最新价: {fmt_num(quote.get('latest_price'))}
- MA5/MA10/MA20: {fmt_num(quote.get('ma5'))}/{fmt_num(quote.get('ma10'))}/{fmt_num(quote.get('ma20'))}
- 趋势描述: {profile.get('ma_alignment', '暂无')}
- 量能状态: {profile.get('volume_trend', '暂无')}
- MACD: {profile.get('macd_signal', '暂无')}
- RSI: {profile.get('rsi_signal', '暂无')}
- 位置参考: {trade_setup.get('zone_note', '暂无')}

【市场环境】
- 市场阶段: {REGIME_CN.get(market_regime, market_regime)}
- 风险等级: {RISK_CN.get(market_risk, market_risk)}
- 市场说明: {market_note}

【多维新闻情报】
{format_news_context(news_payload)}

要求：
1. 策略判定必须结合新闻中的风险排查和业绩预期，不可只看均线。
2. 若新闻面出现明显利空，即便技术面接近满足，也要在 failed_checks 或 risks 中明确体现。
3. 输出中文 JSON。"""
    return system_prompt, user_prompt


def build_market_prompt(context: Dict[str, Any]) -> Tuple[str, str]:
    payload = get_payload(context, 'market') or {}
    indexes = payload.get('major_indexes') or []
    lines = []
    for idx in indexes[:5]:
        lines.append(f"- {idx.get('name') or idx.get('symbol')}: {fmt_num(idx.get('latest_price'))} ({fmt_num(idx.get('change_pct'))}%)")
    system_prompt = "你是一位中文市场复盘分析师。请根据市场快照生成简明、可执行的市场结论。只输出 JSON。"
    user_prompt = f"""请基于以下市场数据生成中文市场分析 JSON。

输出 JSON 字段必须包含：
- market_conclusion
- market_evidence
- risk_level
- suggested_posture
- explanation

【市场】
- 区域: {context.get('market') or payload.get('market') or 'unknown'}
- 指数列表:
{chr(10).join(lines) if lines else '- 无'}
- 市场摘要: {payload.get('market_summary') or '暂无'}

要求：
1. 输出中文 JSON。
2. suggested_posture 只能是 进攻/均衡/防守。
3. explanation 要结合指数涨跌和环境描述。"""
    return system_prompt, user_prompt


def render_stock_llm(context: Dict[str, Any]) -> str:
    quote = find_symbol_quote(context) or {}
    news_payload = find_symbol_news(context)
    market_payload = get_payload(context, 'market')
    market_regime, market_risk, market_note = infer_market_regime(market_payload)
    profile = compute_signal_profile(quote, news_payload) if quote else {}
    support, resistance, invalidation, target, trade_setup = support_resistance(quote, profile) if quote else ('暂无', '暂无', '暂无', '暂无', {'ideal_entry': '暂无', 'secondary_entry': '暂无', 'stop_loss': '暂无', 'take_profit': '暂无', 'zone_note': '暂无'})
    system_prompt, user_prompt = skill_llm.build_stock_prompts(
        symbol=context.get('symbol') or 'UNKNOWN',
        stock_name=quote.get('name') or (context.get('symbol') or 'UNKNOWN'),
        market=context.get('market') or quote.get('market') or 'unknown',
        quote=quote,
        profile=profile,
        market_regime_cn=REGIME_CN.get(market_regime, market_regime),
        market_risk_cn=RISK_CN.get(market_risk, market_risk),
        market_note=market_note,
        support=support,
        resistance=resistance,
        invalidation=invalidation,
        target=target,
        trade_setup=trade_setup,
        recent_bars=quote.get('recent_bars') or [],
        news_payload=news_payload,
    )
    data = skill_llm.call_openai_chat(system_prompt, user_prompt)
    catalysts = data.get('catalysts') or []
    risks = data.get('risks') or []
    reasoning = data.get('reasoning') or []
    key_levels = data.get('key_levels') or {}
    trade_plan = data.get('trade_plan') or {}
    lines = [
        f"结论：{data.get('conclusion', '观望')}（{context.get('symbol') or 'UNKNOWN'}） | 置信度 {data.get('confidence', '低')}",
        f"评分：{data.get('score', '暂无')}/100",
        f"趋势：{data.get('trend', '暂无')}",
        f"市场环境：{data.get('market_environment', '暂无')}",
        f"新闻情报：{data.get('news_summary', '新闻情报不足')}",
        '利好催化：' + ('；'.join(catalysts) if catalysts else '当前输入中未捕捉到高置信度利好催化'),
        '加分依据：' + ('；'.join(reasoning) if reasoning else '暂无明显加分项'),
        f"关键价位：支撑 {key_levels.get('support', '暂无')} | 压力 {key_levels.get('resistance', '暂无')} | 失效位 {key_levels.get('invalidation', '暂无')} | 参考目标 {key_levels.get('target', '暂无')}",
        f"交易计划：理想买点 {trade_plan.get('ideal_entry', '暂无')} | 次优买点 {trade_plan.get('secondary_entry', '暂无')} | 止损位 {trade_plan.get('stop_loss', '暂无')} | 止盈参考 {trade_plan.get('take_profit', '暂无')}",
        f"位置判断：{data.get('position_judgment', '暂无')}",
        '风险警报：' + ('；'.join(risks) if risks else '当前未发现突出的新增风险项'),
        f"操作计划：{data.get('action_plan', '暂无')}",
    ]
    return '\n'.join(lines)


def render_strategy_llm(context: Dict[str, Any]) -> str:
    quote = find_symbol_quote(context) or {}
    news_payload = find_symbol_news(context)
    market_payload = get_payload(context, 'market')
    market_regime, market_risk, market_note = infer_market_regime(market_payload)
    profile = compute_signal_profile(quote, news_payload) if quote else {}
    _, _, _, _, trade_setup = support_resistance(quote, profile) if quote else ('暂无', '暂无', '暂无', '暂无', {'ideal_entry': '暂无', 'secondary_entry': '暂无', 'stop_loss': '暂无', 'take_profit': '暂无', 'zone_note': '暂无'})
    system_prompt, user_prompt = skill_llm.build_strategy_prompts(
        symbol=context.get('symbol') or 'UNKNOWN',
        stock_name=quote.get('name') or (context.get('symbol') or 'UNKNOWN'),
        strategy=context.get('strategy') or 'unknown',
        quote=quote,
        profile=profile,
        market_regime_cn=REGIME_CN.get(market_regime, market_regime),
        market_risk_cn=RISK_CN.get(market_risk, market_risk),
        market_note=market_note,
        trade_setup=trade_setup,
        news_payload=news_payload,
    )
    data = skill_llm.call_openai_chat(system_prompt, user_prompt)
    buy_points = data.get('strategy_buy_points') or {}
    risk_control = data.get('strategy_risk_control') or {}
    evidence = data.get('evidence') or []
    failed_checks = data.get('failed_checks') or []
    risks = data.get('risks') or []
    return '\n'.join([
        f"策略名称：{data.get('strategy_name', context.get('strategy') or 'unknown')}",
        f"判定结果：{data.get('result', '不满足')}（{context.get('symbol') or 'UNKNOWN'}）",
        '支持证据：' + ('；'.join(evidence) if evidence else '暂无'),
        '不满足项：' + ('；'.join(failed_checks) if failed_checks else '无'),
        f"策略买点：理想买点 {buy_points.get('ideal_entry', '暂无')} | 次优买点 {buy_points.get('secondary_entry', '暂无')}",
        f"策略风控：止损位 {risk_control.get('stop_loss', '暂无')} | 目标位 {risk_control.get('target', '暂无')}",
        f"位置判断：{data.get('position_judgment', '暂无')}",
        '风险提示：' + ('；'.join(risks) if risks else '暂无明显新增风险'),
        f"执行建议：{data.get('action_bias', '暂不参与')}",
    ])


def render_market_llm(context: Dict[str, Any]) -> str:
    payload = get_payload(context, 'market') or {}
    indexes = payload.get('major_indexes') or []
    index_lines = '\n'.join(
        f"- {idx.get('name') or idx.get('symbol')}: {fmt_num(idx.get('latest_price'))} ({fmt_num(idx.get('change_pct'))}%)"
        for idx in indexes[:5]
    )
    system_prompt, user_prompt = skill_llm.build_market_prompts(
        market=context.get('market') or payload.get('market') or 'unknown',
        market_summary=payload.get('market_summary') or '暂无',
        index_lines=index_lines,
    )
    data = skill_llm.call_openai_chat(system_prompt, user_prompt)
    evidence = data.get('market_evidence') or []
    return '\n'.join([
        f"市场结论：{data.get('market_conclusion', '暂无')}（{context.get('market') or 'unknown'}）",
        '市场证据：' + ('；'.join(evidence) if evidence else '暂无'),
        f"风险等级：{data.get('risk_level', '未知')}",
        f"建议姿态：{data.get('suggested_posture', '均衡')}",
        f"说明：{data.get('explanation', '暂无')}",
    ])


def render_output(context: Dict[str, Any], mode: str) -> str:
    if skill_llm.llm_is_configured():
        try:
            if mode == 'stock':
                return render_stock_llm(context)
            if mode == 'market':
                return render_market_llm(context)
            return render_strategy_llm(context)
        except Exception as exc:
            fallback_note = f'LLM 分析失败，已回退到本地规则：{exc}'
            if mode == 'stock':
                return render_stock(context) + '\n' + fallback_note
            if mode == 'market':
                return render_market(context) + '\n' + fallback_note
            return render_strategy(context) + '\n' + fallback_note
    if mode == 'stock':
        return render_stock(context)
    if mode == 'market':
        return render_market(context)
    return render_strategy(context)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['stock', 'market', 'strategy'], required=True)
    parser.add_argument('--context', required=True)
    args = parser.parse_args()

    context = load_json(args.context)
    print(render_output(context, args.mode))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
