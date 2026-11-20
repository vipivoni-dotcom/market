"""Eneba (eneba.com): зарубежный маркетплейс ключей и подарочных карт. Только источник цен.

Страница категории («/store/apple-gift-cards») содержит состояние Apollo с товарами и самым
дешёвым предложением по каждому. Регион каталога Eneba выбирает по IP покупателя.
Цены в EUR (в центах) — переводим в рубли по курсу ЦБ. Покупка вручную.
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx

from ..fx import SHARED as FX
from ..models import Offer
from .base import Platform, log
from .jsonld import UA

BASE = "https://www.eneba.com"
_STATE_RE = re.compile(r'id="__APOLLO_STATE__"[^>]*>(.*?)</script>', re.S)


class Eneba(Platform):
    name = "eneba"
    can_scan = True

    async def scan(self) -> list[Offer]:
        await FX.refresh()
        offers: list[Offer] = []
        async with httpx.AsyncClient(proxy=self.next_scan_proxy(), headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=30, follow_redirects=True) as client:
            for brand, slug in (self.pcfg.get("categories") or {}).items():
                try:
                    resp = await client.get(f"{BASE}/store/{slug}")
                    resp.raise_for_status()
                except Exception as e:  # noqa: BLE001
                    log.warning("eneba: категория %s не загрузилась: %s", slug, e)
                    continue
                offers.extend(self._parse(resp.text, brand))
                await asyncio.sleep(self.request_delay)
        return offers

    def _parse(self, html: str, brand: str) -> list[Offer]:
        m = _STATE_RE.search(html)
        if not m:
            return []
        state = json.loads(m.group(1))
        result = []
        for key, prod in state.items():
            if not key.startswith("Product:"):
                continue
            ref = (prod.get("cheapestAuction") or {}).get("__ref")
            auction = state.get(ref) or {}
            if not auction.get("isInStock"):
                continue
            money = auction.get('price({"currency":"EUR"})') or {}
            rub = FX.pay_rub(money.get("amount", 0) / 100, money.get("currency", "EUR"), self.cfg.get_path("fx.usdt_rub"))
            title = prod.get("name") or ""
            product = self.parse(title, brand)
            if not product or not rub:
                continue
            merchant = auction.get("merchant") or {}
            result.append(Offer(
                platform=self.name,
                offer_id=str(auction.get("id") or prod.get("slug")),
                title=title,
                price=round(rub, 2),
                url=f"{BASE}/{prod.get('slug', '')}",
                seller=merchant.get("displayname") or "",
                seller_id=merchant.get("slug") or "",
                auto_delivery=True,
                product=product,
                raw={"eur": money.get("amount", 0) / 100},
            ))
        return result
