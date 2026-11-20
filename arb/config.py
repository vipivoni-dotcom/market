"""Загрузка config.yaml и настроек, изменённых из Telegram (data/settings.json поверх него)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "data" / "settings.json"


class Config(dict):
    """dict с доступом по пути: cfg.get_path("rules.min_profit_rub")."""

    # Куда set_path сохраняет изменения. None — только в памяти (тесты, разовые утилиты).
    settings_path: Path | None = None

    def get_path(self, path: str, default: Any = None) -> Any:
        node: Any = self
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set_path(self, path: str, value: Any) -> None:
        """Изменить настройку на лету и запомнить её до следующего запуска.

        config.yaml не переписываем: в нём комментарии и токены. Изменения лежат в
        data/settings.json и при загрузке накладываются поверх него.
        """
        _put(self, path, value)
        if not self.settings_path:
            return
        saved = _read_settings(self.settings_path)
        saved[path] = value
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.settings_path)

    def platform(self, name: str) -> dict[str, Any]:
        return (self.get("platforms") or {}).get(name) or {}

    @property
    def dry_run(self) -> bool:
        return bool(self.get_path("mode.dry_run", True))


def _put(node: dict, path: str, value: Any) -> None:
    *parents, last = path.split(".")
    for part in parents:
        node = node.setdefault(part, {})
    node[last] = value


def _read_settings(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def load_config(path: str | Path | None = None, settings: str | Path | None = SETTINGS) -> Config:
    path = Path(path) if path else ROOT / "config.yaml"
    if not path.exists():
        raise SystemExit(
            f"Нет файла {path}. Скопируйте config.example.yaml в config.yaml и заполните."
        )
    with open(path, encoding="utf-8") as f:
        cfg = Config(yaml.safe_load(f) or {})
    from .games import merge_into
    merge_into(cfg)   # игры из covers3d/games.json
    if settings:
        cfg.settings_path = Path(settings)
        for key, value in _read_settings(cfg.settings_path).items():
            _put(cfg, key, value)
    return cfg
