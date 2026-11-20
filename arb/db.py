"""SQLite-хранилище: объявления, связки, наши карточки, заказы."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import ROOT
from .models import Offer, Opportunity

OFFERS_KEEP_SEC = 3 * 86400

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    platform TEXT, offer_id TEXT, key TEXT, title TEXT, price REAL, url TEXT,
    seller TEXT, seller_id TEXT, seller_rating REAL, auto_delivery INTEGER,
    seen_at REAL, PRIMARY KEY (platform, offer_id)
);
CREATE INDEX IF NOT EXISTS offers_key ON offers(key);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT, sell_platform TEXT,
    buy_platform TEXT, buy_offer_id TEXT, buy_title TEXT, buy_url TEXT, buy_price REAL,
    sell_price REAL, profit REAL, margin_pct REAL, competitors INTEGER, best_competitor REAL,
    status TEXT DEFAULT 'new',      -- new / listed / skipped / stale
    updated_at REAL,
    UNIQUE (key, sell_platform)
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER, platform TEXT, external_id TEXT, key TEXT,
    title TEXT, price REAL, status TEXT,   -- active / paused / dry_run
    created_at REAL, updated_at REAL
);

-- Неизвестный исход внешнего создания нельзя безопасно повторять после перезапуска.
CREATE TABLE IF NOT EXISTS listing_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL, key TEXT NOT NULL, title TEXT NOT NULL,
    price REAL NOT NULL, status TEXT NOT NULL,
    external_id TEXT, error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS listing_attempts_unresolved
    ON listing_attempts(platform, key) WHERE status IN ('in_progress', 'unknown');

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT, external_id TEXT, listing_id INTEGER, key TEXT,
    buyer TEXT, chat_id TEXT, price REAL,
    source_platform TEXT, source_url TEXT, source_offer_id TEXT, source_price REAL,
    purchase_ref TEXT,
    status TEXT,   -- new / buying / bought / attention / delivering / delivery_unknown / delivered / failed
    note TEXT, supplier_text TEXT, created_at REAL, updated_at REAL,
    UNIQUE (platform, external_id)
);

CREATE TABLE IF NOT EXISTS price_checks (
    platform TEXT, key TEXT, attempted_at REAL NOT NULL DEFAULT 0,
    checked_at REAL NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (platform, key)
);
CREATE TABLE IF NOT EXISTS platform_cooldowns (platform TEXT PRIMARY KEY, until_at REAL NOT NULL);
"""


class DB:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else ROOT / "data" / "arb.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(orders)")}
            if "supplier_text" not in columns:
                self._conn.execute("ALTER TABLE orders ADD COLUMN supplier_text TEXT")
                self._conn.commit()
            if "buyer_data" not in columns:  # что покупатель написал в чате сделки: ID игрока, ник
                self._conn.execute("ALTER TABLE orders ADD COLUMN buyer_data TEXT")
                self._conn.commit()

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # --- offers -----------------------------------------------------------

    def save_offers(self, offers: list[Offer]) -> None:
        now = time.time()
        rows = [
            (o.platform, o.offer_id, o.key, o.title, o.price, o.url, o.seller, o.seller_id,
             o.seller_rating, int(o.auto_delivery), now)
            for o in offers
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO offers VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
            )
            # Объявления, которых давно нет ни в одном скане, никому не нужны: без этого база росла бесконечно.
            self._conn.execute("DELETE FROM offers WHERE seen_at < ?", (now - OFFERS_KEEP_SEC,))
            self._conn.commit()

    # --- opportunities ----------------------------------------------------

    def upsert_opportunity(self, op: Opportunity) -> int:
        self.execute(
            """INSERT INTO opportunities (key, sell_platform, buy_platform, buy_offer_id, buy_title,
                   buy_url, buy_price, sell_price, profit, margin_pct, competitors, best_competitor,
                   status, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'new', ?)
               ON CONFLICT(key, sell_platform) DO UPDATE SET
                   buy_platform=excluded.buy_platform, buy_offer_id=excluded.buy_offer_id,
                   buy_title=excluded.buy_title, buy_url=excluded.buy_url,
                   buy_price=excluded.buy_price, sell_price=excluded.sell_price,
                   profit=excluded.profit, margin_pct=excluded.margin_pct,
                   competitors=excluded.competitors, best_competitor=excluded.best_competitor,
                   status=CASE WHEN status='stale' THEN 'new' ELSE status END,
                   updated_at=excluded.updated_at""",
            (op.key, op.sell_platform, op.buy.platform, op.buy.offer_id, op.buy.title, op.buy.url,
             op.buy.price, op.sell_price, op.profit, op.margin_pct, op.competitors,
             op.best_competitor_price, time.time()),
        )
        row = self.one(
            "SELECT id FROM opportunities WHERE key=? AND sell_platform=?", (op.key, op.sell_platform)
        )
        return int(row["id"])

    def set_opportunity_status(self, op_id: int, status: str) -> None:
        self.execute(
            "UPDATE opportunities SET status=?, updated_at=? WHERE id=?", (status, time.time(), op_id)
        )

def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
