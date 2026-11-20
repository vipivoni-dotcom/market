"""Общие структуры данных."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProductKey:
    """Нормализованный товар: бренд + номинал + валюта, например apple:100INR."""

    brand: str
    amount: float
    currency: str
    variable: bool = False  # «100 - 10000 INR»: цена указана за минимальный номинал
    login: bool = False  # пополнение по логину/на аккаунт покупателя, а не код
    region: str | None = None  # только для USD/EUR, если регион не по умолчанию (US/EU)

    @property
    def key(self) -> str:
        amount = int(self.amount) if float(self.amount).is_integer() else self.amount
        return (f"{self.brand}:{amount}{self.currency}" + (f"@{self.region}" if self.region else "")
                + (":login" if self.login else ""))


@dataclass
class Offer:
    """Объявление на площадке."""

    platform: str
    offer_id: str
    title: str
    price: float  # в рублях, цена для покупателя
    url: str
    seller: str = ""
    seller_id: str = ""
    seller_rating: float | None = None
    auto_delivery: bool = False
    stock: int | None = None
    product: ProductKey | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def key(self) -> str | None:
        return self.product.key if self.product else None


@dataclass
class Opportunity:
    """Связка: купить на buy.platform, продать на sell_platform."""

    key: str
    buy: Offer
    sell_platform: str
    sell_price: float
    buy_cost: float  # цена закупки с комиссией платёжки
    net_income: float  # что останется после комиссий площадки продажи и вывода
    profit: float
    margin_pct: float
    competitors: int
    best_competitor_price: float | None
