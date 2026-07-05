"""CoinGlass — деривативы: funding rate, соотношение long/short.

Работает с API-ключом (есть бесплатный тариф). Логика:
- Умеренно отрицательный/низкий funding при росте цены = запас хода вверх.
- Экстремально высокий funding = перегруженные лонги = риск каскада ликвидаций.

ПРИМЕЧАНИЕ: точные пути эндпоинтов зависят от версии/тарифа CoinGlass.
При несовпадении источник просто не голосует (возвращает None).
"""
from __future__ import annotations

import time
from typing import Optional

from .base import SCOPE_SYMBOL, Contribution, DataSource
from .http import get_json

_BASE = "https://open-api-v4.coinglass.com"
_cache: dict = {}
_CACHE_TTL = 180


class CoinGlass(DataSource):
    name = "CoinGlass"
    scope = SCOPE_SYMBOL
    requires_key = True

    def __init__(self, cfg, weight=2.0):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("coinglass", "")

    def enabled(self) -> bool:
        return bool(self.key)

    def _funding(self, base_asset: str):
        now = time.time()
        hit = _cache.get(base_asset)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
        data = get_json(
            f"{_BASE}/api/futures/funding-rate/exchange-list",
            params={"symbol": base_asset},
            headers={"CG-API-KEY": self.key},
        )
        _cache[base_asset] = (now, data)
        return data

    @staticmethod
    def _extract_rate(data) -> Optional[float]:
        """Пытаемся достать усреднённый funding rate (%) из ответа."""
        try:
            rows = data["data"] if isinstance(data, dict) else data
            rates = []
            for r in rows:
                for key in ("fundingRate", "funding_rate", "rate"):
                    if key in r and r[key] is not None:
                        rates.append(float(r[key]))
                        break
            if not rates:
                return None
            return sum(rates) / len(rates)
        except (KeyError, TypeError, ValueError):
            return None

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        data = self._funding(base_asset)
        if data is None:
            return None
        rate = self._extract_rate(data)
        if rate is None:
            return None

        # rate обычно в процентах за 8ч (например 0.01 = 0.01%)
        if rate < -0.02:
            score, note = 0.35, "отрицат. funding (лонги дешёвые)"
        elif rate < 0.02:
            score, note = 0.15, "нейтральный funding"
        elif rate < 0.08:
            score, note = -0.1, "повышенный funding"
        else:
            score, note = -0.35, "экстрим funding (риск ликвидаций)"

        reason = f"funding {rate:+.3f}% — {note}"
        return Contribution(self.name, score, self.weight, reason).clamped()
