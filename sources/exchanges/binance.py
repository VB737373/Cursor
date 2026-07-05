"""Binance — публичный spot API."""
from __future__ import annotations

from typing import List, Optional

from ..http import get_json
from .base import Exchange, is_skippable

_BASE = "https://api.binance.com"


class Binance(Exchange):
    name = "Binance"
    interval_map = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h",
        "12h": "12h", "1d": "1d",
    }

    def get_tickers(self) -> List[dict]:
        data = get_json(f"{_BASE}/api/v3/ticker/24hr")
        if not isinstance(data, list):
            return []
        out = []
        for t in data:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            base = symbol[:-4]
            if is_skippable(base):
                continue
            try:
                out.append({
                    "base": base,
                    "symbol": symbol,
                    "quote_volume": float(t.get("quoteVolume", 0)),
                    "last_price": float(t.get("lastPrice", 0)),
                    "pct_change": float(t.get("priceChangePercent", 0)),
                })
            except (TypeError, ValueError):
                continue
        return out

    def get_klines(self, symbol, interval, limit=200) -> Optional[dict]:
        iv = self.map_interval(interval)
        if not iv:
            return None
        data = get_json(
            f"{_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": iv, "limit": limit},
        )
        if not isinstance(data, list):
            return None
        rows = [[c[0], c[1], c[2], c[3], c[4], c[5]] for c in data]
        return self._finish_klines(rows)
