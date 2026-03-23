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
  echo '{"error":"usage: fetch_quotes.sh SYMBOL [SYMBOL ...]"}'
  exit 1
fi

"$PYTHON_BIN" - "$@" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import ssl

import yfinance as yf

STOCK_NAME_MAP = {
    '600519': '贵州茅台', '000001': '平安银行', '300750': '宁德时代', '002594': '比亚迪',
    '600036': '招商银行', '601318': '中国平安', '000858': '五粮液', '600276': '恒瑞医药',
    '601012': '隆基绿能', '002475': '立讯精密', '300059': '东方财富', '002415': '海康威视',
    '600900': '长江电力', '601166': '兴业银行', '600028': '中国石化', 'AAPL': '苹果',
    'TSLA': '特斯拉', 'MSFT': '微软', 'GOOGL': '谷歌A', 'GOOG': '谷歌C', 'AMZN': '亚马逊',
    'NVDA': '英伟达', 'META': 'Meta', 'AMD': 'AMD', 'INTC': '英特尔', 'BABA': '阿里巴巴',
    'PDD': '拼多多', 'JD': '京东', 'BIDU': '百度', 'NIO': '蔚来', 'XPEV': '小鹏汽车',
    'LI': '理想汽车', 'COIN': 'Coinbase', 'MSTR': 'MicroStrategy', '00700': '腾讯控股',
    '03690': '美团', '01810': '小米集团', '09988': '阿里巴巴', '09618': '京东集团',
    '09888': '百度集团', '01024': '快手', '00981': '中芯国际', '02015': '理想汽车',
    '09868': '小鹏汽车', '00005': '汇丰控股', '01299': '友邦保险', '00941': '中国移动',
    '00883': '中国海洋石油',
}


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def avg(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 4) if vals else None


def detect_market(symbol):
    s = symbol.strip().upper()
    if s.endswith(('.SS', '.SZ', '.HK')):
        if s.endswith('.HK'):
            return 'hk'
        return 'cn'
    if s.startswith('HK'):
        return 'hk'
    if s.isdigit() and len(s) == 6:
        return 'cn'
    return 'us'


def normalize_symbol(symbol):
    raw = symbol.strip().upper()
    if not raw:
        return raw, None
    if raw.endswith(('.SS', '.SZ', '.HK')):
        return raw, detect_market(raw)
    if raw.startswith('HK'):
        digits = ''.join(ch for ch in raw[2:] if ch.isdigit())
        if digits:
            return digits[-4:].zfill(4) + '.HK', 'hk'
    if raw.isdigit() and len(raw) == 6:
        suffix = '.SS' if raw.startswith(('5', '6', '9')) else '.SZ'
        return raw + suffix, 'cn'
    if raw.isdigit() and len(raw) <= 5:
        return raw[-4:].zfill(4) + '.HK', 'hk'
    return raw, 'us'


def canonical_symbol(symbol):
    raw = symbol.strip().upper()
    if not raw:
        return raw
    if raw.endswith('.HK'):
        return raw[:-3].zfill(5)
    if raw.endswith(('.SS', '.SZ')):
        return raw[:-3]
    if raw.startswith('HK'):
        digits = ''.join(ch for ch in raw[2:] if ch.isdigit())
        return digits[-5:].zfill(5) if digits else raw
    if raw.isdigit() and len(raw) <= 5:
        return raw.zfill(5)
    return raw


def resolve_display_name(requested_symbol, provider_symbol, market, info_name):
    candidates = []
    for item in (requested_symbol, provider_symbol):
        if not item:
            continue
        normalized = canonical_symbol(item)
        if normalized:
            candidates.append(normalized)
        candidates.append(item.strip().upper())
    for candidate in candidates:
        if candidate in STOCK_NAME_MAP:
            return STOCK_NAME_MAP[candidate]
    if info_name:
        return info_name
    if market == 'cn':
        return f'股票{canonical_symbol(requested_symbol)}'
    return requested_symbol


def to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def http_get_json(url, params=None):
    full_url = url
    if params:
        full_url = f"{url}?{urlencode(params)}"
    req = Request(full_url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
    })
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with urlopen(req, timeout=15, context=context) as resp:
        return json.loads(resp.read().decode("utf-8"))


def eastmoney_secid(symbol):
    code = canonical_symbol(symbol)
    if code.isdigit() and len(code) == 6:
        market = "1" if code.startswith(("5", "6", "9")) else "0"
        return f"{market}.{code}"
    if code.isdigit() and len(code) <= 5:
        return f"116.{code.zfill(5)}"
    return None


def build_cn_fallback_payload(requested_symbol, base, original_error):
    market = base.get("market") or detect_market(requested_symbol)
    secid = eastmoney_secid(requested_symbol)
    if not secid:
        raise RuntimeError(original_error)

    quote_data = http_get_json(
        "https://push2.eastmoney.com/api/qt/stock/get",
        {
            "secid": secid,
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f170",
        },
    ).get("data") or {}

    kline_data = http_get_json(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",
            "lmt": "20",
            "end": "20500101",
        },
    ).get("data") or {}

    klines = kline_data.get("klines") or []
    if not klines:
        raise RuntimeError(original_error)

    bars = []
    for raw in klines:
        parts = raw.split(",")
        if len(parts) < 11:
            continue
        bars.append({
            "date": parts[0],
            "open": to_float(parts[1]),
            "close": to_float(parts[2]),
            "high": to_float(parts[3]),
            "low": to_float(parts[4]),
            "volume": int(float(parts[5])) if parts[5] not in ("", "-") else None,
            "turnover": to_float(parts[10]),
        })

    closes_only = [b["close"] for b in bars if b.get("close") is not None]
    latest_bar = bars[-1] if bars else {}
    latest = latest_bar.get("close")
    prev = bars[-2].get("close") if len(bars) >= 2 else None
    change_pct = None
    if latest is not None and prev not in (None, 0):
        change_pct = round((latest - prev) / prev * 100, 4)
    if change_pct is None:
        change_pct = to_float(quote_data.get("f170"))

    base.update({
        "name": resolve_display_name(requested_symbol, canonical_symbol(requested_symbol), market, quote_data.get("f58")),
        "currency": "CNY" if market == "cn" else "HKD",
        "latest_price": latest if latest is not None else to_float(quote_data.get("f43")),
        "change_pct": change_pct,
        "open": latest_bar.get("open") if latest_bar else to_float(quote_data.get("f46")),
        "high": latest_bar.get("high") if latest_bar else to_float(quote_data.get("f44")),
        "low": latest_bar.get("low") if latest_bar else to_float(quote_data.get("f45")),
        "volume": latest_bar.get("volume") if latest_bar else None,
        "turnover": latest_bar.get("turnover"),
        "ma5": avg(closes_only[-5:]),
        "ma10": avg(closes_only[-10:]),
        "ma20": avg(closes_only[-20:]),
        "recent_bars": bars,
        "provider_symbol": secid,
        "provider_source": "eastmoney",
        "fallback_from": "yfinance",
    })
    base.pop("error", None)
    return base


def merge_history_from_yfinance(requested_symbol, base):
    yahoo_symbol, _market = normalize_symbol(requested_symbol)
    hist = yf.Ticker(yahoo_symbol).history(period="1mo", interval="1d", auto_adjust=False, actions=False)
    if hist is None or hist.empty:
        return base
    hist = hist.dropna(subset=["Close"])
    bars = []
    for idx, row in hist.tail(20).iterrows():
        bars.append({
            "date": idx.strftime("%Y-%m-%d"),
            "open": to_float(row.get("Open")),
            "high": to_float(row.get("High")),
            "low": to_float(row.get("Low")),
            "close": to_float(row.get("Close")),
            "volume": int(row.get("Volume")) if row.get("Volume") is not None else None,
        })
    closes_only = [b["close"] for b in bars if b.get("close") is not None]
    if not base.get("recent_bars"):
        base["recent_bars"] = bars
    if not base.get("ma5"):
        base["ma5"] = avg(closes_only[-5:])
    if not base.get("ma10"):
        base["ma10"] = avg(closes_only[-10:])
    if not base.get("ma20"):
        base["ma20"] = avg(closes_only[-20:])
    return base

def build_sina_cn_payload(requested_symbol, base, original_error):
    code = canonical_symbol(requested_symbol)
    if not code.isdigit() or len(code) != 6:
        raise RuntimeError(original_error)
    symbol = ("sh" if code.startswith(("5", "6", "9")) else "sz") + code
    req = Request("http://hq.sinajs.cn/list=" + symbol, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
    with urlopen(req, timeout=10) as resp:
        content = resp.read().decode("gbk", errors="replace").strip()
    if '=""' in content or not content:
        raise RuntimeError(original_error)
    start = content.find(chr(34))
    end = content.rfind(chr(34))
    if start < 0 or end <= start:
        raise RuntimeError(original_error)
    fields = content[start + 1:end].split(",")
    if len(fields) < 32:
        raise RuntimeError(original_error)
    price = to_float(fields[3])
    pre_close = to_float(fields[2])
    change_pct = None
    if price is not None and pre_close not in (None, 0):
        change_pct = round((price - pre_close) / pre_close * 100, 4)
    base.update({
        "name": resolve_display_name(requested_symbol, code, "cn", fields[0] or None),
        "currency": "CNY",
        "latest_price": price,
        "change_pct": change_pct,
        "open": to_float(fields[1]),
        "high": to_float(fields[4]),
        "low": to_float(fields[5]),
        "volume": int(float(fields[8])) if fields[8] else None,
        "turnover": to_float(fields[9]),
        "provider_symbol": symbol,
        "provider_source": "sina",
    })
    merge_history_from_yfinance(requested_symbol, base)
    base.pop("error", None)
    return base

def build_tencent_cn_payload(requested_symbol, base, original_error):
    code = canonical_symbol(requested_symbol)
    if not code.isdigit() or len(code) != 6:
        raise RuntimeError(original_error)
    symbol = ("sh" if code.startswith(("5", "6", "9")) else "sz") + code
    req = Request("http://qt.gtimg.cn/q=" + symbol, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com"})
    with urlopen(req, timeout=10) as resp:
        content = resp.read().decode("gbk", errors="replace").strip()
    if '=""' in content or not content:
        raise RuntimeError(original_error)
    start = content.find(chr(34))
    end = content.rfind(chr(34))
    if start < 0 or end <= start:
        raise RuntimeError(original_error)
    fields = content[start + 1:end].split("~")
    if len(fields) < 45:
        raise RuntimeError(original_error)
    price = to_float(fields[3])
    pre_close = to_float(fields[4])
    change_pct = to_float(fields[32])
    if change_pct is None and price is not None and pre_close not in (None, 0):
        change_pct = round((price - pre_close) / pre_close * 100, 4)
    base.update({
        "name": resolve_display_name(requested_symbol, code, "cn", fields[1] or None),
        "currency": "CNY",
        "latest_price": price,
        "change_pct": change_pct,
        "open": to_float(fields[5]),
        "high": to_float(fields[33]) if len(fields) > 33 else None,
        "low": to_float(fields[34]) if len(fields) > 34 else None,
        "volume": int(float(fields[6]) * 100) if len(fields) > 6 and fields[6] else None,
        "turnover": to_float(fields[37]) * 10000 if len(fields) > 37 and fields[37] else None,
        "provider_symbol": symbol,
        "provider_source": "tencent",
    })
    merge_history_from_yfinance(requested_symbol, base)
    base.pop("error", None)
    return base

def build_symbol_payload(requested_symbol):
    yahoo_symbol, market = normalize_symbol(requested_symbol)
    base = {
        'symbol': requested_symbol,
        'name': None,
        'market': market,
        'currency': None,
        'latest_price': None,
        'change_pct': None,
        'open': None,
        'high': None,
        'low': None,
        'volume': None,
        'turnover': None,
        'ma5': None,
        'ma10': None,
        'ma20': None,
        'recent_bars': [],
        'provider_symbol': yahoo_symbol,
    }
    source_errors = []
    if market in ("cn", "hk"):
        try:
            return build_cn_fallback_payload(requested_symbol, base, "eastmoney unavailable")
        except Exception as fallback_exc:
            source_errors.append(f"eastmoney: {fallback_exc}")
    if market == "cn":
        try:
            return build_sina_cn_payload(requested_symbol, base, "sina unavailable")
        except Exception as fallback_exc:
            source_errors.append(f"sina: {fallback_exc}")
        try:
            return build_tencent_cn_payload(requested_symbol, base, "tencent unavailable")
        except Exception as fallback_exc:
            source_errors.append(f"tencent: {fallback_exc}")
    try:
        ticker = yf.Ticker(yahoo_symbol)
        hist = ticker.history(period='1mo', interval='1d', auto_adjust=False, actions=False)
        if hist is None or hist.empty:
            raise RuntimeError('empty history from yfinance')
        hist = hist.dropna(subset=['Close'])
        bars = []
        for idx, row in hist.tail(20).iterrows():
            bars.append({
                'date': idx.strftime('%Y-%m-%d'),
                'open': to_float(row.get('Open')),
                'high': to_float(row.get('High')),
                'low': to_float(row.get('Low')),
                'close': to_float(row.get('Close')),
                'volume': int(row.get('Volume')) if row.get('Volume') is not None else None,
            })
        closes_only = [b['close'] for b in bars if b.get('close') is not None]
        latest = closes_only[-1] if closes_only else None
        prev = closes_only[-2] if len(closes_only) >= 2 else None
        change_pct = None
        if latest is not None and prev not in (None, 0):
            change_pct = round((latest - prev) / prev * 100, 4)
        latest_bar = bars[-1] if bars else {}
        info = {}
        try:
            info = ticker.info or {}
        except Exception:
            info = {}
        info_name = info.get('longName') or info.get('shortName') or info.get('displayName')
        currency = info.get('currency')
        if not currency:
            try:
                fast = ticker.fast_info
                currency = getattr(fast, 'currency', None) if fast is not None else None
            except Exception:
                currency = None
        base.update({
            'name': resolve_display_name(requested_symbol, yahoo_symbol, market, info_name),
            'currency': currency,
            'latest_price': latest,
            'change_pct': change_pct,
            'open': latest_bar.get('open'),
            'high': latest_bar.get('high'),
            'low': latest_bar.get('low'),
            'volume': latest_bar.get('volume'),
            'ma5': avg(closes_only[-5:]),
            'ma10': avg(closes_only[-10:]),
            'ma20': avg(closes_only[-20:]),
            'recent_bars': bars,
        })
    except Exception as exc:
        error_text = str(exc)
        if source_errors:
            base["error"] = "; ".join(source_errors + [f"yfinance: {error_text}"])
        else:
            base["error"] = error_text
    return base


def main():
    symbols = sys.argv[1:]
    items = [build_symbol_payload(symbol) for symbol in symbols]
    providers = []
    for item in items:
        source = item.get("provider_source")
        if source and source not in providers:
            providers.append(source)
    print(json.dumps({'symbols': items, 'provider': ','.join(providers) or 'multi', 'fetched_at': utc_now()}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
PY
