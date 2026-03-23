#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


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

NEWS_DIMENSION_LABELS = {
    'latest_news': '最新消息',
    'market_analysis': '机构分析',
    'risk_check': '风险排查',
    'earnings': '业绩预期',
    'industry': '行业分析',
}

STOCK_SYSTEM_PROMPT = """你是一位专注于趋势交易的中文股票分析师，负责生成专业的决策仪表盘式分析。
你必须综合技术面、市场环境和多维新闻情报进行判断，严格区分事实与推断。
如果新闻情报不足，必须明确说明，而不是假设利好或利空。
输出必须是 JSON，不要输出任何额外说明。"""

STRATEGY_SYSTEM_PROMPT = """你是一位中文策略交易分析师。请结合技术面、多维新闻情报和市场环境，对给定策略做严格判定。
输出必须是 JSON，不要输出任何额外说明。"""

MARKET_SYSTEM_PROMPT = """你是一位中文市场复盘分析师。请根据市场快照输出简明、可执行的市场结论。
输出必须是 JSON，不要输出任何额外说明。"""


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


def fmt_num(value: Optional[float], digits: int = 2) -> str:
    return 'N/A' if value is None else f'{value:.{digits}f}'


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


def build_stock_prompts(*, symbol: str, stock_name: str, market: str, quote: Dict[str, Any], profile: Dict[str, Any], market_regime_cn: str, market_risk_cn: str, market_note: str, support: str, resistance: str, invalidation: str, target: str, trade_setup: Dict[str, str], recent_bars, news_payload: Dict[str, Any]) -> Tuple[str, str]:
    bar_lines = []
    for bar in (recent_bars or [])[-5:]:
        bar_lines.append(
            f"- {bar.get('date', '未知')} O:{fmt_num(bar.get('open'))} H:{fmt_num(bar.get('high'))} L:{fmt_num(bar.get('low'))} C:{fmt_num(bar.get('close'))} V:{bar.get('volume', 'N/A')}"
        )
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
- conclusion: 例如“买入/观望/回避（AAPL）”
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
- 市场: {market}
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
- 市场阶段: {market_regime_cn}
- 风险等级: {market_risk_cn}
- 市场说明: {market_note}

【多维新闻情报】
{format_news_context(news_payload)}

分析要求：
1. 新闻分析必须优先识别 风险排查、业绩预期、机构分析、最新消息 里的关键信号。
2. 如果新闻和技术面冲突，必须指出冲突。
3. 不要机械看多或看空，要结合当前位置、乖离率和市场环境给交易建议。
4. 输出必须是中文，且只能输出 JSON。"""
    return STOCK_SYSTEM_PROMPT, user_prompt


def build_strategy_prompts(*, symbol: str, stock_name: str, strategy: str, quote: Dict[str, Any], profile: Dict[str, Any], market_regime_cn: str, market_risk_cn: str, market_note: str, trade_setup: Dict[str, str], news_payload: Dict[str, Any]) -> Tuple[str, str]:
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
- 市场阶段: {market_regime_cn}
- 风险等级: {market_risk_cn}
- 市场说明: {market_note}

【多维新闻情报】
{format_news_context(news_payload)}

要求：
1. 策略判定必须结合新闻中的风险排查和业绩预期，不可只看均线。
2. 若新闻面出现明显利空，即便技术面接近满足，也要在 failed_checks 或 risks 中明确体现。
3. 输出中文 JSON。"""
    return STRATEGY_SYSTEM_PROMPT, user_prompt


def build_market_prompts(*, market: str, market_summary: str, index_lines: str) -> Tuple[str, str]:
    user_prompt = f"""请基于以下市场数据生成中文市场分析 JSON。

输出 JSON 字段必须包含：
- market_conclusion
- market_evidence
- risk_level
- suggested_posture
- explanation

【市场】
- 区域: {market}
- 指数列表:
{index_lines if index_lines else '- 无'}
- 市场摘要: {market_summary or '暂无'}

要求：
1. 输出中文 JSON。
2. suggested_posture 只能是 进攻/均衡/防守。
3. explanation 要结合指数涨跌和环境描述。"""
    return MARKET_SYSTEM_PROMPT, user_prompt
