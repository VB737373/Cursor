"""Ликвидации в реальном времени (websocket фьючерсов Binance, без ключа).

Топ-трейдеры смотрят на ликвидации как на топливо движения:
  * массовые ликвидации ШОРТОВ (принудительные покупки) = short squeeze → рост;
  * массовые ликвидации ЛОНГОВ (принудительные продажи) = каскад вниз.

Сборщик подключается к потоку !forceOrder@arr и копит события в памяти.
Источник Liquidations читает накопленное за окно времени по каждой монете.

В stream Binance:  o.S = "SELL"  -> ликвидирован ЛОНГ (форс-продажа)
                   o.S = "BUY"   -> ликвидирован ШОРТ (форс-покупка)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional, Tuple

from .base import SCOPE_SYMBOL, Contribution, DataSource

log = logging.getLogger("liquidations")

_STREAM = "wss://fstream.binance.com/ws/!forceOrder@arr"
_KEEP_SECONDS = 2 * 3600  # держим события 2 часа


class LiquidationStore:
    def __init__(self):
        # список кортежей (ts, symbol, side, usd)
        self._events: list[tuple] = []
        self._adds = 0

    def add(self, ts: float, symbol: str, side: str, usd: float) -> None:
        self._events.append((ts, symbol, side, usd))
        self._adds += 1
        if self._adds % 200 == 0:
            self._prune()

    def _prune(self) -> None:
        cutoff = time.time() - _KEEP_SECONDS
        self._events = [e for e in self._events if e[0] >= cutoff]

    def recent(self, symbol: str, window_sec: int = 3600) -> Tuple[float, float]:
        """Возвращает (ликвидации_лонгов_usd, ликвидации_шортов_usd) за окно."""
        cutoff = time.time() - window_sec
        long_usd = 0.0
        short_usd = 0.0
        for ts, sym, side, usd in self._events:
            if ts < cutoff or sym != symbol:
                continue
            if side == "SELL":
                long_usd += usd
            elif side == "BUY":
                short_usd += usd
        return long_usd, short_usd

    def has_data(self) -> bool:
        return bool(self._events)


# Общий синглтон: пишет сборщик, читает источник
STORE = LiquidationStore()


async def run_collector(app=None) -> None:
    """Фоновая задача: подключается к потоку ликвидаций и наполняет STORE."""
    try:
        import websockets
    except ImportError:
        log.warning("Пакет websockets не установлен — ликвидации отключены")
        return

    while True:
        try:
            async with websockets.connect(_STREAM, ping_interval=20,
                                           ping_timeout=20) as ws:
                log.info("Поток ликвидаций Binance подключён")
                async for msg in ws:
                    try:
                        o = json.loads(msg).get("o", {})
                        sym = o.get("s")
                        side = o.get("S")
                        qty = float(o.get("q") or 0)
                        price = float(o.get("ap") or o.get("p") or 0)
                        if sym and side and qty > 0 and price > 0:
                            STORE.add(time.time(), sym, side, qty * price)
                    except (ValueError, TypeError, AttributeError):
                        continue
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Поток ликвидаций оборвался, переподключение через 5с: %s", e)
            await asyncio.sleep(5)


class Liquidations(DataSource):
    name = "Liquidations"
    scope = SCOPE_SYMBOL
    requires_key = False

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        if not STORE.has_data():
            return None  # сборщик ещё не накопил данные
        perp = f"{base_asset}USDT"
        long_usd, short_usd = STORE.recent(perp, window_sec=3600)
        total = long_usd + short_usd
        if total < 20_000:  # слишком мало ликвидаций — не голосуем
            return None

        net = short_usd - long_usd  # шорты сквизят = плюс к лонгу
        score = max(-0.35, min(0.35, net / total * 0.35))

        # Крупный сквиз шортов — бонус
        if short_usd > 500_000 and short_usd > long_usd * 1.5:
            score = min(0.4, score + 0.1)

        reason = (f"ликв. шортов ${short_usd:,.0f} / лонгов ${long_usd:,.0f} (1ч)")
        return Contribution(self.name, score, self.weight, reason).clamped()
