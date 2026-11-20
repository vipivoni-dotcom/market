"""Playerok: поиск, выставление, покупка с баланса, продажи и чаты (библиотека PlayerokAPI)."""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from pathlib import Path

from PlayerokAPI import Account
from PlayerokAPI.transport import Upload
from PlayerokAPI.updater import EventType

from ..covers import render_cover
from ..models import Offer, ProductKey
from ..normalize import competitor_keys
from .base import BuyerMessage, IncomingMessage, MessageHandler, OwnListing, Platform, Sale, SaleHandler, log

from ..normalize import GAME_UNITS  # noqa: E402 — один список игровых единиц на весь проект
AUTO_RE = re.compile(r"авто\s*-?\s*выдач|автовыдач|auto", re.IGNORECASE)
DEAL_RETRY_DELAY = 1.5  # секунд между поисками сделки после покупки
TITLE_LIMIT = 72  # длиннее Playerok название не принимает
ROOT = Path(__file__).resolve().parents[2]  # папка проекта: от неё считается listing.cover_dir

# Запросы со страницы выставления playerok.com: в библиотеке их нет.
OBTAINING_TYPES = """
query gameCategoryObtainingTypes($pagination: Pagination, $filter: GameCategoryObtainingTypeFilter!) {
    gameCategoryObtainingTypes(pagination: $pagination, filter: $filter) { edges { node { id name } } }
}
"""
ITEM_ATTRIBUTES = """
query item($id: UUID) { item(id: $id) { id attributes } }
"""
LIVE_STATUSES = ("APPROVED", "PENDING_MODERATION", "PENDING_APPROVAL")
DATA_FIELDS = """
query gameCategoryDataFields($pagination: Pagination, $filter: GameCategoryDataFieldFilter!) {
    gameCategoryDataFields(pagination: $pagination, filter: $filter) {
        edges { node { id label inputType required } }
    }
}
"""

# Код страны в ключе товара → начало подписи варианта в разделе Playerok («Германия (EUR)»).
COUNTRIES = {
    "US": "США", "EU": "Европа", "GB": "Великобритания", "DE": "Германия", "FR": "Франция", "ES": "Испания",
    "IT": "Италия", "NL": "Нидерланды", "AT": "Австрия", "BE": "Бельгия", "IE": "Ирландия", "PT": "Португалия",
    "FI": "Финляндия", "BG": "Болгария", "TR": "Турция", "IN": "Индия", "ID": "Индонезия", "PL": "Польша",
    "AE": "ОАЭ", "SA": "Саудовская Аравия", "QA": "Катар", "KW": "Кувейт", "KZ": "Казахстан", "BR": "Бразилия",
    "AR": "Аргентина", "MX": "Мексика", "CA": "Канада", "AU": "Австралия", "NZ": "Новая Зеландия", "JP": "Япония",
    "KR": "Южная Корея", "CN": "Китай", "HK": "Гонконг", "TW": "Тайвань", "SG": "Сингапур", "MY": "Малайзия",
    "TH": "Таиланд", "PH": "Филиппины", "VN": "Вьетнам", "CH": "Швейцария", "NO": "Норвегия", "ZA": "Южно-Африканская",
    "IL": "Израиль", "CL": "Чили", "CO": "Колумбия", "PE": "Перу", "UY": "Уругвай", "CR": "Коста-Рика",
    "MD": "Молдова", "HU": "Венгрия", "RU": "Россия",
}
# Регион по умолчанию, если в ключе его нет: так же его понимает нормализатор (USD — США, EUR — еврозона).
DEFAULT_COUNTRY = {"USD": "US", "EUR": "EU", "GBP": "GB"}
# Как продавцы подписывают единицу в названии: по «число + слово» поиск с сортировкой по цене отвечает быстро.
LOOKUP_WORDS = {"UC": ("UC",), "ROBUX": ("Robux", "робуксов"), "STARS": ("звезд",), "GEMS": ("гемов",),
                "DIAMONDS": ("алмазов",), "CRYSTALS": ("кристаллов",), "VP": ("VP",), "VBUCKS": ("V-Bucks",),
                "GOLD": ("голды",), "CP": ("CP",), "M": ("мес",)}
# Короткие имена брендов в файлах обложек data/cards3d (см. arb/covers3d/index.html).
COVER_PREFIX = {"google_play": "gp", "mobile_legends": "ml", "free_fire": "ff", "genshin": "gs", "telegram": "tg"}


def amount_text(amount: float) -> str:
    """Номинал как в ключе товара: 1000000, а не 1e+06 (так же называется файл обложки и ищутся конкуренты)."""
    return str(int(amount)) if float(amount).is_integer() else f"{amount:g}"


def fit_title(title: str) -> str:
    """Убрать хвостовые «| …», пока название не влезет в лимит Playerok."""
    while len(title) > TITLE_LIMIT and " | " in title:
        title = title.rsplit(" | ", 1)[0]
    return title[:TITLE_LIMIT]


def listing_attributes(product: ProductKey, options: list[dict], region_field: str | None,
                       static: dict, cat: dict | None = None) -> dict:
    """Атрибуты раздела по ключу товара. Не нашли подходящий вариант — ошибка, а не наугад.

    Необязательные настройки раздела (cat):
      amount_field — поле номинала, если оно называется не amount (у Razer Gold — «amout»);
      currency_values — вариант региона по валюте, когда региона в ключе нет (Steam: USD → global);
      tier_field + tiers — тариф подписки (discord_nitro-basic → nitro-basic, без тарифа — ключ "");
      months_field + months — срок подписки, когда это не число месяцев (1 → 30-days).
    """
    cat = cat or {}
    by_field: dict[str, list[dict]] = {}
    for o in options:
        by_field.setdefault(o["field"], []).append(o)
    attrs = {}
    amount_field = cat.get("amount_field", "amount")
    amount = by_field.get(amount_field)
    if amount:
        if amount[0]["type"] == "RANGE":
            attrs[amount_field] = int(product.amount) if float(product.amount).is_integer() else product.amount
        else:
            hit = next((o for o in amount if option_amount(o) == product.amount), None) \
                or next((o for o in amount if o["value"].lower() in ("other", "другое")), None)
            if not hit:
                raise RuntimeError(f"playerok: в разделе нет номинала {amount_text(product.amount)}")
            attrs[amount_field] = chosen(hit)
    if region_field:
        value = None if product.region else ((cat.get("currency_values") or {}).get(product.currency) or cat.get("default_region"))
        opts = by_field.get(region_field) or []
        hit = next((o for o in opts if o["value"] == value), None) if value else None
        attrs[region_field] = chosen(hit or region_option(product, opts))
    tier = product.brand.split("-", 1)[1] if "-" in product.brand else ""
    for field, wanted, label in ((cat.get("tier_field"), (cat.get("tiers") or {}).get(tier), f"тарифа {tier or 'обычный'}"),
                                 (cat.get("months_field"), (cat.get("months") or {}).get(amount_text(product.amount)),
                                  f"срока {amount_text(product.amount)} мес.")):
        if not field:
            continue
        hit = next((o for o in by_field.get(field, []) if o["value"] == wanted), None) if wanted else None
        if not hit:
            raise RuntimeError(f"playerok: в разделе нет {label}")
        attrs[field] = chosen(hit)
    for name, value in static.items():
        hit = next((o for o in by_field.get(name, []) if o["value"] == str(value)), None)
        if not hit:
            raise RuntimeError(f"playerok: в разделе нет варианта {name}={value}")
        attrs[name] = chosen(hit)
    # Переключатели («Особая акция» в Clash Royale) Playerok требует явно: не наш случай — false
    for name, opts in by_field.items():
        if name not in attrs and opts and opts[0].get("type") == "SWITCH":
            attrs[name] = False
    return attrs


def chosen(option: dict) -> str | list[str]:
    """Поле с множественным выбором (номинал Mobile Legends, регион Roblox) сайт хранит списком."""
    return [option["value"]] if option.get("multiple") else option["value"]


def option_amount(option: dict) -> float | None:
    """Номинал варианта. В Mobile Legends значение бывает и суммой (14 = «13+1»), и базой (250 = «250+25»),
    поэтому верим подписи: «250+25 алмазов» — это 275."""
    m = re.match(r"\s*(\d+)\s*\+\s*(\d+)", option["label"])
    if m:
        return float(int(m[1]) + int(m[2]))
    m = re.match(r"\s*(\d+)", option["label"]) or re.fullmatch(r"\s*(\d+)\s*", option["value"])
    return float(m[1]) if m else None


def region_option(product: ProductKey, options: list[dict]) -> dict:
    """Вариант валюты/региона: по коду региона игры (ru, global) или по стране и валюте карты."""
    region = (product.region or "").upper()
    if region:
        hit = next((o for o in options if o["value"].lower() == region.lower()), None)
        if hit:
            return hit
    by_currency = [o for o in options if o["label"].endswith(f"({product.currency})")]
    country = COUNTRIES.get(region or DEFAULT_COUNTRY.get(product.currency, ""))
    if country:
        hit = next((o for o in by_currency or options if o["label"].startswith(country)), None)
        if hit:
            return hit
    if not region and len(by_currency) == 1:
        return by_currency[0]
    raise RuntimeError(f"playerok: не понял регион для {product.key}: "
                       + ", ".join(o["label"] for o in by_currency or options[:10]))


def find_cover(folder: Path, product: ProductKey, *, require_style: bool = False) -> Path | None:
    """Файл обложки: gp_250_TRY_tr.png, ml_165_ru.png, ff_110.png, apple_25_TRY.png …"""
    amount = amount_text(product.amount)
    base_brand, _, tier = product.brand.partition("-")
    short = COVER_PREFIX.get(base_brand, base_brand) + (f"_{tier}" if tier else "")  # тариф подписки — своя обложка
    region = (product.region or "").lower()
    suffix = ('__comic' if product.currency in GAME_UNITS else '__luxe') if require_style else ''
    if product.currency in GAME_UNITS:
        names = [f"{short}_{amount}_{region}", f"{short}_{amount}"] if region else [f"{short}_{amount}"]
        found = [folder / f"{n}{suffix}.png" for n in names]
    else:
        base = f"{short}_{amount}_{product.currency}"
        found = [folder / f"{base}_{region}{suffix}.png"] if region else []
        found += [folder / f"{base}{suffix}.png"]
        # Обложка с регионом в имени без региона в ключе (gp_10_EUR_es) подходит, только если она одна.
        if not region:
            extra = sorted(p for p in folder.glob(f"{base}_*{suffix}.png")
                           if suffix or '__' not in p.stem)
            found += extra if len(extra) == 1 else []
    return next((p for p in found if p.is_file()), None)


class Playerok(Platform):
    name = "playerok"
    can_scan = True
    can_sell = True
    can_buy = True

    def __init__(self, cfg, normalizer) -> None:
        super().__init__(cfg, normalizer)
        token = self.pcfg.get("token") or None
        # Создание карточки везёт обложку ~1,5 МБ: стандартных 20 с библиотеки на это не хватает.
        self.acc = Account(token, timeout=float(self.pcfg.get("timeout_sec", 60)), proxy=self.proxy)
        # С токеном поиск площадки отдаёт только свои карточки, конкурентов не видно.
        # Поэтому цены ищем отдельной сессией без входа. С scan_proxies таких сессий несколько,
        # по одной на адрес: поиск идёт с них одновременно, а лимит запросов у каждого адреса свой.
        # Поиск отвечает за 0,5–2,5 с; зависший запрос ждать 20 с незачем — товар проверится в следующем цикле.
        read_timeout = float(self.pcfg.get("read_timeout_sec", 10))
        self.publics = ([Account(None, timeout=read_timeout, proxy=address) for address in self.scan_proxies]
                        if token else [self.acc])
        self.public = self.publics[0]
        self._free_readers: asyncio.Queue | None = None
        self.authorized = bool(token)
        self.my_id: str | None = None
        # deal_id нашей покупки → чат, чтобы пересылать сообщения поставщика
        self.purchase_chats: dict[str, str] = {}
        self._buy_lock = asyncio.Lock()
        # ключ товара → черновик, который создался, но не опубликовался
        self._drafts: dict[str, str] = {}
        self._cover_locks: dict[str, asyncio.Lock] = {}
        self._cover_tasks: dict[str, asyncio.Task] = {}
        self._cover_retry: dict[str, float] = {}
        # Поля разделов меняются редко: запрашиваем один раз за запуск.
        self._options_cache: dict[str, list[dict]] = {}
        self._obtaining_cache: dict[str, list[dict]] = {}
        self._own_keys: dict[str, str | None] = {}  # id своей карточки → ключ товара
        self._search_tasks: dict[tuple, asyncio.Task] = {}

    async def _read_search(self, acc, **kw):
        """Одинаковый поиск разделяет один запрос; все адреса соблюдают общий темп."""
        import json
        identity = 'public' if acc in self.publics else id(acc)
        key = (identity, json.dumps(kw, sort_keys=True, default=str))
        task = self._search_tasks.get(key)
        if task is None:
            async def run():
                await self.wait_read_slot()
                try:
                    return await acc.items.search(**kw)
                except Exception as e:
                    self.note_error(e)
                    raise
            task = asyncio.create_task(run())
            self._search_tasks[key] = task
            def finished(done):
                if self._search_tasks.get(key) is done:
                    del self._search_tasks[key]
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def prepare_cover(self, product: ProductKey) -> None:
        """Нарисовать обложку заранее, пока до карточки не дошла очередь выставления."""
        if self.sells(product):
            await self._cover(product)

    def cover_ready(self, product: ProductKey) -> bool:
        folder = self.cfg.get_path("listing.cover_dir")
        return not folder or find_cover(ROOT / folder, product, require_style=True) is not None or not self.cfg.get_path("listing.require_cover", True)

    def queue_cover(self, product: ProductKey) -> None:
        """Только локальная подготовка: не держит очередь внешних записей."""
        key = product.key
        if self.cover_ready(product) or key in self._cover_tasks or self._cover_retry.get(key, 0) > time.monotonic():
            return
        if not self.cfg.get_path("listing.auto_render_covers", True):
            return
        async def prepare():
            try:
                await self.prepare_cover(product)
            except Exception as e:
                self._cover_retry[key] = time.monotonic() + 900
                log.warning("playerok: подготовка обложки %s отложена на 15 мин: %s", key, e)
            finally:
                self._cover_tasks.pop(key, None)
        self._cover_tasks[key] = asyncio.create_task(prepare())

    async def start(self) -> None:
        if not self.authorized:
            log.info("playerok: токен не задан — только сканирование")
            return
        me = await self.acc.get_me()
        self.my_id = me.id
        self.own_seller_ids.add(me.id)
        log.info("playerok: вошли как %s", getattr(me, "username", me.id))

    # --- сканирование -----------------------------------------------------

    @property
    def readers(self) -> int:
        """Сколько поисков можно вести одновременно: по одному на адрес."""
        return len(self.publics)

    @contextlib.asynccontextmanager
    async def _reader(self):
        """Сессия без входа для поиска. При нескольких адресах каждый занят одним поиском за раз."""
        if len(self.publics) == 1:
            yield self.public
            return
        if self._free_readers is None:
            self._free_readers = asyncio.Queue()
            for acc in self.publics:
                self._free_readers.put_nowait(acc)
        acc = await self._free_readers.get()
        try:
            yield acc
        finally:
            self._free_readers.put_nowait(acc)

    async def scan(self) -> list[Offer]:
        offers: dict[str, Offer] = {}
        pages = int(self.pcfg.get("pages_per_query", 5))

        async def run(query: str) -> None:
            async with self._reader() as acc:
                after = None
                for _ in range(pages):
                    try:
                        # больше 24 за запрос площадка отвечает 403
                        page = await self._read_search(acc, query=query, first=24, after=after)
                    except Exception as e:  # noqa: BLE001
                        log.warning("playerok: поиск %r не удался: %s", query, e)
                        break
                    self.note_ok()  # иначе после одного 429 весь скан шёл бы с удвоенными паузами
                    for it in page.items:
                        offer = self._offer(it)
                        if offer:
                            offers[offer.offer_id] = offer
                    await asyncio.sleep(self.request_delay)
                    if not page.has_next_page:
                        break
                    after = page.end_cursor

        queries = self.pcfg.get("search_queries", [])
        if self.readers > 1:
            await asyncio.gather(*(run(query) for query in queries))  # запросы расходятся по адресам
        else:
            for query in queries:
                await run(query)
        return list(offers.values())

    @property
    def lookup_brands(self) -> set[str]:
        return set(self.pcfg.get("categories") or {})

    async def lookup(self, product: ProductKey) -> list[Offer]:
        async with self._reader() as acc:
            return await self._lookup(product, acc)

    async def _lookup(self, product: ProductKey, acc) -> list[Offer]:
        """Самые дешёвые объявления этого товара: категория + «100 INR» + сортировка по цене."""
        base = product.brand.split("-")[0]
        cat = (self.pcfg.get("categories") or {}).get(base) or {}
        amount = amount_text(product.amount)
        by_price = {"field": "price", "direction": "ASC"}
        if not cat.get("category_id"):
            searches = [(f"{base.replace('_', ' ')} {amount} {product.currency}", by_price)]
        elif product.currency in GAME_UNITS or product.currency == "M":
            # Продавцы пишут номинал по-разному: 60 UC, 60💎, 60 гемов. Сортировку по цене по одному числу
            # («100») Playerok в больших разделах не выдерживает — 40 с и таймаут. Поэтому: сортировка
            # по «число + единица» и отдельно самые подходящие по одному числу без сортировки.
            words = LOOKUP_WORDS.get(product.currency)
            searches = [(f"{amount} {w}", by_price) for w in words] if words else [(amount, by_price)]
            searches.append((amount, None))
        else:
            searches = [(f"{amount} {product.currency}", by_price)]
        offers: dict[str, Offer] = {}
        keys = set(competitor_keys(product.key))  # ML: объявления без региона в названии тоже конкуренты
        failed = tried = 0
        for query, sort in searches:
            if sort is None and len(offers) >= 3:
                break  # конкурентов уже хватает — запасной поиск без сортировки не нужен (меньше запросов, меньше 429)
            tried += 1
            after = None
            # По цене самые дешёвые уже на первой странице; без сортировки смотрим глубже
            for _ in range(1 if sort else int(self.pcfg.get("lookup_pages", 2))):
                try:
                    page = await self._read_search(acc, query=query, category_id=cat.get("category_id"),
                                                  first=24, after=after, sort=sort)
                except Exception as e:  # noqa: BLE001
                    log.info("playerok: поиск %r не ответил (%s)", query, e)
                    failed += 1
                    if re.search(r'\b429\b|Слишком много', str(e), re.I):
                        raise  # не выдаём неполный результат за проверенную цену
                    break
                self.note_ok()
                for it in page.items:
                    offer = self._offer(it, product.brand)
                    if offer and offer.key in keys:
                        offers[offer.offer_id] = offer
                await asyncio.sleep(self.request_delay)
                if not page.has_next_page:
                    break
                after = page.end_cursor
        if failed and failed == tried:
            raise RuntimeError(f"поиск Playerok не ответил ни на один запрос по {product.key}")
        return sorted(offers.values(), key=lambda o: o.price)

    async def _search_retry(self, acc=None, **kw):
        acc = acc or self.public
        try:
            return await self._read_search(acc, **kw)
        except Exception as e:  # noqa: BLE001
            log.info("playerok: поиск %r не ответил (%s), повторяю", kw.get("query"), e)
            await asyncio.sleep(max(3.0, self.request_delay))
            return await self._read_search(acc, **kw)

    def _offer(self, it, brand_hint: str | None = None) -> Offer | None:
        title = it.name or ""
        product = self.parse(title, brand_hint)
        if not product or not it.price:
            return None
        user = it.user
        return Offer(
            platform=self.name,
            offer_id=it.id,
            title=title,
            price=float(it.price),
            url=f"https://playerok.com/products/{it.slug or it.id}",
            seller=(user.username or "") if user else "",
            seller_id=user.id if user else "",
            seller_rating=user.rating if user else None,
            auto_delivery=bool(it.is_automated or AUTO_RE.search(title)),
            product=product,
        )

    # --- продажа ----------------------------------------------------------

    async def create_listing(self, product: ProductKey, title: str, description: str, price: float) -> str:
        return await self.create_listing_tracked(product, title, description, price, lambda _: None)

    async def recover_listing_drafts(self, attempts: list[dict]) -> dict[int, str]:
        """Только чтение: однозначно найти прежний черновик по ключу, названию и цене."""
        if not attempts or not self.my_id:
            return {}
        items, after, cursors = [], None, set()
        while True:
            page = await self._search_retry(self.acc, user_id=self.my_id, status="DRAFT", first=24, after=after)
            items.extend(page.items)
            if not page.has_next_page:
                break
            after = page.end_cursor
            if not after or after in cursors:
                raise RuntimeError("playerok: неполная пагинация черновиков")
            cursors.add(after)
            await asyncio.sleep(self.request_delay)
        found = {}
        for attempt in attempts:
            matches = [it for it in items if it.name == fit_title(attempt["title"])
                       and abs(float(it.price) - attempt["price"]) < 0.01]
            if len(matches) == 1 and await self._own_key(matches[0]) == attempt["key"]:
                found[attempt["id"]] = matches[0].id
        return found

    async def restore_listing_draft(self, key: str, external_id: str) -> bool:
        """Повтор допустим только для того же подтверждённого черновика владельца."""
        item = await self.acc.items.get(item_id=external_id)
        status = str(getattr(item.status, "value", item.status))
        if status != "DRAFT" or not item.user or item.user.id != self.my_id or await self._own_key(item) != key:
            return False
        self._drafts[key] = external_id
        return True

    async def create_listing_tracked(self, product: ProductKey, title: str, description: str,
                                     price: float, on_created) -> str:
        cat = (self.pcfg.get("categories") or {}).get(product.brand.split("-")[0])
        if not cat:
            raise RuntimeError(
                f"playerok: нет категории для бренда {product.brand!r} в platforms.playerok.categories"
            )
        # Всё проверяем до создания черновика: недозаполненная карточка на площадке хуже, чем никакой.
        fields = dict(cat.get("fields") or {})
        fields.update(await self._listing_fields(product, cat))
        # Прошлый раз черновик создался, а публикация упала (429, 502): публикуем его, а не плодим копии.
        draft = self._drafts.get(product.key)
        if draft:
            on_created(draft)
            # Цена в черновике — с прошлой попытки: ставим нынешнюю, иначе в базе и на сайте разойдутся.
            await self.acc.items.update(draft, {**fields, "price": price, "name": fit_title(title), "description": description})
            await self.acc.items.publish(draft)
            self._drafts.pop(product.key, None)
            return draft
        cover = await self._cover(product)
        item = await self.acc.items.create(
            game_category_id=cat["category_id"],
            name=fit_title(title),
            description=description,
            price=price,
            fields=fields,
            attachments=[cover] if cover else (),
        )
        self._drafts[product.key] = item.id
        on_created(item.id)  # SQLite фиксирует ID до публикации, включая случай перезапуска.
        await self.acc.items.publish(item.id)  # без тарифа библиотека берёт бесплатный
        self._drafts.pop(product.key, None)
        return item.id

    async def _listing_fields(self, product: ProductKey, cat: dict) -> dict:
        """Способ передачи, атрибуты раздела (номинал, валюта/регион) и поля для покупателя."""
        cid = cat["category_id"]
        obtaining = cat.get("obtaining")
        if not obtaining:
            raise RuntimeError(f"playerok: для {product.brand} не задан способ передачи (categories.*.obtaining)")
        types = await self._obtaining_types(cid)
        # У PSN старое имя способа в конфигурации, API теперь называет его подарочной картой.
        if product.brand == "psn" and obtaining == "Карта пополнения" and any(t["name"] == "Подарочная карта" for t in types):
            obtaining = "Подарочная карта"
        type_id = next((t["id"] for t in types if t["name"] == obtaining), None)
        if not type_id:
            raise RuntimeError(f"playerok: в разделе нет способа передачи «{obtaining}»: "
                               + ", ".join(t["name"] for t in types))
        options = await self._category_options(cid)
        attributes = listing_attributes(product, options, cat.get("region_field"), cat.get("attributes") or {}, cat)
        # «Пришлите ID игрока» — только для пополнения по ID/тегу; V-Bucks, VP, Robux продаём кодом.
        is_code = any(w in obtaining.lower() for w in ("промокод", "ключ", "карта", "ссылка", "код"))
        by_id = product.currency in GAME_UNITS and not is_code
        comment = "listing.currency_buyer_comment" if by_id else "listing.buyer_comment"
        if product.currency in GAME_UNITS and "подар" in obtaining.lower() and self.cfg.get_path("listing.gift_buyer_comment"):
            comment = "listing.gift_buyer_comment"  # звёзды подарком: нужен @username, а не ID игрока
        comment = cat.get("buyer_comment_key") or comment
        # «Пришлите ID игрока» → «тег игрока» (Supercell) или «никнейм» (Stumble Guys) — как просит раздел
        id_word = "тег игрока" if "тег" in obtaining.lower() else "никнейм" if "ник" in obtaining.lower() else None
        data_fields = []
        for f in await self._data_fields(cid, type_id):
            text = self.cfg.get_path("listing.item_data_note" if f["inputType"] == "INPUT" else comment)
            if text and id_word and by_id:
                text = text.replace("ID игрока", id_word)
            if text:
                data_fields.append({"fieldId": f["id"], "value": text})
        result = {"obtainingTypeId": type_id, "attributes": attributes}
        if data_fields:
            result["dataFields"] = data_fields
        return result

    async def _category_options(self, category_id: str) -> list[dict]:
        if category_id not in self._options_cache:
            self._options_cache[category_id] = (await self.acc.games.get_category(category_id=category_id)).options
        return self._options_cache[category_id]

    async def _obtaining_types(self, category_id: str) -> list[dict]:
        if category_id not in self._obtaining_cache:
            data = await self.acc.graphql.execute(
                OBTAINING_TYPES, {"pagination": {"first": 20}, "filter": {"gameCategoryId": category_id}},
                operation_name="gameCategoryObtainingTypes")
            self._obtaining_cache[category_id] = [e["node"] for e in data["gameCategoryObtainingTypes"]["edges"]]
        return self._obtaining_cache[category_id]

    async def _data_fields(self, category_id: str, obtaining_type_id: str) -> list[dict]:
        data = await self.acc.graphql.execute(
            DATA_FIELDS, {"pagination": {"first": 20}, "filter": {
                "gameCategoryId": category_id, "obtainingTypeId": obtaining_type_id, "type": "ITEM_DATA"}},
            operation_name="gameCategoryDataFields")
        return [e["node"] for e in data["gameCategoryDataFields"]["edges"]]

    async def _cover(self, product: ProductKey) -> Upload | None:
        folder = self.cfg.get_path("listing.cover_dir")
        if not folder:
            return None
        path = find_cover(ROOT / folder, product, require_style=True)  # абсолютный путь из конфига останется как есть
        if not path and self.cfg.get_path("listing.auto_render_covers", True):
            # Обложки нет — рисуем её сами по ключу товара тем же 3D-шаблоном.
            # Под замком по ключу: вторая задача за той же обложкой дождётся первой, а не нарисует заново.
            async with self._cover_locks.setdefault(product.key, asyncio.Lock()):
                path = find_cover(ROOT / folder, product, require_style=True)
                if not path:
                    try:
                        await render_cover(product.key, ROOT / folder, self.cfg.get_path("listing.cover_browser"),
                                           parallel=int(self.cfg.get_path("listing.cover_parallel", 3)))
                    except Exception as e:  # noqa: BLE001
                        raise RuntimeError(f"нет обложки для {product.key}, нарисовать сам не смог: {e}") from e
                    path = find_cover(ROOT / folder, product, require_style=True)
                    if not path:
                        raise RuntimeError(f"обложка {product.key} нарисована, но под другим именем — проверьте arb/covers3d")
        if path:
            return Upload(path.read_bytes(), path.name, "image/png")
        if self.cfg.get_path("listing.require_cover", True):
            raise RuntimeError(f"нет обложки для {product.key} в {folder}: отрисуйте её в arb/covers3d")
        return None

    async def update_price(self, external_id: str, price: float) -> None:
        await self.acc.items.update(external_id, {"price": price})

    async def deactivate(self, external_id: str) -> None:
        await self.acc.items.discontinue(external_id)

    async def republish(self, external_id: str) -> None:
        await self.acc.items.republish(external_id)

    async def own_listings(self) -> list[OwnListing]:
        if not self.authorized or not self.my_id:
            raise NotImplementedError  # без входа свои карточки не видны
        items = []
        # «В обработке» — тоже наша живая карточка: иначе только что выставленная считалась бы пропавшей.
        for status in LIVE_STATUSES:
            after = None
            while True:
                # Ошибку не глотаем: по неполному списку бот решил бы, что карточки пропали.
                page = await self._search_retry(self.acc, user_id=self.my_id, status=status, first=24, after=after)
                items += page.items
                await asyncio.sleep(self.request_delay)
                if not page.has_next_page:
                    break
                after = page.end_cursor
        return [OwnListing(it.id, it.name or "", float(it.price), await self._own_key(it)) for it in items]

    async def _own_key(self, item) -> str | None:
        """Ключ своей карточки. Регион Mobile Legends в названии не пишем — он в атрибутах карточки."""
        if item.id in self._own_keys:
            return self._own_keys[item.id]
        product = self.parse(item.name or "")
        if product and not product.region:
            base = product.brand.split("-")[0]
            region_field = ((self.pcfg.get("categories") or {}).get(base) or {}).get("region_field")
            if region_field and product.currency in GAME_UNITS:
                data = await self.acc.graphql.execute(ITEM_ATTRIBUTES, {"id": item.id}, operation_name="item")
                value = ((data.get("item") or {}).get("attributes") or {}).get(region_field)
                value = value[0] if isinstance(value, list) and value else value
                if isinstance(value, str) and value:
                    product.region = value.upper()
        key = product.key if product else None
        self._own_keys[item.id] = key
        return key

    async def deliver(self, chat_id: str | None, order_id: str, buyer: str, text: str) -> None:
        if not chat_id:
            chat_id = (await self.acc.deals.get(order_id)).chat_id
        await self.acc.chats.send(chat_id, text)
        # Отмечаем, что товар отправлен — покупатель подтвердит получение.
        # Код покупатель уже получил: сбой отметки не ошибка выдачи, иначе повтор отправил бы код второй раз.
        try:
            await self.acc.deals.update(order_id, {"status": "SENT"})
        except Exception as e:  # noqa: BLE001
            log.warning("playerok: код по сделке %s отправлен, но отметить «отправлено» не удалось: %s — "
                        "отметьте на сайте", order_id, e)

    def sells(self, product: ProductKey) -> bool:
        cat = (self.pcfg.get("categories") or {}).get(product.brand.split("-")[0])
        return bool(cat and cat.get("category_id"))

    async def deal_status(self, order_id: str) -> str | None:
        if not self.authorized:
            return None
        status = (await self.acc.deals.get(order_id)).status
        return str(getattr(status, "value", status)) if status else None

    async def open_sales(self) -> list[Sale]:
        if not self.authorized or not self.my_id:
            return []
        sales: list[Sale] = []
        after = None
        cursors: set[str] = set()
        while True:
            page = await self.acc.deals.search(
                filter={"userId": self.my_id, "direction": "OUT", "status": ["PAID"]},
                first=20, after=after,
            )
            sales.extend(self._sale(deal) for deal in page.items)
            if not page.has_next_page:
                return sales
            cursor = page.end_cursor
            if not cursor or cursor in cursors:
                raise RuntimeError("Playerok: пагинация оплаченных сделок вернула пустой или повторный курсор")
            cursors.add(cursor)
            after = cursor
            await asyncio.sleep(self.request_delay)

    def _sale(self, deal) -> Sale:
        item = deal.item
        return Sale(
            platform=self.name,
            order_id=deal.id,
            listing_external_id=item.id if item else None,
            title=(item.name if item else "") or "",
            buyer=(deal.user.username if deal.user else "") or "",
            chat_id=deal.chat_id,
            price=float(item.price) if item else 0.0,
        )

    # --- покупка ----------------------------------------------------------

    async def current_price(self, offer: Offer) -> float | None:
        data = await self.public.graphql.execute(
            "query item($id: UUID) { item(id: $id) { id price status } }", {"id": offer.offer_id}, operation_name="item")
        item = data.get("item") or {}
        if item.get("status") != "APPROVED":
            raise RuntimeError(f"объявление не в продаже (статус {item.get('status') or 'нет'})")
        return float(item["price"])

    async def buy(self, offer: Offer) -> str:
        async with self._buy_lock:  # иначе две покупки одного лота не различить
            # Сбой снимка прерывает покупку до оплаты: без него новую сделку не отличить от старой
            page = await self.acc.deals.search(filter={"direction": "IN"}, first=20)
            known = {deal.id for deal in page.items}
            tx = await self.acc.deals.create(offer.offer_id, "LOCAL")  # LOCAL — оплата с баланса
            # Транзакция не содержит id сделки — ищем новую покупку этого товара
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(DEAL_RETRY_DELAY)
                try:
                    page = await self.acc.deals.search(filter={"direction": "IN"}, first=20)
                except Exception as e:  # noqa: BLE001
                    log.warning("playerok: не нашёл сделку покупки %s: %s", offer.offer_id, e)
                    continue
                for deal in page.items:
                    if deal.id not in known and deal.item and deal.item.id == offer.offer_id:
                        if deal.chat_id:
                            self.purchase_chats[deal.chat_id] = deal.id
                        return deal.id
            return f"tx:{tx.id}"

    async def restore_purchases(self, deal_ids: list[str]) -> None:
        """После перезапуска вспомнить чаты своих покупок: иначе код поставщика, пришедший позже, бот не перешлёт."""
        if not self.authorized:
            return
        for deal_id in deal_ids:
            if deal_id in self.purchase_chats.values():
                continue
            try:
                chat_id = (await self.acc.deals.get(deal_id)).chat_id
            except Exception as e:  # noqa: BLE001
                log.info("playerok: чат покупки %s не найден: %s", deal_id, e)
                continue
            if chat_id:
                self.purchase_chats[chat_id] = deal_id
            await asyncio.sleep(self.request_delay)

    # --- события ----------------------------------------------------------

    async def listen(self, on_sale: SaleHandler, on_message: MessageHandler) -> None:
        if not self.authorized:
            return
        listener = self.acc.listener(events=[EventType.NEW_DEAL, EventType.NEW_MESSAGE])

        @listener.on(EventType.NEW_DEAL)
        async def _deal(event) -> None:
            deal = event.deal
            if not deal or deal.is_purchase:
                if deal and deal.chat_id:
                    self.purchase_chats[deal.chat_id] = deal.id
                return
            await on_sale(self._sale(deal))

        @listener.on(EventType.NEW_MESSAGE)
        async def _message(event) -> None:
            msg = event.message
            chat_id = event.chat_id
            if not msg or (msg.user and msg.user.id == self.my_id):
                return
            if chat_id not in self.purchase_chats:
                # Чат нашей продажи: покупатель пишет ID игрока или вопрос. Чей это чат, решает Orders.
                if msg.text and msg.user and self.on_buyer_message:
                    await self.on_buyer_message(BuyerMessage(self.name, chat_id, msg.text))
                return
            text = msg.text
            if text:
                await on_message(IncomingMessage(self.name, self.purchase_chats[chat_id], chat_id, text))

        while True:
            try:
                await listener.run()
                log.warning("playerok: слушатель завершился, переподключаюсь через 10 с")
            except Exception as e:  # noqa: BLE001
                log.warning("playerok: слушатель упал (%s), переподключаюсь через 10 с", e)
            await asyncio.sleep(10)  # и после тихого выхода: иначе цикл крутился бы без пауз
