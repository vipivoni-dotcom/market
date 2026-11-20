"""Расчёт комиссий и прибыли."""

from __future__ import annotations

import math

from .config import Config


def buy_cost(cfg: Config, platform: str, price: float) -> float:
    """Сколько реально заплатим поставщику с учётом комиссии платёжки."""
    return price * (1 + buy_fee_pct(cfg, platform) / 100)


def pay_method(cfg: Config) -> str:
    """Чем платим поставщикам: sbp или card (rules.pay_method). От этого зависит комиссия площадки."""
    return str(cfg.get_path("rules.pay_method", "sbp")).lower()


def buy_fee_pct(cfg: Config, platform: str) -> float:
    """Комиссия оплаты сверх цены из скана. Число или {sbp: …, card: …} — по способу оплаты."""
    fee = cfg.platform(platform).get("buy_fee_pct", 0)
    if isinstance(fee, dict):
        fee = fee.get(pay_method(cfg), max(fee.values(), default=0))  # способ не описан — считаем по худшему
    return float(fee)


def _income_ratio(cfg: Config, platform: str) -> float:
    p = cfg.platform(platform)
    sell_fee = float(p.get("sell_fee_pct", 0)) / 100
    withdraw_fee = float(p.get("withdraw_fee_pct", 0)) / 100
    return (1 - sell_fee) * (1 - withdraw_fee) / seller_price_ratio(cfg, platform)


def seller_price_ratio(cfg: Config, platform: str) -> float:
    """Во сколько раз цена для покупателя больше цены, которую вводит продавец (FunPay: +комиссия)."""
    return 1 + float(cfg.platform(platform).get("buyer_commission_pct", 0)) / 100


def net_income(cfg: Config, platform: str, sell_price: float) -> float:
    """Сколько дойдёт до кошелька после комиссии площадки и вывода (sell_price — цена для покупателя)."""
    return sell_price * _income_ratio(cfg, platform)


def min_sell_price(cfg: Config, platform: str, cost: float, min_profit: float) -> float:
    """Минимальная цена продажи, при которой прибыль >= min_profit (округлена вверх до рубля)."""
    return math.ceil((cost + min_profit) / _income_ratio(cfg, platform))
