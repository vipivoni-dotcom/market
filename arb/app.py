"""Сборка всех частей в одно приложение."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .config import Config
from .db import DB
from .engine import Engine
from .notify import Notifier
from .orders import Orders
from .platforms import build_platforms

log = logging.getLogger("arb")

RESTART_DELAY = 30  # секунд до перезапуска упавшей фоновой задачи


async def supervise(name: str, factory: Callable[[], Awaitable[None]], notify: Notifier | None = None,
                    delay: float = RESTART_DELAY) -> None:
    """Вести фоновую задачу: упала — записать, сообщить и запустить снова.

    Без этого исключение в одном слушателе площадки останавливало весь бот вместе с приёмом заказов.
    Обычное завершение (площадка без токена слушать не стала) не перезапускается.
    """
    while True:
        try:
            await factory()
            return
        except Exception as e:  # noqa: BLE001
            log.exception("%s: упало, перезапуск через %s с", name, delay)
            if notify:
                try:
                    await notify(f"⚠️ {name}: сбой ({type(e).__name__}: {str(e)[:200]}). Перезапускаю через {delay:g} с.")
                except Exception:  # noqa: BLE001
                    log.warning("%s: сообщить о сбое не удалось", name)
            await asyncio.sleep(delay)


class App:
    def __init__(self, cfg: Config, db: DB | None = None) -> None:
        self.cfg = cfg
        self.db = db or DB()
        self.notify = Notifier()
        self.platforms = build_platforms(cfg)
        self.engine = Engine(cfg, self.db, self.platforms, self.notify)
        self.orders = Orders(cfg, self.db, self.platforms, self.notify)

    async def start_platforms(self) -> None:
        timeout = max(0.0, float(self.cfg.get_path("rules.platform_startup_timeout_sec", 60)))
        deadline = asyncio.get_running_loop().time() + timeout
        for p in list(self.platforms.values()):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                log.error("%s: общий срок входа на площадки истёк — пропускаю авторизацию", p.name)
                p.can_sell = p.can_buy = False
                continue
            try:
                await asyncio.wait_for(p.start(), timeout=remaining)
            except asyncio.TimeoutError:
                # Event-loop timers may fire slightly before the clock deadline.
                # Once the remaining-budget wait times out, do not start another login.
                deadline = 0
                log.error("%s: не удалось войти за общий срок %.1f с — площадка работает без продажи/покупки",
                          p.name, timeout)
                p.can_sell = p.can_buy = False
            except Exception as e:  # noqa: BLE001
                p.can_sell = p.can_buy = False
                if p.name == "funpay":
                    # Повторные публичные запросы каталога после отказа входа
                    # могут усилить ограничение площадки (429). До перезапуска
                    # считаем весь источник недоступным и сохраняем прошлый снимок
                    # вне цикла, вместо сканирования сессией/адресом в цикле.
                    p.can_scan = False
                    response = getattr(e, "response", None)
                    status = getattr(response, "status_code", None)
                    reason = f"HTTP {status}" if status else type(e).__name__
                    log.error("%s: вход не выполнен (%s); сканирование, продажа и покупка отключены до перезапуска",
                              p.name, reason)
                else:
                    log.error("%s: не удалось войти (%s) — площадка работает только на сканирование", p.name, e)

    def stats(self) -> dict:
        q = self.db.one
        return {
            "offers": q("SELECT COUNT(*) n FROM offers")["n"],
            "opportunities": q("SELECT COUNT(*) n FROM opportunities WHERE status IN ('new','listed')")["n"],
            "listings": q("SELECT COUNT(*) n FROM listings WHERE status IN ('active','dry_run')")["n"],
            "orders": q("SELECT COUNT(*) n FROM orders")["n"],
            "delivered": q("SELECT COUNT(*) n FROM orders WHERE status='delivered'")["n"],
            "revenue": q("SELECT COALESCE(SUM(price),0) s FROM orders WHERE status='delivered'")["s"],
            "cost": q("SELECT COALESCE(SUM(source_price),0) s FROM orders WHERE status='delivered'")["s"],
            "paused": q("SELECT COUNT(*) n FROM listings WHERE status='paused'")["n"],
            "waiting": q("SELECT COUNT(*) n FROM orders WHERE status IN ('new','buying','bought','attention','delivering','delivery_unknown')")["n"],
            "cancelled": q("SELECT COUNT(*) n FROM orders WHERE status='cancelled'")["n"],
            "profit": self.realized_profit(),
        }

    def realized_profit(self) -> float:
        """Чистая прибыль по выданным заказам: что дошло после комиссии и вывода минус оплата поставщику."""
        from .fees import buy_cost, net_income
        total = 0.0
        for o in self.db.query("SELECT platform, price, source_platform, source_price FROM orders WHERE status='delivered'"):
            cost = buy_cost(self.cfg, o["source_platform"], o["source_price"]) if o["source_platform"] and o["source_price"] else 0
            total += net_income(self.cfg, o["platform"], o["price"] or 0) - cost
        return round(total, 2)

    def stats_text(self) -> str:
        s = self.stats()
        return (
            f"📊 Объявлений в базе: {s['offers']}\nСвязок: {s['opportunities']}\nКарточек: {s['listings']}\n"
            f"Заказов: {s['orders']} (выдано {s['delivered']})\n"
            f"Выручка: {s['revenue']:.0f} ₽, закупка: {s['cost']:.0f} ₽ (без учёта комиссий)"
        )
