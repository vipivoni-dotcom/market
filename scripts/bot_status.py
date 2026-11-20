"""Состояние бота без запуска, записи в БД и вывода секретов из настроек/логов."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arb.config import load_config

FIELDS = (
    'mode.audit_only', 'mode.auto_list', 'mode.auto_buy', 'mode.auto_deliver',
    'mode.paused', 'mode.dry_run', 'rules.code_only_products', 'rules.allow_uid_topups', 'rules.skip_login_products',
    'rules.max_active_listings', 'rules.min_markup_pct',
)


def snapshot(root: Path = ROOT) -> dict:
    cfg = load_config(root / 'config.yaml', root / 'data/settings.json')
    now = time.time()
    result = {'at_utc': datetime.now(timezone.utc).isoformat(),
              'settings': {k: cfg.get_path(k) for k in FIELDS}}
    base = load_config(root / 'config.yaml', settings=None)
    saved_path = root / 'data/settings.json'
    saved = json.loads(saved_path.read_text(encoding='utf-8')) if saved_path.exists() else {}
    if not isinstance(saved, dict):
        saved = {}
    result['settings_sources'] = {k: {
        'yaml': base.get_path(k),
        'effective_source': 'data/settings.json' if k in saved else 'config.yaml',
    } for k in FIELDS}
    result['settings_overrides'] = [k for k in FIELDS
                                    if k in saved and base.get_path(k) != cfg.get_path(k)]
    db = sqlite3.connect((root / 'data/arb.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result['missing_tables'] = sorted({'listings', 'opportunities', 'platform_cooldowns'} - tables)
        for table in ('listings', 'opportunities'):
            result[table] = (dict(db.execute(f'SELECT status,count(*) FROM {table} GROUP BY status'))
                             if table in tables else None)
        result['fresh_new_candidates'] = (db.execute(
            "SELECT count(*) FROM opportunities WHERE status='new' AND updated_at>=?",
            (now - 600,)).fetchone()[0] if 'opportunities' in tables else None)
        result['cooldown_seconds'] = ({p: max(0, round(t - now)) for p, t in db.execute(
            'SELECT platform,until_at FROM platform_cooldowns')}
            if 'platform_cooldowns' in tables else None)
    finally:
        db.close()
    try:
        blocked = json.loads((root / 'data/list_blocked.json').read_text(encoding='utf-8'))
        result['blocked_products'] = sum(float(t) > now for t in blocked.values())
    except (OSError, ValueError, AttributeError, TypeError):
        result['blocked_products'] = None
    try:
        with (root / 'data/cycle-audit.jsonl').open(encoding='utf-8') as f:
            recent = deque(f, maxlen=5)
        for line in reversed(recent):
            try:
                audit = json.loads(line)
            except ValueError:  # последний цикл мог ещё дописывать строку
                continue
            result['last_cycle'] = {k: audit[k] for k in (
                'at', 'duration_sec', 'audit_only', 'offers', 'opportunities', 'filtered', 'publication',
                'filtered_by_game', 'supplier_checks', 'opportunities_by_game') if k in audit}
            result['cycle_age_seconds'] = round(now - audit['at'])
            result['coverage'] = {p: {'offers': v['offers'], 'games': len(v['games']),
                                      'missing_categories': len(v['missing_configured'])}
                                  for p, v in audit.get('platforms', {}).items()}
            break
    except OSError:
        pass
    return result


if __name__ == '__main__':
    print(json.dumps(snapshot(), ensure_ascii=True, indent=2))
