"""Агрегатор рыночных данных по нескольким биржам.

Собирает объединённую «вселенную» монет со всех подключённых бирж:
монета может торговаться на нескольких биржах — их объёмы суммируются,
а свечи для анализа берутся с биржи с наибольшим объёмом (или со следующей,
если первая не отдала данные).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from .exchanges import Exchange, build_exchanges

log = logging.getLogger("market")

# Топовые биржи: листинг здесь считаем признаком «настоящей» монеты
TIER1 = {"Binance", "Bybit"}


@dataclass
class Listing:
    exchange: Exchange
    symbol: str
    quote_volume: float
    last_price: float
    pct_change: float


@dataclass
class Coin:
    base: str
    listings: List[Listing] = field(default_factory=list)

    @property
    def total_volume(self) -> float:
        return sum(l.quote_volume for l in self.listings)

    @property
    def exchange_names(self) -> List[str]:
        return [l.exchange.name for l in self.listings]

    @property
    def has_tier1(self) -> bool:
        return any(l.exchange.name in TIER1 for l in self.listings)

    @property
    def best(self) -> Listing:
        return max(self.listings, key=lambda l: l.quote_volume)

    @property
    def last_price(self) -> float:
        return self.best.last_price

    def klines(self, interval: str, limit: int = 200) -> Optional[tuple]:
        """Свечи с биржи с наибольшим объёмом, с фолбэком на остальные.
        Возвращает (klines_dict, exchange_name) или None."""
        for lst in sorted(self.listings, key=lambda l: l.quote_volume, reverse=True):
            k = lst.exchange.get_klines(lst.symbol, interval, limit)
            if k and len(k.get("close", [])) >= 60:
                return k, lst.exchange.name
        return None


def build_universe(exchanges: List[Exchange], min_volume_usdt: float,
                   limit: int, min_exchanges: int = 2) -> List[Coin]:
    """Опрашивает все биржи, объединяет монеты по базовому активу.

    Фильтр качества: монета проходит, если торгуется минимум на
    `min_exchanges` биржах ИЛИ листится на топ-бирже (Binance/Bybit).
    Это отсекает мусор вроде токенизированных акций с фейковым объёмом,
    которые встречаются лишь на одной второстепенной бирже.
    """
    coins: dict[str, Coin] = {}
    for ex in exchanges:
        try:
            tickers = ex.get_tickers()
        except Exception as e:
            log.warning("Биржа %s не отдала тикеры: %s", ex.name, e)
            continue
        added = 0
        for t in tickers:
            if t["last_price"] <= 0 or t["quote_volume"] <= 0:
                continue
            base = t["base"]
            coin = coins.get(base)
            if coin is None:
                coin = Coin(base=base)
                coins[base] = coin
            coin.listings.append(Listing(
                exchange=ex,
                symbol=t["symbol"],
                quote_volume=t["quote_volume"],
                last_price=t["last_price"],
                pct_change=t["pct_change"],
            ))
            added += 1
        log.info("%s: %d USDT-пар", ex.name, added)

    # Фильтр качества + по объёму
    universe = [
        c for c in coins.values()
        if c.total_volume >= min_volume_usdt
        and (len(c.listings) >= min_exchanges or c.has_tier1)
    ]
    universe.sort(key=lambda c: c.total_volume, reverse=True)
    log.info("Вселенная: %d монет (после фильтров), беру топ-%d",
             len(universe), limit)
    return universe[:limit]


def make_exchanges(cfg) -> List[Exchange]:
    return build_exchanges(cfg.exchanges)
