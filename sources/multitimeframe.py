"""Мультитаймфрейм-фильтр: тренд на старшем таймфрейме (HTF).

Принцип №1 у профи: направление задаётся старшим ТФ, вход — на младшем.
Если бот сканирует на 1h, этот источник проверяет тренд на 4h и голосует
за лонг только когда старший ТФ тоже смотрит вверх.
"""
from __future__ import annotations

from typing import Optional

import indicators as ind

from .base import SCOPE_SYMBOL, Contribution, DataSource

# Младший ТФ -> старший ТФ
HTF_MAP = {
    "1m": "15m", "5m": "1h", "15m": "1h", "30m": "4h",
    "1h": "4h", "2h": "1d", "4h": "1d", "6h": "1d", "12h": "1d",
}


class MultiTimeframe(DataSource):
    name = "Multi-Timeframe"
    scope = SCOPE_SYMBOL
    requires_key = False

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        htf = HTF_MAP.get(self.cfg.interval)
        if not htf:
            return None
        client = context.get("exchange_client")
        ex_symbol = context.get("exchange_symbol")
        if client is None or not ex_symbol:
            return None
        if not client.supports_interval(htf):
            return None

        k = client.get_klines(ex_symbol, htf, limit=200)
        if not k or len(k["close"]) < 60:
            return None

        closes = k["close"]
        ema_fast = ind.last_valid(ind.ema(closes, self.cfg.ema_fast))
        ema_slow = ind.last_valid(ind.ema(closes, self.cfg.ema_slow))
        ema_trend = ind.last_valid(ind.ema(closes, self.cfg.ema_trend))
        price = closes[-1]
        if None in (ema_fast, ema_slow, ema_trend):
            return None

        up = ema_fast > ema_slow
        above_trend = price > ema_trend

        if up and above_trend:
            score = 0.4
            note = f"{htf}-тренд вверх (цена выше EMA{self.cfg.ema_trend})"
        elif up or above_trend:
            score = 0.1
            note = f"{htf}-тренд смешанный"
        else:
            score = -0.4
            note = f"{htf}-тренд вниз"

        return Contribution(self.name, score, self.weight, note).clamped()
