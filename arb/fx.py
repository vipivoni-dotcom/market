"""Курсы ЦБ РФ — для проверки, что цена объявления похожа на номинал карты."""

from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger("arb.fx")

URL = "https://www.cbr-xml-daily.ru/daily_json.js"
# Запасной источник — сам ЦБ (XML): зеркало cbr-xml-daily бывает недоступно.
URL_CBR = "https://www.cbr.ru/scripts/XML_daily.asp"


def parse_cbr_xml(text: str) -> dict[str, float]:
    import xml.etree.ElementTree as ET
    rates = {}
    for v in ET.fromstring(text).iter("Valute"):
        value = float(v.findtext("Value").replace(",", "."))
        rates[v.findtext("CharCode")] = value / float(v.findtext("Nominal"))
    return rates


class FX:
    def __init__(self) -> None:
        self.rates: dict[str, float] = {"RUB": 1.0}
        self.updated = 0.0

    async def refresh(self) -> None:
        if time.time() - self.updated < 6 * 3600:
            return
        errors = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            try:
                data = (await client.get(URL)).json()
                rates = {code: float(v["Value"]) / float(v["Nominal"]) for code, v in data["Valute"].items()}
            except Exception as e:  # noqa: BLE001
                errors.append(f"{type(e).__name__} {e}")
                try:
                    r = await client.get(URL_CBR)
                    r.raise_for_status()
                    rates = parse_cbr_xml(r.content.decode("windows-1251"))
                except Exception as e2:  # noqa: BLE001
                    errors.append(f"{type(e2).__name__} {e2}")
                    log.warning("курсы ЦБ не загрузились: %s — проверка номинала отключена", "; ".join(errors))
                    return
        self.rates.update(rates)
        self.updated = time.time()

    def face_value_rub(self, amount: float, currency: str) -> float | None:
        rate = self.rates.get(currency)
        return amount * rate if rate else None

    def pay_rub(self, amount: float, currency: str, usdt_rub: float | None) -> float | None:
        """Сколько рублей уйдёт на оплату криптой: валюта → USD по кросс-курсу ЦБ → ₽ по курсу USDT.

        Без курса USDT считает по ЦБ, как face_value_rub.
        """
        if not usdt_rub:
            return self.face_value_rub(amount, currency)
        usd = 1.0 if currency == "USD" else None
        if usd is None and self.rates.get(currency) and self.rates.get("USD"):
            usd = self.rates[currency] / self.rates["USD"]
        return amount * usd * usdt_rub if usd else None


# Общий экземпляр для зарубежных площадок, у которых цены в USD/EUR/PLN
SHARED = FX()
