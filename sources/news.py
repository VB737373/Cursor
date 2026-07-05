"""Новостной фон по монетам (RSS крупных крипто-СМИ, без ключа).

Тянем заголовки из нескольких RSS-лент, находим упоминания монеты и
оцениваем тональность (события, партнёрства, листинги = плюс; взломы,
иски, дампы = минус). Ленты кэшируются, чтобы не дёргать их на каждую монету.
"""
from __future__ import annotations

import re
import time
from typing import List, Optional
from xml.etree import ElementTree as ET

from . import sentiment
from .base import SCOPE_SYMBOL, Contribution, DataSource
from .http import get_text

_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptoslate.com/feed/",
    "https://decrypt.co/feed",
    "https://bitcoinmagazine.com/.rss/full/",
]

_cache: dict = {"ts": 0.0, "titles": []}
_CACHE_TTL = 600  # 10 минут


def _load_titles() -> List[str]:
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL and _cache["titles"]:
        return _cache["titles"]

    titles: List[str] = []
    for url in _FEEDS:
        raw = get_text(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        # RSS: .//item/title ; Atom: .//{ns}entry/{ns}title
        for tag in (".//item/title", ".//{http://www.w3.org/2005/Atom}entry/"
                    "{http://www.w3.org/2005/Atom}title"):
            for t in root.findall(tag):
                if t.text:
                    titles.append(t.text.strip())

    _cache["ts"] = now
    _cache["titles"] = titles
    return titles


class News(DataSource):
    name = "News"
    scope = SCOPE_SYMBOL
    requires_key = False

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        titles = _load_titles()
        if not titles:
            return None
        hits = [t for t in titles if sentiment.mentions(t, base_asset)]
        if not hits:
            return None  # нет новостей по монете — не голосуем

        sent = sentiment.aggregate(hits)
        count = len(hits)
        if sent is None:
            # упоминания есть, но без явной тональности — лёгкий плюс за инфоповод
            score = 0.05
        else:
            score = sent * 0.35
            if count >= 3:  # много новостей = усиление сигнала
                score *= 1.2

        reason = f"новостей: {count}, тон {('+' if (sent or 0) >= 0 else '')}{(sent or 0):.2f}"
        return Contribution(self.name, score, self.weight, reason).clamped()
