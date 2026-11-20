"""LZT Market (lzt.market): официальный API с токеном. Источник: поиск + мгновенная покупка.

Купленный товар (ссылка на подписку, данные) API отдаёт сразу в ответе fast-buy,
поэтому заказ можно закрыть полностью автоматически.
Токен: lolz.team/account/api (нужны права market).
Лимит API на поиск — порядка 20 запросов в минуту, поэтому пауза между запросами 3+ с.
"""

from __future__ import annotations

import asyncio

import httpx

from ..models import Offer
from .base import Platform, PurchaseUncertain, log

BASE = "https://api.lzt.market"


class LZT(Platform):
    name = "lzt"
    can_scan = True
    can_buy = True

    def __init__(self, cfg, normalizer) -> None:
        super().__init__(cfg, normalizer)
        self._goods: dict[str, str] = {}

    @property
    def request_delay(self) -> float:
        return max(3.0, float(self.pcfg.get("request_delay_sec", 3.5)))

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=BASE, timeout=60, proxy=self.proxy,
            headers={"Authorization": f"Bearer {self.pcfg.get('token', '')}", "Accept": "application/json"},
        )

    async def scan(self) -> list[Offer]:
        if not self.pcfg.get("token"):
            log.info("lzt: токен не задан — пропускаю")
            return []
        offers: dict[str, Offer] = {}
        pages = int(self.pcfg.get("pages_per_category", 3))
        async with self._client() as client:
            for category in self.pcfg.get("categories", ["gifts"]):
                for page in range(1, pages + 1):
                    try:
                        resp = await client.get(f"/{category}", params={
                            "page": page, "order_by": "price_to_up", "currency": "rub",
                        })
                        resp.raise_for_status()
                        items = resp.json().get("items") or []
                    except Exception as e:  # noqa: BLE001
                        log.warning("lzt: категория %s стр. %d не загрузилась: %s", category, page, e)
                        break
                    for it in items:
                        offer = self._offer(it)
                        if offer:
                            offers[offer.offer_id] = offer
                    await asyncio.sleep(self.request_delay)
                    if not items:
                        break
        return list(offers.values())

    def _offer(self, it: dict) -> Offer | None:
        title = it.get("title") or it.get("title_en") or ""
        product = self.parse(title)
        if not product:
            return None
        try:
            price = float(it.get("rub_price") or it.get("price"))
        except (TypeError, ValueError):
            return None
        seller = it.get("seller") or {}
        return Offer(
            platform=self.name,
            offer_id=str(it["item_id"]),
            title=title,
            price=price,
            url=f"https://lzt.market/{it['item_id']}/",
            seller=str(seller.get("username") or ""),
            seller_id=str(seller.get("user_id") or ""),
            auto_delivery=True,  # данные выдаются сразу после оплаты
            product=product,
            raw={"price": it.get("price")},
        )

    async def current_price(self, offer: Offer) -> float | None:
        async with self._client() as client:
            resp = await client.get(f"/{offer.offer_id}")
            resp.raise_for_status()
            item = resp.json().get("item") or {}
        state = item.get("item_state")
        if state and state != "active":
            raise RuntimeError(f"объявление не в продаже ({state})")
        price = item.get("rub_price") or item.get("price")
        if price is None:
            return None
        offer.raw = {"price": item.get("price")}  # fast-buy принимает цену в валюте объявления
        return float(price)

    async def buy(self, offer: Offer) -> str:
        price = offer.raw.get("price") or offer.price
        async with self._client() as client:
            for _ in range(5):
                resp = await client.post(f"/{offer.offer_id}/fast-buy", json={"price": price})
                try:
                    data = resp.json()
                except ValueError:
                    data = None
                if not isinstance(data, dict) or (resp.status_code >= 500 and not data.get("errors")):
                    if resp.status_code < 500:
                        raise RuntimeError(f"lzt fast-buy: ответ {resp.status_code} не разобран")
                    # 502 с HTML-страницей и т.п.: покупка могла пройти — повторять и покупать вручную рано.
                    raise PurchaseUncertain(f"lzt fast-buy: непонятный ответ {resp.status_code}")
                if "retry_request" not in str(data.get("errors", "")):
                    break
                await asyncio.sleep(2)  # API просит повторить тот же запрос
            if resp.status_code >= 400 or data.get("errors"):
                raise RuntimeError(f"lzt fast-buy: {data.get('errors') or resp.status_code}")
        item = data.get("item") or {}
        login = item.get("loginData") or {}
        goods = login.get("raw") or "\n".join(x for x in (login.get("login"), login.get("password")) if x)
        ref = str(item.get("item_id") or offer.offer_id)
        if goods:
            self._goods[ref] = goods
        return ref

    async def purchased_goods(self, purchase_ref: str) -> str | None:
        return self._goods.get(purchase_ref)
