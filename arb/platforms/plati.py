"""Plati.market (движок Digiseller): открытый поисковый API, только источник цен."""

from __future__ import annotations

import asyncio
import json
import re

import httpx

from ..models import Offer
from .base import Platform, log

SEARCH_URL = "https://plati.io/api/search.ashx"
PRODUCT_URL = "https://api.digiseller.com/api/products/{id}/data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"


class Plati(Platform):
    name = "plati"
    can_scan = True

    async def scan(self) -> list[Offer]:
        offers: dict[str, Offer] = {}
        async with httpx.AsyncClient(proxy=self.next_scan_proxy(), headers={"User-Agent": UA}, timeout=30) as client:
            for query in self.pcfg.get("search_queries", []):
                try:
                    resp = await client.get(
                        SEARCH_URL,
                        params={"query": query, "pagesize": 500, "pagenum": 1,
                                "visibleOnly": "true", "response": "json"},
                    )
                    resp.raise_for_status()
                    items = resp.json().get("items") or []
                except Exception as e:  # noqa: BLE001
                    log.warning("plati: запрос %r не удался: %s", query, e)
                    self.note_error(e)
                    continue
                for it in items:
                    offer = self._offer(it)
                    if offer:
                        offers[offer.offer_id] = offer
                await asyncio.sleep(self.request_delay)
        return list(offers.values())

    def _offer(self, it: dict) -> Offer | None:
        title = it.get("name") or ""
        product = self.parse(title) or self.parse(it.get("name_eng") or "")
        if not product:
            return None
        try:
            price = float(it["price_rur"])
        except (KeyError, TypeError, ValueError):
            return None
        return Offer(
            platform=self.name,
            offer_id=str(it["id"]),
            title=title,
            price=price,
            url=str(it.get("url") or f"https://plati.market/itm/{it['id']}"),
            seller=str(it.get("seller_name") or ""),
            seller_id=str(it.get("seller_id") or ""),
            seller_rating=_float(it.get("seller_rating")),
            auto_delivery=True,  # товары Digiseller выдаются автоматически после оплаты
            product=product,
        )


    checks_pay_price = True

    async def pay_price(self, offer: Offer, method: str = "sbp") -> float | None:
        """Сколько спишется при оплате лота этим способом; None — купить этот товар здесь нельзя.

        Цена в поиске Plati — без комиссии платёжки, а её платит то продавец, то покупатель: у одного
        лота СБП = цена из поиска, у другого +8,5 % (12.11: Steam 578,85 ₽ в поиске, 627,80 ₽ по СБП).
        Ещё у лота бывает выбор номинала: цена в поиске — за самый дешёвый вариант.
        """
        await self.wait_read_slot()
        async with httpx.AsyncClient(proxy=self.next_scan_proxy(), timeout=20,
                                     headers={"User-Agent": UA, "Accept": "application/json"}) as client:
            resp = await client.get(PRODUCT_URL.format(id=offer.offer_id), params={"currency": "RUB", "lang": "ru-RU"})
            resp.raise_for_status()
            product = json.loads(resp.content.decode("utf-8-sig")).get("product") or {}
        return product_pay_price(product, offer.product.amount if offer.product else None, method)


def product_pay_price(product: dict, amount: float | None, method: str) -> float | None:
    if not product or not product.get("is_available"):
        return None
    wanted = {"sbp": ("сбп",), "card": ("карта",)}.get(method, (method,))
    rub = {m["name"].strip().lower(): float(c["price"]) for m in product.get("payment_methods") or []
           for c in m.get("currencies") or [] if c.get("currency") in ("RUB", "RUR") and c.get("price")}
    price = next((rub[name] for name in wanted if name in rub), None)
    if price is None:
        return None  # этим способом лот не оплатить
    default = (product.get("prices") or {}).get("default") or {}
    for option in product.get("options") or []:
        variants = option.get("variants") or []
        if not any(v.get("modify_value") for v in variants):
            continue  # варианты цену не меняют (платформа, язык…)
        if amount is None:
            return None
        number = re.compile(rf"(?<![\d.,]){re.escape(_amount_text(amount))}(?![\d.,])")
        variant = next((v for v in variants if number.search(str(v.get("text") or ""))), None)
        if not variant:
            return None  # нужного номинала у лота нет: «10-75$», а на выбор 5, 20, 30, 50
        extra, unit = float(variant.get("modify_value") or 0), str(variant.get("modify_type") or "RUB").upper()
        if extra and unit == "%":
            price *= 1 + extra / 100
        elif extra:
            base = float(default.get("RUB" if unit in ("RUB", "RUR") else unit) or 0)
            if not base:
                return None
            price *= 1 + extra / base  # наценка варианта — в той же доле, что и к цене без комиссии
    return round(price, 2)


def _amount_text(amount: float) -> str:
    return str(int(amount)) if float(amount).is_integer() else str(amount)


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
