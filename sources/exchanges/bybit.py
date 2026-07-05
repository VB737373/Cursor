"""Bybit — публичный spot API (v5)."""
from __future__ import annotations

from typing import List, Optional

from ..http import get_json
from .base import Exchange, is_skippable

_BASE = "https://api.bybit.com"


class Bybit(Exchange):
    name = "Bybit"
    interval_map = {
        "1m": "1", "5m": "5", "15m": "15", "30m": "30",
        "1h": "60", "2h": "120", "4h": "240", "6h": "360",
        "12h": "720", "1d": "D",
    }

    def get_tickers(self) -> List[dict]:
        data = get_json(f"{_BASE}/v5/market/tickers", params={"category": "spot"})
        try:
            rows = data["result"]["list"]
        except (KeyError, TypeError):
            return []
        out = []
        for t in rows:
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
                    "quote_volume": float(t.get("turnover24h", 0)),
                    "last_price": float(t.get("lastPrice", 0)),
                    "pct_change": float(t.get("price24hPcnt", 0)) * 100,
                })
            except (TypeError, ValueError):
                continue
        return out

    def get_klines(self, symbol, interval, limit=200) -> Optional[dict]:
        iv = self.map_interval(interval)
        if not iv:
            return None
        data = get_json(
            f"{_BASE}/v5/market/kline",
            params={"category": "spot", "symbol": symbol,
                    "interval": iv, "limit": min(limit, 1000)},
        )
        try:
            rows = data["result"]["list"]  # [start, o, h, l, c, volume, turnover]
        except (KeyError, TypeError):
            return None
        norm = [[r[0], r[1], r[2], r[3], r[4], r[5]] for r in rows]
        return self._finish_klines(norm)
