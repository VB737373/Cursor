"""Базовый класс биржи и общие утилиты для рыночных данных.

Каждая биржа отдаёт публичные данные без API-ключей:
  * get_tickers()  -> список USDT-пар с объёмом/ценой;
  * get_klines()   -> свечи в едином формате (ascending по времени).
"""
from __future__ import annotations

import logging
from typing import List, Optional

log = logging.getLogger("exchange")

# Базовые активы, которые не торгуем в лонг к USDT
SKIP_BASES = {
    "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "USDD", "EUR",
    "AEUR", "GBP", "TRY", "BRL", "ARS", "WBTC", "WBETH", "BETH",
    "EURI", "XUSD", "USTC",
}


def is_skippable(base: str) -> bool:
    if base in SKIP_BASES:
        return True
    # Плечевые токены Binance/прочих: BTCUP, BTCDOWN, ETH3L, ETH3S, BULL/BEAR
    if base.endswith(("UP", "DOWN", "3L", "3S", "5L", "5S", "BULL", "BEAR")):
        return True
    return False


class Exchange:
    name: str = "base"
    # Маппинг обобщённого интервала ("1h") в формат биржи
    interval_map: dict = {}

    def map_interval(self, interval: str) -> Optional[str]:
        return self.interval_map.get(interval)

    def supports_interval(self, interval: str) -> bool:
        return interval in self.interval_map

    def get_tickers(self) -> List[dict]:
        """Список dict: {base, symbol, quote_volume, last_price, pct_change}."""
        raise NotImplementedError

    def get_klines(self, symbol: str, interval: str,
                   limit: int = 200) -> Optional[dict]:
        """dict со списками open/high/low/close/volume (по возрастанию времени)."""
        raise NotImplementedError

    @staticmethod
    def _finish_klines(rows: List[list]) -> Optional[dict]:
        """rows: [[ts, o, h, l, c, v], ...] в любом порядке -> нормализованный dict."""
        if not rows:
            return None
        try:
            rows = sorted(rows, key=lambda r: float(r[0]))
            return {
                "open": [float(r[1]) for r in rows],
                "high": [float(r[2]) for r in rows],
                "low": [float(r[3]) for r in rows],
                "close": [float(r[4]) for r in rows],
                "volume": [float(r[5]) for r in rows],
            }
        except (TypeError, ValueError, IndexError):
            return None
