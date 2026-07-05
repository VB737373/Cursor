"""Bitget — публичный spot API (v2)."""
from __future__ import annotations

from typing import List, Optional

from ..http import get_json
from .base import Exchange, is_skippable

_BASE = "https://api.bitget.com"


class Bitget(Exchange):
    name = "Bitget"
    interval_map = {
        "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
        "1h": "1h", "4h": "4h", "6h": "6h", "12h": "12h", "1d": "1day",
    }

    def get_tickers(self) -> List[dict]:
        data = get_json(f"{_BASE}/api/v2/spot/market/tickers")
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
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
                    "quote_volume": float(t.get("quoteVolume", 0)),
                    "last_price": float(t.get("lastPr", 0)),
                    "pct_change": float(t.get("change24h", 0)) * 100,
                })
            except (TypeError, ValueError):
                continue
        return out

    def get_klines(self, symbol, interval, limit=200) -> Optional[dict]:
        iv = self.map_interval(interval)
        if not iv:
            return None
        data = get_json(
            f"{_BASE}/api/v2/spot/market/candles",
            params={"symbol": symbol, "granularity": iv, "limit": min(limit, 1000)},
        )
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return None
        # [ts, open, high, low, close, baseVol, quoteVol]
        norm = [[r[0], r[1], r[2], r[3], r[4], r[5]] for r in rows]
        return self._finish_klines(norm)
