"""Donatov.net: магазин доната и подарочных карт с фиксированными ценами. Только источник цен.

Каждая страница товара (Apple, PSN, UC…) содержит все номиналы с ценами в JSON-LD.
API для покупки нет — покупка вручную по ссылке из уведомления.
"""

from __future__ import annotations

import asyncio
import html as htmllib
import json
import re

import httpx

from ..models import Offer
from ..normalize import SPLIT_REGION_BRANDS
from .base import Platform, log
from .jsonld import UA, in_stock, ld_blocks

BASE = "https://donatov.net"
_RESOURCE_RE = re.compile(r':resource="([^"]*)"')
_TAG_RE = re.compile(r"<[^>]+>")


def pack_groups(page: str) -> dict[str, str]:
    """sku → вкладка страницы («Россия», «Глобал»…). Один номинал во вкладках стоит по-разному."""
    m = _RESOURCE_RE.search(page)
    if not m:
        return {}
    try:
        data = json.loads(htmllib.unescape(m.group(1)))
        names = {g["id"]: _TAG_RE.sub("", g["name"]).strip() for g in data["data"]["pack_groups"]}
        return {f"P{p['id']}": names[p["group"]] for p in data["packs"] if p.get("group") in names}
    except (ValueError, KeyError, TypeError):
        return {}


class Donatov(Platform):
    name = "donatov"
    can_scan = True

    async def scan(self) -> list[Offer]:
        offers: list[Offer] = []
        async with httpx.AsyncClient(proxy=self.next_scan_proxy(), headers={"User-Agent": UA, "Accept-Language": "ru"}, timeout=30, follow_redirects=True) as client:
            for brand, page in (self.pcfg.get("pages") or {}).items():
                url = f"{BASE}/{page}"
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                except Exception as e:  # noqa: BLE001
                    log.warning("donatov: страница %s не загрузилась: %s", page, e)
                    self.note_error(e)
                    continue
                offers.extend(self._parse(resp.text, brand, url))
                await asyncio.sleep(self.request_delay)
        return offers

    def _parse(self, html: str, brand: str, url: str) -> list[Offer]:
        result = []
        groups = pack_groups(html)
        delivery = ""
        resource = _RESOURCE_RE.search(html)
        if resource:
            try:
                data = json.loads(htmllib.unescape(resource.group(1))).get("data", {})
                # Только описание текущего товара, без меню/похожих товаров.
                if data.get("uid_help"):
                    delivery = str(data.get("short_description") or data.get("meta_description") or "")
            except (ValueError, TypeError, AttributeError):
                pass
        if brand in SPLIT_REGION_BRANDS and not groups:
            log.warning("donatov: на странице %s нет вкладок регионов — товары пропущены", url)
            return result
        for block in ld_blocks(html):
            if block.get("@type") != "Product":
                continue
            agg = block.get("offers") or {}
            for o in agg.get("offers") or ([agg] if agg.get("price") else []):
                title = o.get("name") or ""
                group = groups.get(str(o.get("sku")))
                if group:
                    title = f"{title} ({group})"
                product = self.parse(title, brand)
                if not product or not in_stock(o):
                    continue
                if brand in SPLIT_REGION_BRANDS and not product.region:
                    product.region = "OTHER"  # «Другие регионы»: не RU и не Global
                try:
                    price = float(o["price"])
                except (KeyError, TypeError, ValueError):
                    continue
                result.append(Offer(
                    platform=self.name,
                    offer_id=str(o.get("sku") or f"{brand}:{title}"),
                    title=f"{block.get('name', '')}: {title}",
                    price=price,
                    url=url,
                    seller="Donatov.net",
                    seller_id="donatov",
                    auto_delivery=True,
                    product=product,
                    raw={"delivery_method": delivery},
                ))
        return result
