"""Индекс страха и жадности (alternative.me) — бесплатно, без ключа.

Рыночный источник: применяется ко всем монетам одинаково.
Логика: умеренная жадность/выход из страха благоприятны для лонга,
крайняя жадность = риск разворота.
"""
from __future__ import annotations

from typing import Optional

from .base import SCOPE_MARKET, Contribution, DataSource
from .http import get_json


class FearGreed(DataSource):
    name = "Fear & Greed"
    scope = SCOPE_MARKET
    requires_key = False

    def analyze_market(self, context) -> Optional[Contribution]:
        data = get_json("https://api.alternative.me/fng/", params={"limit": 1})
        if not isinstance(data, dict):
            return None
        try:
            item = data["data"][0]
            value = int(item["value"])
            label = item.get("value_classification", "")
        except (KeyError, IndexError, ValueError, TypeError):
            return None

        # 0..100 -> оценка
        if value <= 20:            # extreme fear
            score, note = 0.3, "выход из страха возможен"
        elif value <= 45:          # fear
            score, note = 0.1, "рынок осторожен"
        elif value <= 55:          # neutral
            score, note = 0.0, "нейтрально"
        elif value <= 75:          # greed
            score, note = 0.25, "аппетит к риску"
        else:                      # extreme greed
            score, note = -0.2, "перегрев рынка"

        reason = f"F&G {value} ({label}) — {note}"
        return Contribution(self.name, score, self.weight, reason).clamped()
