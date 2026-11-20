"""Безопасно меняет только перечисленные несекретные runtime-настройки."""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import tempfile
from pathlib import Path

ALLOWED = {
    "mode.audit_only", "mode.auto_list", "mode.auto_buy", "mode.auto_deliver", "mode.paused",
    "platforms.lzt.enabled", "rules.code_only_products", "rules.allow_uid_topups", "rules.min_markup_pct",
    "rules.supplier_max_offline_days",
}

def value(key: str, text: str):
    low = text.lower()
    if key.startswith("mode.") or key in {"platforms.lzt.enabled", "rules.code_only_products", "rules.allow_uid_topups"}:
        if low not in {"true", "false"}:
            raise ValueError("Ожидается true или false")
        return low == "true"
    number = float(text)
    if not math.isfinite(number) or number < 0:
        raise ValueError("Ожидается конечное неотрицательное число")
    return number

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs", nargs="+", metavar="KEY=VALUE")
    ap.add_argument("--file", default=str(Path(__file__).resolve().parents[1] / "data/settings.json"))
    args = ap.parse_args()
    path = Path(args.file)
    original_stat = path.stat() if path.exists() else None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise SystemExit("Настройки должны быть JSON-объектом")
    for pair in args.pairs:
        key, sep, raw = pair.partition("=")
        if not sep or key not in ALLOWED:
            raise SystemExit(f"Недопустимая настройка: {key}")
        try:
            data[key] = value(key, raw)
        except ValueError:
            raise SystemExit(f"Недопустимый тип или диапазон настройки: {key}") from None
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1, allow_nan=False)
        if original_stat is not None:
            # mkstemp создаёт 0600 текущего пользователя. Служба может работать
            # от другого UID: атомарная замена обязана сохранить её доступ.
            if hasattr(os, "chown"):
                os.chown(name, original_stat.st_uid, original_stat.st_gid)
            os.chmod(name, stat.S_IMODE(original_stat.st_mode))
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    print("Обновлены:", ", ".join(pair.partition("=")[0] for pair in args.pairs))

if __name__ == "__main__":
    main()
