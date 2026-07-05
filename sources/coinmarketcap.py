"""CoinMarketCap — рыночные данные. Работает на бесплатном тарифе с API-ключом.

Оцениваем импульс монеты по изменению цены за 24ч/7д и объёму.
"""
from __future__ import annotations

import time
from typing import Optional

from .base import SCOPE_SYMBOL, Contribution, DataSource
from .http import get_json

_BASE = "https://pro-api.coinmarketcap.com"
_cache: dict = {}
_CACHE_TTL = 300


class CoinMarketCap(DataSource):
    name = "CoinMarketCap"
    scope = SCOPE_SYMBOL
    requires_key = True

    def __init__(self, cfg, weight=1.0):
        super().__init__(cfg, weight)
        self.key = cfg.api_keys.get("coinmarketcap", "")

    def enabled(self) -> bool:
        return bool(self.key)

    def _quote(self, base_asset: str):
        now = time.time()
        hit = _cache.get(base_asset)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
        data = get_json(
            f"{_BASE}/v1/cryptocurrency/quotes/latest",
            params={"symbol": base_asset, "convert": "USD"},
            headers={"X-CMC_PRO_API_KEY": self.key},
        )
        _cache[base_asset] = (now, data)
        return data

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        data = self._quote(base_asset)
        try:
            quote = data["data"][base_asset]
            if isinstance(quote, list):
                quote = quote[0]
            usd = quote["quote"]["USD"]
            ch24 = float(usd.get("percent_change_24h") or 0)
            ch7 = float(usd.get("percent_change_7d") or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            return None

        score = 0.0
        reasons = []
        if ch24 > 0:
            score += 0.15
        else:
            score -= 0.15
        if ch7 > 0:
            score += 0.15
            reasons.append(f"7д {ch7:+.1f}%")
        else:
            score -= 0.15
            reasons.append(f"7д {ch7:+.1f}%")
        # Перегрев: слишком резкий рост за сутки — риск отката
        if ch24 > 25:
            score -= 0.2
            reasons.append("резкий памп 24ч")

        reason = "CMC " + ", ".join(reasons) if reasons else "CMC нейтрально"
        return Contribution(self.name, score, self.weight, reason).clamped()
