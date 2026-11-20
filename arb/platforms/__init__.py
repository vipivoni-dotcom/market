from __future__ import annotations

from ..config import Config
from ..normalize import Normalizer
from .base import Platform
from .donatov import Donatov
from .eldorado import Eldorado
from .eneba import Eneba
from .funpay import FunPay
from .ggsel import GGSel
from .kupikod import Kupikod
from .lzt import LZT
from .paygame import PayGame
from .plati import Plati
from .playerok import Playerok
from .seagm import SEAGM
from .starvell import Starvell

ALL: list[type[Platform]] = [Playerok, FunPay, Plati, Starvell, GGSel, LZT, Kupikod, Donatov, PayGame, Eneba, SEAGM, Eldorado]


def build_platforms(cfg: Config) -> dict[str, Platform]:
    normalizer = Normalizer(cfg.get("brands") or {}, cfg.get("exclude"), cfg.get("subscriptions") or {})
    platforms = {}
    for cls in ALL:
        p = cls(cfg, normalizer)
        if p.enabled:
            platforms[p.name] = p
    return platforms
