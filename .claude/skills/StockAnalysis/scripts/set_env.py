#!/usr/bin/env python3
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / '.env'
ENV_EXAMPLE = ROOT / '.env.example'


def ensure_env() -> None:
    if ENV_FILE.exists():
        return
    if ENV_EXAMPLE.exists():
        ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding='utf-8'), encoding='utf-8')
        return
    ENV_FILE.write_text('', encoding='utf-8')


def upsert(lines, key, value):
    prefix = f'{key}='
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            lines[idx] = f'{key}={value}'
            return lines, 'updated'
    lines.append(f'{key}={value}')
    return lines, 'added'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--set', dest='pairs', action='append', required=True, help='KEY=VALUE')
    args = parser.parse_args()

    ensure_env()
    lines = ENV_FILE.read_text(encoding='utf-8').splitlines()
    actions = []
    for pair in args.pairs:
        if '=' not in pair:
            raise SystemExit(f'invalid --set value: {pair}')
        key, value = pair.split('=', 1)
        key = key.strip()
        if not key:
            raise SystemExit(f'invalid key in --set value: {pair}')
        lines, action = upsert(lines, key, value)
        actions.append({'key': key, 'action': action})
    ENV_FILE.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    for item in actions:
        print(f"{item['action']}: {item['key']}")
    print(str(ENV_FILE))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
