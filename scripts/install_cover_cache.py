"""Установить заранее отрисованные PNG, не заменяя существующие обложки."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def install(archive: Path, out: Path) -> dict:
    checked = {}
    total = 0
    with tarfile.open(archive, 'r:gz') as package:
        for entry in package:
            if not entry.isfile() or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*\.png', entry.name):
                raise ValueError('archive must contain only PNG basenames')
            total += entry.size
            if entry.size > 10 * 1024 * 1024 or total > 256 * 1024 * 1024 or len(checked) >= 500:
                raise ValueError('cover archive exceeds batch limits')
            data = package.extractfile(entry).read()
            with Image.open(io.BytesIO(data)) as img:
                if img.format != 'PNG' or img.size != (1200, 900):
                    raise ValueError('cover must be a 1200x900 PNG')
                img.load()
            checked[entry.name] = data
    out.mkdir(parents=True, exist_ok=True)
    result = {'added': 0, 'existing': 0, 'files': []}
    for name, data in checked.items():
        with tempfile.NamedTemporaryFile(dir=out, prefix='.cover-', suffix='.tmp', delete=False) as stream:
            staging = Path(stream.name)
            stream.write(data)
        try:
            staging.chmod(0o644)
            # Публикуем готовый файл атомарно; даже при гонке существующий не заменяем.
            try:
                os.link(staging, out / name)
                status = 'added'
            except FileExistsError:
                status = 'existing'
            result[status] += 1
            result['files'].append({'name': name, 'status': status,
                                    'sha256': hashlib.sha256((out / name).read_bytes()).hexdigest()})
        finally:
            staging.unlink(missing_ok=True)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('archive', type=Path)
    ap.add_argument('--out', type=Path, default=ROOT / 'data/cards_v2')
    args = ap.parse_args()
    print(json.dumps(install(args.archive, args.out), ensure_ascii=True))


if __name__ == '__main__':
    main()
