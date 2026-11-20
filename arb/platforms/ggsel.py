"""GGSel: API продавца (seller.ggsel.com, по схеме Digiseller).

Каталог ggsel.net закрыт защитой Qrator, поэтому сканирования цен здесь нет.
Модуль умеет принимать продажи и писать покупателю в чат заказа.

ВНИМАНИЕ: пути ниже взяты по аналогии с API Digiseller — публичная документация
GGSel (seller.ggsel.com/docs) на момент написания не открывалась. Сверьте их в
кабинете продавца перед включением (platforms.ggsel.enabled).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

import httpx

from ..config import ROOT
from .base import MessageHandler, Platform, Sale, SaleHandler, log

BASE = "https://seller.ggsel.com/api_sellers/api"
SEEN_FILE = ROOT / "data" / "ggsel_seen.json"


class GGSel(Platform):
    name = "ggsel"

    def __init__(self, cfg, normalizer) -> None:
        super().__init__(cfg, normalizer)
        self._token: str | None = None
        self._token_until = 0.0
        self._seen: set[str] = set()

    async def _auth(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token_until:
            return self._token
        ts = str(int(time.time()))
        sign = hashlib.sha256((self.pcfg["api_key"] + ts).encode()).hexdigest()
        resp = await client.post(f"{BASE}/apilogin",
                                 json={"seller_id": int(self.pcfg["seller_id"]), "timestamp": ts, "sign": sign})
        resp.raise_for_status()
        data = resp.json()
        self._token = data["token"]
        self._token_until = time.time() + 60 * 50
        return self._token

    async def scan(self):
        return []

    async def deliver(self, chat_id: str | None, order_id: str, buyer: str, text: str) -> None:
        async with httpx.AsyncClient(proxy=self.proxy, timeout=30) as client:
            token = await self._auth(client)
            resp = await client.post(f"{BASE}/debates/v2", params={"token": token, "id_i": order_id},
                                     json={"message": text})
            resp.raise_for_status()

    # Какие продажи уже обработаны — в файле, а не в памяти: продажа, пришедшая пока бот был выключен,
    # обработается после запуска, а старые не задублируются.
    def _load_seen(self) -> bool:
        try:
            self._seen = set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
            return True
        except (OSError, ValueError):
            return False

    def _save_seen(self) -> None:
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SEEN_FILE.write_text(json.dumps(sorted(self._seen)[-2000:]), encoding="utf-8")

    async def poll_sales(self, on_sale: SaleHandler, first_run: bool) -> None:
        async with httpx.AsyncClient(proxy=self.proxy, timeout=30) as client:
            token = await self._auth(client)
            resp = await client.get(f"{BASE}/seller-last-sales",
                                    params={"token": token, "seller_id": self.pcfg["seller_id"], "top": 50})
            resp.raise_for_status()
            sales = resp.json().get("sales") or []
        fresh = []
        for s in sales:
            inv = str(s.get("invoice_id"))
            if inv not in self._seen:
                self._seen.add(inv)
                fresh.append(s)
        self._save_seen()
        if first_run:
            return  # самый первый запуск: история продаж до бота — не наши заказы
        for s in reversed(fresh):  # от старых к новым
            product = s.get("product") or {}
            await on_sale(Sale(self.name, str(s.get("invoice_id")), str(product.get("id") or ""),
                               product.get("name") or "", s.get("email") or "", str(s.get("invoice_id")),
                               float(s.get("amount_in") or 0)))

    async def listen(self, on_sale: SaleHandler, on_message: MessageHandler) -> None:
        if not (self.pcfg.get("seller_id") and self.pcfg.get("api_key")):
            return
        if not str(self.pcfg["seller_id"]).strip().isdigit():
            log.warning("ggsel: seller_id должен быть числовым ID продавца, а не ником — продажи GGSel не принимаю")
            return
        first_run = not self._load_seen()
        while True:
            try:
                await self.poll_sales(on_sale, first_run)
                first_run = False
            except Exception as e:  # noqa: BLE001
                log.warning("ggsel: опрос продаж не удался: %s", e)
                self.note_error(e)
            await asyncio.sleep(30 * self.slowdown)
