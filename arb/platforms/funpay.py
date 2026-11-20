"""FunPay — публичный источник предложений для ручной закупки, без входа в аккаунт."""

from __future__ import annotations

import asyncio
import re
import threading
import time

import requests
from bs4 import BeautifulSoup
from lxml import etree
from lxml import html as lxml_html

from ..fees import seller_price_ratio
from ..models import Offer, ProductKey
from .base import IncomingMessage, MessageHandler, Platform, Purchase, Sale, SaleHandler, deliverable, log, offline_days

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
OFFER_ID_RE = re.compile(r"id=(\d+)")
_PAID_RE = re.compile(r"Покупатель (\S+) оплатил заказ #([A-Z0-9]{8})\.\s*(.*?)(?:\s*\S+, не забудьте потом нажать|$)", re.S)


def seller_status(offer_html: str) -> str:
    """«Онлайн» / «Был 5 часов назад» — строка под ником продавца на странице лота."""
    soup = BeautifulSoup(offer_html, "lxml")
    el = soup.select_one(".param-item .media-user-status") or soup.select_one(".media-user-status")
    return el.get_text(" ", strip=True) if el else ""


def paid_goods(order_html: str) -> str | None:
    """Блок «Оплаченный товар» на странице заказа FunPay."""
    soup = BeautifulSoup(order_html, "lxml")
    for item in soup.select("div.param-item"):
        head = item.find("h5")
        if head and "оплаченный товар" in head.get_text(" ", strip=True).lower():
            head.extract()
            text = item.get_text("\n", strip=True)
            return text or None
    return None


def session_account(golden_key: str, proxy: str | None = None):
    """FunPayAPI.Account, который хранит все cookie сервера.

    С ноября 2026 FunPay выдаёт cookie golden_seal и без неё отвечает на runner/ кодом 400
    («Необходимая cookie отсутствует или устарела»). Библиотека 1.1.0 шлёт только golden_key
    и PHPSESSID, поэтому запросы идут через requests.Session с полным набором cookie.
    """
    from FunPayAPI import Account
    from FunPayAPI.common import exceptions

    class SessionAccount(Account):
        def method(self, request_method, api_method, headers, payload, exclude_phpsessid=False,
                   raise_not_200=False):
            http = self.__dict__.setdefault("_http", requests.Session())
            http.cookies.set("golden_key", self.golden_key, domain="funpay.com")
            if exclude_phpsessid:
                for name in ("PHPSESSID", "golden_seal"):
                    http.cookies.pop(name, None)
            elif self.phpsessid and http.cookies.get("PHPSESSID") != self.phpsessid:
                http.cookies.set("PHPSESSID", self.phpsessid, domain="funpay.com")
            headers.pop("cookie", None)
            if self.user_agent:
                headers["user-agent"] = self.user_agent
            link = api_method if api_method.startswith("https://funpay.com") else "https://funpay.com/" + api_method
            response = http.request(request_method.upper(), link, headers=headers, data=payload,
                                    timeout=self.requests_timeout, proxies=self.proxy or {})
            if response.status_code == 403:
                raise exceptions.UnauthorizedError(response)
            if response.status_code != 200 and raise_not_200:
                raise exceptions.RequestFailedError(response)
            return response

    return SessionAccount(golden_key, user_agent=UA, proxy={"http": proxy, "https": proxy} if proxy else None)


def _by_class(tag: str, name: str) -> etree.XPath:
    return etree.XPath(f'.//{tag}[contains(concat(" ", normalize-space(@class), " "), " {name} ")]')


_ROWS, _DESC, _PRICE = _by_class("a", "tc-item"), _by_class("*", "tc-desc-text"), _by_class("*", "tc-price")
_REVIEWS = _by_class("*", "rating-mini-count")
_STARS, _NAME = _by_class("*", "rating-stars"), _by_class("*", "media-user-name")


def _first(found: list):
    return found[0] if found else None


class FunPay(Platform):
    name = "funpay"
    can_scan = True
    can_sell = False
    can_buy = False  # закупка владельцем в браузере

    def __init__(self, cfg, normalizer) -> None:
        super().__init__(cfg, normalizer)
        self.acc = None  # FunPayAPI.Account после start()
        self.purchase_chats: dict[str, str] = {}  # чат с продавцом → номер нашего заказа у него
        self._section_cache: dict[int, tuple[float, list[Offer]]] = {}  # раздел → (когда, объявления)

    async def start(self) -> None:
        # Даже сохранённый старый ключ не разрешает вход или операции аккаунта.
        self.acc = None
        self.can_sell = self.can_buy = False
        log.info("funpay: публичный поставщик без авторизации; закупка вручную, чаты и заказы отключены")

    # --- сканирование -----------------------------------------------------

    SECTION_CACHE_SEC = 45 * 60  # сколько живут прошлые цены раздела, который не прочитался

    async def scan(self) -> list[Offer]:
        result: list[Offer] = []
        failed: list[tuple[str, int]] = []
        for brand, section in (self.pcfg.get("sections") or {}).items():
            found = await self._scan_section(brand, int(section))
            if found is None:
                failed.append((brand, int(section)))
            else:
                result.extend(found)
            # Пауза и после отказа тоже: без неё следующий раздел уходил через 0,2 с и тоже получал 429 —
            # 12.11 так пропало по 7–8 разделов за скан, и бот снял 22 карточки как «невыгодные».
            await asyncio.sleep(self.request_delay)
        for brand, section in failed:  # вторая попытка — уже в замедленном темпе
            found = await self._scan_section(brand, section)
            if found is None:
                at, found = self._section_cache.get(section, (0.0, []))
                if time.time() - at > self.SECTION_CACHE_SEC:
                    found = []
                log.warning("funpay: раздел %s не прочитался дважды — беру прошлые цены: %d объявлений", section, len(found))
            result.extend(found)
            await asyncio.sleep(self.request_delay)
        return result

    async def _scan_section(self, brand: str, section: int) -> list[Offer] | None:
        """Объявления раздела или None, если страница не прочиталась."""
        await self.wait_read_slot()
        try:
            # Страница раздела — до десятков мегабайт и тысячи строк: и загрузка, и разбор идут в отдельном
            # потоке. Разбор в основном потоке на секунды останавливал весь бот — Telegram, заказы, другие сканы.
            found = await asyncio.to_thread(self._section, f"https://funpay.com/lots/{section}/", brand,
                                            section, self.next_scan_proxy())
        except Exception as e:  # noqa: BLE001
            log.warning("funpay: раздел %s не прочитался: %s", section, e)
            self.note_error(e)
            return None
        self.note_ok()
        self._section_cache[section] = (time.time(), found)
        return found

    def _section(self, url: str, brand: str, section: int, proxy: str | None = None) -> list[Offer]:
        html = self._get(url, proxy)
        # HTTP 200 с защитной страницей — отказ чтения, а не пустой каталог.
        root = lxml_html.fromstring(html)
        if not _ROWS(root) and not root.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " tc-table ")]'):
            raise RuntimeError("funpay: публичный раздел недоступен — нет таблицы предложений")
        return self._parse(html, brand, section)

    @staticmethod
    def _get(url: str, proxy: str | None = None) -> str:
        resp = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ru"}, cookies={"cy": "rub"},
                            timeout=30, proxies={"http": proxy, "https": proxy} if proxy else None)
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def deliverable(row, brand: str) -> bool:
        """Фильтры FunPay (data-f-*: способ получения и т.п.)."""
        attrs = row.attrs if hasattr(row, "attrs") else row.attrib
        return deliverable(" ".join(v for k, v in attrs.items() if k.startswith("data-f-") and isinstance(v, str)), brand)

    def _parse(self, html: str, brand: str, section: int) -> list[Offer]:
        """Объявления раздела. Быстрый разбор (lxml напрямую, в 5–10 раз быстрее BeautifulSoup);
        если страница ему не далась — прежний разбор."""
        try:
            return self._parse_fast(html, brand, section)
        except Exception as e:  # noqa: BLE001
            log.info("funpay: быстрый разбор раздела %s не удался (%s), разбираю по-старому", section, e)
            return self._parse_soup(html, brand, section)

    def _parse_fast(self, html: str, brand: str, section: int) -> list[Offer]:
        root = lxml_html.fromstring(html)
        offers = []
        for row in _ROWS(root):
            desc, price_el = _first(_DESC(row)), _first(_PRICE(row))
            if desc is None or price_el is None or not price_el.get("data-s"):
                continue
            title = " ".join(t for t in (s.strip() for s in desc.itertext()) if t)
            if not self.deliverable(row, brand):
                continue
            product = self.parse(title, brand)
            if not product:
                continue
            href = row.get("href", "")
            m = OFFER_ID_RE.search(href)
            stars = _first(_STARS(row))
            rm = re.search(r"rating-(\d)", stars.get("class", "")) if stars is not None else None
            reviews = _first(_REVIEWS(row))
            count = re.sub(r"\D", "", "".join(reviews.itertext())) if reviews is not None else ""
            name_el = _first(_NAME(row))
            offers.append(Offer(
                platform=self.name,
                offer_id=m.group(1) if m else href,
                title=title,
                price=float(price_el.get("data-s")),
                url=href,
                seller="".join(s.strip() for s in name_el.itertext()) if name_el is not None else "",
                seller_id=str(row.get("data-user") or ""),
                seller_rating=float(rm.group(1)) if rm else None,
                auto_delivery=row.get("data-auto") == "1",
                product=product,
                raw={"section": section, "seller_reviews": int(count) if count else None, "delivery_method": " ".join(str(v) for k, v in row.attrib.items() if k.startswith("data-f-"))},
            ))
        return offers

    def _parse_soup(self, html: str, brand: str, section: int) -> list[Offer]:
        soup = BeautifulSoup(html, "lxml")
        offers = []
        for row in soup.select("a.tc-item"):
            desc = row.select_one(".tc-desc-text")
            price_el = row.select_one(".tc-price")
            if not desc or not price_el or not price_el.get("data-s"):
                continue
            title = desc.get_text(" ", strip=True)
            if not self.deliverable(row, brand):
                continue
            product = self.parse(title, brand)
            if not product:
                continue
            m = OFFER_ID_RE.search(row.get("href", ""))
            stars = row.select_one(".rating-stars")
            rating = None
            if stars:
                rm = re.search(r"rating-(\d)", " ".join(stars.get("class", [])))
                rating = float(rm.group(1)) if rm else None
            reviews = row.select_one(".rating-mini-count")
            count = re.sub(r"\D", "", reviews.get_text()) if reviews is not None else ""
            name_el = row.select_one(".media-user-name")
            offers.append(Offer(
                platform=self.name,
                offer_id=m.group(1) if m else row.get("href", ""),
                title=title,
                price=float(price_el["data-s"]),
                url=row.get("href", ""),
                seller=name_el.get_text(strip=True) if name_el else "",
                seller_id=str(row.get("data-user") or ""),
                seller_rating=rating,
                auto_delivery=row.get("data-auto") == "1",
                product=product,
                raw={"section": section, "seller_reviews": int(count) if count else None, "delivery_method": " ".join(str(v) for k, v in row.attrs.items() if k.startswith("data-f-"))},
            ))
        return offers

    # --- выставление ------------------------------------------------------

    async def create_listing(self, product: ProductKey, title: str, description: str, price: float) -> str:
        if not self.acc:
            raise RuntimeError("funpay: нужен golden_key")
        brand = product.brand.split("-")[0]  # discord_nitro-basic → раздел discord_nitro
        section = (self.pcfg.get("sections") or {}).get(brand)
        if not section:
            raise RuntimeError(f"funpay: нет раздела для бренда {brand!r}")
        extra = ((self.pcfg.get("lot_fields") or {}).get(brand)) or {}
        return await asyncio.to_thread(self._create_lot, int(section), title, description, self._seller_price(price), extra)

    def _seller_price(self, buyer_price: float) -> float:
        """В лот вводится цена без комиссии FunPay, покупатель увидит её с комиссией."""
        return round(buyer_price / seller_price_ratio(self.cfg, self.name), 2)

    def _create_lot(self, node: int, title: str, description: str, price: float, extra: dict) -> str:
        from FunPayAPI import types

        headers = {"accept": "*/*", "x-requested-with": "XMLHttpRequest"}
        resp = self.acc.method("get", f"lots/offerEdit?node={node}", headers, {}, raise_not_200=True)
        soup = BeautifulSoup(resp.json()["html"], "html.parser")
        fields = {f["name"]: f.get("value") or "" for f in soup.find_all("input") if f.get("name")}
        fields.update({f["name"]: f.text or "" for f in soup.find_all("textarea") if f.get("name")})
        for sel in soup.find_all("select"):
            opt = sel.find("option", selected=True) or sel.find("option")
            if sel.get("name") and opt:
                fields[sel["name"]] = opt.get("value", "")
        fields.update({
            "offer_id": "0",
            "node_id": str(node),
            "fields[summary][ru]": title,
            "fields[summary][en]": title,
            "fields[desc][ru]": description,
            "price": str(price),
            "amount": "1",
            "active": "on",
            "deactivate_after_sale[]": "on",
        })
        fields.update({k: str(v) for k, v in extra.items()})
        lot = types.LotFields(0, fields)
        self.acc.save_lot(lot)
        # Лот уже создан: ошибка поиска не должна выглядеть как неудача, иначе повтор создаст дубликат
        try:
            found = self._find_my_lot(node, title)
        except Exception as e:  # noqa: BLE001
            log.warning("funpay: не нашёл созданный лот %r: %s", title[:40], e)
            self.note_error(e)
            found = None
        return found or f"node{node}:{title[:40]}"

    def _find_my_lot(self, node: int, title: str) -> str | None:
        """FunPay не возвращает id нового лота — ищем его в своих лотах раздела (страница видна только после входа)."""
        html = self.acc.method("get", f"lots/{node}/trade", {"accept": "*/*"}, {}, raise_not_200=True).text
        soup = BeautifulSoup(html, "lxml")
        for row in soup.select("a.tc-item"):
            desc = row.select_one(".tc-desc-text")
            if desc and title[:40] in desc.get_text(" ", strip=True):
                m = OFFER_ID_RE.search(row.get("href", ""))
                if m:
                    return m.group(1)
        return None

    def _resolve_lot_id(self, lot_id: str) -> int:
        """Заглушка node<id>:<название> остаётся, пока лот не нашли после публикации — ищем его заново."""
        if not lot_id.startswith("node"):
            return int(lot_id)
        node, _, title = lot_id.removeprefix("node").partition(":")
        found = self._find_my_lot(int(node), title)
        if not found:
            raise RuntimeError(f"funpay: лот {title!r} не найден в разделе {node}")
        return int(found)

    async def update_price(self, external_id: str, price: float) -> None:
        await asyncio.to_thread(self._edit_lot, external_id, {"price": str(self._seller_price(price))})

    async def deactivate(self, external_id: str) -> None:
        await asyncio.to_thread(self._edit_lot, external_id, {"active": None})

    def _edit_lot(self, lot_id: str, changes: dict) -> None:
        lot = self.acc.get_lot_fields(self._resolve_lot_id(lot_id))
        fields = lot.fields
        for k, v in changes.items():
            if v is None:
                fields.pop(k, None)
            else:
                fields[k] = v
        lot.set_fields(fields)
        self.acc.save_lot(lot)

    # --- заказы -----------------------------------------------------------

    async def deliver(self, chat_id: str | None, order_id: str, buyer: str, text: str) -> None:
        def send() -> None:
            cid = chat_id
            if not cid:
                chat = self.acc.get_chat_by_name(buyer, True)
                if not chat:
                    raise RuntimeError(f"funpay: не найден чат с {buyer}")
                cid = chat.id
            self.acc.send_message(cid, text)

        await asyncio.to_thread(send)

    checks_pay_price = True

    async def pay_price(self, offer: Offer, method: str = "sbp") -> float | None:
        """Цена лота-поставщика, если продавец заходил недавно; None — давно не был, заказ не выдаст.

        Комиссию за способ оплаты считает buy_fee_pct: цена в скане уже по СБП.
        """
        cache = getattr(self, "_supplier_activity", None)
        if cache is None:
            cache = self._supplier_activity = {}
        identity = offer.seller_id
        hit = cache.get(identity) if identity else None
        if hit and time.time() - hit[0] < 3600:
            checked_at, days = hit
            status = "cached"
        else:
            await self.wait_read_slot()
            try:
                html = await asyncio.to_thread(self._get, offer.url, self.next_scan_proxy())
            except Exception as exc:
                self.note_error(exc)
                raise
            self.note_ok()
            status = seller_status(html)
            days = offline_days(status)
            checked_at = time.time()
            if days is not None and identity:
                cache[identity] = (checked_at, days)
        offer.raw["seller_activity_checked_at"] = checked_at
        offer.raw["seller_offline_days"] = days
        if self.seller_gone(days):
            offer.raw["reject_reason"] = "seller_offline"
            log.info("funpay: продавец лота %s %s — не беру в поставщики", offer.offer_id, status.lower())
            return None
        return offer.price

    def _on_chat_message(self, m, types, on_message):
        """Сообщение в чате FunPay → что с ним делать (корутина) или None.

        «Покупатель <мы> оплатил заказ #XXXXXXXX. <лот>» — это наша закупка: владелец оплатил лот поставщика
        в браузере под этим же аккаунтом. Дальше сообщения продавца из этого чата — код или вопросы.
        """
        text, chat = (m.text or "").strip(), str(m.chat_id)
        if m.type == types.ORDER_PURCHASED:
            hit = _PAID_RE.search(text)
            if not hit or hit.group(1).lower() != str(self.acc.username).lower() or not self.on_purchase:
                return None  # оплатили у нас — это продажа, её ведёт NewOrderEvent
            self.purchase_chats[chat] = hit.group(2)
            title = hit.group(3).strip()
            product = self.parse(title)
            return self.on_purchase(Purchase(self.name, hit.group(2), chat, title, m.chat_name or "",
                                             product.key if product else None))
        if m.type == types.NON_SYSTEM and chat in self.purchase_chats and text and m.author_id != self.acc.id:
            return on_message(IncomingMessage(self.name, self.purchase_chats[chat], chat, text))
        return None

    async def purchased_goods(self, purchase_ref: str) -> str | None:
        """Оплаченный товар со страницы заказа: при автовыдаче код лежит там сразу после оплаты."""
        order = await asyncio.to_thread(self.acc.get_order, purchase_ref)
        return paid_goods(order.html)

    async def send_to_supplier(self, purchase_ref: str, text: str) -> None:
        chat = next((c for c, ref in self.purchase_chats.items() if ref == purchase_ref), None)
        if not chat:
            raise RuntimeError(f"чат заказа {purchase_ref} неизвестен")
        await asyncio.to_thread(self.acc.send_message, int(chat) if chat.isdigit() else chat, text)

    async def restore_purchases(self, refs: list[str]) -> None:
        """В публичном режиме заказы и чаты сверяет владелец вручную."""
        if not self.acc:
            return  # публичный поставщик: заказы владелец сверяет вручную
        for ref in refs:
            order = await asyncio.to_thread(self.acc.get_order, ref)
            chat = await asyncio.to_thread(self.acc.get_chat_by_name, order.seller_username, True)
            if chat:
                self.purchase_chats[str(chat.id)] = ref

    async def listen(self, on_sale: SaleHandler, on_message: MessageHandler) -> None:
        if not self.acc:
            return
        from FunPayAPI.common.enums import MessageTypes
        from FunPayAPI.updater.events import NewMessageEvent, NewOrderEvent
        from FunPayAPI.updater.runner import Runner

        loop = asyncio.get_running_loop()

        def report(future) -> None:
            if not future.cancelled() and future.exception():
                log.error("funpay: обработка продажи упала: %s", future.exception())

        def worker() -> None:
            runner = Runner(self.acc)  # второй Runner на аккаунт библиотека не разрешает
            while True:
                try:
                    for event in runner.listen(requests_delay=6):
                        if isinstance(event, NewOrderEvent):
                            o = event.order
                            sale = Sale(self.name, o.id, None, o.description, o.buyer_username, None, float(o.price))
                            asyncio.run_coroutine_threadsafe(on_sale(sale), loop).add_done_callback(report)
                        elif isinstance(event, NewMessageEvent):
                            coro = self._on_chat_message(event.message, MessageTypes, on_message)
                            if coro:
                                asyncio.run_coroutine_threadsafe(coro, loop).add_done_callback(report)
                    log.warning("funpay: поток событий завершился, переподключаюсь через 10 с")
                except Exception as e:  # noqa: BLE001
                    log.warning("funpay: слушатель упал (%s), переподключаюсь через 10 с", e)
                time.sleep(10)

        threading.Thread(target=worker, name="funpay-runner", daemon=True).start()
