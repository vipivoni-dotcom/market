"""Read-only контроль публикации: агрегаты БД и необязательные GET Playerok."""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from collections import Counter, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def report(live: bool = False, since: float = 0) -> dict:
    db = sqlite3.connect((ROOT / 'data/arb.sqlite').as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        result = {'listings': dict(db.execute('SELECT status,count(*) FROM listings GROUP BY status')),
                  'attempts': dict(db.execute('SELECT status,count(*) FROM listing_attempts GROUP BY status')),
                  'unresolved_with_id': db.execute("SELECT count(*) FROM listing_attempts WHERE "
                       "status IN ('in_progress','unknown') AND external_id IS NOT NULL").fetchone()[0]}
        new = [dict(r) for r in db.execute("SELECT key,external_id,price FROM listings WHERE created_at>=? "
                                          "AND status='active' ORDER BY id DESC LIMIT 50", (since,))]
    finally:
        db.close()
    for line in reversed(deque((ROOT / 'data/cycle-audit.jsonl').open(encoding='utf-8'), maxlen=5)):
        try:
            audit = json.loads(line)
        except ValueError:
            continue
        result['last_cycle'] = {k: audit.get(k) for k in ('at','duration_sec','offers','opportunities','publication')}
        break
    if live:
        from arb.config import load_config
        from arb.platforms import build_platforms
        cfg = load_config(ROOT / 'config.yaml', ROOT / 'data/settings.json')
        p = build_platforms(cfg)['playerok']
        p.my_id = (await p.acc.get_me()).id
        items = await p.own_listings()
        result['live_storefront_count'] = len(items)
        result['live_duplicate_keys'] = {k: n for k, n in Counter(i.key for i in items if i.key).items() if n > 1}
        result['live_recent'] = []
        for row in new:
            item = await p.acc.items.get(item_id=row['external_id'])
            result['live_recent'].append({'key': row['key'], 'price': float(item.price),
                'status': str(getattr(item.status, 'value', item.status))})
            await asyncio.sleep(p.request_delay)
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--since', type=float, default=0)
    args = ap.parse_args()
    try:
        print(json.dumps(asyncio.run(report(args.live, args.since)), ensure_ascii=True, indent=2))
    except Exception as error:
        print(json.dumps({'error_class': type(error).__name__}))
        raise SystemExit(1)
