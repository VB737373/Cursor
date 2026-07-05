"""Пакет бирж: клиенты публичных spot API."""
from __future__ import annotations

import logging
from typing import List

from .base import Exchange
from .binance import Binance
from .bitget import Bitget
from .bybit import Bybit
from .gateio import GateIO
from .kucoin import KuCoin

log = logging.getLogger("exchanges")

# Имя (в нижнем регистре) -> класс
REGISTRY = {
    "binance": Binance,
    "bybit": Bybit,
    "bitget": Bitget,
    "gate": GateIO,
    "kucoin": KuCoin,
}


def build_exchanges(names: List[str]) -> List[Exchange]:
    out: List[Exchange] = []
    for n in names:
        cls = REGISTRY.get(n.strip().lower())
        if cls:
            out.append(cls())
        else:
            log.warning("Неизвестная биржа в настройках: %s", n)
    if not out:
        out.append(Binance())
    log.info("Биржи: %s", ", ".join(e.name for e in out))
    return out


__all__ = ["Exchange", "build_exchanges", "REGISTRY"]
