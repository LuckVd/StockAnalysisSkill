#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET = SCRIPT_DIR / 'fetch_news.sh'

args = sys.argv[1:]
if len(args) >= 2:
    symbol = args[0]
    name = ' '.join(args[1:]).strip()
    if name:
        args = [f'{symbol}::{name}']
result = subprocess.run(['bash', str(TARGET), *args])
raise SystemExit(result.returncode)
