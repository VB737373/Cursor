"""Рыночный режим (CoinGecko /global, бесплатно, без ключа).

Общий фон рынка применяется ко всем монетам:
  * растёт общая капитализация = risk-on = лонги надёжнее;
  * падает = risk-off = осторожно с лонгами.
Дополнительно показываем доминацию BTC (ориентир по альтсезону).
"""
from __future__ import annotations

from typing import Optional

from .base import SCOPE_MARKET, Contribution, DataSource
from .http import get_json


class MarketRegime(DataSource):
    name = "Market Regime"
    scope = SCOPE_MARKET
    requires_key = False

    def analyze_market(self, context) -> Optional[Contribution]:
        d = get_json("https://api.coingecko.com/api/v3/global")
        if not isinstance(d, dict):
            return None
        try:
            data = d["data"]
            mcap_change = float(data["market_cap_change_percentage_24h_usd"])
            btc_dom = float(data["market_cap_percentage"]["btc"])
        except (KeyError, TypeError, ValueError):
            return None

        if mcap_change > 2:
            score = 0.2
        elif mcap_change > 0:
            score = 0.1
        elif mcap_change < -2:
            score = -0.25
        else:
            score = -0.1

        reason = f"рынок 24ч {mcap_change:+.1f}%, BTC доминация {btc_dom:.0f}%"
        return Contribution(self.name, score, self.weight, reason).clamped()
