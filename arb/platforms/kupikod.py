"""Kupikod (kupikod.com): магазин с фиксированными ценами. Только источник цен.

Весь каталог (коды Apple/PSN/Google Play, игровая валюта, подписки) отдаётся одним
открытым запросом. API для покупки нет — покупка вручную по ссылке из уведомления.
"""

from __future__ import annotations

import json
import re

import httpx

from ..models import Offer
from .base import Platform, log

WIDGETS_URL = "https://kupikod.com/api/topup/widgets"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
# Разделы без своего slug в API, но со страницей в магазине
SHOP_SLUGS = {"PlayStation Store": "playstation", "Steam": "steam"}


class Kupikod(Platform):
    name = "kupikod"
    can_scan = True

    async def scan(self) -> list[Offer]:
        try:
            async with httpx.AsyncClient(proxy=self.next_scan_proxy(), headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30) as client:
                resp = await client.get(WIDGETS_URL, params={"placement": "brand"})
                resp.raise_for_status()
                widgets = resp.json().get("data") or []
        except Exception as e:  # noqa: BLE001
            log.warning("kupikod: каталог не загрузился: %s", e)
            self.note_error(e)
            return []
        brand_hints = self.pcfg.get("brand_hints") or {}
        skip = set(self.pcfg.get("skip_sections") or ["Steam"])
        offers = []
        for w in widgets:
            section = w.get("name") or ""
            if section in skip:
                continue  # Steam: цена «за 1 ₽», это не товар с номиналом
            slug = w.get("product_slug") or SHOP_SLUGS.get(section)
            url = f"https://kupikod.com/shop/{slug}" if slug else "https://kupikod.com/brand"
            inputs = [i for i in w.get("inputs") or [] if i.get("kind") == "data"]
            input_text = json.dumps(inputs, ensure_ascii=False)
            uid = bool(re.search(r"\bUID\b|Player ID|ID игрока", input_text, re.I))
            login = bool(re.search(r"password|парол|email|e-mail", input_text, re.I))
            for p in w.get("products") or []:
                title = f"{section} {p.get('name') or ''}"
                restrict = " ".join(r.get("text", "") for r in p.get("restricts") or [])
                product = self.parse(f"{title} {restrict}", brand_hints.get(section)) or self.parse(title, brand_hints.get(section))
                if not product or not p.get("price"):
                    continue
                if login:
                    product.login = True
                offers.append(Offer(
                    platform=self.name,
                    offer_id=str(p["id"]),
                    title=title,
                    price=float(p["price"]),
                    url=url,
                    seller="Kupikod",
                    seller_id="kupikod",
                    auto_delivery=True,
                    product=product,
                    raw={"delivery_kind": "id"} if uid and not login else {},
                ))
        return offers
