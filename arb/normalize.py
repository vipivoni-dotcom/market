"""Сведение названий объявлений к единому ключу товара.

Три вида товаров:
  подарочные карты / пополнения  apple:100INR, psn:10USD@AE, steam:500RUB:login
  игровая валюта                 pubg:60UC, telegram:50STARS, roblox:100ROBUX
  подписки                       telegram_premium:3M, discord_nitro-basic:1M, spotify:12M:login
"""

from __future__ import annotations

import re

from .games import GAMES, UNITS, unit_aliases
from .models import ProductKey

# Синонимы валют и игровых единиц → код
CURRENCY_ALIASES: dict[str, str] = {
    "inr": "INR", "рупи": "INR", "рупий": "INR", "rs": "INR", "₹": "INR",
    "try": "TRY", "tl": "TRY", "лир": "TRY", "лиры": "TRY", "₺": "TRY",
    "usd": "USD", "$": "USD", "долл": "USD", "доллар": "USD", "долларов": "USD",
    "eur": "EUR", "€": "EUR", "евро": "EUR",
    "gbp": "GBP", "£": "GBP",
    "kzt": "KZT", "тенге": "KZT", "₸": "KZT",
    "uah": "UAH", "грн": "UAH",
    "brl": "BRL", "pln": "PLN", "aed": "AED", "sar": "SAR", "cad": "CAD", "aud": "AUD",
    "jpy": "JPY", "cny": "CNY", "hkd": "HKD", "sgd": "SGD", "nok": "NOK", "chf": "CHF",
    "idr": "IDR", "php": "PHP", "myr": "MYR", "thb": "THB", "krw": "KRW", "mxn": "MXN",
    "ars": "ARS", "clp": "CLP", "cop": "COP", "pen": "PEN", "zar": "ZAR", "egp": "EGP",
    "rub": "RUB", "руб": "RUB", "рублей": "RUB", "₽": "RUB",
    # игровая валюта
    "robux": "ROBUX", "робукс": "ROBUX", "робуксов": "ROBUX", "робукса": "ROBUX", "робуксы": "ROBUX",
    "uc": "UC",
    "stars": "STARS", "звезд": "STARS", "звёзд": "STARS", "звезды": "STARS", "звёзды": "STARS",
    "звезда": "STARS", "звёзда": "STARS",
    "гемов": "GEMS", "гемы": "GEMS", "гема": "GEMS", "gems": "GEMS",
    "алмазов": "DIAMONDS", "алмаза": "DIAMONDS", "алмазы": "DIAMONDS", "diamonds": "DIAMONDS",
    "кристаллов": "CRYSTALS", "кристалла": "CRYSTALS", "кристаллы": "CRYSTALS", "crystals": "CRYSTALS",
    "vp": "VP", "золота": "GOLD", "голды": "GOLD", "голда": "GOLD", "голд": "GOLD", "gold": "GOLD",
    "v-bucks": "VBUCKS", "vbucks": "VBUCKS", "в-баксов": "VBUCKS", "вбаксов": "VBUCKS",
    # 06.11: Honkai: Star Rail, Zenless Zone Zero, Wuthering Waves, Call of Duty Mobile, FC Mobile, Honor of Kings
    "древних снов": "SHARDS", "древних сна": "SHARDS", "древний сон": "SHARDS", "oneiric shards": "SHARDS", "oneiric shard": "SHARDS",
    "монохромов": "MONOCHROME", "монохрома": "MONOCHROME", "монохромы": "MONOCHROME", "monochrome": "MONOCHROME",
    "лунитов": "LUNITE", "лунита": "LUNITE", "луниты": "LUNITE", "lunite": "LUNITE", "lunites": "LUNITE",
    "cp": "CP", "fc points": "FCPOINTS", "fc поинтов": "FCPOINTS",
    "жетонов": "TOKENS", "жетона": "TOKENS", "жетоны": "TOKENS", "tokens": "TOKENS",
}
# Единицы игр из covers3d/games.json (встроенные слова важнее)
for _alias, _code in unit_aliases().items():
    CURRENCY_ALIASES.setdefault(_alias, _code)

_CUR_PATTERN = "|".join(
    sorted((re.escape(c) for c in CURRENCY_ALIASES), key=len, reverse=True)
)
_NUM = r"\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?"

# «100 - 10000 INR», «100-10000 INR»
_RANGE_RE = re.compile(
    rf"(?<![\w.])({_NUM})\s*(?:{_CUR_PATTERN})?\s*[-–—]\s*({_NUM})\s*({_CUR_PATTERN})(?![a-zа-яё])",
    re.IGNORECASE,
)
# «100 INR», «100INR», «$10»
_AMOUNT_RE = re.compile(
    rf"(?<![\w.])({_NUM})\s*({_CUR_PATTERN})(?![a-zа-яё])|(\$|€|£|₹|₺)\s*({_NUM})",
    re.IGNORECASE,
)

# «TRY 250», «Номинал: USD 10», «BRL 35» — код валюты перед числом. Только деньги (трёхбуквенные коды) и только
# когда обычной записи «250 TRY» в названии нет: иначе «10 USD 5 шт» дало бы два номинала.
_FIAT_CODES = "|".join(sorted(a for a, code in CURRENCY_ALIASES.items() if len(a) == 3 and a.isascii() and a.upper() == code
                              and code not in UNITS))
_PREFIX_AMOUNT_RE = re.compile(rf"(?<![a-zа-яё\d])({_FIAT_CODES})\s*[:\-]?\s*({_NUM})(?![\w%.,]|\s*(?:шт|pcs|x\b|х\b))", re.IGNORECASE)

# «25+3 алмаза» — номинал с бонусом: покупатель получает 28, а не 3
_BONUS_RE = re.compile(rf"(?<![\w.=])(\d+)\s*\+\s*(\d+)\s*(?=(?:{_CUR_PATTERN})(?![a-zа-яё]))", re.IGNORECASE)

_LOGIN_RE = re.compile(
    r"по\s*логин|на\s*(ваш\w*\s*)?(личн\w*\s*)?(акк?аунт|акк\b)|\bвход\b|с\s*входом|с\s*заход\w*|by\s*login|на\s*ваш\s*steam",
    re.IGNORECASE,
)
# «без захода на аккаунт», «без входа» — наоборот, вход не нужен
_NO_LOGIN_RE = re.compile(r"без\s+(заход\w*|вход\w*|передач\w*\s+данных)(\s+(в|на)\s+(ваш\w*\s+)?(акк?аунт\w*|игру|акк\b))?", re.IGNORECASE)

# Фразы о способе выдачи — их убираем перед проверкой стоп-слов,
# чтобы «активация на любой аккаунт» не считалась продажей аккаунта.
_DELIVERY_PHRASE_RE = re.compile(
    # «на ваш личный акк», «любой акк» — способ выдачи; «личный акк» без предлога — продажа аккаунта
    r"\b((на|для|с|в)\s+((ваш\w*|любо\w*|свой|сво\w+|личн\w*)\s+)*|(ваш\w*|любо\w*|свой|сво\w+)\s+)(акк?аунт\w*|акк\b)",
    re.IGNORECASE,
)

# --- подписки -------------------------------------------------------------

_MONTHS_RE = re.compile(r"(\d+)\s*(?:-?\s*)(?:мес\w*|month\w*|mo\b|м\b|m\b)", re.IGNORECASE)
_YEARS_RE = re.compile(r"(\d+)\s*(?:год\w*|лет|year\w*)", re.IGNORECASE)
_ONE_YEAR_RE = re.compile(r"\b(год|годовая|годовой|year|yearly|annual)\b", re.IGNORECASE)
_ONE_MONTH_RE = re.compile(r"\b(месяц|month|monthly)\b", re.IGNORECASE)
# Тарифы подписок. None — тариф по умолчанию (не добавляется к ключу).
_TIERS: list[tuple[str | None, re.Pattern]] = [
    (tier, re.compile(rx, re.IGNORECASE)) for tier, rx in [
        ("trial", r"trial|пробн"),
        ("basic", r"\bbasic\b|\bclassic\b|базов"),
        ("family", r"family|семейн"),
        ("duo", r"\bduo\b|\bдуо\b"),          # Spotify Duo и Student — отдельные тарифы, а не обычный Premium
        ("student", r"student|студен"),
        ("ultimate", r"ultimate|ultimаtе"),
        ("essential", r"essential"),
        ("extra", r"\bextra\b"),
        ("deluxe", r"deluxe"),
        ("platinum", r"platinum"),
        ("plus", r"\bplus\b"),
        ("pro", r"\bpro\b"),
        ("premier", r"premier\b"),
        ("ultra", r"\bultra\b"),
    ]
]

# Регион важен для валют, которыми номинированы карты разных стран (PSN ОАЭ в USD ≠ PSN США).
REGION_DEFAULT = {"USD": "US", "EUR": "EU"}
REGIONS: list[tuple[str, re.Pattern]] = [
    (code, re.compile(rx, re.IGNORECASE)) for code, rx in [
        ("AE", r"оаэ|\buae\b|эмират|emirates|🇦🇪"),
        ("SA", r"сауд|saudi|\bksa\b|🇸🇦"),
        ("CA", r"канад|canada|🇨🇦"),
        ("AU", r"австрал|australia|🇦🇺"),
        ("UK", r"великобрит|британ|\buk\b|united\s*kingdom|🇬🇧"),
        ("DE", r"германи|germany|\bde\b|🇩🇪"),
        ("FR", r"франци|france|🇫🇷"),
        ("IT", r"итали|italy|\bita\b|🇮🇹"),
        ("ES", r"испани|spain|🇪🇸"),
        ("NL", r"нидерланд|голланд|netherlands|🇳🇱"),
        ("AT", r"австри[яи]|austria|🇦🇹"),
        ("BE", r"бельги|belgium|🇧🇪"),
        ("LU", r"люксембург|luxembourg|🇱🇺"),
        ("IE", r"ирланд|ireland|🇮🇪"),
        ("FI", r"финлянд|finland|🇫🇮"),
        ("PT", r"португал|portugal|🇵🇹"),
        ("GR", r"греци|greece|🇬🇷"),
        ("SK", r"словаки|slovakia|🇸🇰"),
        ("KW", r"кувейт|kuwait|🇰🇼"),
        ("QA", r"катар|qatar|🇶🇦"),
        ("OM", r"оман\b|oman\b|🇴🇲"),
        ("BH", r"бахрейн|bahrain|🇧🇭"),
        ("LB", r"ливан|lebanon|🇱🇧"),
        ("HK", r"гонконг|hong\s*kong|🇭🇰"),
        ("SG", r"сингапур|singapore|🇸🇬"),
        ("AR", r"аргентин|argentina|🇦🇷"),
        # 11.11: Steam в Турции и Казахстане — в USD: такие карты работают только на аккаунтах этих стран
        ("TR", r"турци|turkey|türkiye|🇹🇷"),
        ("KZ", r"казахстан|kazakhstan|kz|🇰🇿"),
        ("UA", r"украин|ukraine|🇺🇦"),
        ("BR", r"бразил|brazil|🇧🇷"),
        ("GLOBAL", r"global|глобал|весь\s*мир|worldwide|\brow\b|any\s*region|любой\s*регион"),
        ("US", r"сша|\busa?\b|америк|united\s*states|🇺🇸"),
    ]
]


# Донат по ID работает только для аккаунтов своего региона. RU / СНГ / Global — основной рынок
# (регион не пишем в ключ), остальные регионы — отдельный товар. «по ID» — это id игрока, не Индонезия.
GAME_UNITS = {"UC", "STARS", "GEMS", "DIAMONDS", "CRYSTALS", "ROBUX", "VP", "GOLD", "VBUCKS",
              "SHARDS", "MONOCHROME", "LUNITE", "CP", "FCPOINTS", "TOKENS"} | set(UNITS)
GAME_REGIONS: list[tuple[str, re.Pattern]] = [
    (code, re.compile(rx, re.IGNORECASE)) for code, rx in [
        ("ID", r"индонез|indonesia|🇮🇩"), ("PH", r"филиппин|philippin|🇵🇭"), ("MY", r"малайз|malaysia|🇲🇾"),
        ("BR", r"бразил|brazil|🇧🇷"), ("TR", r"турц|turkey|türkiye|🇹🇷"), ("IN", r"инди[яи]\b|india|🇮🇳"),
        ("SG", r"сингапур|singapore|🇸🇬"), ("VN", r"вьетнам|vietnam|🇻🇳"), ("TH", r"таиланд|thailand|🇹🇭"),
    ]
]


# «❌ НЕ ДЛЯ РОССИИ ❌» — пополнение не пройдёт на российском аккаунте
_NOT_RU_RE = re.compile(r"не\s+для\s+(росси|ру\b|ru\b|рф)|для\s+ру\s+не|россия\s+не\s+покупать|russia\s+не|\bno\s*ru\b|not\s+for\s+russia"
                        r"|(?<![а-яё])не\s+(рф|росси\w*|ру|ru)\b|❌\s*(рф|росси\w*|ру|ru)\b", re.IGNORECASE)

# Mobile Legends: пополнение по ID привязано к региону аккаунта, поэтому RU и Global — разные товары
# (на Playerok это отдельные значения «Регион»). Остальные игры — как раньше: Global = RU = СНГ.
SPLIT_REGION_BRANDS = {"mobile_legends"} | {b for b, g in GAMES.items() if g.get("split_region")}
# Подарочные карты и кошельки: номинал только в деньгах. «Xbox 1000 V-Bucks» — это валюта Fortnite, а не карта Xbox.
CARD_BRANDS = {"apple", "google_play", "psn", "xbox", "steam", "nintendo", "razer", "battlenet"}
_RU_RE = re.compile(r"\bru\b|росси|(?<![а-яё])(рф|ру|снг|русск\w*)(?![а-яё])|\bcis\b", re.IGNORECASE)
_GLOBAL_RE = re.compile(r"global|глобал|весь\s*мир|worldwide|\brow\b|any\s*region|любой\s*регион", re.IGNORECASE)


def competitor_keys(key: str) -> list[str]:
    """Сравниваем только точный ключ; неизвестный регион не доказывает совпадения."""
    return [key]


def _game_region(title: str, brand: str | None = None) -> str | None:
    # Global, RU и СНГ — один рынок: Global подходит и для российских аккаунтов.
    # Отдельно только то, где продавец сам пишет «не для России»: такое российскому покупателю не продать.
    found = {code for code, rx in GAME_REGIONS if rx.search(title)}
    not_ru = bool(_NOT_RU_RE.search(title))
    if brand in SPLIT_REGION_BRANDS:
        # «Global (не РФ)» — это Global; RU и Global в одном лоте — неясно, что придёт
        rest = _NOT_RU_RE.sub(" ", title)
        if _RU_RE.search(rest):
            found.add("RU")
        if not_ru or _GLOBAL_RE.search(rest):
            found.add("GLOBAL")
    elif not_ru:
        found.add("NORU")
    if len(found) > 1:
        return "MIXED"  # «RU + GLOBAL», «Индонезия и Филиппины» — непонятно, что придёт
    return found.pop() if found else None


def _region(title: str, currency: str, brand: str | None = None) -> str | None:
    if currency in GAME_UNITS:
        return _game_region(title, brand)
    if currency not in REGION_DEFAULT:
        return None  # INR, TRY, PLN… — валюта уже определяет страну
    for code, rx in REGIONS:
        if rx.search(title):
            return None if code == REGION_DEFAULT[currency] else code
    return None


_THOUSANDS_RE = re.compile(r"[1-9]\d{0,2}(?:[.,]\d{3})+")


def _num(text: str) -> float:
    text = text.replace(" ", "").replace(" ", "").replace(" ", "")
    # «11,200 Diamonds», «2.200 алмазов», «1,000 INR» — разделитель тысяч, а не дробь (было 11.2 и 2.2)
    if _THOUSANDS_RE.fullmatch(text):
        return float(re.sub(r"[.,]", "", text))
    return float(text.replace(",", "."))


def _currency(token: str) -> str:
    return CURRENCY_ALIASES[token.lower()]


def _duration_months(title: str) -> int | None:
    found = {int(m.group(1)) for m in _MONTHS_RE.finditer(title) if int(m.group(1)) > 0}
    found |= {int(m.group(1)) * 12 for m in _YEARS_RE.finditer(title) if int(m.group(1)) > 0}
    if not found:
        if _ONE_YEAR_RE.search(title):
            found.add(12)
        elif _ONE_MONTH_RE.search(title):
            found.add(1)
    return found.pop() if len(found) == 1 else None


def _tier(title: str) -> str | None:
    for tier, rx in _TIERS:
        if rx.search(title):
            return tier
    return None


class Normalizer:
    def __init__(self, brands: dict[str, str], exclude: str | None = None,
                 subscriptions: dict[str, str] | None = None) -> None:
        self.brands = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in brands.items()]
        self.subscriptions = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in (subscriptions or {}).items()]
        self.exclude = re.compile(exclude, re.IGNORECASE) if exclude else None

    def brand(self, text: str) -> str | None:
        for name, rx in self.brands:
            if rx.search(text):
                return name
        return None

    def parse(self, title: str, brand_hint: str | None = None) -> ProductKey | None:
        """Вернуть ключ товара или None, если объявление не распознано / исключено."""
        login = bool(_LOGIN_RE.search(_NO_LOGIN_RE.sub(" ", title)))
        if self.exclude and self.exclude.search(_DELIVERY_PHRASE_RE.sub(" ", title)):
            return None
        sub = self._subscription(title, login)
        if sub:
            return sub
        brand = brand_hint or self.brand(title)
        if not brand:
            return None
        if brand.split("-")[0] in {name for name, _ in self.subscriptions}:
            return None  # подписка без срока: «Telegram Premium за 1500 звёзд» — это цена, а не товар

        m = _RANGE_RE.search(title)
        if m:
            cur = _currency(m.group(3))
            return ProductKey(brand, _num(m.group(1)), cur, variable=True, login=login, region=_region(title, cur, brand))

        found: set[tuple[float, str]] = set()
        title = _BONUS_RE.sub(lambda b: f"{int(b.group(1)) + int(b.group(2))} ", title)
        for m in _AMOUNT_RE.finditer(title):
            if m.group(1):
                amount, cur = _num(m.group(1)), _currency(m.group(2))
            else:
                amount, cur = _num(m.group(4)), _currency(m.group(3))
            if cur == "RUB" and brand != "steam":
                continue  # «за 89 руб» — это цена, а не номинал
            if amount > 0:
                found.add((amount, cur))
        if not found:
            for m in _PREFIX_AMOUNT_RE.finditer(title):
                amount, cur = _num(m.group(2)), _currency(m.group(1))
                if amount > 0 and not (cur == "RUB" and brand != "steam"):
                    found.add((amount, cur))
        if len(found) != 1:
            return None  # нет номинала или несколько разных — непонятно, что продаётся
        amount, cur = found.pop()
        if brand in CARD_BRANDS and cur in GAME_UNITS:
            return None
        if brand in GAMES and cur != GAMES[brand].get("unit"):
            return None  # у игры из games.json одна валюта: «Hay Day 100 монет» не попадёт в раздел «Алмазы»
        if cur in GAME_UNITS and not float(amount).is_integer():
            return None  # «1,5 гема» — игровая валюта целая, номинал разобран неверно
        return ProductKey(brand, amount, cur, login=login, region=_region(title, cur, brand))

    def _subscription(self, title: str, login: bool) -> ProductKey | None:
        for name, rx in self.subscriptions:
            if rx.search(title):
                months = _duration_months(title)
                if not months:
                    return None
                tier = _tier(title)
                brand = f"{name}-{tier}" if tier else name
                return ProductKey(brand, months, "M", login=login)
        return None
