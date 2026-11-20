"""Starvell: цены берём из открытого каталога. Только источник цен.

Раздел читается запросом каталога (POST /api/catalog/list-category-offers): он отдаёт все объявления
раздела по 150 штук, по возрастанию цены. Страница раздела показывает только первые 100 и только одну
вкладку (у Discord — «Nitro Full», у Steam — «По логину»), поэтому раньше бот видел около половины
объявлений. Со страницы берём лишь id раздела и названия его фильтров — один раз за запуск.
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx

from ..models import Offer, ProductKey
from .base import Platform, days_since, deliverable, log

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
BASE = "https://starvell.com"
PAGE_SIZE = 150  # больше каталог не отдаёт («limit must not be greater than 150»)


class Starvell(Platform):
    name = "starvell"
    can_scan = True

    def __init__(self, cfg, normalizer) -> None:
        super().__init__(cfg, normalizer)
        self._category_ids: dict[str, int] = {}  # страница раздела → id раздела
        self._options: dict[str, str] = {}       # id варианта фильтра → название («Пополнение по ID»)

    async def scan(self) -> list[Offer]:
        result: dict[str, Offer] = {}
        pages: dict[str, list[dict]] = {}
        async with httpx.AsyncClient(proxy=self.next_scan_proxy(), headers={"User-Agent": UA}, timeout=30,
                                     follow_redirects=True) as client:
            for brand, page in (self.pcfg.get("pages") or {}).items():
                try:
                    if page not in pages:
                        pages[page] = await self._category_offers(client, page)
                    raw_offers = pages[page]
                except Exception as e:  # noqa: BLE001
                    log.warning("starvell: раздел %s не прочитался: %s", page, e)
                    self.note_error(e)
                    continue
                for o in raw_offers:
                    offer = self._offer(o, brand)
                    if offer:
                        result[offer.offer_id] = offer
                await asyncio.sleep(self.request_delay)
        return list(result.values())

    async def _category_offers(self, client: httpx.AsyncClient, page: str) -> list[dict]:
        """Все объявления раздела: каталогом, а если он не ответил — первые 100 со страницы, как раньше."""
        from_page: list[dict] | None = None
        if page not in self._category_ids:
            from_page = await self._page_offers(client, page)
            await asyncio.sleep(self.request_delay)
        category_id = self._category_ids.get(page)
        if category_id is None:
            return from_page or []
        try:
            return await self._catalog_offers(client, category_id)
        except Exception as e:  # noqa: BLE001
            log.info("starvell: каталог раздела %s не ответил (%s), читаю страницу", page, e)
            self.note_error(e)
            return from_page if from_page is not None else await self._page_offers(client, page)

    async def _page_offers(self, client: httpx.AsyncClient, page: str) -> list[dict]:
        resp = await client.get(f"{BASE}/{page}")
        resp.raise_for_status()
        props = json.loads(NEXT_DATA.search(resp.text).group(1))["props"]["pageProps"]
        category = props.get("category") or {}
        if category.get("id") is not None:
            self._category_ids[page] = int(category["id"])
        self._remember_options(category)
        for sub in category.get("subCategories") or []:
            self._remember_options(sub)
        return props.get("offers") or []

    async def _catalog_offers(self, client: httpx.AsyncClient, category_id: int) -> list[dict]:
        offers: list[dict] = []
        for n in range(int(self.pcfg.get("catalog_pages", 10))):
            resp = await client.post(f"{BASE}/api/catalog/list-category-offers",
                                     json={"categoryId": category_id, "limit": PAGE_SIZE, "offset": n * PAGE_SIZE})
            resp.raise_for_status()
            chunk = resp.json().get("offers") or []
            offers.extend(chunk)
            if len(chunk) < PAGE_SIZE:
                break
            await asyncio.sleep(self.request_delay)
        return offers

    def _remember_options(self, node: dict) -> None:
        for flt in node.get("filters") or []:
            for option in flt.get("options") or []:
                if option.get("id") and option.get("nameRu"):
                    self._options[option["id"]] = option["nameRu"]

    def _labels(self, o: dict) -> str:
        """Значения фильтров объявления: способ получения, регион… Каталог часть из них отдаёт только номером варианта."""
        self._remember_options(o.get("subCategory") or {})
        return " ".join(filter(None, (
            a.get("valueLabel") or a.get("optionNameRu") or self._options.get(a.get("optionId") or "", "")
            for a in o.get("attributes") or [])))

    def product_for(self, brand: str, sub: str, brief: str, labels: str) -> ProductKey | None:
        """Товар по трём источникам: фильтры объявления, название продавца, подкатегория раздела.

        Подкатегория — это номинал («60 UC», «100 звёзд») или тариф («Nitro Basic», «Пробная подписка»).
        В разделах UC, звёзд и Steam продавцы названий не пишут вовсе: без подкатегории бот не видел
        в них ни одного объявления.
        """
        if not deliverable(f"{sub} {labels}", brand):
            return None
        title = f"{brief} {labels}".strip()
        # Тариф и регион из подкатегории добавляем всегда; число из неё — только если своего в названии нет:
        # «80+8 CP» в подкатегории «80 CP» иначе дало бы два разных номинала.
        extra = "" if re.search(r"\d", sub) else sub
        return (self.parse(f"{labels} {extra}", brand) or self.parse(f"{title} {extra}", brand)
                or self.parse(sub, brand) or self.parse(f"{title} {sub}", brand))

    checks_pay_price = True

    async def pay_price(self, offer: Offer, method: str = "sbp") -> float | None:
        """Цена лота, если продавец заходил недавно (seller.lastOnlineAt на странице лота)."""
        async with httpx.AsyncClient(proxy=self.next_scan_proxy(), headers={"User-Agent": UA}, timeout=20,
                                     follow_redirects=True) as client:
            resp = await client.get(offer.url)
            resp.raise_for_status()
        page = json.loads(NEXT_DATA.search(resp.text).group(1))["props"]["pageProps"]
        if page.get("offerNotFound"):
            return None
        seller = page.get("seller") or {}
        if seller.get("isOnline"):
            import time
            offer.raw["seller_offline_days"] = 0.0
            offer.raw["seller_activity_checked_at"] = time.time()
            return offer.price
        days = days_since(seller.get("lastOnlineAt"))
        import time
        offer.raw["seller_activity_checked_at"] = time.time()
        offer.raw["seller_offline_days"] = days
        if self.seller_gone(days):
            offer.raw["reject_reason"] = "seller_offline"
            log.info("starvell: продавец лота %s не заходил %.0f дн. — не беру в поставщики", offer.offer_id, days)
            return None
        return offer.price

    def _offer(self, o: dict, brand: str) -> Offer | None:
        brief = ((o.get("descriptions") or {}).get("rus") or {}).get("briefDescription") or ""
        sub = (o.get("subCategory") or {}).get("name") or ""
        labels = self._labels(o)
        product = self.product_for(brand, sub, brief, labels)
        if not product:
            return None
        user = o.get("user") or {}
        try:
            price = float(o.get("price") or o.get("finalPrice"))
        except (TypeError, ValueError):
            return None
        return Offer(
            platform=self.name,
            offer_id=str(o.get("publicId")),
            title=" ".join(filter(None, (brief or sub, labels))),
            price=price,
            url=f"{BASE}/offers/{o.get('publicId')}",
            seller=str(user.get("username") or ""),
            seller_id=str(user.get("publicId") or ""),
            seller_rating=user.get("rating"),
            auto_delivery=bool(o.get("autoDelivery") or o.get("instantDelivery")),
            stock=o.get("availability"),
            product=product,
        )
