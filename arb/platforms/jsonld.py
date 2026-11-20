"""Общее для сайтов, которые отдают каталог в разметке schema.org (JSON-LD).

Цены в этой разметке видят поисковики, поэтому она открыта и не прячется за защитой.
"""

from __future__ import annotations

import json
import re

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
_LD_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S)


def ld_blocks(html: str) -> list[dict]:
    """Все JSON-LD объекты страницы (вложенные @graph и списки — плоско)."""
    out: list[dict] = []
    for raw in _LD_RE.findall(html):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        for item in stack:
            if isinstance(item, dict):
                out.append(item)
                out.extend(x for x in item.get("@graph") or [] if isinstance(x, dict))
    return out


def in_stock(offer: dict) -> bool:
    return "OutOfStock" not in str(offer.get("availability") or "")
