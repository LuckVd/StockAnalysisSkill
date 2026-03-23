#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent
RUN_SH = ROOT / '.claude' / 'skills' / 'StockAnalysis' / 'scripts' / 'run.sh'


def normalize_market(value: Optional[str]) -> str:
    raw = (value or '').strip().lower()
    if raw in {'a', 'ashare', 'cn', 'china'}:
        return 'cn'
    if raw in {'hk', 'h', 'hongkong'}:
        return 'hk'
    if raw in {'us', 'u', 'america'}:
        return 'us'
    return raw or 'cn'


def run_mode(args: List[str]) -> int:
    env = dict(os.environ)
    env.setdefault('PYTHON', sys.executable)
    result = subprocess.run(['bash', str(RUN_SH), *args], cwd=str(ROOT), env=env)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='mode')

    market_parser = subparsers.add_parser('market')
    market_parser.add_argument('--market', default='cn')

    stock_parser = subparsers.add_parser('stock')
    stock_parser.add_argument('--symbol', required=True)
    stock_parser.add_argument('--market', default='')

    status_parser = subparsers.add_parser('status')
    status_parser.add_argument('--doctor', action='store_true')

    args = parser.parse_args()
    if not args.mode:
        parser.print_help()
        return 2

    if args.mode == 'market':
        return run_mode(['market', normalize_market(args.market)])
    if args.mode == 'stock':
        cmd = ['stock', args.symbol]
        if args.market:
            cmd.append(normalize_market(args.market))
        return run_mode(cmd)
    if args.mode == 'status':
        return run_mode(['doctor' if args.doctor else 'status'])
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
