"""Проверка активности продавца без предположений об отсутствующих данных."""

import math
import time

from .models import Offer


def activity(offer: Offer, max_days: float = 3, now: float | None = None) -> str:
    if offer.platform in {"kupikod", "donatov"} and offer.auto_delivery:
        return "active"  # каталог магазина, время входа продавца неприменимо
    days = offer.raw.get("seller_offline_days")
    if isinstance(days, bool) or not isinstance(days, (int, float)) or not math.isfinite(days) or days < 0:
        return "unknown"
    checked = offer.raw.get("seller_activity_checked_at")
    if isinstance(checked, (int, float)) and math.isfinite(checked):
        days += max(0, (time.time() if now is None else now) - checked) / 86400
    return "inactive" if days >= max_days else "active"
