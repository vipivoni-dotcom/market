"""Картинка для карточки товара (площадки вроде Playerok без фото карточку не принимают).

Простая обложка 4:3: название сервиса, номинал и тип товара на фоне цвета бренда.
Логотипы брендов не рисуем — только текст.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import ROOT
from .engine import BRAND_TITLES, UNIT_TITLES

OUT_DIR = ROOT / "data" / "cards"
FONTS = Path("C:/Windows/Fonts")
SIZE = (1200, 900)

# цвет фона: (сверху, снизу)
COLORS = {
    "apple": ((40, 40, 48), (10, 10, 14)),
    "google_play": ((1, 135, 95), (0, 70, 50)),
    "psn": ((0, 80, 200), (0, 30, 100)),
    "xbox": ((16, 124, 16), (6, 60, 6)),
    "steam": ((27, 40, 56), (12, 18, 28)),
}
DEFAULT_COLOR = ((70, 50, 160), (30, 20, 80))
CURRENCY_NAMES = {
    "INR": "Индия", "TRY": "Турция", "USD": "США", "PLN": "Польша", "GBP": "Великобритания",
    "EUR": "Европа", "CAD": "Канада", "AED": "ОАЭ", "BRL": "Бразилия", "KZT": "Казахстан",
}


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default(size)


def _center(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill) -> None:
    w = draw.textlength(text, font=font)
    draw.text(((SIZE[0] - w) / 2, y), text, font=font, fill=fill)


# Ключ приходит из адреса /cards/<ключ>.png, а эта ссылка открыта без токена: пускаем только настоящие
# ключи товаров. Иначе «..\\..\\x:1Y» записал бы PNG в любую папку диска, а случайные ключи забили бы data/cards.
KEY_RE = re.compile(r"[a-z0-9_]+(-[a-z0-9_]+)?:\d+(\.\d+)?[A-Z]{1,12}(@[A-Za-z]{2,10})?(:login)?")


def render(key: str) -> Path:
    """Нарисовать обложку для ключа товара вида apple:100INR и вернуть путь к PNG."""
    if not KEY_RE.fullmatch(key):
        raise ValueError(f"не ключ товара: {key[:60]!r}")
    brand, rest = key.split(":", 1)
    value = rest.split(":")[0]
    amount = value.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ@").split("@")[0]
    cur = value[len(amount):].split("@")[0]
    base = brand.split("-")[0]
    top, bottom = COLORS.get(base, DEFAULT_COLOR)

    img = Image.new("RGB", SIZE)
    draw = ImageDraw.Draw(img)
    for y in range(SIZE[1]):
        t = y / SIZE[1]
        draw.line([(0, y), (SIZE[0], y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))

    white, grey = (255, 255, 255), (200, 200, 210)
    _center(draw, 150, BRAND_TITLES.get(base, base), _font("segoeuib.ttf", 80), white)
    if cur == "M":
        big, sub = f"{amount} мес.", "Подписка"
    elif cur in UNIT_TITLES:
        big, sub = f"{amount} {UNIT_TITLES[cur]}", "Пополнение"
    else:
        big, sub = f"{amount} {cur}", "Подарочная карта"
    _center(draw, 330, big, _font("segoeuib.ttf", 200), white)
    region = CURRENCY_NAMES.get(cur)
    _center(draw, 640, f"{sub} · {region}" if region else sub, _font("segoeui.ttf", 64), grey)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{key.replace(':', '_').replace('@', '_')}.png"
    img.save(path, optimize=True)
    return path
