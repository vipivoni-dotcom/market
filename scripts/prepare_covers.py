"""Пакетный локальный рендер кэша. Не запускает бота и не обращается к площадкам."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arb.covers import render_cover
from arb.models import ProductKey
from arb.platforms.playerok import find_cover

KEY = re.compile(r"([a-z][a-z0-9_]*(?:-[a-z0-9_]+)?):(\d+(?:\.\d+)?)([A-Z]+)(?:@([A-Z0-9_]+))?\Z")


def product_from_key(key: str) -> ProductKey | None:
    match = KEY.fullmatch(key)
    if not match:
        return None
    brand, amount, currency, region = match.groups()
    amount = float(amount)
    if not math.isfinite(amount) or amount <= 0:
        return None
    return ProductKey(brand, amount, currency, region=region)


def catalog_keys(path: Path, max_age_minutes: float = 30) -> list[str]:
    cutoff = time.time() - max_age_minutes * 60
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=15)
    try:
        candidates = [r[0] for r in conn.execute(
            "SELECT key FROM opportunities WHERE status='new' AND updated_at>=? ORDER BY profit DESC", (cutoff,))]
        candidates += [r[0] for r in conn.execute(
            'SELECT key FROM offers WHERE seen_at>=? AND key IS NOT NULL GROUP BY key ORDER BY count(*) DESC,key', (cutoff,))]
        return list(dict.fromkeys(candidates))
    finally:
        conn.close()


async def prepare(keys: list[str], out: Path, *, browser: str | None = None,
                  limit: int = 30, timeout: float = 120) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {'cached': 0, 'rendered': 0, 'failed': 0, 'invalid': 0, 'items': []}
    attempted = 0
    for key in dict.fromkeys(keys):
        product = product_from_key(key)
        if product is None:
            report['invalid'] += 1
            continue
        path = find_cover(out, product, require_style=True)
        if path:
            report['cached'] += 1
            report['items'].append({'key': key, 'status': 'cached', 'file': path.name})
            continue
        if attempted >= limit:
            continue
        attempted += 1
        item_started = time.monotonic()
        try:
            await render_cover(key, out, browser, timeout=timeout, parallel=1)
            path = find_cover(out, product, require_style=True)
            if path is None:
                raise RuntimeError('rendered file does not match product key')
            report['rendered'] += 1
            item = {'key': key, 'status': 'rendered', 'file': path.name}
        except Exception as error:
            report['failed'] += 1
            item = {'key': key, 'status': 'failed', 'error_class': type(error).__name__}
        item['seconds'] = round(time.monotonic() - item_started, 2)
        report['items'].append(item)
        print(json.dumps(item, ensure_ascii=True), flush=True)
    report['seconds'] = round(time.monotonic() - started, 2)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--key', action='append', default=[])
    ap.add_argument('--keys-file', type=Path, help='JSON array of product keys')
    ap.add_argument('--db', type=Path, default=ROOT / 'data/arb.sqlite')
    ap.add_argument('--max-age-minutes', type=float, default=30)
    ap.add_argument('--out', type=Path, default=ROOT / 'data/cards_v2')
    ap.add_argument('--browser')
    ap.add_argument('--limit', type=int, default=30)
    ap.add_argument('--timeout', type=float, default=120)
    ap.add_argument('--manifest', type=Path)
    args = ap.parse_args()
    if args.limit < 1 or not math.isfinite(args.timeout) or args.timeout <= 0 \
            or not math.isfinite(args.max_age_minutes) or args.max_age_minutes <= 0:
        ap.error('limit, timeout and max-age-minutes must be positive finite values')
    keys = args.key
    if args.keys_file:
        supplied = json.loads(args.keys_file.read_text(encoding='utf-8-sig'))
        if not isinstance(supplied, list) or not all(isinstance(k, str) for k in supplied):
            ap.error('keys-file must contain a JSON array of strings')
        keys += supplied
    if not keys:
        keys = catalog_keys(args.db, args.max_age_minutes)
    report = asyncio.run(prepare(keys, args.out, browser=args.browser, limit=args.limit, timeout=args.timeout))
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'items'}), flush=True)
    return 1 if report['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
