#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def load_json(path_str: str):
    path = Path(path_str)
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: normalize_data.py FILE [FILE ...]"}, ensure_ascii=False))
        return 1

    payload = {"inputs": [], "normalized": True}
    for item in sys.argv[1:]:
        payload["inputs"].append(load_json(item))

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
