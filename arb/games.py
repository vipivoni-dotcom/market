"""Дополнительные игры с донатом — одна запись на игру в covers3d/games.json.

Из записи берут всё сразу: распознавание объявлений (regex бренда, слова единицы),
раздел Playerok, разделы поставщиков, название и падежи в карточке, цвета и образ дракона
на обложке (страница covers3d читает тот же файл). Ручные настройки config.yaml важнее записи.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FILE = Path(__file__).parent / "covers3d" / "games.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"units": {}, "games": {}}


DATA = _load()
UNITS: dict[str, dict[str, Any]] = DATA.get("units") or {}
GAMES: dict[str, dict[str, Any]] = DATA.get("games") or {}


def unit_aliases() -> dict[str, str]:
    """Слово в объявлении → код единицы: «монет» → COINS."""
    return {alias.lower(): code for code, u in UNITS.items() for alias in u.get("aliases", [])}


def merge_into(cfg: dict) -> None:
    """Дописать игры в конфиг, не трогая то, что задано в config.yaml вручную."""
    def node(*path: str) -> dict:
        cur = cfg
        for p in path:
            if not isinstance(cur.get(p), dict):
                cur[p] = {}
            cur = cur[p]
        return cur

    # Бренды игр — в начало: их regex узкие («Magic Chess … MLBB» — не Mobile Legends)
    own = node("brands")
    extra = {b: g["match"] for b, g in GAMES.items() if g.get("match") and b not in own}
    cfg["brands"] = {**extra, **own}
    for brand, g in GAMES.items():
        if g.get("playerok"):
            node("platforms", "playerok", "categories").setdefault(brand, dict(g["playerok"]))
        if g.get("funpay"):
            node("platforms", "funpay", "sections").setdefault(brand, g["funpay"])
        if g.get("donatov"):
            node("platforms", "donatov", "pages").setdefault(brand, g["donatov"])
        if g.get("starvell"):
            node("platforms", "starvell", "pages").setdefault(brand, g["starvell"])
        for section in g.get("paygame") or []:
            node("platforms", "paygame", "sections").setdefault(section, brand)
