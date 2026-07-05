"""BingX — публичный spot API."""
from __future__ import annotations

from typing import List, Optional

from ..http import get_json
from .base import Exchange, is_skippable

_BASE = "https://open-api.bingx.com"


class BingX(Exchange):
    name = "BingX"
    interval_map = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "4h": "4h", "1d": "1d",
    }

    def get_tickers(self) -> List[dict]:
        data = get_json(f"{_BASE}/openApi/spot/v1/ticker/24hr")
        if not isinstance(data, dict) or data.get("code") != 0:
            return []
        rows = data.get("data")
        if not isinstance(rows, list):
            return []
        out = []
        for t in rows:
            symbol = t.get("symbol", "")  # BTC-USDT
            if not symbol.endswith("-USDT"):
                continue
            base = symbol[:-5]
            if is_skippable(base):
                continue
            try:
                pct_raw = t.get("priceChangePercent") or 0
                if isinstance(pct_raw, str):
                    pct_raw = pct_raw.replace("%", "").strip()
                out.append({
                    "base": base,
                    "symbol": symbol,
                    "quote_volume": float(t.get("quoteVolume", 0) or 0),
                    "last_price": float(t.get("lastPrice", 0) or 0),
                    "pct_change": float(pct_raw),
                })
            except (TypeError, ValueError):
                continue
        return out

    def get_klines(self, symbol, interval, limit=200) -> Optional[dict]:
        iv = self.map_interval(interval)
        if not iv:
            return None
        data = get_json(
            f"{_BASE}/openApi/spot/v2/market/kline",
            params={"symbol": symbol, "interval": iv, "limit": min(limit, 1000)},
        )
        if not isinstance(data, dict) or data.get("code") != 0:
            return None
        rows = data.get("data")
        if not isinstance(rows, list):
            return None
        # [openTime, open, high, low, close, volume, closeTime, quoteVolume]
        norm = [[r[0], r[1], r[2], r[3], r[4], r[5]] for r in rows]
        return self._finish_klines(norm)
