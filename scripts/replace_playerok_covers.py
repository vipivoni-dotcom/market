"""Разовая согласованная замена обложек. По умолчанию только план без сети.

Журнал сохраняется до записи в API: после неизвестного результата повторный
запуск только сверяет вложения и не повторяет update. БД бота не изменяется.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arb.platforms.playerok import find_cover
from scripts.prepare_covers import product_from_key
from PlayerokAPI.transport import Upload


def save_journal(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     delete=False) as stream:
        staging = Path(stream.name)
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        staging.chmod(0o600)
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def attachment_ids(item) -> list[str]:
    return [a.id for a in item.attachments]


async def cover_matches(item, cover: Path) -> bool:
    """Playerok перекодирует PNG в JPEG: проверяем размер и малую ошибку пикселей."""
    import httpx
    from PIL import Image, ImageChops, ImageStat
    if not item.attachments or not getattr(item.attachments[0], 'url', None):
        return False
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(item.attachments[0].url)
    if response.status_code != 200 or len(response.content) > 10 * 1024 * 1024:
        return False
    with Image.open(io.BytesIO(response.content)) as actual, Image.open(cover) as expected:
        if actual.size != expected.size or actual.size != (1200, 900):
            return False
        diff = ImageStat.Stat(ImageChops.difference(actual.convert('RGB'), expected.convert('RGB')))
        return max(diff.mean) < 3 and max(diff.rms) < 10


async def observe_new_cover(item, cover: Path, old: dict) -> bool:
    ids, previous = attachment_ids(item), old['previous_ids']
    if (len(ids) != max(1, len(previous)) or set(previous[:1]) & set(ids)
            or not set(previous[1:]) <= set(ids)):
        return False
    if await cover_matches(item, cover):
        old['target_ids'] = ids
        old['verification'] = 'jpeg_pixel_match'
        return True
    return False


async def replace_one(acc, item_id: str, key: str, cover: Path, owner_id: str,
                      journal: dict, journal_path: Path, *, reconcile_unchanged=False) -> dict:
    digest = hashlib.sha256(cover.read_bytes()).hexdigest()
    item = await acc.items.get(item_id=item_id)
    if not item.user or item.user.id != owner_id:
        raise RuntimeError('item owner mismatch')
    old = journal.get(item_id)
    if old:
        if old['sha256'] != digest:
            return {'key': key, 'result': 'different_cover_requires_review'}
        if old.get('target_ids') and attachment_ids(item) == old['target_ids']:
            old['state'] = 'confirmed'
            save_journal(journal_path, journal)
            return {'key': key, 'result': 'confirmed', 'status': str(item.status)}
        if await observe_new_cover(item, cover, old):
            old['state'] = 'confirmed'
            save_journal(journal_path, journal)
            return {'key': key, 'result': 'confirmed', 'status': str(item.status)}
        if old['state'] in ('updating', 'unknown', 'confirmed'):
            if not (reconcile_unchanged and old['state'] == 'unknown'
                    and attachment_ids(item) == old['previous_ids']):
                return {'key': key, 'result': 'unknown_requires_review'}
    status = getattr(item.status, 'value', item.status)
    if status != 'APPROVED':
        return {'key': key, 'result': 'skip_status', 'status': str(status)}
    if not old:
        old = journal[item_id] = {'key': key, 'sha256': digest, 'state': 'prepared',
                                 'previous_ids': attachment_ids(item), 'target_ids': None}
        save_journal(journal_path, journal)
    old['state'] = 'updating'
    save_journal(journal_path, journal)
    try:
        # Файловый сервис на Playerok выключен: используем штатный multipart,
        # как форма сайта при fileServiceEnabled=false.
        updated = await acc.items.update(item_id, {'removedAttachments': old['previous_ids'][:1]},
                                         added_attachments=[Upload(cover.read_bytes(), cover.name, 'image/png')])
        ids = attachment_ids(updated)
        previous = old['previous_ids']
        if len(ids) == max(1, len(previous)) and not (set(previous[:1]) & set(ids)) and set(previous[1:]) <= set(ids):
            old['target_ids'] = ids
            save_journal(journal_path, journal)
    except Exception as exc:
        # Ответ с ошибкой не доказывает отсутствие внешней записи.
        old['state'] = 'unknown'
        old['error_class'] = type(exc).__name__
        save_journal(journal_path, journal)
    # Новые вложения видны в чтении с задержкой. Повторяем только GET, не update.
    for attempt in range(4):
        item = await acc.items.get(item_id=item_id)
        if ((old.get('target_ids') and attachment_ids(item) == old['target_ids'])
                or await observe_new_cover(item, cover, old)):
            old['state'] = 'confirmed'
            save_journal(journal_path, journal)
            return {'key': key, 'result': 'confirmed', 'status': str(item.status)}
        if attempt < 3:
            await asyncio.sleep(2)
    old['state'] = 'unknown'
    save_journal(journal_path, journal)
    return {'key': key, 'result': 'unknown_requires_review'}


async def main(args):
    conn = sqlite3.connect((ROOT / 'data/arb.sqlite').as_uri() + '?mode=ro', uri=True)
    try:
        rows = conn.execute("SELECT key,external_id FROM listings WHERE platform='playerok' AND status='active'").fetchall()
    finally:
        conn.close()
    plan, missing = [], []
    requested = set(json.loads(args.keys_file.read_text(encoding='utf-8-sig'))) if args.keys_file else None
    for key, item_id in rows:
        if requested is not None and key not in requested:
            continue
        product = product_from_key(key)
        cover = find_cover(args.covers, product, require_style=True) if product else None
        if cover is None:
            missing.append(key)
        else:
            plan.append((item_id, key, cover))
    print(json.dumps({'ready': len(plan), 'missing': missing, 'apply': args.apply}), flush=True)
    if missing or not args.apply:
        return 1 if missing else 0
    args.journal.parent.mkdir(parents=True, exist_ok=True)
    # Отдельный inode: атомарная замена JSON не должна отпускать блокировку.
    lock = args.journal.with_suffix('.lock').open('a+b')
    if os.name == 'posix':
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    from arb.config import load_config
    from PlayerokAPI import Account
    cfg = load_config(ROOT / 'config.yaml', ROOT / 'data/settings.json')
    journal = json.loads(args.journal.read_text(encoding='utf-8')) if args.journal.exists() else {}
    acc = Account(cfg.get_path('platforms.playerok.token'), timeout=60, retries=0)
    try:
        owner = await acc.get_me()
        for item_id, key, cover in plan:
            try:
                result = await replace_one(acc, item_id, key, cover, owner.id, journal, args.journal,
                                           reconcile_unchanged=args.reconcile_unchanged)
            except Exception as exc:
                print(json.dumps({'key': key, 'result': 'stopped', 'error_class': type(exc).__name__}), flush=True)
                return 1
            print(json.dumps(result), flush=True)
            if result['result'] not in ('confirmed', 'skip_status'):
                return 1
            await asyncio.sleep(5)
    finally:
        await acc.aclose()
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--covers', type=Path, default=ROOT / 'data/cards_v2')
    ap.add_argument('--journal', type=Path, default=ROOT / 'data/cover-replacements.json')
    ap.add_argument('--keys-file', type=Path, help='Ограничить замену согласованным снимком ключей')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--reconcile-unchanged', action='store_true',
                    help='После отдельной сверки разрешить исправленную запись, только если вложения прежние')
    raise SystemExit(asyncio.run(main(ap.parse_args())))
