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

"$PYTHON_BIN" - "$@" <<'PY'
import contextlib
import io
import json
import os
import sys
import ssl
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yfinance as yf

MARKETS = {
    'us': [('^GSPC', 'S&P 500'), ('^IXIC', 'NASDAQ'), ('^DJI', 'Dow Jones')],
    'hk': [('^HSI', 'Hang Seng'), ('^HSCE', 'HSCEI')],
}

CN_INDEXES = [
    ('1.000001', '000001.SH', '上证指数'),
    ('0.399001', '399001.SZ', '深证成指'),
    ('0.399006', '399006.SZ', '创业板指'),
]

CN_INDEX_LABELS = {
    'sh000001': ('000001.SH', '上证指数'),
    'sz399001': ('399001.SZ', '深证成指'),
    'sz399006': ('399006.SZ', '创业板指'),
}


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def http_get_json(url, params=None):
    full_url = url
    if params:
        full_url = f"{url}?{urlencode(params)}"
    req = Request(full_url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json,text/plain,*/*',
        'Referer': 'https://quote.eastmoney.com/',
    })
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with urlopen(req, timeout=15, context=context) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_index_cn_eastmoney(secid, symbol, label):
    base = {'symbol': symbol, 'name': label, 'latest_price': None, 'change_pct': None}
    try:
        quote_data = http_get_json(
            'https://push2.eastmoney.com/api/qt/stock/get',
            {'secid': secid, 'fields': 'f43,f58,f170'},
        ).get('data') or {}
        raw_latest = quote_data.get('f43')
        raw_change = quote_data.get('f170')
        latest = float(raw_latest) / 100 if raw_latest not in (None, '', '-') else None
        change_pct = float(raw_change) / 100 if raw_change not in (None, '', '-') else None
        base.update({
            'name': quote_data.get('f58') or label,
            'latest_price': latest,
            'change_pct': change_pct,
            'provider_source': 'eastmoney',
        })
    except Exception as exc:
        base['error'] = str(exc)
    return base


def fetch_indexes_cn_akshare():
    try:
        import akshare as ak
    except Exception as exc:
        return [], f'akshare import failed: {exc}'

    try:
        df = ak.stock_zh_index_spot_sina()
    except Exception as exc:
        return [], f'akshare fetch failed: {exc}'

    indexes = []
    for code, (symbol, label) in CN_INDEX_LABELS.items():
        row = df[df['代码'] == code]
        item = {'symbol': symbol, 'name': label, 'latest_price': None, 'change_pct': None}
        if row.empty:
            item['error'] = f'missing {code}'
            indexes.append(item)
            continue
        row = row.iloc[0]
        item.update({
            'name': str(row.get('名称') or label),
            'latest_price': float(row.get('最新价')) if row.get('最新价') not in (None, '', '-') else None,
            'change_pct': float(row.get('涨跌幅')) if row.get('涨跌幅') not in (None, '', '-') else None,
            'provider_source': 'akshare',
        })
        indexes.append(item)
    return indexes, None


def fetch_indexes_cn():
    indexes = [fetch_index_cn_eastmoney(secid, symbol, label) for secid, symbol, label in CN_INDEXES]
    if any(idx.get('change_pct') is not None for idx in indexes):
        return indexes, 'eastmoney'

    ak_indexes, ak_error = fetch_indexes_cn_akshare()
    if any(idx.get('change_pct') is not None for idx in ak_indexes):
        return ak_indexes, 'akshare'

    if ak_error:
        for idx in indexes:
            prev = idx.get('error')
            idx['error'] = f'{prev}; {ak_error}' if prev else ak_error
    return indexes, 'eastmoney'


def fetch_index_yfinance(symbol, label):
    base = {'symbol': symbol, 'name': label, 'latest_price': None, 'change_pct': None}
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period='5d', interval='1d', auto_adjust=False, actions=False)
        if hist is None or hist.empty:
            raise RuntimeError('empty history from yfinance')
        closes = [float(v) for v in hist['Close'].dropna().tolist()]
        latest = closes[-1] if closes else None
        prev = closes[-2] if len(closes) >= 2 else None
        change_pct = None
        if latest is not None and prev not in (None, 0):
            change_pct = round((latest - prev) / prev * 100, 4)
        info = {}
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                info = ticker.info or {}
        except Exception:
            info = {}
        base.update({
            'name': info.get('shortName') or info.get('longName') or label,
            'latest_price': latest,
            'change_pct': change_pct,
            'provider_source': 'yfinance',
        })
    except Exception as exc:
        base['error'] = str(exc)
    return base


def summarize(indexes):
    usable = [idx for idx in indexes if idx.get('change_pct') is not None]
    if not usable:
        return 'Market summary unavailable because live index data could not be fetched.'
    avg_change = sum(idx['change_pct'] for idx in usable) / len(usable)
    if avg_change > 1:
        tone = 'broadly strong'
    elif avg_change > 0.2:
        tone = 'slightly constructive'
    elif avg_change < -1:
        tone = 'under notable pressure'
    elif avg_change < -0.2:
        tone = 'slightly weak'
    else:
        tone = 'mixed and range-bound'
    return f'Indexes are {tone} with average move {avg_change:.2f}% across tracked benchmarks.'


def main():
    market = (sys.argv[1] if len(sys.argv) > 1 else os.getenv('DEFAULT_MARKET', 'cn')).lower()
    if market == 'cn':
        indexes, provider = fetch_indexes_cn()
    else:
        symbols = MARKETS.get(market, MARKETS['us'])
        indexes = [fetch_index_yfinance(symbol, label) for symbol, label in symbols]
        provider = os.getenv('MARKET_PROVIDER', 'yfinance')
    print(json.dumps({
        'market': market,
        'major_indexes': indexes,
        'breadth': None,
        'leaders_laggards': [],
        'market_summary': summarize(indexes),
        'provider': provider,
        'fetched_at': utc_now(),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
PY
