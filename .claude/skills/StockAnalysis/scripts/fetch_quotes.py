#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET = SCRIPT_DIR / 'fetch_quotes.sh'

result = subprocess.run(['bash', str(TARGET), *sys.argv[1:]])
raise SystemExit(result.returncode)
