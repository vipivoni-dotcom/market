"""Обработка продаж: найти поставщика → купить (авто или вручную) → выдать покупателю."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from weakref import WeakValueDictionary

import httpx
from PlayerokAPI.exceptions import NetworkError

from .config import Config
from .db import DB
from .fees import buy_cost, pay_method
from .models import Offer
from .notify import Notifier
from .platforms.base import BuyerMessage, IncomingMessage, Purchase, Platform, PurchaseUncertain, Sale

log = logging.getLogger("arb.orders")

# Ответа площадки нет: покупка могла пройти, а могла и нет.
UNCERTAIN_ERRORS = (TimeoutError, httpx.TransportError, NetworkError, PurchaseUncertain)
OPEN_STATUSES = "('new','buying','bought','attention','delivering','delivery_unknown')"


# Пароли, коды входа, почта с паролем: такое не храним и не пересылаем.
SECRET_RE = re.compile(r"парол|password|\bpass\b|\bпасс\b|логин\s*[:=]|login\s*[:=]|код\s+(из|от)\s+(смс|sms|почт)|2fa", re.IGNORECASE)
CODE_WORDS = ("промокод", "ключ", "карта", "ссылка", "код")


def needs_buyer_data(cfg: Config, key: str) -> bool:
    """Товар выдаёт продавец по данным покупателя (ID игрока, тег, ник, @username), а не кодом."""
    brand, _, rest = key.partition(":")
    cat = (cfg.get_path("platforms.playerok.categories") or {}).get(brand.split("-")[0]) or {}
    obtaining = str(cat.get("obtaining") or "").lower()
    if not obtaining or any(w in obtaining for w in CODE_WORDS):
        return False
    return True


def _match_purchase(rows: list[dict], key: str | None) -> dict | None:
    """Сопоставить только полный ключ товара; пропускать ноль или несколько совпадений."""
    if not key:
        return None
    matches = [row for row in rows if row.get("key") == key]
    return matches[0] if len(matches) == 1 else None


class Orders:
    def __init__(self, cfg: Config, db: DB, platforms: dict[str, Platform], notify: Notifier) -> None:
        self.cfg = cfg
        self.db = db
        self.platforms = platforms
        self.notify = notify
        # Заказ выдаётся один раз: двойное нажатие кнопки не должно отправить код дважды.
        self._deliver_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()

    # --- новая продажа ----------------------------------------------------

    async def on_sale(self, sale: Sale) -> None:
        listing = self._find_listing(sale)
        if not listing:
            log.info("%s: продажа %s не наша (не из карточек бота) — пропускаю", sale.platform, sale.order_id)
            return
        source = self._best_source(listing)
        now = time.time()
        cur = self.db.execute(
            "INSERT OR IGNORE INTO orders (platform, external_id, listing_id, key, buyer, chat_id, price,"
            " source_platform, source_url, source_offer_id, source_price, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?, 'new', ?, ?)",
            (sale.platform, sale.order_id, listing["id"], listing["key"], sale.buyer, sale.chat_id, sale.price,
             source["platform"] if source else None, source["url"] if source else None,
             source["offer_id"] if source else None, source["price"] if source else None, now, now),
        )
        if not cur.rowcount:
            return  # уже обрабатывали
        order_id = cur.lastrowid
        if source and await self._try_auto_buy(order_id, source):
            return
        if source:
            await self.notify(f"💰 Продажа #{order_id} на {sale.platform}: {listing['key']} за {sale.price:.0f} ₽\n"
                              f"Поставщик: {source['platform']}, оплатить "
                              f"{buy_cost(self.cfg, source['platform'], source['price']):.0f} ₽.\n{source['url']}\n"
                              f"Дальше: {self._next_step(listing['key'], source)}",
                              [("📨 Отправить код", f"code:{order_id}")])
        else:
            log.warning("заказ #%s: поставщик не найден; требуется ручная обработка", order_id)
            await self.notify(f"💰 Продажа #{order_id} на {sale.platform}: {listing['key']} за {sale.price:.0f} ₽\n"
                              "Поставщик не найден — требуется ручная обработка.")

    def _pay_text(self, source: dict) -> str:
        cost = buy_cost(self.cfg, source["platform"], source["price"])
        how = {"sbp": "по СБП", "card": "картой"}.get(pay_method(self.cfg), pay_method(self.cfg))
        return f"Оплатить у {source['platform']}: {cost:.0f} ₽ {how}\n{source['url']}"

    def _next_step(self, key: str, source: dict | None) -> str:
        """Что делать владельцу после продажи — зависит от того, видит ли бот закупку сам."""
        supplier = self.platforms.get(source["platform"]) if source else None
        # FunPay: бот вошёл в тот же аккаунт, с которого платит владелец, и видит оплату в чате с продавцом
        tracked = supplier is not None and supplier.name != "playerok" and hasattr(supplier, "purchase_chats")
        by_id = needs_buyer_data(self.cfg, key)
        if tracked and by_id:
            return ("оплатите лот по ссылке выше. Оплату увижу сам и отправлю продавцу данные покупателя "
                    "(ID, ник), как только он пришлёт их в чат сделки.")
        if tracked:
            return ("оплатите лот по ссылке выше. Оплату увижу сам: код со страницы заказа заберу и отправлю "
                    "покупателю. Если продавец выдаёт вручную, перешлю его сообщение сюда.")
        return "купите товар по ссылке выше и нажмите кнопку, чтобы отправить код покупателю."

    # --- сообщение покупателя и наша оплата у поставщика -------------------

    async def on_buyer_message(self, msg: BuyerMessage) -> None:
        order = self.db.one(
            f"SELECT * FROM orders WHERE platform=? AND chat_id=? AND status IN {OPEN_STATUSES} ORDER BY id DESC",
            (msg.platform, msg.chat_id))
        if not order:
            return
        text = msg.text.strip()[:500]
        if SECRET_RE.search(text):
            # Пароли и коды входа не храним и никому не пересылаем: товар выдаётся без входа в аккаунт.
            await self.notify(f"⚠️ Заказ #{order['id']}: покупатель {order['buyer']} прислал в чат пароль или данные "
                              "для входа. Я их не сохранил и не переслал — для выдачи они не нужны. "
                              "Напишите покупателю, что нужен только ID игрока или ник.")
            return
        known = [t for t in (order["buyer_data"] or "").split("\n") if t]
        if text in known:
            return
        self.db.execute("UPDATE orders SET buyer_data=?, updated_at=? WHERE id=?",
                        ("\n".join((known + [text])[-5:]), time.time(), order["id"]))
        if order["purchase_ref"] and needs_buyer_data(self.cfg, order["key"]):
            await self._send_buyer_data(order["id"], text)
        else:
            await self.notify(f"✉️ Заказ #{order['id']}: покупатель {order['buyer']} пишет:\n\n{text}")

    async def _send_buyer_data(self, order_id: int, text: str) -> None:
        order = self.db.one("SELECT * FROM orders WHERE id=?", (order_id,))
        platform = self.platforms.get(order["source_platform"])
        try:
            await platform.send_to_supplier(order["purchase_ref"], text)
        except Exception as e:  # noqa: BLE001
            await self.notify(f"⚠️ Заказ #{order_id}: данные покупателя продавцу не отправлены ({e}). "
                              f"Отправьте вручную в чат заказа {order['purchase_ref']}:\n\n{text}")
            return
        log.info("заказ #%s: данные покупателя отправлены поставщику %s", order_id, order["source_platform"])

    async def on_purchase(self, p: Purchase) -> None:
        """Владелец оплатил лот поставщика: привязываем оплату к заказу и ведём его дальше сами."""
        if self.db.one("SELECT id FROM orders WHERE source_platform=? AND purchase_ref=?", (p.platform, p.ref)):
            return
        rows = self.db.query(
            f"SELECT * FROM orders WHERE source_platform=? AND purchase_ref IS NULL AND status IN {OPEN_STATUSES} "
            "ORDER BY id", (p.platform,))
        order = _match_purchase(rows, p.key)
        if not order:
            log.info("оплата %s на %s не сопоставлена с открытым заказом", p.ref, p.platform)
            await self.notify(
                f"⚠️ Оплата {p.ref} у {p.platform} не привязана: нет единственного открытого заказа "
                f"с тем же полным ключом товара. Проверьте заказ и покупку вручную.\n{p.title[:120]}"
            )
            return
        order_id = order["id"]
        self.db.execute("UPDATE orders SET purchase_ref=?, status='bought', updated_at=? WHERE id=?",
                        (p.ref, time.time(), order_id))
        await self.notify(f"✅ Покупка у поставщика #{order_id}: {p.platform}, {p.title[:80]}")
        platform = self.platforms[p.platform]
        if needs_buyer_data(self.cfg, order["key"]):
            if order["buyer_data"]:
                await self._send_buyer_data(order_id, order["buyer_data"])
            else:
                log.info("заказ #%s: ожидаю данные покупателя для поставщика", order_id)
            return
        try:
            goods = await platform.purchased_goods(p.ref)
        except Exception as e:  # noqa: BLE001
            log.warning("заказ #%s: товар со страницы заказа %s не получен: %s", order_id, p.ref, e)
            goods = None
        if not goods:
            await self.notify(f"✅ Покупка у поставщика #{order_id}: {p.platform}, {p.title[:80]}; "
                              "код ожидается в чате поставщика.",
                              [("📨 Отправить код вручную", f"code:{order_id}")])
            return
        self._save_supplier_text(order_id, goods)
        if self.cfg.get_path("mode.auto_deliver", False):
            res = await self.deliver(order_id, goods)
            if res != "ok":
                log.warning("заказ #%s: покупка получена, выдача не выполнена: %s", order_id, res)
        else:
            await self.notify(f"✅ Покупка у поставщика #{order_id}: {p.platform}, {p.title[:80]}; "
                              f"товар получен.\n\n{goods}",
                              [("➡️ Отправить покупателю", f"fwd:{order_id}")])

    def _find_listing(self, sale: Sale) -> dict | None:
        if sale.listing_external_id:
            row = self.db.one(
                "SELECT * FROM listings WHERE platform=? AND external_id=? ORDER BY id DESC",
                (sale.platform, sale.listing_external_id),
            )
            if row:
                return row
        # FunPay отдаёт только название — сравниваем с названиями своих карточек. Сначала с действующими,
        # потом со всеми: проданная, пока бот был выключен, карточка уже снята («gone»)
        for only_active in (" AND status IN ('active','dry_run')", ""):
            for row in self.db.query(
                f"SELECT * FROM listings WHERE platform=?{only_active} ORDER BY id DESC",
                (sale.platform,),
            ):
                if row["title"][:40] and row["title"][:40] in sale.title:
                    return row
        return None

    def _best_source(self, listing: dict) -> dict | None:
        """Поставщик из актуальной связки (она пересчитывается каждый скан с учётом рейтинга и лимитов)."""
        op = self.db.one("SELECT * FROM opportunities WHERE id=?", (listing["opportunity_id"],))
        if not op or not op["buy_offer_id"]:
            return None
        return {"platform": op["buy_platform"], "offer_id": op["buy_offer_id"], "title": op["buy_title"],
                "url": op["buy_url"], "price": op["buy_price"]}

    async def _try_auto_buy(self, order_id: int, source: dict) -> bool:
        platform = self.platforms.get(source["platform"])
        if self.cfg.get_path("mode.audit_only", False):
            return False
        if not (self.cfg.get_path("mode.auto_buy") and platform and platform.can_buy):
            return False
        if self.cfg.dry_run:
            await self.notify(f"🧪 [dry-run] Купил бы у {source['platform']} за {source['price']:.0f} ₽ для заказа #{order_id}")
            return False
        offer = Offer(platform=source["platform"], offer_id=source["offer_id"], title=source["title"],
                      price=source["price"], url=source["url"])
        # Цена в связке — со скана, ей до часа. Перед оплатой сверяем с площадкой: товар могли снять или поднять в цене.
        try:
            fresh = await platform.current_price(offer)
        except Exception as e:  # noqa: BLE001
            await self.notify(f"⚠️ Заказ #{order_id}: товар поставщика недоступен ({e}). Купите вручную у другого.")
            return False
        if fresh is None:
            await self.notify(f"⚠️ Заказ #{order_id}: не удалось проверить цену у {source['platform']} перед оплатой — купите вручную.")
            return False
        tolerance = float(self.cfg.get_path("rules.auto_buy_price_tolerance_pct", 2)) / 100
        if fresh > source["price"] * (1 + tolerance):
            await self.notify(f"⚠️ Заказ #{order_id}: поставщик поднял цену {source['price']:.0f} → {fresh:.0f} ₽. "
                              "Автопокупку не делаю — проверьте выгоду и купите вручную.")
            return False
        offer.price = fresh
        self._set(order_id, "buying")
        try:
            ref = await platform.buy(offer)
        except UNCERTAIN_ERRORS as e:
            # Деньги могли списаться, поэтому заказ остаётся на ручную сверку.
            self._set(order_id, "attention", f"исход автопокупки неизвестен: {e}")
            await self.notify(
                f"⚠️ Заказ #{order_id}: площадка не ответила ({e}), покупка могла пройти. "
                f"Проверьте покупки на {source['platform']} и не покупайте повторно, пока не убедитесь.",
                [("📨 Отправить код", f"code:{order_id}")],
            )
            return True
        except Exception as e:  # noqa: BLE001
            self._set(order_id, "new", f"автопокупка не удалась: {e}")
            await self.notify(f"⚠️ Заказ #{order_id}: автопокупка не удалась ({e}). Купите вручную.")
            return False
        self.db.execute("UPDATE orders SET purchase_ref=?, status='bought', updated_at=? WHERE id=?",
                        (ref, time.time(), order_id))
        await self.notify(f"✅ Покупка у поставщика #{order_id}: {source['platform']}")
        if ref.startswith("tx:"):
            await self.notify(
                f"⚠️ Заказ #{order_id}: куплено, но сделку определить не удалось — код может не прийти сюда "
                f"автоматически. Проверьте покупки на {source['platform']} вручную.",
                [("📨 Отправить код вручную", f"code:{order_id}")],
            )
            return True
        try:
            goods = await platform.purchased_goods(ref)
        except Exception as e:  # noqa: BLE001
            # Деньги уже ушли: сбой запроса товара не должен оборвать обработку заказа без сообщения.
            log.warning("заказ #%s: товар после покупки не получен: %s", order_id, e)
            goods = None
        if goods:
            # Площадка отдала товар сразу (LZT) — выдаём без ожидания поставщика
            self._save_supplier_text(order_id, goods)
            if self.cfg.get_path("mode.auto_deliver", False):
                res = await self.deliver(order_id, goods)
            else:
                await self.notify(f"✅ Покупка у поставщика #{order_id}: {source['platform']}; товар получен.",
                                  [("➡️ Отправить покупателю", f"fwd:{order_id}")])
            return True
        await self.notify(
            f"✅ Покупка у поставщика #{order_id}: {source['platform']}; код ожидается в чате.",
            [("📨 Отправить код вручную", f"code:{order_id}")],
        )
        return True

    # --- сообщение от поставщика ------------------------------------------

    async def on_supplier_message(self, msg: IncomingMessage) -> None:
        order = self.db.one("SELECT * FROM orders WHERE purchase_ref=?", (msg.purchase_ref,))
        if not order:
            return
        self._save_supplier_text(order["id"], msg.text)
        await self.notify(
            f"📩 Поставщик по заказу #{order['id']} пишет:\n\n{msg.text}",
            [("➡️ Переслать покупателю", f"fwd:{order['id']}"), ("✏️ Свой текст", f"code:{order['id']}")],
        )

    def supplier_text(self, order_id: int) -> str | None:
        """Последнее сообщение поставщика или полученный товар — для кнопки «переслать покупателю»."""
        row = self.db.one("SELECT supplier_text FROM orders WHERE id=?", (order_id,))
        return row["supplier_text"] if row else None

    def _save_supplier_text(self, order_id: int, text: str) -> None:
        self.db.execute("UPDATE orders SET supplier_text=?, updated_at=? WHERE id=?", (text, time.time(), order_id))

    # --- восстановление после перезапуска -----------------------------------

    async def sync_deals(self) -> None:
        """Сверить открытые заказы со сделками на площадке: отменённые и закрытые без бота больше не висят.

        Без этого заказ, который покупатель отменил (деньги вернулись), напоминал о себе при каждом запуске.
        """
        await self.catch_up_sales()
        for order in self.db.query(f"SELECT * FROM orders WHERE status IN {OPEN_STATUSES} ORDER BY id"):
            platform = self.platforms.get(order["platform"])
            if not platform:
                continue
            try:
                status = await platform.deal_status(order["external_id"])
            except Exception as e:  # noqa: BLE001
                log.info("статус сделки заказа #%s не получен: %s", order["id"], e)
                continue
            head = f"заказ #{order['id']} ({order['key']}, {order['price']:.0f} ₽)"
            if status in ("ROLLED_BACK", "FAILED"):
                self._set(order["id"], "cancelled", f"сделка на {order['platform']}: {status}")
                bought = order["status"] in ("bought", "attention") or order["purchase_ref"]
                await self.notify(f"❌ Отменён {head}: деньги вернулись покупателю."
                                  + (" Товар у поставщика уже куплен — его можно продать снова." if bought else ""))
            elif status in ("SENT", "CONFIRMED"):
                # Выдали вручную на сайте, минуя бота.
                self._set(order["id"], "delivered", f"сделка на {order['platform']}: {status}")
                log.info("%s закрыт на площадке (%s)", head, status)

    async def catch_up_sales(self) -> None:
        """Подхватить оплаченные продажи, которых нет в заказах: пришли, пока бот был выключен
        или слушатель площадки переподключался (09.11: Fortnite 1600 V-Bucks ждал выдачи полдня)."""
        for name, platform in self.platforms.items():
            try:
                sales = await platform.open_sales()
            except Exception as e:  # noqa: BLE001
                log.info("%s: список оплаченных продаж не получен: %s", name, e)
                continue
            for sale in sales:
                if self.db.one("SELECT id FROM orders WHERE platform=? AND external_id=?", (sale.platform, sale.order_id)):
                    continue
                log.info("%s: найдена пропущенная продажа %s (%s)", name, sale.order_id, sale.title)
                await self.on_sale(sale)

    async def loop(self, every: float = 600) -> None:
        while True:
            await asyncio.sleep(every)
            try:
                await self.sync_deals()
            except Exception as e:  # noqa: BLE001
                log.warning("сверка заказов упала: %s", e)

    async def recover(self) -> None:
        """Напомнить о незавершённых заказах. Автопокупку не повторяем: цена могла устареть."""
        try:
            await self.sync_deals()
        except Exception as e:  # noqa: BLE001
            log.warning("сверка заказов упала: %s", e)
        rows = self.db.query(f"SELECT * FROM orders WHERE status IN {OPEN_STATUSES} ORDER BY id")
        await self._restore_purchase_chats(rows)
        for order in rows:
            if time.time() - (order["created_at"] or 0) < 120:
                continue  # только что подхвачен сверкой — о нём уже пришло «💰 Продажа», не дублируем
            order_id = order["id"]
            code = [("📨 Отправить код", f"code:{order_id}")]
            head = f"🔁 Незавершённый заказ #{order_id} ({order['key']}, покупатель {order['buyer']})"
            if order["status"] == "new":
                link = f"\n{order['source_url']}" if order["source_url"] else ""
                await self.notify(f"{head}: товар не куплен. Проверьте цену и купите вручную.{link}", code)
            elif order["status"] == "buying":
                self._set(order_id, "attention", "бот остановился во время автопокупки, исход неизвестен")
                await self.notify(
                    f"{head}: бот остановился во время покупки, исход неизвестен. Проверьте покупки "
                    f"на {order['source_platform']} и не покупайте повторно, пока не убедитесь.", code,
                )
            elif order["status"] == "attention":
                await self.notify(f"{head}: исход покупки на {order['source_platform']} всё ещё не проверен.", code)
            elif order["status"] in ("delivering", "delivery_unknown"):
                await self.notify(f"{head}: исход отправки кода неизвестен. Сначала проверьте чат сделки на площадке; повтор пока заблокирован.")
            elif order["supplier_text"]:
                await self.notify(f"{head}: куплено, товар получен, но не выдан:\n\n{order['supplier_text']}",
                                  [("➡️ Отправить покупателю", f"fwd:{order_id}")])
            else:
                await self.notify(f"{head}: куплено (сделка {order['purchase_ref']}), код не получен. "
                                  "Проверьте чат с поставщиком.", code)

    async def _restore_purchase_chats(self, rows: list[dict]) -> None:
        """Купленные заказы без кода: площадка-поставщик снова слушает их чаты (в памяти они не пережили перезапуск)."""
        waiting: dict[str, list[str]] = {}
        for order in rows:
            ref = order["purchase_ref"]
            if order["status"] == "bought" and ref and not ref.startswith("tx:") and not order["supplier_text"]:
                waiting.setdefault(order["source_platform"], []).append(ref)
        for name, refs in waiting.items():
            restore = getattr(self.platforms.get(name), "restore_purchases", None)
            if restore:
                try:
                    await restore(refs)
                except Exception as e:  # noqa: BLE001
                    log.info("%s: чаты покупок не восстановлены: %s", name, e)

    # --- выдача -----------------------------------------------------------

    async def deliver(self, order_id: int, text: str, confirm_unknown: bool = False) -> str:
        # Ожидающие задачи держат сильную ссылку на один lock. Нельзя удалять
        # запись после первой попытки: третья задача иначе обгонит уже ожидающую.
        lock = self._deliver_locks.setdefault(order_id, asyncio.Lock())
        async with lock:
            return await self._deliver(order_id, text, confirm_unknown)

    async def _deliver(self, order_id: int, text: str, confirm_unknown: bool = False) -> str:
        order = self.db.one("SELECT * FROM orders WHERE id=?", (order_id,))
        if not order:
            return "заказ не найден"
        if order["status"] == "delivered":
            return "заказ уже выдан — второй раз не отправляю"
        if order["status"] in ("delivering", "delivery_unknown") and not confirm_unknown:
            return "исход выдачи неизвестен — проверьте сделку на площадке; повтор разрешён только после подтверждения, что сообщение не отправлено"
        if order["status"] == "cancelled":
            return "заказ отменён, деньги вернулись покупателю — код не отправляю"
        if not text or not text.strip():
            return "пустой текст — отправлять нечего"
        platform = self.platforms.get(order["platform"])
        if not platform:
            return f"площадка {order['platform']} не подключена"
        message = f"Ваш заказ:\n{text}\n\nСпасибо за покупку! Пожалуйста, подтвердите получение и оставьте отзыв 🙏"
        # Сохраняем намерение до внешнего вызова. Если процесс остановится или
        # ответ потеряется, следующий запуск не отправит код повторно молча.
        self._set(order_id, "delivering", "отправка начата; проверьте исход на площадке при остановке или таймауте")
        try:
            await platform.deliver(order["chat_id"], order["external_id"], order["buyer"], message)
        except Exception as e:  # noqa: BLE001
            self._set(order_id, "delivery_unknown", f"исход выдачи неизвестен: {e}; проверьте сделку на площадке перед повтором")
            return f"исход выдачи неизвестен: {e}; проверьте сделку на площадке перед повтором"
        self._set(order_id, "delivered")
        return "ok"

    def _set(self, order_id: int, status: str, note: str | None = None) -> None:
        self.db.execute("UPDATE orders SET status=?, note=COALESCE(?, note), updated_at=? WHERE id=?",
                        (status, note, time.time(), order_id))
