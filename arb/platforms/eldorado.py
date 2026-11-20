"""Eldorado.gg: зарубежная биржа игровых товаров. Только источник цен.

Сайт берёт данные из открытого JSON API — его же читает и бот:
  /api/library                                   — список игр и разделов (seoAlias для ссылок)
  /api/library/{id}/GiftCard                     — регионы и номиналы подарочных карт
  /api/predefinedOffers/giftCards/{id}/topOffersPrices — лучшая цена по каждому номиналу
  /api/predefinedOffers/topUps/{id}/topOffersPrices    — лучшая цена пополнений («170-gems»)
Цены запрашиваем в USD и переводим в рубли по курсу ЦБ. Покупка вручную.
"""

from __future__ import annotations

import asyncio

import httpx

from ..fx import SHARED as FX
from ..models import Offer
from .base import Platform, log
from .jsonld import UA

BASE = "https://www.eldorado.gg"


class Eldorado(Platform):
    name = "eldorado"
    can_scan = True

    async def scan(self) -> list[Offer]:
        await FX.refresh()
        offers: list[Offer] = []
        headers = {"User-Agent": UA, "Accept": "application/json", "Cookie": "eldoradogg_currencyPreference=USD"}
        async with httpx.AsyncClient(proxy=self.next_scan_proxy(), base_url=BASE, headers=headers, timeout=30) as client:
            try:
                library = (await client.get("/api/library", params={"locale": "en-US"})).json()
            except Exception as e:  # noqa: BLE001
                log.warning("eldorado: список игр не загрузился: %s", e)
                return []
            games = {(g["gameId"], g["category"]): g for g in library}
            for game_id, brand in (self.pcfg.get("gift_cards") or {}).items():
                game = games.get((str(game_id), "GiftCard"))
                if game:
                    offers.extend(await self._gift_cards(client, game, brand))
                    await asyncio.sleep(self.request_delay)
            for game_id, brand in (self.pcfg.get("top_ups") or {}).items():
                game = games.get((str(game_id), "TopUp"))
                if game:
                    offers.extend(await self._top_ups(client, game, brand))
                    await asyncio.sleep(self.request_delay)
        return offers

    async def _gift_cards(self, client: httpx.AsyncClient, game: dict, brand: str) -> list[Offer]:
        gid = game["gameId"]
        try:
            lib = (await client.get(f"/api/library/{gid}/GiftCard", params={"locale": "en-US"})).json()
            prices = (await client.get(f"/api/predefinedOffers/giftCards/{gid}/topOffersPrices")).json()
        except Exception as e:  # noqa: BLE001
            log.warning("eldorado: подарочные карты %s не загрузились: %s", game["gameName"], e)
            return []
        names = {}
        for region in lib.get("tradeEnvironments") or []:
            for value in region.get("childTradeEnvironments") or []:
                names[value["id"]] = f"{game['gameName']} {value['value']} {region['value']}"
        return self._offers(prices, lambda p: names.get(p.get("tradeEnvironmentId")), brand,
                            f"{BASE}/{game.get('seoAlias')}/v/{gid}", lambda p: p.get("tradeEnvironmentId"))

    async def _top_ups(self, client: httpx.AsyncClient, game: dict, brand: str) -> list[Offer]:
        gid = game["gameId"]
        try:
            prices = (await client.get(f"/api/predefinedOffers/topUps/{gid}/topOffersPrices")).json()
        except Exception as e:  # noqa: BLE001
            log.warning("eldorado: пополнения %s не загрузились: %s", game["gameName"], e)
            return []
        # «170-gems» → «Brawl Stars 170 gems»
        title = lambda p: f"{game['gameName']} {str(p.get('attributeValueId') or '').replace('-', ' ')}"  # noqa: E731
        return self._offers(prices, title, brand, f"{BASE}/{game.get('seoAlias')}/t/{gid}",
                            lambda p: f"{gid}:{p.get('attributeValueId')}")

    def _offers(self, prices, title_of, brand: str, url: str, id_of) -> list[Offer]:
        result = []
        for p in prices if isinstance(prices, list) else []:
            title = title_of(p)
            money = p.get("price") or {}
            rub = FX.pay_rub(float(money.get("amount") or 0), money.get("currency", "USD"), self.cfg.get_path("fx.usdt_rub"))
            product = self.parse(title, brand) if title else None
            if not product or not rub:
                continue
            result.append(Offer(
                platform=self.name, offer_id=str(id_of(p)), title=title, price=round(rub, 2), url=url,
                seller="Eldorado (лучшее предложение)", seller_id="", product=product,
                raw={"usd": money.get("amount")},
            ))
        return result
