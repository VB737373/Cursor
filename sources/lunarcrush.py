"""LunarCrush — соцнастроения (Twitter/X + Reddit), по API-ключу.

Бесплатного чтения Twitter/X больше нет, поэтому социальный сигнал берём
у агрегатора LunarCrush: он собирает посты, считает объём упоминаний и
тональность. Включается при наличии LUNARCRUSH_API_KEY (нужна подписка).

Точные поля зависят от версии API/тарифа — при несоответствии источник не
голосует (возвращает None).
"""
from __future__ import annotations

import time
from typing import Optional

from .base import SCOPE_SYMBOL, Contribution, DataSource
from .http import get_json

_BASE = "https://lunarcrush.com/api4/public"
_cache: dict = {}
_CACHE_TTL = 600


class LunarCrush(DataSource):
    name = "LunarCrush (соцсети)"
    scope = SCOPE_SYMBOL
    requires_key = True

    def __init__(self, cfg, weight=1.5):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("lunarcrush", "")

    def enabled(self) -> bool:
        return bool(self.key)

    def _coin(self, base_asset: str):
        now = time.time()
        hit = _cache.get(base_asset)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
        data = get_json(
            f"{_BASE}/coins/{base_asset}/v1",
            headers={"Authorization": f"Bearer {self.key}"},
        )
        _cache[base_asset] = (now, data)
        return data

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        data = self._coin(base_asset)
        if not isinstance(data, dict):
            return None
        d = data.get("data", data)
        try:
            # sentiment: 0..100 (доля позитива), galaxy_score: 0..100
            senti = d.get("sentiment")
            galaxy = d.get("galaxy_score")
        except AttributeError:
            return None
        if senti is None and galaxy is None:
            return None

        score = 0.0
        reasons = []
        if senti is not None:
            s = (float(senti) - 50) / 50  # 50 = нейтрально -> [-1..1]
            score += s * 0.3
            reasons.append(f"соц. настроение {float(senti):.0f}/100")
        if galaxy is not None:
            g = (float(galaxy) - 50) / 50
            score += g * 0.2
            reasons.append(f"Galaxy {float(galaxy):.0f}")

        reason = ", ".join(reasons) if reasons else "соцсети нейтр."
        return Contribution(self.name, score, self.weight, reason).clamped()
