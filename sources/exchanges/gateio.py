"""Gate.io — публичный spot API (v4)."""
from __future__ import annotations

from typing import List, Optional

from ..http import get_json
from .base import Exchange, is_skippable

_BASE = "https://api.gateio.ws/api/v4"


class GateIO(Exchange):
    name = "Gate"
    interval_map = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "4h": "4h", "8h": "8h", "1d": "1d",
    }

    def get_tickers(self) -> List[dict]:
        data = get_json(f"{_BASE}/spot/tickers")
        if not isinstance(data, list):
            return []
        out = []
        for t in data:
            pair = t.get("currency_pair", "")
            if not pair.endswith("_USDT"):
                continue
            base = pair[:-5]
            if is_skippable(base):
                continue
            try:
                out.append({
                    "base": base,
                    "symbol": pair,
                    "quote_volume": float(t.get("quote_volume", 0) or 0),
                    "last_price": float(t.get("last", 0) or 0),
                    "pct_change": float(t.get("change_percentage", 0) or 0),
                })
            except (TypeError, ValueError):
                continue
        return out

    def get_klines(self, symbol, interval, limit=200) -> Optional[dict]:
        iv = self.map_interval(interval)
        if not iv:
            return None
        data = get_json(
            f"{_BASE}/spot/candlesticks",
            params={"currency_pair": symbol, "interval": iv, "limit": min(limit, 1000)},
        )
        if not isinstance(data, list):
            return None
        # [timestamp, quote_volume, close, high, low, open, base_volume, closed]
        norm = [[r[0], r[5], r[3], r[4], r[2], r[6] if len(r) > 6 else r[1]]
                for r in data]
        return self._finish_klines(norm)
