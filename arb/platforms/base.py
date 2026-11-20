"""Общий интерфейс площадки."""

from __future__ import annotations

import logging
import asyncio
import random
import re
import time
from email.utils import parsedate_to_datetime
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..config import Config
from ..models import Offer, ProductKey
from ..normalize import Normalizer

log = logging.getLogger("arb.platforms")


@dataclass
class Sale:
    """Новая продажа нашей карточки."""

    platform: str
    order_id: str
    listing_external_id: str | None  # id нашей карточки, если площадка его отдаёт
    title: str
    buyer: str
    chat_id: str | None
    price: float


@dataclass
class IncomingMessage:
    """Сообщение от продавца-поставщика в чате нашей покупки (там обычно приходит код)."""

    platform: str
    purchase_ref: str
    chat_id: str
    text: str


@dataclass
class Purchase:
    """Мы (владелец аккаунта) оплатили лот у поставщика — вручную в браузере или автопокупкой."""

    platform: str
    ref: str       # номер заказа у поставщика
    chat_id: str   # чат с продавцом: туда придёт код и туда шлём ID покупателя
    title: str     # что куплено, как это называет площадка
    seller: str = ""
    key: str | None = None  # полный нормализованный ключ товара, если площадка смогла его определить


@dataclass
class BuyerMessage:
    """Сообщение покупателя в чате нашей продажи (ID игрока, ник, вопрос)."""

    platform: str
    chat_id: str
    text: str


@dataclass
class OwnListing:
    """Наша карточка на площадке, как её видит сама площадка."""

    external_id: str
    title: str
    price: float
    key: str | None  # ключ товара; None — не распознали, такой карточкой бот не управляет


class PurchaseUncertain(RuntimeError):
    """Площадка не дала понятного ответа на покупку: деньги могли списаться, повторять нельзя."""


SaleHandler = Callable[[Sale], Awaitable[None]]
MessageHandler = Callable[[IncomingMessage], Awaitable[None]]


class Platform:
    name: str = ""
    can_scan = False
    can_sell = False
    can_buy = False

    def __init__(self, cfg: Config, normalizer: Normalizer) -> None:
        self.cfg = cfg
        self.pcfg: dict[str, Any] = cfg.platform(self.name)
        self.normalizer = normalizer
        self._read_gate = asyncio.Lock()
        self._next_read = 0.0
        self._cooldown_until = 0.0
        self.save_cooldown = None
        # Свои объявления — не конкуренты. id добавляется при входе по токену,
        # а без токена хватит имени продавца из platforms.<площадка>.own_sellers.
        self.own_seller_ids: set[str] = {str(s) for s in self.pcfg.get("own_sellers") or []}

    @property
    def enabled(self) -> bool:
        return bool(self.pcfg.get("enabled"))

    @property
    def request_delay(self) -> float:
        return float(self.cfg.get_path("scan.request_delay_sec", 1.5)) * self.slowdown

    # --- прокси ---------------------------------------------------------------------------
    # platforms.<площадка>.proxy        — через него идёт всё: чтение цен и действия аккаунта;
    # platforms.<площадка>.scan_proxies — только чтение открытых страниц, по кругу. Аккаунт сюда не ходит:
    #                                     вход с меняющихся адресов площадки принимают за взлом.

    @property
    def proxy(self) -> str | None:
        return self.pcfg.get("proxy") or None

    @property
    def scan_proxies(self) -> list[str | None]:
        """Адреса для чтения цен. Всегда хотя бы один; None — без прокси (или общий proxy площадки)."""
        pool = [str(p) for p in self.pcfg.get("scan_proxies") or [] if p]
        if self.pcfg.get("scan_direct", True) or not pool:
            pool.insert(0, self.proxy)
        return pool

    _proxy_turn = 0

    def next_scan_proxy(self) -> str | None:
        """Следующий адрес для чтения: запросы расходятся по адресам поровну."""
        pool = self.scan_proxies
        self._proxy_turn += 1
        return pool[self._proxy_turn % len(pool)]

    # --- бережный режим: площадка ответила «слишком много запросов» — сбавляем темп ---------
    # Чтение цен и действия аккаунта (выставить, сменить цену, снять) площадки ограничивают порознь,
    # поэтому и паузы раздельные. 10.11 отказы на снятии карточек подняли общий множитель до ×16,
    # и скан Playerok шёл 34 минуты вместо четырёх: 95 запросов с паузой 24 с.

    slowdown = 1.0        # чтение: во сколько раз паузы между запросами длиннее обычных
    write_slowdown = 1.0  # действия аккаунта
    MAX_SLOWDOWN = 16.0

    def note_error(self, error: BaseException | str, write: bool = False) -> bool:
        """Учесть ошибку запроса. 429 и «слишком много попыток» — вдвое реже ходим на эту площадку."""
        text = str(error)
        if not re.search(r"\b429\b|Too Many Requests|Слишком много", text, re.IGNORECASE):
            return False
        attr = "write_slowdown" if write else "slowdown"
        before = getattr(self, attr)
        setattr(self, attr, min(before * 2, self.MAX_SLOWDOWN))
        # Серверная пауза общая для площадки: смена адреса её не сбрасывает.
        response = getattr(error, 'response', None)
        headers = getattr(response, 'headers', None) or getattr(error, 'headers', {}) or {}
        retry = headers.get('Retry-After') or headers.get('retry-after')
        seconds = float(self.pcfg.get('rate_limit_pause_sec', 30))
        if retry is not None:
            try:
                seconds = max(seconds, float(retry))
            except (TypeError, ValueError):
                try:
                    seconds = max(seconds, parsedate_to_datetime(str(retry)).timestamp() - time.time())
                except (TypeError, ValueError, OverflowError):
                    pass
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + max(0, seconds))
        if self.save_cooldown:
            self.save_cooldown(time.time() + max(0, self._cooldown_until - time.monotonic()))
        if getattr(self, attr) != before:
            log.warning("%s: площадка просит реже (429) — паузы %s ×%g", self.name,
                        "действий" if write else "чтения", getattr(self, attr))
        return True

    async def wait_read_slot(self) -> None:
        """Общая частота чтения для всех сессий одной площадки."""
        async with self._read_gate:
            while True:
                delay = max(self._next_read, self._cooldown_until) - time.monotonic()
                if delay <= 0:
                    break
                await asyncio.sleep(delay)
            self._next_read = time.monotonic() + self.request_delay * random.uniform(1.0, 1.2)

    def note_ok(self, write: bool = False) -> None:
        """Запрос прошёл — понемногу возвращаемся к обычному темпу."""
        attr = "write_slowdown" if write else "slowdown"
        if getattr(self, attr) > 1.0:
            setattr(self, attr, max(1.0, getattr(self, attr) * 0.9))

    async def start(self) -> None:
        """Авторизация и прочая подготовка. Вызывается один раз."""

    async def scan(self) -> list[Offer]:
        raise NotImplementedError

    @property
    def lookup_brands(self) -> set[str]:
        """Бренды, по которым lookup ищет точно (в своей категории)."""
        return set()

    async def lookup(self, product: ProductKey) -> list[Offer] | None:
        """Точный поиск конкурентов по одному товару (самые дешёвые объявления).

        Общий скан видит только часть площадки, поэтому перед тем как считать связку,
        цену продажи сверяем этим поиском. None — площадка так не умеет.
        """
        return None

    async def create_listing(self, product: ProductKey, title: str, description: str, price: float) -> str:
        raise NotImplementedError(f"{self.name}: выставление не поддерживается")

    async def update_price(self, external_id: str, price: float) -> None:
        raise NotImplementedError

    async def deactivate(self, external_id: str) -> None:
        raise NotImplementedError

    async def republish(self, external_id: str) -> None:
        """Вернуть в продажу ранее снятую карточку."""
        raise NotImplementedError

    async def own_listings(self) -> list[OwnListing]:
        """Наши карточки в продаже прямо сейчас (в том числе выставленные вручную)."""
        raise NotImplementedError

    async def buy(self, offer: Offer) -> str:
        """Купить объявление, вернуть идентификатор покупки (сделки)."""
        raise NotImplementedError(f"{self.name}: покупка через API не поддерживается")

    async def current_price(self, offer: Offer) -> float | None:
        """Цена объявления прямо сейчас (перед автопокупкой). None — площадка проверить не даёт.

        Если объявление снято или продано — исключение с понятным текстом.
        """
        return None

    async def purchased_goods(self, purchase_ref: str) -> str | None:
        """Товар (код/ссылка/данные), если площадка отдаёт его сразу после покупки."""
        return None

    async def deliver(self, chat_id: str | None, order_id: str, buyer: str, text: str) -> None:
        raise NotImplementedError

    def sells(self, product: ProductKey) -> bool:
        """Можно ли выставить такой товар на этой площадке."""
        return True

    async def deal_status(self, order_id: str) -> str | None:
        """Статус продажи на площадке (PAID, SENT, CONFIRMED, ROLLED_BACK…); None — площадка не сообщает."""
        return None

    on_purchase = None        # async (Purchase) — ставит run.py: площадка сообщает о нашей оплате у поставщика
    on_buyer_message = None   # async (BuyerMessage) — сообщение покупателя в чате продажи

    async def send_to_supplier(self, purchase_ref: str, text: str) -> None:
        """Написать продавцу в чат нашей покупки (ID игрока для пополнения)."""
        raise NotImplementedError

    def max_offline_days(self) -> float:
        """Продавец, который не заходил дольше, — не поставщик: заказ он не выдаст (rules.supplier_max_offline_days)."""
        return float(self.cfg.get_path("rules.supplier_max_offline_days", 3))

    def seller_gone(self, days: float | None) -> bool:
        return days is not None and days >= self.max_offline_days()

    checks_pay_price = False  # True — у площадки есть pay_price(): настоящая цена оплаты лота

    async def open_sales(self) -> list[Sale]:
        """Оплаченные, но ещё не выданные продажи на площадке — чтобы не потерять те, что пришли без бота."""
        return []

    async def listen(self, on_sale: SaleHandler, on_message: MessageHandler) -> None:
        """Бесконечно слушать продажи и сообщения. По умолчанию — ничего."""

    def parse(self, title: str, brand_hint: str | None = None) -> ProductKey | None:
        product = self.normalizer.parse(title, brand_hint)
        if product is None and brand_hint:
            # В разделе «Telegram → Premium» продавцы пишут просто «Premium 3 месяца»
            product = self.normalizer.parse(f"{brand_hint.replace('_', ' ')} {title}", brand_hint)
        return product


# Способ получения у поставщика: вход в чужой аккаунт не перепродаём никогда, а «подарком»
# (продавец сам дарит предмет или добавляет в друзья) годится только там, где и мы продаём подарком.
NOT_DELIVERABLE_RE = re.compile(r"(?<!без )заход|(?<!без )вход[а-я]* (на|в) аккаунт|by-login|логин")
CODE_RE = re.compile(r"\b(?:код|ключ|key)\b|gift\s*card|подарочн[а-я]*\s+карт|промокод", re.IGNORECASE)
DIRECT_TOPUP_RE = re.compile(
    r"\b(?:uid|id|player\s*id|тег|ник(?:нейм)?|email|почт[а-я]*)\b|"
    r"пополн(?:ение|ить)|зачисл(?:ение|ить)|на\s+аккаунт",
    re.IGNORECASE,
)
CARD_BRANDS = {"apple", "google_play", "psn", "xbox", "steam", "nintendo", "razer", "battlenet"}


_MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8,
           "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
_UNIT_DAYS = [("секунд", 1 / 86400), ("минут", 1 / 1440), ("час", 1 / 24), ("дн", 1), ("ден", 1), ("недел", 7), ("месяц", 30),
              ("год", 365), ("лет", 365)]


def offline_days(status: str, now: float | None = None) -> float | None:
    """«Онлайн», «Был 5 часов назад», «Был 2 месяца назад», «Был 15 октября» → сколько дней продавца не было.

    None — время входа неизвестно; выбор поставщика решает движок.
    """
    import datetime as dt
    s = (status or "").lower().replace("ё", "е")
    if not s:
        return None
    if "онлайн" in s or "в сети" in s or "сейчас" in s:
        return 0.0
    if "вчера" in s:
        return 1.0
    m = re.search(r"(\d+)?\s*(секунд|минут|час|дн|ден|недел|месяц|год|лет)", s)
    if m:
        days = next(d for unit, d in _UNIT_DAYS if m.group(2).startswith(unit))
        return float(int(m.group(1) or 1) * days)
    m = re.search(r"(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?", s)
    if m:
        month = next((n for stem, n in _MONTHS.items() if m.group(2).startswith(stem)), None)
        if month:
            today = dt.datetime.fromtimestamp(now or time.time())
            year = int(m.group(3)) if m.group(3) else today.year
            try:
                seen = dt.datetime(year, month, int(m.group(1)))
            except ValueError:
                return None
            if seen > today and not m.group(3):
                seen = seen.replace(year=year - 1)
            return max(0.0, (today - seen).total_seconds() / 86400)
    return None


def days_since(iso: str | None, now: float | None = None) -> float | None:
    """ISO-время последнего входа («2026-09-28T16:46:12.599441Z») → сколько дней назад."""
    import datetime as dt
    if not iso:
        return None
    try:
        seen = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, ((now or time.time()) - seen.timestamp()) / 86400)


def deliverable(how: str, brand: str) -> bool:
    how = how.lower()
    if NOT_DELIVERABLE_RE.search(how):
        return False
    return not ("подарк" in how and not brand.startswith(GIFT_BRANDS))


def code_delivery(offer: Offer) -> bool:
    """Товар поставщика выдаётся кодом, а не пополнением чужого аккаунта.

    Явная метка адаптера имеет приоритет. Для подарочных карт нормализованный
    бренд достаточен; для игровой валюты требуем слова «код/ключ/карта» и
    отклоняем объявления по ID, UID, тегу, нику или почте.
    """
    explicit = offer.raw.get("delivery_kind")
    if explicit:
        return explicit == "code"
    if not offer.product or offer.product.login:
        return False
    text = " ".join(str(x) for x in (offer.title, offer.raw.get("description", ""), offer.raw.get("delivery_method", "")) if x)
    if DIRECT_TOPUP_RE.search(text):
        return False
    return offer.product.brand in CARD_BRANDS or bool(CODE_RE.search(text))


def transfer_kind(offer: Offer) -> str:
    explicit = offer.raw.get("delivery_kind")
    if explicit in {"code", "id", "gift"}:
        return explicit
    if code_delivery(offer):
        return "code"
    text = " ".join(str(x) for x in (offer.title, offer.raw.get("description", ""), offer.raw.get("delivery_method", "")))
    if DIRECT_TOPUP_RE.search(text):
        return "id"
    if re.search(r"подар|gift", text, re.I):
        return "gift"
    return "unknown"


GIFT_BRANDS = ("telegram", "fortnite")   # fortnite: «подарок из магазина на N V-Bucks» (10.11)
