"""Поиск связок, выставление карточек и переоценка."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import statistics
import time
from collections import Counter, defaultdict
from copy import deepcopy

from .config import ROOT, Config
from .db import DB
from .fees import buy_cost, min_sell_price, net_income, pay_method
from .fx import FX
from .games import GAMES, UNITS
from .models import Offer, Opportunity, ProductKey
from .normalize import competitor_keys
from .suppliers import activity
from .notify import Notifier
from .platforms.base import Platform, code_delivery, transfer_kind

log = logging.getLogger("arb.engine")

BRAND_TITLES = {
    "apple": "App Store & iTunes", "google_play": "Google Play", "psn": "PlayStation Store",
    "xbox": "Xbox", "steam": "Steam", "roblox": "Roblox", "nintendo": "Nintendo eShop",
    "razer": "Razer Gold", "battlenet": "Battle.net", "pubg": "PUBG Mobile", "telegram": "Telegram",
    "brawl_stars": "Brawl Stars", "clash_royale": "Clash Royale", "clash_of_clans": "Clash of Clans",
    "genshin": "Genshin Impact", "free_fire": "Free Fire", "mobile_legends": "Mobile Legends",
    "valorant": "Valorant", "fortnite": "Fortnite", "telegram_premium": "Telegram Premium",
    "discord_nitro": "Discord Nitro", "spotify": "Spotify Premium", "chatgpt": "ChatGPT",
    "youtube_premium": "YouTube Premium", "xbox_game_pass": "Xbox Game Pass", "ps_plus": "PlayStation Plus",
    "honkai_star_rail": "Honkai: Star Rail", "zenless_zone_zero": "Zenless Zone Zero",
    "wuthering_waves": "Wuthering Waves", "codm": "Call of Duty: Mobile", "fc_mobile": "EA SPORTS FC Mobile",
    "honor_of_kings": "Honor of Kings",
}
# Игровая валюта: код → как писать в карточке
UNIT_TITLES = {
    "UC": "UC", "STARS": "звёзд", "ROBUX": "Robux", "GEMS": "гемов", "DIAMONDS": "алмазов",
    "CRYSTALS": "кристаллов", "VP": "VP", "GOLD": "золота", "VBUCKS": "V-Bucks",
    "SHARDS": "древних снов", "MONOCHROME": "монохромов", "LUNITE": "лунитов", "CP": "CP",
    "FCPOINTS": "FC Points", "TOKENS": "жетонов",
}
# Для названий карточек: единица по числу (1 звезда, 43 звезды, 13 звёзд) и значок товара.
UNIT_FORMS = {
    "STARS": ("звезда", "звезды", "звёзд"), "GEMS": ("гем", "гема", "гемов"), "DIAMONDS": ("алмаз", "алмаза", "алмазов"),
    "CRYSTALS": ("кристалл", "кристалла", "кристаллов"), "SHARDS": ("древний сон", "древних сна", "древних снов"),
    "MONOCHROME": ("монохром", "монохрома", "монохромов"), "LUNITE": ("лунит", "лунита", "лунитов"),
    "TOKENS": ("жетон", "жетона", "жетонов"), "M": ("месяц", "месяца", "месяцев"),
}
UNIT_ICONS = {"STARS": "⭐", "DIAMONDS": "💎", "GEMS": "💎", "CRYSTALS": "💠", "SHARDS": "💠", "MONOCHROME": "💠",
              "LUNITE": "💠", "UC": "🔶", "CP": "🔶", "ROBUX": "🟢", "VBUCKS": "🔷", "VP": "🔺", "GOLD": "🟡",
              "FCPOINTS": "⚽", "TOKENS": "🪙"}
# Как покупатель получает донат: по способу передачи в разделе Playerok
UID_BRANDS = {"genshin", "honkai_star_rail", "zenless_zone_zero", "wuthering_waves"}
# Игры и единицы из covers3d/games.json
for _code, _u in UNITS.items():
    UNIT_FORMS.setdefault(_code, tuple(_u["forms"]))
    UNIT_TITLES.setdefault(_code, _u["forms"][2])
    UNIT_ICONS.setdefault(_code, _u.get("icon", "🪙"))
for _brand, _g in GAMES.items():
    BRAND_TITLES.setdefault(_brand, _g["title"])
    if "UID" in _g.get("subtitle", ""):
        UID_BRANDS.add(_brand)
# Страна карты по валюте, когда региона в ключе нет (EUR — еврозона, флаг ЕС)
CURRENCY_COUNTRY = {"TRY": "TR", "INR": "IN", "IDR": "ID", "PLN": "PL", "USD": "US", "BRL": "BR", "JPY": "JP", "EUR": "EU",
                    "GBP": "GB", "KZT": "KZ", "ARS": "AR", "MXN": "MX", "CAD": "CA", "AUD": "AU", "HKD": "HK", "MYR": "MY",
                    "PHP": "PH", "CLP": "CL", "NOK": "NO", "CHF": "CH", "AED": "AE", "SAR": "SA", "ZAR": "ZA", "NZD": "NZ",
                    "COP": "CO", "PEN": "PE", "THB": "TH", "CNY": "CN"}


def plural(n: float, forms: tuple[str, str, str]) -> str:
    if not float(n).is_integer():
        return forms[1]
    n = int(n)
    a, b = n % 100, n % 10
    return forms[2] if 10 < a < 20 else forms[0] if b == 1 else forms[1] if 1 < b < 5 else forms[2]


def flag(code: str | None) -> str:
    """Флаг страны эмодзи: TR → 🇹🇷. GLOBAL, RU-регион доната и непонятные коды — без флага."""
    code = (code or "").upper()
    if code == "UK":
        code = "GB"
    if len(code) != 2 or not code.isalpha() or code == "RU":
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)


def how_to_get(base: str, obtaining: str | None) -> str:
    obtaining = (obtaining or "").lower()
    if base in UID_BRANDS:
        return "По UID"
    if "тег" in obtaining:
        return "По тегу"
    if "ник" in obtaining:
        return "По никнейму"
    if "подар" in obtaining:
        return "Подарком"
    if "код" in obtaining:
        return "Код"
    return "По ID"


class Engine:
    AUDIT_FILE = ROOT / "data" / "cycle-audit.jsonl"
    def __init__(self, cfg: Config, db: DB, platforms: dict[str, Platform], notify: Notifier) -> None:
        self.cfg = cfg
        self.db = db
        self.platforms = platforms
        self.notify = notify
        pauses = {r['platform']: r['until_at'] for r in self.db.query('SELECT * FROM platform_cooldowns')}
        for name, platform in self.platforms.items():
            platform._cooldown_until = time.monotonic() + max(0, pauses.get(name, 0) - time.time())
            def save_pause(until_at, name=name):
                self.db.execute('INSERT INTO platform_cooldowns VALUES (?,?) ON CONFLICT(platform) '
                                'DO UPDATE SET until_at=MAX(until_at,excluded.until_at)', (name, until_at))
            platform.save_cooldown = save_pause
        self.offers: list[Offer] = []
        self.last_scan: float = 0
        self.next_scan: float = 0
        self.scanning = False
        self.scan_lock = asyncio.Lock()
        self.list_lock = asyncio.Lock()  # проверка и публикация карточки не должны перемежаться
        self.fx = FX()
        # Товары, цену которых в этом цикле проверить не удалось (429, таймаут): их связки не трогаем.
        self.unverified: set[tuple[str, str]] = set()
        self.verified_opportunity_ids: set[int] = set()
        # (площадка, лот) → (когда проверили, цена оплаты или None, цена из поиска на тот момент)
        self.last_cycle: dict = {}  # длительность шагов последнего цикла — для панели
        self.pay_activity: dict[tuple[str, str], dict] = {}
        self.pay_prices: dict[tuple[str, str], tuple[float, float | None, float]] = {}
        self._pay_attempted: dict[tuple[str, str], float] = {}
        # Сколько циклов подряд связка устаревшая: карточку снимаем не с первого раза.
        self.stale_streak: dict[int, int] = {}
        # Последняя ошибка выставления по связке: одну и ту же не присылаем каждый цикл.
        self.list_errors: dict[int, str] = {}
        # Площадка отклонила товар (400: правила, характеристики): ключ → до какого времени не пробовать автоматически.
        # Товары, которые площадка отклонила по правилам: пауза переживает перезапуск, иначе после каждого
        # старта бот снова пробовал и слал ту же ошибку (Nintendo — 30 одинаковых уведомлений)
        self.list_blocked: dict[str, float] = self._load_blocked()
        # Карточка → цена, которую площадка отказалась ставить («минимальная скидка 5%»): не пробуем её каждый цикл.
        self.reprice_refused: dict[int, float] = {}
        # (площадка, товар) → когда последний раз искали конкурентов точным поиском
        self.discover_checked: dict[tuple[str, str], float] = {
            (r['platform'], r['key']): r['checked_at'] for r in self.db.query('SELECT * FROM price_checks')
            if r['checked_at']
        }
        # Сканы площадок идут своими задачами: площадка → (задача, когда начата) и её последний снимок.
        self._scan_tasks: dict[str, tuple[asyncio.Task, float]] = {}
        self._snapshots: dict[str, tuple[float, list[Offer]]] = {}
        self.scan_seconds: dict[str, float] = {}  # сколько шёл последний скан площадки
        self.unavailable_sources: set[str] = set()
        self._audit: dict = {}
        self._audit_seen: set[tuple[str, str, str]] = set()

    def rule(self, name: str, default=None):
        return self.cfg.get_path(f"rules.{name}", default)

    @staticmethod
    async def _timed_scan(platform: Platform) -> tuple[list[Offer], float, float]:
        started = time.time()
        offers = await platform.scan()
        return offers, started, time.time()

    def _collect_scan(self, platform: Platform) -> None:
        """Скан площадки закончился — забрать результат в её снимок."""
        entry = self._scan_tasks.get(platform.name)
        if not entry or not entry[0].done():
            return
        del self._scan_tasks[platform.name]
        task = entry[0]
        if task.cancelled():
            return
        if task.exception() is not None:
            log.warning("%s: сканирование упало: %s", platform.name, task.exception())
            return
        offers, started, finished = task.result()
        # Возраст считаем с начала сбора: длинный скан не делает ранние цены свежими.
        self._snapshots[platform.name] = (started, offers)
        self.scan_seconds[platform.name] = finished - started
        log.info("%s: %d объявлений за %.0f с", platform.name, len(offers), finished - started)
        platform.slowdown = max(1.0, platform.slowdown / 2)  # скан прошёл — темп понемногу возвращается

    def _min_price(self, platform: str) -> float:
        return float(self.cfg.platform(platform).get("min_price_rub", 0))

    # --- сканирование -----------------------------------------------------

    async def scan(self) -> list[Offer]:
        """Собрать объявления со всех площадок.

        Каждая площадка сканируется своей задачей. Цикл ждёт её не дольше scan.platform_budget_minutes:
        если площадка не успела (её притормозили, сайт отвечает медленно), берём её прошлые данные,
        а скан спокойно доходит до конца и попадёт в следующий цикл. Раньше одна медленная площадка
        держала весь цикл: цены остальных устаревали, карточки не переоценивались и не снимались.
        """
        await self.fx.refresh()
        budget = float(self.cfg.get_path("scan.platform_budget_minutes", 3)) * 60
        max_age = float(self.cfg.get_path("scan.max_snapshot_age_minutes", 30)) * 60
        scanners = [p for p in self.platforms.values() if p.can_scan]
        for p in scanners:
            self._collect_scan(p)  # досканировалась между циклами
            if p.name not in self._scan_tasks:
                self._scan_tasks[p.name] = (asyncio.create_task(self._timed_scan(p), name=f"scan-{p.name}"), time.time())
        # Бюджет действует и после перезапуска. Незавершённые сканы продолжаются в фоне.
        pending = [t for t, _ in self._scan_tasks.values()]
        if pending:
            await asyncio.wait(pending, timeout=max(0, budget))
        offers: list[Offer] = []
        self.unavailable_sources = set()
        now = time.time()
        for p in scanners:
            self._collect_scan(p)
            running = self._scan_tasks.get(p.name)
            snapshot = self._snapshots.get(p.name)
            age = now - snapshot[0] if snapshot else None
            if running:
                log.warning("%s: скан идёт уже %.0f мин — цикл его не ждёт, %s", p.name, (now - running[1]) / 60,
                            f"беру данные {age / 60:.0f}-минутной давности" if snapshot else "данных пока нет")
            if snapshot and age <= max_age:
                # Проверка оплаты меняет price/raw. Исходный снимок нужен неизменным
                # для следующего цикла, особенно при просроченном кэше проверки оплаты.
                offers.extend(deepcopy(snapshot[1]))
            elif snapshot:
                self.unavailable_sources.add(p.name)
                log.warning("%s: данным %.0f мин, это больше %g — в этом цикле площадка не участвует",
                            p.name, age / 60, max_age / 60)
            else:
                self.unavailable_sources.add(p.name)
        for p in self.platforms.values():
            p.write_slowdown = max(1.0, p.write_slowdown / 2)  # прошёл цикл — темп действий понемногу возвращается
        offers = self._drop_outliers(offers)
        self.offers = offers
        self.db.save_offers(offers)
        self.last_scan = time.time()
        return offers

    def _drop_outliers(self, offers: list[Offer]) -> list[Offer]:
        """Убрать подозрительные цены: цена за единицу, приманки, ошибки в названии."""
        lo, hi = self.rule("face_value_range", [0.6, 2.5])
        checked = []
        for o in offers:
            face = self.fx.face_value_rub(o.product.amount, o.product.currency) if o.product else None
            # Дешевле минимальной цены площадки (90 ₽ на Playerok) выставить нельзя, поэтому
            # мелкие коды стоят на этом минимуме, хотя номинал меньше. Это не приманка.
            at_floor = o.price <= self._min_price(o.platform)
            if face and not (face * float(lo) <= o.price and (o.price <= face * float(hi) or at_floor)):
                self._audit_reject("face_value", o)
                continue
            checked.append(o)
        if len(checked) != len(offers):
            log.info("отброшено %d объявлений с ценой, не похожей на номинал", len(offers) - len(checked))
        offers = checked

        ratio = float(self.rule("outlier_low_ratio", 0.5))
        by_key: dict[str, list[float]] = defaultdict(list)
        for o in offers:
            by_key[o.key].append(o.price)
        medians = {k: statistics.median(v) for k, v in by_key.items() if len(v) >= 3}
        kept = []
        for o in offers:
            if o.key in medians and o.price < medians[o.key] * ratio:
                self._audit_reject("suspicious_low", o)
            else:
                kept.append(o)
        if len(kept) != len(offers):
            log.info("отброшено %d подозрительно дешёвых объявлений", len(offers) - len(kept))
        return kept

    def _audit_reject(self, reason: str, offer: Offer) -> None:
        marker = (offer.platform, offer.offer_id, reason)
        if marker in self._audit_seen:
            return
        self._audit_seen.add(marker)
        rejected = self._audit.setdefault("filtered", {})
        rejected[reason] = rejected.get(reason, 0) + 1
        if offer.product:
            by_game = self._audit.setdefault("filtered_by_game", {}).setdefault(offer.product.brand, {})
            by_game[reason] = by_game.get(reason, 0) + 1
            categories = self.cfg.get_path("platforms.playerok.categories", {})
            if offer.product.currency in UNIT_TITLES and offer.product.brand.split("-")[0] in categories:
                by_product = self._audit.setdefault("filtered_by_product", {}).setdefault(offer.key, {})
                by_product[reason] = by_product.get(reason, 0) + 1

    def _audit_products(self, ops: list[Opportunity], at: float) -> list[dict]:
        """Per-key game scan summary without seller IDs, names, titles, or URLs."""
        categories = self.cfg.get_path("platforms.playerok.categories", {})
        grouped: dict[str, list[Offer]] = defaultdict(list)
        for offer in self.offers:
            product = offer.product
            if (product and product.currency in UNIT_TITLES
                    and product.brand.split("-")[0] in categories):
                grouped[offer.key].append(offer)

        op_by_key: dict[str, list[Opportunity]] = defaultdict(list)
        for op in ops:
            op_by_key[op.key].append(op)
        rejected = self._audit.get("filtered_by_product", {})
        result = []
        for key, offers in sorted(grouped.items()):
            product = offers[0].product
            brand = product.brand.split("-")[0]
            category = categories.get(brand) or {}
            offline_days = [float(o.raw["seller_offline_days"]) for o in offers
                            if isinstance(o.raw.get("seller_offline_days"), (int, float))
                            and not isinstance(o.raw.get("seller_offline_days"), bool)
                            and math.isfinite(o.raw["seller_offline_days"])
                            and o.raw["seller_offline_days"] >= 0]
            activity_counts = Counter(activity(o, float(self.rule("supplier_max_offline_days", 3)), at)
                                      for o in offers)
            ratings: dict[str, list[float]] = defaultdict(list)
            for offer in offers:
                if isinstance(offer.seller_rating, (int, float)) and math.isfinite(offer.seller_rating):
                    ratings[offer.platform].append(float(offer.seller_rating))
            seen_prices = [float(o.price) for o in offers
                           if isinstance(o.price, (int, float)) and math.isfinite(o.price) and o.price > 0]
            listing_counts = {row["status"]: row["n"] for row in self.db.query(
                "SELECT status, COUNT(*) n FROM listings WHERE key=? GROUP BY status", (key,))}
            result.append({
                "key": key,
                "brand": brand,
                "amount": product.amount,
                "currency": product.currency,
                "region": product.region,
                "login": product.login,
                "obtaining": category.get("obtaining"),
                "category_configured": bool(category.get("category_id")),
                "offer_count": len(offers),
                "platforms": sorted({o.platform for o in offers}),
                "minimum_seen_price": min(seen_prices) if seen_prices else None,
                "activity": {name: activity_counts.get(name, 0)
                             for name in ("active", "inactive", "unknown")},
                "seller_activity_checked": len(offline_days),
                "seller_offline_days_range": [min(offline_days), max(offline_days)] if offline_days else None,
                "ratings_by_platform": {
                    name: {"count": len(values), "min": min(values), "max": max(values)}
                    for name, values in sorted(ratings.items())
                },
                "auto_delivery_count": sum(bool(o.auto_delivery) for o in offers),
                "confirmed_buy_price_count": sum(bool(o.raw.get("paid")) for o in offers),
                "rejected_by_reason": rejected.get(key, {}),
                "listing_statuses": listing_counts,
                "opportunities": [{
                    "sell_platform": op.sell_platform,
                    "buy_platform": op.buy.platform,
                    "buy_price": op.buy.price,
                    "buy_cost": op.buy_cost,
                    "sell_price": op.sell_price,
                    "net_income": op.net_income,
                    "profit": op.profit,
                    "margin_pct": op.margin_pct,
                    "competitors": op.competitors,
                    "best_competitor_price": op.best_competitor_price,
                } for op in op_by_key.get(key, ())],
            })
        return result

    def _write_audit(self, ops: list[Opportunity], started: float) -> None:
        """Записать компактный итог цикла без токенов, покупателей и иных секретов."""
        observed: dict[str, set[str]] = defaultdict(set)
        for o in self.offers:
            if o.product:
                observed[o.platform].add(o.product.brand)
        configured: dict[str, set[str]] = defaultdict(set)
        for name, p in self.platforms.items():
            pcfg = p.pcfg
            for field in ("pages", "queries"):
                if isinstance(pcfg.get(field), dict):
                    configured[name].update(map(str, pcfg[field].keys()))
            sections = pcfg.get("sections")
            if isinstance(sections, dict):
                vals = [v for v in sections.values() if isinstance(v, str)]
                configured[name].update(vals if vals else map(str, sections.keys()))
        row = {
            "at": time.time(), "duration_sec": round(time.time() - started, 1),
            "audit_only": bool(self.cfg.get_path("mode.audit_only", False)),
            "offers": len(self.offers), "opportunities": len(ops),
            "filtered": self._audit.get("filtered", {}),
            "filtered_by_game": self._audit.get("filtered_by_game", {}),
            "filtered_by_product": self._audit.get("filtered_by_product", {}),
            "supplier_checks": self._audit.get("supplier_checks", {}),
            "products": self._audit_products(ops, time.time()),
            "opportunities_by_game": dict(Counter(op.buy.product.brand for op in ops)),
            "publication": self._audit.get("publication", {}),
            "platforms": {
                name: {"offers": sum(1 for o in self.offers if o.platform == name),
                       "games": sorted(observed[name]),
                       "missing_configured": sorted(configured[name] - observed[name])}
                for name in sorted(set(observed) | set(configured))
            },
        }
        self.last_audit = row
        self.AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with self.AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # --- поиск связок -----------------------------------------------------

    def find_opportunities(self, offers: list[Offer] | None = None, *, pending_activity: bool = False) -> list[Opportunity]:
        offers = offers if offers is not None else self.offers
        by_key: dict[str, list[Offer]] = defaultdict(list)
        for o in offers:
            if o.product:
                by_key[o.key].append(o)

        only = self.rule("sell_platforms")  # где продаём; пусто — везде, где можно выставлять
        sell_platforms = [p for p in self.platforms.values() if p.can_sell and (not only or p.name in only)]
        min_profit = float(self.rule("min_profit_rub", 3))
        min_margin = float(self.rule("min_margin_pct", 3))
        min_markup = float(self.rule("min_markup_pct", 10)) / 100
        undercut = float(self.rule("undercut_rub", 1))
        markup = float(self.rule("markup_if_no_competitors_pct", 25)) / 100
        max_buy = float(self.rule("max_buy_price_rub", 1e9))
        max_ratio = float(self.rule("max_price_ratio", 1.8))

        skip_login = bool(self.rule("skip_login_products", True))
        result: list[Opportunity] = []
        for key, group in by_key.items():
            if skip_login and group[0].product.login:
                for o in group:
                    self._audit_reject("login", o)
                continue  # перепродажа «на ваш аккаунт» = передача чужого логина третьему продавцу
            for sp in sell_platforms:
                if (sp.name, key) in self.unverified:
                    continue  # сбой точной проверки нельзя превращать в цену «без конкурентов»
                if not sp.sells(group[0].product):
                    continue  # раздела под товар нет: выставить нельзя, а точный поиск зря ждал таймаут
                sources = [o for o in group if o.platform != sp.name and self._source_allowed(o, pending_activity)
                           and self._delivery_allowed(o, sp.name)]
                sources = [o for o in sources if o.price <= max_buy]
                if not sources:
                    continue
                best = self.rank_suppliers(sources)[0]
                cost = buy_cost(self.cfg, best.platform, best.price)
                floor = min_sell_price(self.cfg, sp.name, cost, max(min_profit, cost * max(min_markup, min_margin / 100, 0.1 if sp.name == "playerok" else 0)))

                competitors = [o for k in competitor_keys(key) for o in by_key.get(k, ()) if o.platform == sp.name
                               and o.seller_id not in sp.own_seller_ids and o.seller not in sp.own_seller_ids]
                best_comp = min((o.price for o in competitors), default=None)
                min_price = self._min_price(sp.name)
                if best_comp is not None:
                    price = math.floor(best_comp - undercut)
                    # дешевле минимальной цены площадки выставить нельзя — тогда встаём вровень
                    if price < min_price <= best_comp:
                        price = min_price
                elif self.rule("allow_no_competitors", False):
                    price = max(floor, math.ceil(cost * (1 + markup)))
                else:
                    continue  # нет конкурентов — нет доказательства, что товар покупают
                price = max(price, floor, min_price)
                # Разрыв слишком большой — скорее всего, это разные товары. Цена на минимуме
                # площадки не в счёт: дешевле 90 ₽ мелкий код не продать никому.
                if price > best.price * max_ratio and price > min_price:
                    continue
                income = net_income(self.cfg, sp.name, price)
                profit = income - cost
                margin = profit / cost * 100 if cost else 0
                if profit < min_profit or margin < min_margin:
                    continue
                result.append(Opportunity(
                    key=key, buy=best, sell_platform=sp.name, sell_price=price, buy_cost=round(cost, 2),
                    net_income=round(income, 2), profit=round(profit, 2), margin_pct=round(margin, 1),
                    competitors=len(competitors), best_competitor_price=best_comp,
                ))
        result.sort(key=lambda op: op.profit, reverse=True)
        return result

    async def verify_sell_prices(self, ops: list[Opportunity]) -> list[Opportunity]:
        """Сверить связки с точным поиском конкурентов на площадке продажи и пересчитать.

        Общий скан Playerok видит лишь первые сотни объявлений, и самые дешёвые
        конкуренты в него часто не попадают — без этой проверки прибыль завышена.
        """
        targets = {(op.sell_platform, op.key): op.buy.product for op in ops}
        targets.update(self._unseen_products())
        lookups: dict[tuple[str, str], list[Offer]] = {}
        # Несколько товаров проверяем одновременно: по одному 200 товаров шли полчаса.
        # Если площадка ответит 429, её паузы растут сами (Platform.note_error).
        # Число адресов не увеличивает разрешённую нагрузку на площадку.
        gate = asyncio.Semaphore(max(1, int(self.rule("lookup_concurrency", 1))))
        started = time.time()
        history = {(r['platform'], r['key']): r for r in self.db.query('SELECT * FROM price_checks')}
        active = {(r['platform'], r['key']) for r in self.db.query(
            "SELECT platform, key FROM listings WHERE status IN ('active','dry_run')")}
        # Чередуем действующие карточки и новые товары: большая витрина не
        # должна занимать всю очередь точного поиска и лишать донат проверки.
        current = sorted((k for k in targets if k in active),
                         key=lambda k: (history.get(k, {}).get('attempted_at', 0), k))
        live_brands = {targets[k].brand for k in current}
        by_brand = defaultdict(list)
        for k in targets:
            if k not in active:
                by_brand[targets[k].brand].append(k)
        for group in by_brand.values():
            group.sort(key=lambda k: (history.get(k, {}).get('attempted_at', 0), k))
        brands = sorted(by_brand, key=lambda brand: (
            brand in live_brands,
            history.get(by_brand[brand][0], {}).get('attempted_at', 0), brand))
        new = []
        while by_brand:
            for brand in brands:
                group = by_brand.get(brand)
                if group:
                    new.append(group.pop(0))
                    if not group:
                        del by_brand[brand]
        ordered = []
        for index in range(max(len(current), len(new))):
            if index < len(current):
                ordered.append(current[index])
            if index < len(new):
                ordered.append(new[index])
        budget = max(0.01, float(self.rule('lookup_budget_sec', 120)))
        deferred = 0

        async def check(sell_platform: str, key: str, product: ProductKey) -> None:
            async with gate:
                previous = history.get((sell_platform, key), {})
                if previous.get('retry_at', 0) > time.time():
                    self.unverified.add((sell_platform, key))
                    return
                self.db.execute('INSERT INTO price_checks (platform,key,attempted_at) VALUES (?,?,?) '
                                'ON CONFLICT(platform,key) DO UPDATE SET attempted_at=excluded.attempted_at',
                                (sell_platform, key, time.time()))
                try:
                    found = await self.platforms[sell_platform].lookup(product)
                except Exception as e:  # noqa: BLE001
                    # Не смогли проверить — новую связку не заводим, но и прежнюю из-за сбоя сети
                    # не объявляем устаревшей: иначе снимется рабочая карточка.
                    log.warning("%s: проверка цен %s не удалась: %s", sell_platform, key, e)
                    self.unverified.add((sell_platform, key))
                    cooldown = max(0, getattr(self.platforms[sell_platform], '_cooldown_until', 0) - time.monotonic())
                    self.db.execute('UPDATE price_checks SET retry_at=? WHERE platform=? AND key=?',
                                    (time.time() + max(cooldown, float(self.rule('lookup_retry_sec', 60))), sell_platform, key))
                    return  # ошибку не сохраняем как успешный пустой поиск на несколько часов
            if found is not None:
                lookups[(sell_platform, key)] = found
                # Записываем успех только после проверки качества всей группы ниже.

        tasks = {asyncio.create_task(check(sp, key, targets[(sp, key)])): (sp, key) for sp, key in ordered}
        if tasks:
            try:
                _, pending = await asyncio.wait(tasks, timeout=budget)
                deferred = len(pending)
                for task in pending:
                    self.unverified.add(tasks[task])
                    task.cancel()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        raise result
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        log.info('очередь цен: выполнено %d, отложено %d, бюджет %.0f с', len(lookups), deferred, budget)
        log.info("точная проверка цен: %d товаров за %.0f с", len(targets), time.time() - started)
        broken = self._broken_lookups(lookups)
        if broken:
            # Проверка почти ничего не нашла — это сбой поиска, а не пропажа конкурентов.
            # Связки этих площадок не трогаем: ни новых карточек, ни снятия старых.
            for sell_platform, key in list(lookups):
                if sell_platform in broken:
                    self.unverified.add((sell_platform, key))
                    del lookups[(sell_platform, key)]
            ops = [op for op in ops if op.sell_platform not in broken]
        for (sp, key) in lookups:
            checked = time.time()
            self.discover_checked[(sp, key)] = checked
            self.db.execute('UPDATE price_checks SET checked_at=?, retry_at=0 WHERE platform=? AND key=?',
                            (checked, sp, key))
        if not lookups:
            return [op for op in ops if (op.sell_platform, op.key) not in self.unverified]
        offers = [o for o in self.offers if (o.platform, o.key) not in lookups]
        for found in lookups.values():
            offers.extend(found)
        self.offers = offers
        self.db.save_offers([o for found in lookups.values() for o in found])
        verified = [op for op in self.find_opportunities(pending_activity=True) if (op.sell_platform, op.key) not in self.unverified]
        log.info("проверка цен продажи: было %d связок, осталось %d", len(ops), len(verified))
        return verified

    def _broken_lookups(self, lookups: dict[tuple[str, str], list[Offer]]) -> set[str]:
        """Площадки, где точный поиск почти ни у одного товара не нашёл чужих объявлений."""
        min_checks = int(self.rule("lookup_min_checks", 5))
        min_share = float(self.rule("lookup_min_hit_share", 0.2))
        total: dict[str, int] = defaultdict(int)
        hits: dict[str, int] = defaultdict(int)
        for (sell_platform, _key), found in lookups.items():
            own = self.platforms[sell_platform].own_seller_ids
            total[sell_platform] += 1
            if any(o.seller_id not in own for o in found):
                hits[sell_platform] += 1
        broken = {p for p, n in total.items() if n >= min_checks and hits[p] / n < min_share}
        for p in broken:
            log.warning("%s: точный поиск нашёл конкурентов у %d из %d товаров — похоже на сбой поиска, "
                        "карточки в этом скане не трогаю", p, hits[p], total[p])
        return broken

    def _unseen_products(self) -> dict[tuple[str, str], ProductKey]:
        """Товары, которые есть у поставщиков, но не попали в общий скан площадки продажи.

        Так бывает с донатом: в выдаче Playerok по тексту почти нет UC, гемов и алмазов,
        а в разделах игр они есть. Такие товары проверяем точным поиском в разделе.
        Пополнения с входом в аккаунт покупателя (:login) пропускаем — для перепродажи это риск.
        """
        only = self.rule("sell_platforms")
        max_buy = float(self.rule("max_buy_price_rub", 1e9))
        by_key: dict[str, list[Offer]] = defaultdict(list)
        for o in self.offers:
            if o.product:
                by_key[o.key].append(o)
        result: dict[tuple[str, str], ProductKey] = {}
        attempts = {(r['platform'], r['key']): r['attempted_at'] for r in self.db.query('SELECT * FROM price_checks')}
        recheck = float(self.rule("discover_recheck_hours", 3)) * 3600
        priority_brands = self.rule("discover_priority_brands", []) or []
        priority_rank = {str(brand): index for index, brand in enumerate(priority_brands)}
        for sp in self.platforms.values():
            brands = sp.lookup_brands
            if not sp.can_sell or not brands or (only and sp.name not in only):
                continue
            candidates = []
            # Живое — связка из прошлого цикла или карточка в продаже. Их проверяем каждый цикл и вне лимита:
            # 13.11 после перезапуска такие товары не попадали в 60 мест из 1773, связки «пропадали»
            # и бот снимал рабочие карточки, а через цикл выставлял их снова.
            live = {r["key"] for r in self.db.query(
                "SELECT key FROM opportunities WHERE sell_platform=? AND status IN ('new','listed')", (sp.name,))}
            live |= {r["key"] for r in self.db.query(
                "SELECT key FROM listings WHERE platform=? AND status IN ('active','dry_run')", (sp.name,))}
            for key, group in by_key.items():
                product = group[0].product
                if product.login or product.brand.split("-")[0] not in brands:
                    continue
                if any(o.platform == sp.name for o in group):
                    continue  # конкуренты в скане есть — связку посчитает обычный поиск
                sources = [o for o in group if self._source_allowed(o, True) and o.price <= max_buy
                           and self._delivery_allowed(o, sp.name)]
                # Недавно проверенный товар не ищем каждый цикл: меньше запросов к площадке.
                # Товар с живой связкой проверяем всегда, иначе она «пропадёт» и карточку снимут.
                if key not in live and time.time() - self.discover_checked.get((sp.name, key), 0) < recheck:
                    continue
                if sources:
                    candidates.append((key in live, len(sources), key, product))
            # Сначала поддерживаем живые связки, затем равномерно проходим
            # номиналы запрошенных игр. Для MLBB регион РФ идёт первым.
            live_candidates = sorted((c for c in candidates if c[0]),
                                     key=lambda c: (attempts.get((sp.name, c[2]), 0), c[2]))
            by_brand: dict[str, list[tuple[bool, int, str, ProductKey]]] = defaultdict(list)
            for candidate in candidates:
                if not candidate[0]:
                    by_brand[candidate[3].brand.split("-")[0]].append(candidate)
            for brand, group in by_brand.items():
                group.sort(key=lambda c: (
                    0 if brand == "mobile_legends" and c[3].region == "RU" else 1,
                    attempts.get((sp.name, c[2]), 0), -c[1], c[2]))
            brand_order = sorted(by_brand, key=lambda brand: (
                priority_rank.get(brand, len(priority_rank)),
                attempts.get((sp.name, by_brand[brand][0][2]), 0), brand))
            new_candidates = []
            while by_brand:
                for brand in brand_order:
                    group = by_brand.get(brand)
                    if group:
                        new_candidates.append(group.pop(0))
                        if not group:
                            del by_brand[brand]
            candidates = live_candidates + new_candidates
            kept = sum(1 for c in candidates if c[0])
            limit = kept + int(self.rule("discover_limit", 200))
            result.update(((sp.name, key), product) for _, _, key, product in candidates[:limit])
            log.info("%s: точная проверка товаров вне общего скана: %d из %d (из них уже в продаже или в связках: %d)",
                     sp.name, min(limit, len(candidates)), len(candidates), kept)
        return result

    def rank_suppliers(self, offers: list[Offer]) -> list[Offer]:
        return sorted(offers, key=lambda o: (buy_cost(self.cfg, o.platform, o.price), o.platform, o.offer_id))

    def _delivery_allowed(self, offer: Offer, sell_platform: str) -> bool:
        if sell_platform != "playerok" or not offer.product or offer.product.currency not in UNIT_TITLES:
            return True
        cat = self.cfg.get_path("platforms.playerok.categories", {}).get(offer.product.brand.split('-')[0], {})
        obtaining = str(cat.get("obtaining") or "")
        if not obtaining:
            return True  # отсутствие раздела отдельно проверяет адаптер
        target = "code" if any(w in obtaining.lower() for w in ("код", "ключ", "карта", "ссылка")) else \
                 "gift" if "подар" in obtaining.lower() else "id"
        allowed = transfer_kind(offer) == target
        if not allowed:
            self._audit_reject("delivery_mismatch", offer)
        return allowed

    def _source_allowed(self, o: Offer, pending_activity: bool = False) -> bool:
        if not math.isfinite(o.price) or o.price <= 0 or not self._reliable(o) or o.raw.get("dead"):
            return False
        status = activity(o, float(self.rule("supplier_max_offline_days", 3)))
        if status == "active":
            return (pending_activity or not getattr(self.platforms.get(o.platform), "checks_pay_price", False)
                    or bool(o.raw.get("paid")))
        if (status == "unknown" and pending_activity and not o.raw.get("paid")
                and getattr(self.platforms.get(o.platform), "checks_pay_price", False)):
            return True
        self._audit_reject("seller_" + status, o)
        return False

    def search_suppliers(self, q: str = "", platform: str = "", amount: float | None = None) -> dict:
        keys = sorted({o.key for o in self.offers if o.product and (not platform or o.platform == platform)
                       and (amount is None or o.product.amount == amount)
                       and (not q or q.casefold() in (o.key + " " + o.title).casefold())
                       and o.platform not in (self.rule("sell_platforms") or ["playerok"])})
        return {"total": len(keys), "products": [self.supplier_view(k, platform) for k in keys[:100]]}

    def supplier_view(self, key: str, platform: str = "") -> dict:
        offers = [o for o in self.offers if o.key == key and (not platform or o.platform == platform)
                  and o.platform not in (self.rule("sell_platforms") or ["playerok"])]
        rows = []
        for o in self.rank_suppliers(offers):
            status = activity(o, float(self.rule("supplier_max_offline_days", 3)))
            allowed = self._source_allowed(o) and o.price <= float(self.rule("max_buy_price_rub", 1e9))
            rows.append({"platform": o.platform, "offer_id": o.offer_id, "title": o.title,
                         "url": o.url, "price": o.price,
                         "buy_cost": round(buy_cost(self.cfg, o.platform, o.price), 2),
                         "activity": status, "eligible": allowed})
        return {"key": key, "best": [r for r in rows if r["eligible"]][:2], "offers": rows,
                "observed_at": self.last_scan}

    def _reliable(self, o: Offer) -> bool:
        if self.rule("code_only_products", False) and not code_delivery(o):
            uid_allowed = (self.rule("allow_uid_topups", False) and o.product and not o.product.login
                           and o.product.currency in UNIT_TITLES and transfer_kind(o) == "id")
            if not uid_allowed:
                self._audit_reject("not_code", o)
                return False
        if self.rule("require_auto_delivery", False) and not o.auto_delivery:
            self._audit_reject("no_auto_delivery", o)
            return False
        if isinstance(o.stock, (int, float)) and not isinstance(o.stock, bool) and o.stock <= 0:
            self._audit_reject("out_of_stock", o)
            return False  # товар у поставщика закончился — покупать будет нечего
        pcfg = self.cfg.platform(o.platform)
        if o.platform in {"kupikod", "donatov"} and o.auto_delivery:
            return True
        reviews = o.raw.get("seller_reviews")
        if o.platform == "funpay" and isinstance(reviews, int) and not isinstance(reviews, bool):
            if reviews > 0:
                return True
            self._audit_reject("no_reviews", o)
            return False
        min_rating = pcfg.get("min_seller_rating", self.rule("min_seller_rating"))
        if min_rating is None:
            return True
        if o.seller_rating is None:
            # Без рейтинга — только там, где закупает человек и видит продавца.
            ok = bool(pcfg.get("allow_unrated_sellers", False))
            if not ok:
                self._audit_reject("rating_unknown", o)
            return ok
        ok = o.seller_rating >= float(min_rating)
        if not ok:
            self._audit_reject("rating_low", o)
        return ok

    # --- цикл: скан → связки → карточки -------------------------------------

    SUPPLIER_REQUEST_TIMEOUT = 35
    PAY_PRICE_TTL = 6 * 3600  # сколько помним проверенную цену оплаты лота

    async def verify_buy_prices(self, ops: list[Opportunity]) -> list[Opportunity]:
        """Заменить цену поставщика из поиска на ту, что реально спишется при оплате.

        Нужно площадкам с checks_pay_price (Plati): там комиссию платёжки берут то с продавца, то с покупателя,
        а у лота с выбором номинала цена в поиске — за самый дешёвый вариант. Проверяем только поставщиков
        найденных связок; если после поправки связка пропала, лучшим становится другой лот — проверяем и его.
        """
        method = pay_method(self.cfg)
        checked = 0
        request_timeout = self.SUPPLIER_REQUEST_TIMEOUT  # таймаут отдельного запроса, не общий срок проверки каталога
        active = {(r['platform'], r['key']) for r in self.db.query(
            "SELECT platform,key FROM listings WHERE status IN ('active','dry_run')")}
        attempted = set()
        while True:
            self._apply_pay_prices()
            ops = self.find_opportunities(pending_activity=True)
            todo = {}
            for op in ops:
                candidates = self.rank_suppliers([o for o in self.offers if o.key == op.key
                    and o.platform != op.sell_platform and self._source_allowed(o, True)
                    and self._delivery_allowed(o, op.sell_platform)])[:2]
                for o in candidates:
                    if (getattr(self.platforms.get(o.platform), "checks_pay_price", False) and not o.raw.get("paid")
                            and (o.platform, o.offer_id) not in attempted):
                        todo[(o.platform, o.offer_id)] = (o, op.sell_platform, op.key)
            if not todo:
                break
            ordered = sorted(todo, key=lambda identity: (
                (todo[identity][1], todo[identity][2]) not in active,
                self._pay_attempted.get(identity, 0)))
            for platform, offer_id in ordered:
                source, sell_platform, key = todo[(platform, offer_id)]
                attempted.add((platform, offer_id))
                self._pay_attempted[(platform, offer_id)] = time.time()
                # to_thread может закончиться уже после отмены: не даём ему менять снимок.
                probe = deepcopy(source)
                request_timer = asyncio.timeout(request_timeout)
                try:
                    async with request_timer:
                        price = await self.platforms[platform].pay_price(probe, method)
                except Exception as e:  # noqa: BLE001
                    # Сбой сети — не повод снимать карточку: связку в этом цикле не трогаем.
                    log.warning("%s: цена оплаты лота %s не проверена: %s", platform, offer_id, e)
                    self.unverified.add((sell_platform, key))
                    source.raw["dead"] = True
                    continue
                source.raw.update(probe.raw)
                self.pay_prices[(platform, offer_id)] = (time.time(), price, source.price)
                self.pay_activity[(platform, offer_id)] = {k: source.raw[k] for k in
                    ("seller_offline_days", "seller_activity_checked_at") if k in source.raw}
                if price is None and source.raw.get("reject_reason"):
                    self._audit_reject(str(source.raw["reject_reason"]), source)
                checked += 1
        self._apply_pay_prices()
        if checked:
            log.info("проверка поставщиков (цена оплаты, когда продавец был на сайте): %d лотов, связок осталось %d",
                     checked, len(ops))
        self._audit["supplier_checks"] = {"checked": checked, "failed": len(attempted) - checked}
        # Неизвестная активность не разрешает действия со старой карточкой.
        for row in self.db.query("SELECT key, sell_platform FROM opportunities WHERE status IN ('new','listed','stale')"):
            group = [o for o in self.offers if o.key == row["key"] and o.platform != row["sell_platform"]]
            if any(activity(o, float(self.rule("supplier_max_offline_days", 3))) == "unknown"
                   or (getattr(self.platforms.get(o.platform), "checks_pay_price", False) and not o.raw.get("paid"))
                   or (o.product and o.product.currency in UNIT_TITLES and transfer_kind(o) == "unknown")
                   for o in group):
                if not any(self._source_allowed(o) and self._delivery_allowed(o, row["sell_platform"]) for o in group):
                    self.unverified.add((row["sell_platform"], row["key"]))
        return self.find_opportunities()

    def _apply_pay_prices(self) -> None:
        now, keep = time.time(), []
        for o in self.offers:
            hit = self.pay_prices.get((o.platform, o.offer_id))
            if o.raw.get("dead"):
                continue
            if hit and not o.raw.get("paid") and now - hit[0] < self.PAY_PRICE_TTL and abs(hit[2] - o.price) < 0.01:
                if hit[1] is None:
                    continue  # этим способом или в этом номинале лот не купить
                o.raw.update(self.pay_activity.get((o.platform, o.offer_id), {}))
                o.price = hit[1]
                o.raw["paid"] = True
            keep.append(o)
        self.offers = keep

    async def run_cycle(self) -> list[Opportunity]:
        async with self.scan_lock:
            self.scanning = True
            try:
                return await self._cycle()
            finally:
                self.scanning = False

    async def _cycle(self) -> list[Opportunity]:
        t0 = time.time()
        self._audit = {"filtered": {}}
        self._audit_seen = set()
        await self.scan()
        t1 = time.time()
        self.unverified = set()
        # Если поставщик ещё сканируется или его снимок протух, отсутствие его
        # лотов не доказывает убыточность уже выставленной карточки.
        for row in self.db.query("SELECT key, sell_platform, buy_platform FROM opportunities WHERE "
                                 "status IN ('new','listed','stale')"):
            if row["buy_platform"] in self.unavailable_sources:
                self.unverified.add((row["sell_platform"], row["key"]))
        ops = await self.verify_sell_prices(self.find_opportunities(pending_activity=True))
        ops = await self.verify_buy_prices(ops)
        t2 = time.time()
        fresh_ids = []
        fresh = []
        new_ops = []
        for op in ops:
            existing = self.db.one(
                "SELECT id, status FROM opportunities WHERE key=? AND sell_platform=?",
                (op.key, op.sell_platform),
            )
            op_id = self.db.upsert_opportunity(op)
            fresh_ids.append(op_id)
            fresh.append((op_id, op))
            if not existing or existing["status"] == "stale":
                new_ops.append((op_id, op))
        self.verified_opportunity_ids = set(fresh_ids)
        # Связки, которые не удалось перепроверить из-за сбоя, остаются как были:
        # прежние не устаревают, а у уже устаревших счётчик сканов не растёт.
        hold_ids = []
        for sell_platform, key in self.unverified:
            row = self.db.one("SELECT id, status FROM opportunities WHERE key=? AND sell_platform=?", (key, sell_platform))
            if row:
                hold_ids.append(row["id"])
                if row["status"] in ("new", "listed"):
                    fresh_ids.append(row["id"])
        # Ни одной связки при нескольких живых карточках — скорее сбой скана, чем рынок за один интервал.
        trusted = bool(ops) or not self._has_live_listings()
        audit_only = bool(self.cfg.get_path("mode.audit_only", False))
        if trusted and not audit_only:
            self._mark_stale(fresh_ids, hold_ids)
        else:
            log.warning("цикл: связок не найдено, карточки в этом скане не снимаю")
        await self.sync_listings()
        if not audit_only:
            await self._handle_new(new_ops, fresh)
        else:
            self._audit["publication"] = {"audit_only": len(fresh)}
            log.info("audit-only: внешние изменения карточек пропущены")
        # Новые категории получают запись раньше массовой переоценки старых.
        if trusted and not audit_only:
            await self.reprice()
        log.info("цикл: %d связок, новых %d, не проверено %d", len(ops), len(new_ops), len(self.unverified))
        log.info("цикл занял %.0f с: скан %.0f, проверка цен %.0f, карточки %.0f",
                 time.time() - t0, t1 - t0, t2 - t1, time.time() - t2)
        self.last_cycle = {"at": time.time(), "total": time.time() - t0, "scan": t1 - t0, "prices": t2 - t1,
                           "cards": time.time() - t2, "opportunities": len(ops), "unverified": len(self.unverified),
                           "publication": self._audit.get("publication", {})}
        self._write_audit(ops, t0)
        return ops

    def _has_live_listings(self) -> bool:
        """Карточек достаточно много, чтобы их одновременная пропажа была подозрительной."""
        need = int(self.rule("hold_if_no_opportunities_listings", 3))
        row = self.db.one("SELECT COUNT(*) AS n FROM listings WHERE status IN ('active','dry_run') "
                          "AND opportunity_id IS NOT NULL")
        return row["n"] >= need

    def _mark_stale(self, fresh_ids: list[int], hold_ids: list[int] = ()) -> None:
        # «id NOT IN (NULL)» в SQL всегда ложно: без свежих связок устаревают все.
        exclude = f" AND id NOT IN ({','.join('?' * len(fresh_ids))})" if fresh_ids else ""
        self.db.execute(
            f"UPDATE opportunities SET status='stale' WHERE status IN ('new','listed'){exclude}",
            tuple(fresh_ids),
        )
        stale = {r["id"] for r in self.db.query("SELECT id FROM opportunities WHERE status='stale'")}
        # Пропущенная вручную связка статус не меняет, но её карточка (вернули на сайте, пропустили уже
        # выставленную) тоже должна сняться, когда связка пропала: считаем сканы без неё так же.
        stale |= {r["id"] for r in self.db.query("SELECT id FROM opportunities WHERE status='skipped'")} - set(fresh_ids)
        hold = set(hold_ids)
        self.stale_streak = {i: self.stale_streak.get(i, 0) + (0 if i in hold else 1) for i in stale}

    async def _handle_new(self, new_ops: list[tuple[int, Opportunity]],
                          fresh: list[tuple[int, Opportunity]] | None = None) -> None:
        counts: dict[str, int] = defaultdict(int)
        self._audit["publication"] = counts
        if not self.cfg.get_path("mode.auto_list", False):
            counts["auto_list_off"] = len(fresh if fresh is not None else new_ops)
            for op_id, op in new_ops:
                await self.notify(self.describe(op), [("✅ Выставить", f"list:{op_id}"), ("✖ Пропустить", f"skip:{op_id}")])
            log.info("публикация: %s", dict(counts))
            return
        # Автовыставление: каждый скан выставляем все выгодные связки, у которых ещё нет карточки,
        # а не только появившиеся впервые. Пропущенные вручную (skipped) не трогаем.
        queue = sorted(fresh if fresh is not None else new_ops, key=lambda x: x[1].profit, reverse=True)
        counts["candidates"] = len(queue)
        for index, (op_id, op) in enumerate(queue):
            seller = self.platforms.get(op.sell_platform)
            row = self.db.one("SELECT status, key FROM opportunities WHERE id=?", (op_id,))
            if not row or row["status"] != "new":
                counts["already_listed" if row and row["status"] == "listed" else "ineligible"] += 1
                continue
            if self.db.one("SELECT id FROM listings WHERE platform=? AND key=? AND status IN ('active','dry_run')",
                           (op.sell_platform, op.key)):
                self.db.set_opportunity_status(op_id, "listed")
                counts["already_listed"] += 1
                continue
            if self.list_blocked.get(row["key"], 0) > time.time():
                counts["blocked"] += 1
                continue
            if not self._can_list_more():
                counts["limit_remaining"] = len(queue) - index
                break
            # Возврат старой карточки обложки не требует. Новые ждут подготовки
            # вне цикла, а остальные готовые товары публикуются сразу.
            paused = self.db.one("SELECT id FROM listings WHERE platform=? AND key=? AND status='paused' "
                                 "AND external_id NOT LIKE 'dry-%'", (op.sell_platform, op.key))
            draft = self.db.one("SELECT id FROM listing_attempts WHERE platform=? AND key=? "
                                "AND status IN ('in_progress','unknown') AND external_id IS NOT NULL",
                                (op.sell_platform, op.key))
            if not self.cfg.dry_run and not paused and not draft and seller and hasattr(seller, "cover_ready") \
                    and not seller.cover_ready(op.buy.product):
                seller.queue_cover(op.buy.product)
                counts["cover_pending"] += 1
                continue
            if not self.cfg.dry_run and seller and self._write_paused(seller):
                counts["cooldown"] += 1
                continue
            counts["attempted"] += 1
            result = await self.list_opportunity(op_id)
            counts["published" if result == "ok" else "not_published"] += 1
            if result != "ok":
                reason = ("unknown_outcome" if "исход" in result else
                          "supplier_unverified" if "поставщик" in result else
                          "price_unverified" if "не проверена" in result else
                          "write_error" if result.startswith("ошибка:") else "other")
                counts[reason] += 1
            # Подряд без пауз площадка отвечает 429 и карточки не выставляются.
            await asyncio.sleep(float(self.rule("listing_delay_sec", 5)) * (seller.write_slowdown if seller else 1.0))
        log.info("публикация: %s", dict(counts))

    @staticmethod
    def _write_paused(platform: Platform) -> bool:
        """Пауза площадки после 429 относится и к записям, не только к поиску."""
        return platform._cooldown_until > time.monotonic()

    BLOCKED_FILE = ROOT / "data" / "list_blocked.json"

    def _load_blocked(self) -> dict[str, float]:
        try:
            data = json.loads(self.BLOCKED_FILE.read_text(encoding="utf-8"))
            return {k: float(v) for k, v in data.items() if float(v) > time.time()}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save_blocked(self) -> None:
        try:
            now = time.time()
            self.BLOCKED_FILE.write_text(json.dumps({k: v for k, v in self.list_blocked.items() if v > now}), encoding="utf-8")
        except OSError as e:
            log.warning("не сохранил паузы выставления: %s", e)

    def _can_list_more(self) -> bool:
        active = self.db.one("SELECT COUNT(*) AS n FROM listings WHERE status IN ('active','dry_run')")["n"]
        return active < int(self.rule("max_active_listings", 30))

    async def sync_listings(self) -> None:
        """Свериться с площадкой: подхватить карточки, выставленные вручную, и отметить пропавшие.

        Бот управляет только карточками из своей базы. Без этого он не стал бы снимать
        карточки, выставленные через сайт, и мог бы выставить вторую такую же.
        """
        if self.cfg.dry_run:
            return  # в тестовом режиме база живёт своей жизнью, на площадке ничего не меняем
        # Записи тестового режима на площадке не существуют: не даём им занимать место.
        self.db.execute("UPDATE listings SET status='dry_closed', updated_at=? "
                        "WHERE status != 'dry_closed' AND (status='dry_run' OR external_id LIKE 'dry-%')", (time.time(),))
        for p in self.platforms.values():
            if not p.can_sell:
                continue
            try:
                items = await p.own_listings()
            except NotImplementedError:
                continue
            except Exception as e:  # noqa: BLE001
                log.warning("%s: не удалось получить свои карточки: %s", p.name, e)
                continue
            on_site = {i.external_id: i for i in items}
            known = {r["external_id"]: r for r in self.db.query("SELECT * FROM listings WHERE platform=?", (p.name,))}
            now = time.time()
            # Подхватываем создание, ответ на которое потерялся вместе с процессом.
            # Отсутствие карточки не доказывает, что запрос не принят (например, модерация).
            unresolved = self.db.query(
                "SELECT * FROM listing_attempts WHERE platform=? AND status IN ('in_progress','unknown')",
                (p.name,))
            if unresolved and hasattr(p, "recover_listing_drafts"):
                try:
                    recovered = await p.recover_listing_drafts([a for a in unresolved if not a["external_id"]])
                    for attempt in unresolved:
                        if attempt["id"] in recovered:
                            attempt["external_id"] = recovered[attempt["id"]]
                            self.db.execute("UPDATE listing_attempts SET external_id=? WHERE id=?",
                                            (attempt["external_id"], attempt["id"]))
                except Exception as e:
                    p.note_error(e)
                    log.warning("%s: сверка черновиков не завершена (%s)", p.name, type(e).__name__)
            for attempt in unresolved:
                matches = [i for i in items if i.external_id == attempt["external_id"]] if attempt["external_id"] else [i for i in items if i.key == attempt["key"]]
                if len(matches) == 1:
                    item = matches[0]
                    if item.external_id not in known:
                        self.db.execute(
                            "INSERT INTO listings (opportunity_id, platform, external_id, key, title, price, status, created_at, updated_at) "
                            "VALUES (NULL,?,?,?,?,?,'active',?,?)",
                            (p.name, item.external_id, item.key, item.title, item.price, now, now))
                        known[item.external_id] = {"external_id": item.external_id, "key": item.key,
                                                  "status": "active", "title": item.title,
                                                  "price": item.price}
                    self.db.execute("UPDATE listing_attempts SET status='reconciled', external_id=?, updated_at=? WHERE id=?",
                                    (item.external_id, now, attempt["id"]))
                else:
                    self.db.execute("UPDATE listing_attempts SET status='unknown', updated_at=? WHERE id=?",
                                    (now, attempt["id"]))
            for ext, row in known.items():
                if row["status"] == "active" and ext not in on_site:
                    # Продана, снята вручную или удалена: больше ею не управляем.
                    self.db.execute("UPDATE listings SET status='gone', updated_at=? WHERE id=?", (now, row["id"]))
                elif row["status"] in ("paused", "gone") and ext in on_site:
                    self.db.execute("UPDATE listings SET status='active', price=?, updated_at=? WHERE id=?",
                                    (on_site[ext].price, now, row["id"]))
            imported = []
            for ext, item in on_site.items():
                if ext in known or not item.key:
                    continue
                self.db.execute(
                    "INSERT INTO listings (opportunity_id, platform, external_id, key, title, price, status, created_at, updated_at)"
                    " VALUES (NULL,?,?,?,?,?,'active',?,?)", (p.name, ext, item.key, item.title, item.price, now, now))
                imported.append(item.key)
            # Привязываем карточки к связкам по ключу: так их будет переоценивать и снимать reprice.
            for row in self.db.query("SELECT id, key FROM listings WHERE platform=? AND status='active' AND opportunity_id IS NULL",
                                     (p.name,)):
                op = self.db.one("SELECT id, status FROM opportunities WHERE key=? AND sell_platform=?", (row["key"], p.name))
                if op:
                    self.db.execute("UPDATE listings SET opportunity_id=? WHERE id=?", (op["id"], row["id"]))
                    if op["status"] == "new":
                        self.db.set_opportunity_status(op["id"], "listed")
            if imported:
                await self.notify(f"📥 {p.name}: подхватил карточки, выставленные вручную ({len(imported)}): "
                                  + ", ".join(imported[:40]))
        # Связка «выставлена», а живой карточки нет — снова кандидат на выставление.
        self.db.execute(
            "UPDATE opportunities SET status='new' WHERE status='listed' AND id NOT IN "
            "(SELECT opportunity_id FROM listings WHERE status='active' AND opportunity_id IS NOT NULL)")

    @staticmethod
    def describe(op: Opportunity) -> str:
        comp = f"{op.best_competitor_price:.0f} ₽ ({op.competitors} шт.)" if op.best_competitor_price else "нет"
        return (
            f"💡 Связка {op.key}\n"
            f"Купить: {op.buy.platform} за {op.buy.price:.0f} ₽ — {op.buy.title[:80]}\n{op.buy.url}\n"
            f"Продать: {op.sell_platform} за {op.sell_price:.0f} ₽ (конкуренты от {comp})\n"
            f"Чистыми: {op.profit:.2f} ₽ ({op.margin_pct}%)"
        )

    # --- карточки ---------------------------------------------------------

    def render_card(self, key: str) -> tuple[ProductKey, str, str]:
        brand, rest = key.split(":", 1)
        nominal, _, region = rest.split(":")[0].partition("@")
        i = len(nominal) - len(nominal.lstrip("0123456789."))
        amount, currency = nominal[:i], nominal[i:]
        product = ProductKey(brand, float(amount), currency, login=key.endswith(":login"), region=region or None)
        base, _, tier = brand.partition("-")
        brand_title = BRAND_TITLES.get(base, base.replace("_", " ").title()) + (f" {tier.title()}" if tier else "")
        cat = ((self.cfg.get_path("platforms.playerok.categories") or {}).get(base) or {})
        n = float(amount)
        if currency in UNIT_TITLES or currency == "M":  # донат: флаг только у отдельного региона (TR, ID …)
            country = region if region and region.upper() not in ("GLOBAL", "RU", "CIS") else None
        else:
            # Steam USD — глобальная карта (currency_values раздела), флаг США был бы неправдой
            global_card = currency in (cat.get("currency_values") or {})
            country = region or (None if global_card else CURRENCY_COUNTRY.get(currency))
        ctx = {"brand_title": brand_title, "amount": amount,
               "currency": UNIT_TITLES.get(currency, f"{currency} ({region})" if region else currency),
               # для новых шаблонов: падеж по числу, флаг, значок и способ получения
               "unit": plural(n, UNIT_FORMS[currency]) if currency in UNIT_FORMS else UNIT_TITLES.get(currency, currency),
               "flag": f" {flag(country)}" if flag(country) else "",
               "icon": UNIT_ICONS.get(currency, "🎁"),
               "how": cat.get("how") or how_to_get(base, cat.get("obtaining")),
               "region": f" {region.title() if region.upper() == 'GLOBAL' else region.upper()}" if region else ""}
        if currency == "M":
            prefix = "subscription_"
        elif currency in UNIT_TITLES:
            prefix = "currency_"
        else:
            prefix = ""
        title = cat.get("title") or self.cfg.get_path(f"listing.{prefix}title") or self.cfg.get_path("listing.title", "{brand_title} {amount} {currency}")
        ctx["how_lower"] = ctx["how"][:1].lower() + ctx["how"][1:]
        ctx["id_word"] ={"По UID": "UID", "По тегу": "тег игрока", "По никнейму": "никнейм"}.get(ctx["how"], "ID игрока")
        # Донат кодом (Robux, V-Bucks, VP) и подарком (звёзды) — свой текст: просить ID там неверно
        special = {"Код": "code_currency_", "Подарком": "gift_currency_"}.get(ctx["how"]) if prefix == "currency_" else None
        desc = (cat.get("description_key") and self.cfg.get_path(cat["description_key"])) or (special and self.cfg.get_path(f"listing.{special}description")) \
            or self.cfg.get_path(f"listing.{prefix}description") or self.cfg.get_path("listing.description", "")
        title, desc = title.format(**ctx), desc.format(**ctx)
        if product.login:
            title = title.replace("Подарочная карта", "Пополнение по логину").replace("Быстрая активация", "На ваш аккаунт")
        return product, title, desc

    async def list_opportunity(self, op_id: int) -> str:
        async with self.list_lock:
            return await self._list_opportunity(op_id)

    async def _list_opportunity(self, op_id: int) -> str:
        row = self.db.one("SELECT * FROM opportunities WHERE id=?", (op_id,))
        if not row:
            return "связка не найдена"
        if self.db.one("SELECT id FROM listings WHERE (opportunity_id=? OR (key=? AND platform=?)) AND status IN ('active','dry_run')",
                       (op_id, row["key"], row["sell_platform"])):
            self.db.set_opportunity_status(op_id, "listed")
            return "уже выставлено"
        if row["status"] == "stale":
            return "связка устарела — она больше не выгодна"
        if (row["sell_platform"], row["key"]) in self.unverified:
            return "цена связки не проверена — дождитесь успешного скана"
        max_age = float(self.rule("max_opportunity_age_minutes", 120)) * 60
        if time.time() - (row["updated_at"] or 0) > max_age:
            return "данные связки устарели — дождитесь нового скана"
        if not self.cfg.dry_run:
            source = next((o for o in self.offers if o.key == row["key"]
                           and o.platform == row["buy_platform"] and o.offer_id == row["buy_offer_id"]), None)
            if source is None or not self._source_allowed(source) or not self._delivery_allowed(source, row["sell_platform"]):
                return "поставщик не проверен — дождитесь успешного скана"
            cost = buy_cost(self.cfg, source.platform, source.price)
            required = max(float(self.rule("min_profit_rub", 3)), cost * max(
                float(self.rule("min_markup_pct", 10)), float(self.rule("min_margin_pct", 3)),
                10 if row["sell_platform"] == "playerok" else 0) / 100)
            if row["sell_price"] < min_sell_price(self.cfg, row["sell_platform"], cost, required):
                return "цена ниже минимальной чистой наценки — дождитесь нового скана"
        if not self._can_list_more():
            return "достигнут лимит активных карточек"
        platform = self.platforms.get(row["sell_platform"])
        if not platform or not platform.can_sell:
            return f"площадка {row['sell_platform']} не подключена для продажи"
        pending = self.db.one(
            "SELECT id, status, external_id FROM listing_attempts WHERE platform=? AND key=? AND status IN ('in_progress','unknown')",
            (platform.name, row["key"]))
        if pending:
            if self.cfg.dry_run or not pending["external_id"] or not hasattr(platform, "restore_listing_draft"):
                return "исход создания карточки не подтверждён — сначала сверяю витрину"
            if self._write_paused(platform):
                return "площадка просит паузу после 429 — повторю в следующем цикле"
            try:
                restored = await platform.restore_listing_draft(row["key"], pending["external_id"])
            except Exception as e:
                platform.note_error(e)
                return "исход создания карточки не подтверждён — сверка черновика недоступна"
            if not restored:
                return "исход создания карточки не подтверждён — сначала сверяю витрину"
        if not self.cfg.dry_run and self._write_paused(platform):
            return "площадка просит паузу после 429 — повторю в следующем цикле"
        product, title, desc = self.render_card(row["key"])
        now = time.time()
        # Та же карточка уже снималась с продажи — возвращаем её, а не плодим копии.
        paused = None if self.cfg.dry_run else self.db.one(
            "SELECT * FROM listings WHERE key=? AND platform=? AND status='paused' AND external_id NOT LIKE 'dry-%' "
            "ORDER BY id DESC",
            (row["key"], platform.name))
        if paused:
            try:
                await platform.republish(paused["external_id"])
            except NotImplementedError:
                paused = None
            except Exception as e:  # noqa: BLE001
                # Публикация могла пройти до таймаута ответа. Новая карточка
                # здесь создаст дубль; сначала следующая сверка витрины.
                platform.note_error(e, write=True)
                log.warning("вернуть карточку %s не удалось, новую до сверки не создаю: %s", row["key"], e)
                return "не удалось вернуть карточку — повторю после сверки витрины"
        if paused:
            platform.note_ok(write=True)
            self.db.execute("UPDATE listings SET opportunity_id=?, status='active', updated_at=? WHERE id=?",
                            (op_id, now, paused["id"]))
            self.db.set_opportunity_status(op_id, "listed")
            await self.notify(f"🟢 Снова в продаже на {platform.name}: {paused['title']} "
                              f"(цену {row['sell_price']:.0f} ₽ выставит переоценка)")
            return "ok"
        if self.cfg.dry_run:
            external_id, status = f"dry-{op_id}", "dry_run"
        else:
            if not pending and hasattr(platform, "cover_ready") and not platform.cover_ready(product):
                platform.queue_cover(product)
                return "обложка готовится в фоне — публикация отложена до свежей проверки"
            anchor = self._strikethrough_price(row, platform)
            attempt_at = time.time()
            if pending:
                attempt_id = pending["id"]
                self.db.execute("UPDATE listing_attempts SET status='in_progress', updated_at=? WHERE id=?",
                                (attempt_at, attempt_id))
            else:
                attempt_cur = self.db.execute(
                    "INSERT INTO listing_attempts (platform,key,title,price,status,created_at,updated_at) VALUES (?,?,?,?, 'in_progress',?,?)",
                    (platform.name, row["key"], title, anchor or row["sell_price"], attempt_at, attempt_at))
                attempt_id = attempt_cur.lastrowid
            try:
                def on_created(external_id):
                    self.db.execute("UPDATE listing_attempts SET external_id=?, updated_at=? WHERE id=?",
                                    (external_id, time.time(), attempt_id))
                if hasattr(platform, "create_listing_tracked"):
                    external_id = await platform.create_listing_tracked(product, title, desc, anchor or row["sell_price"], on_created)
                else:
                    external_id = await platform.create_listing(product, title, desc, anchor or row["sell_price"])
                self.db.execute("UPDATE listing_attempts SET status='published', external_id=?, updated_at=? WHERE id=?",
                                (external_id, time.time(), attempt_id))
                platform.note_ok(write=True)
                status = "active"
            except Exception as e:  # noqa: BLE001
                platform.note_error(e, write=True)  # 429 — действия на площадке делаем реже
                # Неизвестный исход нельзя повторять: сервер мог создать карточку до потери ответа.
                ambiguous = bool(re.match(r"(429|5\d\d)\b", str(e)) or "timeout" in f"{type(e).__name__} {e}".lower())
                has_draft = bool(self.db.one("SELECT external_id FROM listing_attempts WHERE id=?", (attempt_id,))["external_id"])
                self.db.execute("UPDATE listing_attempts SET status=?, error=?, updated_at=? WHERE id=?",
                                ("unknown" if ambiguous or has_draft else "failed", str(e)[:500], time.time(), attempt_id))
                if ambiguous:
                    log.warning("выставить %s не удалось, площадка не ответила: %.200s", row["key"], e)
                    return f"исход создания неизвестен, повтор заблокирован до сверки: {str(e)[:100]}"
                # Тот же товар с той же ошибкой площадка отклонит и в следующем скане: пауза, чтобы не долбить её.
                self.list_blocked[row["key"]] = time.time() + float(self.rule("list_error_pause_hours", 12)) * 3600
                self._save_blocked()
                if self.list_errors.get(op_id) != str(e):  # одну и ту же ошибку пишем один раз
                    self.list_errors[op_id] = str(e)
                    await self.notify(f"⚠️ Не удалось выставить {row['key']} на {platform.name}: {e}\n"
                                      f"Автоматически повторю через {float(self.rule('list_error_pause_hours', 12)):g} ч.")
                return f"ошибка: {e}"
        self.list_errors.pop(op_id, None)
        if self.list_blocked.pop(row["key"], None):
            self._save_blocked()
        listed_price = row["sell_price"]
        if status == "active" and anchor:
            # Выставили по обычной цене площадки — сразу снижаем до своей: Playerok покажет старую зачёркнутой.
            # Не вышло (429, модерация) — в базе остаётся цена выставления, переоценка снизит её в следующем цикле.
            listed_price = anchor
            try:
                await asyncio.sleep(float(self.rule("reprice_delay_sec", 3)) * platform.write_slowdown)
                if self._write_paused(platform):
                    raise RuntimeError("пауза площадки после 429")
                await platform.update_price(external_id, row["sell_price"])
                platform.note_ok(write=True)
                listed_price = row["sell_price"]
            except Exception as e:  # noqa: BLE001
                log.warning("скидку на %s сразу поставить не удалось, сделает переоценка: %.200s", row["key"], e)
        self.db.execute(
            "INSERT INTO listings (opportunity_id, platform, external_id, key, title, price, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (op_id, platform.name, external_id, row["key"], title, listed_price, status, now, now),
        )
        self.db.set_opportunity_status(op_id, "listed")
        prefix = "🧪 [dry-run] " if status == "dry_run" else "🟢 "
        await self.notify(
            f"{prefix}Выставлено на {platform.name}: {title} за {row['sell_price']:.0f} ₽ "
            f"(прибыль ~{row['profit']:.2f} ₽)"
        )
        return "ok"

    def _strikethrough_price(self, row, platform) -> int | None:
        """Зачёркнутая цена: обычная цена этого товара у других продавцов площадки (медиана), а не выдуманная.

        Playerok зачёркивает цену, по которой карточку выставили, если потом снизить её минимум на 5%.
        Наша цена ниже медианы меньше чем на 5% — скидку не показываем.
        """
        if not self.cfg.get_path("listing.strikethrough", False) or platform.name != "playerok":
            return None
        fresh = time.time() - float(self.rule("max_opportunity_age_minutes", 120)) * 60
        keys = list(competitor_keys(row["key"]))
        own = getattr(platform, "own_seller_ids", set())
        prices = [r["price"] for r in self.db.query(
            f"SELECT price, seller, seller_id FROM offers WHERE platform=? AND seen_at>=? "
            f"AND key IN ({','.join('?' * len(keys))})", (platform.name, fresh, *keys))
            if r["seller_id"] not in own and r["seller"] not in own]
        if len(prices) < int(self.rule("strikethrough_min_competitors", 3)):
            return None
        market = statistics.median(prices)
        price = row["sell_price"]
        min_discount = float(self.rule("strikethrough_min_discount_pct", 6)) / 100
        max_discount = float(self.rule("strikethrough_max_discount_pct", 40)) / 100
        if price > market * (1 - min_discount):
            return None
        # Медиана сильно выше нас (там дорогие «премиум» карточки) — зачёркиваем не больше max_discount.
        return math.floor(min(market, price / (1 - max_discount)))

    def _below_cost(self, lst: dict) -> bool:
        """Нынешняя цена карточки ниже минимальной прибыльной при текущей закупке."""
        if not lst.get("buy_platform") or lst.get("buy_price") is None:
            return False
        cost = buy_cost(self.cfg, lst["buy_platform"], lst["buy_price"])
        required = max(float(self.rule("min_profit_rub", 3)), cost * max(
            float(self.rule("min_markup_pct", 10)), float(self.rule("min_margin_pct", 3)),
            10 if lst["platform"] == "playerok" else 0) / 100)
        return lst["price"] < min_sell_price(self.cfg, lst["platform"], cost, required)

    def _worth_relisting(self, lst: dict) -> bool:
        """Новая цена выше на rules.relist_gain_pct % и не меньше rules.relist_gain_rub ₽ — перевыставить выгоднее,
        чем держать старую. 13.11: Free Fire 2420 висел за 2054 ₽, а рынок давал 2498."""
        gain = lst["target"] - lst["price"]
        return gain >= float(self.rule("relist_gain_rub", 30)) and gain >= lst["price"] * float(self.rule("relist_gain_pct", 5)) / 100

    async def reprice(self) -> None:
        """Подстроить цены своих карточек или снять те, где связка пропала."""
        listings = self.db.query(
            "SELECT l.*, o.status AS op_status, o.sell_price AS target, o.buy_platform, o.buy_price FROM listings l "
            "JOIN opportunities o ON o.id = l.opportunity_id WHERE l.status IN ('active','dry_run')"
        )
        need = int(self.rule("unlist_after_stale_scans", 2))
        delay = float(self.rule("reprice_delay_sec", 3))
        refused: dict[str, int] = defaultdict(int)  # площадка → сколько раз за проход ответила 429
        for lst in listings:
            platform = self.platforms.get(lst["platform"])
            if not platform:
                continue
            if (lst["platform"], lst["key"]) in self.unverified:
                continue  # даже прежний stale_streak не разрешает действие по непроверенным данным
            dry = lst["status"] == "dry_run" or self.cfg.dry_run
            if not dry and refused[platform.name] >= self.REPRICE_MAX_429:
                continue  # площадка не пускает: остальные её карточки — в следующем цикле
            if not dry and self._write_paused(platform):
                continue
            try:
                if lst["op_status"] == "stale" or (lst["op_status"] == "skipped"
                                                   and lst["opportunity_id"] in self.stale_streak):
                    # Снимаем, только если связка невыгодна несколько сканов подряд: один скан
                    # мог просто не увидеть поставщика или конкурентов.
                    if self.stale_streak.get(lst["opportunity_id"], 0) < need:
                        continue
                    if not dry:
                        try:
                            await platform.deactivate(lst["external_id"])
                            platform.note_ok(write=True)
                        finally:
                            # Подряд без пауз площадка отвечает 429 (10.11: сняв три карточки за секунду,
                            # остальные двадцать бот не мог снять весь день, и они висели в продаже).
                            await asyncio.sleep(delay * platform.write_slowdown)
                    self.db.execute("UPDATE listings SET status='paused', updated_at=? WHERE id=?", (time.time(), lst["id"]))
                    await self.notify(f"⏸ Снято с продажи {lst['key']} на {lst['platform']}: связка больше не выгодна")
                elif abs(lst["target"] - lst["price"]) >= 1:
                    if self.reprice_refused.get(lst["id"]) == lst["target"]:
                        continue  # эту цену площадка уже не приняла — ждём, пока цель изменится
                    if not dry:
                        try:
                            await platform.update_price(lst["external_id"], lst["target"])
                            platform.note_ok(write=True)
                        except Exception as e:  # noqa: BLE001
                            if "скидка" in str(e).lower():
                                # Playerok не даёт менять цену меньше чем на 5% от исходной: оставляем прежнюю.
                                self.reprice_refused[lst["id"]] = lst["target"]
                                log.info("цену %s %.0f → %.0f площадка не приняла (%s), оставляю прежнюю",
                                         lst["key"], lst["price"], lst["target"], e)
                                if self._below_cost(lst) or self._worth_relisting(lst):
                                    # Если снятие упадёт, оно должно повториться с той же целью.
                                    self.reprice_refused.pop(lst["id"], None)
                                    # Поднять нельзя, а по прежней цене продажа в минус или заметно дешевле рынка:
                                    # снимаем насовсем, следующий скан выставит новую карточку по нужной цене.
                                    await platform.deactivate(lst["external_id"])
                                    platform.note_ok(write=True)
                                    self.db.execute("UPDATE listings SET status='retired', updated_at=? WHERE id=?",
                                                    (time.time(), lst["id"]))
                                    self.db.execute("UPDATE opportunities SET status='new' WHERE id=? AND status='listed'",
                                                    (lst["opportunity_id"],))
                                    why = "закупка подорожала" if self._below_cost(lst) else "рынок подрос"
                                    await self.notify(
                                        f"♻️ Снял {lst['key']} на {lst['platform']}: {why}, а поднять цену "
                                        f"{lst['price']:.0f} → {lst['target']:.0f} ₽ площадка не даёт. Выставлю заново.")
                                continue
                            raise
                        finally:
                            # Подряд без пауз площадка отвечает 429.
                            await asyncio.sleep(delay * platform.write_slowdown)
                    self.reprice_refused.pop(lst["id"], None)
                    self.db.execute("UPDATE listings SET price=?, updated_at=? WHERE id=?", (lst["target"], time.time(), lst["id"]))
                    log.info("цена %s на %s: %.0f → %.0f", lst["key"], lst["platform"], lst["price"], lst["target"])
            except Exception as e:  # noqa: BLE001
                log.warning("переоценка %s не удалась: %s", lst["key"], e)
                if platform.note_error(e, write=True):
                    refused[platform.name] += 1
                    if refused[platform.name] >= self.REPRICE_MAX_429:
                        log.warning("%s: снова 429 — остальные карточки переоценю и сниму в следующем цикле", platform.name)
                    else:
                        await asyncio.sleep(delay * platform.write_slowdown)  # паузы уже удвоены — выдерживаем

    REPRICE_MAX_429 = 3  # столько отказов «слишком много запросов» за проход — и площадку больше не трогаем

    @property
    def paused(self) -> bool:
        return bool(self.cfg.get_path("mode.paused", False))

    async def pause_listing(self, listing_id: int) -> str:
        """Снять одну карточку с продажи (из Telegram)."""
        lst = self.db.one("SELECT * FROM listings WHERE id=?", (listing_id,))
        if not lst or lst["status"] not in ("active", "dry_run"):
            return "карточка не найдена или уже снята"
        platform = self.platforms.get(lst["platform"])
        if lst["status"] == "active" and not self.cfg.dry_run:
            if not platform:
                return f"площадка {lst['platform']} не подключена"
            if self._write_paused(platform):
                return "площадка просит паузу после 429 — повторите позже"
            try:
                await platform.deactivate(lst["external_id"])
                platform.note_ok(write=True)
            except Exception as e:  # noqa: BLE001
                platform.note_error(e, write=True)
                return f"ошибка: {e}"
        self.db.execute("UPDATE listings SET status='paused', updated_at=? WHERE id=?", (time.time(), listing_id))
        if lst["opportunity_id"]:
            self.db.set_opportunity_status(lst["opportunity_id"], "skipped")  # иначе бот выставит её снова
        return "ok"

    async def loop(self) -> None:
        while True:
            # Интервал и паузу читаем каждый раз: их меняют из Telegram без перезапуска.
            interval = float(self.cfg.get_path("scan.interval_minutes", 15)) * 60
            if self.paused:
                log.info("сканирование на паузе")
            else:
                try:
                    await self.run_cycle()
                except Exception:  # noqa: BLE001
                    log.exception("цикл сканирования упал")
            self.next_scan = time.time() + interval
            await asyncio.sleep(interval)
