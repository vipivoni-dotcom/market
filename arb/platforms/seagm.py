"""SEAGM (seagm.com): зарубежный магазин подарочных карт и пополнений. Только источник цен.

Обзорные страницы («/landing/itunes-gift-card») ссылаются на страницы товаров по регионам
(«/apple-gift-card-us»), а на странице товара в коде есть список номиналов с ценами
(prodectBuyList — так у них и написано). Валюту цены SEAGM выбирает по IP; переводим в рубли.
Покупка вручную.
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

BASE = "https://www.seagm.com"
_LIST_RE = re.compile(r"prodectBuyList:\s*(\[.*?\])\s*[,}]", re.S)
_LINK_RE = re.compile(r'href="(?:https://www\.seagm\.com)?/([a-z0-9\-]{5,80})"')


class SEAGM(Platform):
    name = "seagm"
    can_scan = True

    async def scan(self) -> list[Offer]:
        await FX.refresh()
        offers: list[Offer] = []
        async with httpx.AsyncClient(proxy=self.next_scan_proxy(), headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=30, follow_redirects=True) as client:
            for landing, spec in (self.pcfg.get("landings") or {}).items():
                brand, pattern = spec["brand"], re.compile(spec["pages"])
                try:
                    html = (await client.get(f"{BASE}/landing/{landing}")).text
                except Exception as e:  # noqa: BLE001
                    log.warning("seagm: обзор %s не загрузился: %s", landing, e)
                    continue
                pages = sorted({p for p in _LINK_RE.findall(html) if pattern.search(p)})
                for page in pages[: int(self.pcfg.get("max_pages_per_landing", 25))]:
                    await asyncio.sleep(self.request_delay)
                    try:
                        resp = await client.get(f"{BASE}/{page}")
                        resp.raise_for_status()
                    except Exception as e:  # noqa: BLE001
                        log.warning("seagm: страница %s не загрузилась: %s", page, e)
                        continue
                    offers.extend(self._parse(resp.text, brand, f"{BASE}/{page}"))
        return offers

    def _parse(self, html: str, brand: str, url: str) -> list[Offer]:
        m = _LIST_RE.search(html)
        if not m:
            return []
        try:
            items = json.loads(m.group(1))
        except ValueError:
            return []
        result = []
        for it in items:
            if it.get("item_variant") and it["item_variant"] != "Available":
                continue
            title = it.get("item_name") or ""
            rub = FX.pay_rub(float(it.get("price") or 0), it.get("currency") or "", self.cfg.get_path("fx.usdt_rub"))
            product = self.parse(title, brand)
            if not product or not rub:
                continue
            result.append(Offer(
                platform=self.name, offer_id=str(it.get("item_id") or title), title=title, price=round(rub, 2),
                url=url, seller="SEAGM", seller_id="seagm", auto_delivery=True, product=product,
                raw={"price": it.get("price"), "currency": it.get("currency")},
            ))
        return result
