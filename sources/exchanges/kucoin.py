"""KuCoin — публичный spot API (v1)."""
from __future__ import annotations

from typing import List, Optional

from ..http import get_json
from .base import Exchange, is_skippable

_BASE = "https://api.kucoin.com"


class KuCoin(Exchange):
    name = "KuCoin"
    interval_map = {
        "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
        "1h": "1hour", "4h": "4hour", "6h": "6hour", "12h": "12hour", "1d": "1day",
    }

    def get_tickers(self) -> List[dict]:
        data = get_json(f"{_BASE}/api/v1/market/allTickers")
        try:
            rows = data["data"]["ticker"]
        except (KeyError, TypeError):
            return []
        out = []
        for t in rows:
            symbol = t.get("symbol", "")  # формат BTC-USDT
            if not symbol.endswith("-USDT"):
                continue
            base = symbol[:-5]
            if is_skippable(base):
                continue
            try:
                out.append({
                    "base": base,
                    "symbol": symbol,
                    "quote_volume": float(t.get("volValue", 0) or 0),
                    "last_price": float(t.get("last", 0) or 0),
                    "pct_change": float(t.get("changeRate", 0) or 0) * 100,
                })
            except (TypeError, ValueError):
                continue
        return out

    def get_klines(self, symbol, interval, limit=200) -> Optional[dict]:
        iv = self.map_interval(interval)
        if not iv:
            return None
        data = get_json(
            f"{_BASE}/api/v1/market/candles",
            params={"symbol": symbol, "type": iv},
        )
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return None
        # [time, open, close, high, low, volume, turnover]
        norm = [[r[0], r[1], r[3], r[4], r[2], r[5]] for r in rows]
        return self._finish_klines(norm[:limit] if len(norm) > limit else norm)
