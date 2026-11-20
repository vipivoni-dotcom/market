"""PayGame (paygame.ru): биржа цифровых товаров, как FunPay. Только источник цен.

Страница раздела («PlayStation → Баланс» и т.п.) отдаёт список объявлений в JSON-LD:
название, цена, продавец, ссылка. API для покупки нет — покупка вручную.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from ..models import Offer
from .base import Platform, days_since, deliverable, log
from .jsonld import UA, in_stock, ld_blocks

BASE = "https://paygame.ru/games"


class PayGame(Platform):
    name = "paygame"
    can_scan = True

    checks_pay_price = True

    async def pay_price(self, offer: Offer, method: str = "sbp") -> float | None:
        """Цена лота, если продавец заходил недавно. 13.11: лот PSN 1000 INR за 1560 ₽ держал продавец,
        который не был на сайте полтора месяца и не сделал ни одной продажи."""
        async with httpx.AsyncClient(proxy=self.next_scan_proxy(), headers={"User-Agent": UA, "Accept-Language": "ru"},
                                     timeout=20, follow_redirects=True) as client:
            resp = await client.get(offer.url)
            resp.raise_for_status()
        seller = seller_info(resp.text)
        if seller.get("isOnline"):
            import time
            offer.raw["seller_offline_days"] = 0.0
            offer.raw["seller_activity_checked_at"] = time.time()
            return offer.price
        days = days_since(seller.get("lastActive"))
        import time
        offer.raw["seller_activity_checked_at"] = time.time()
        offer.raw["seller_offline_days"] = days
        if self.seller_gone(days):
            offer.raw["reject_reason"] = "seller_offline"
            log.info("paygame: продавец лота %s не заходил %.0f дн. — не беру в поставщики", offer.offer_id, days)
            return None
        return offer.price

    async def scan(self) -> list[Offer]:
        offers: dict[str, Offer] = {}
        failures = 0
        pages = int(self.pcfg.get("pages_per_section", 3))
        async with httpx.AsyncClient(proxy=self.next_scan_proxy(), headers={"User-Agent": UA, "Accept-Language": "ru"}, timeout=30, follow_redirects=True) as client:
            for section, brand in (self.pcfg.get("sections") or {}).items():
                for page in range(1, pages + 1):
                    url = f"{BASE}/{section}" + (f"&page={page}" if page > 1 else "")
                    try:
                        resp = await client.get(url)
                        resp.raise_for_status()
                    except Exception as e:  # noqa: BLE001
                        failures += 1
                        log.warning("paygame: раздел %s не загрузился: %s", section, e)
                        self.note_error(e)
                        break
                    found = self._parse(resp.text, brand)
                    new = [o for o in found if o.offer_id not in offers]
                    offers.update((o.offer_id, o) for o in found)
                    await asyncio.sleep(self.request_delay)
                    if not new:
                        break  # страницы кончились (или сайт отдаёт ту же)
        if failures and not offers:
            raise RuntimeError(f"paygame: каталог недоступен ({failures} ошибок разделов)")
        return list(offers.values())

    def _parse(self, html: str, brand: str) -> list[Offer]:
        result = []
        for block in ld_blocks(html):
            listing = block.get("mainEntity") or {}
            for el in listing.get("itemListElement") or []:
                item = el.get("item") or {}
                o = item.get("offers") or {}
                title = item.get("name") or ""
                product = self.parse(title, brand) if deliverable(title, brand) else None
                if not product or not in_stock(o):
                    continue
                try:
                    price = float(o["price"])
                except (KeyError, TypeError, ValueError):
                    continue
                url = item.get("url") or o.get("url") or ""
                seller = (o.get("seller") or {}).get("name") or ""
                result.append(Offer(
                    platform=self.name,
                    offer_id=url.rstrip("/").rsplit("/", 1)[-1] or title,
                    title=title,
                    price=price,
                    url=url,
                    seller=seller,
                    seller_id=seller,
                    product=product,
                ))
        return result


def seller_info(offer_html: str) -> dict:
    """Продавец со страницы лота: в данных Next.js рядом стоят isOnline и lastActive."""
    m = re.search(r'"isOnline"\s*:\s*(true|false)\s*,\s*"lastActive"\s*:\s*("([^"]*)"|null)', offer_html)
    if not m:
        return {}
    return {"isOnline": m.group(1) == "true", "lastActive": m.group(3)}
