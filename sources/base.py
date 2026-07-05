"""Базовые абстракции для источников данных.

Каждый источник анализирует монету (или рынок в целом) и возвращает
`Contribution` — вклад в общий скоринг: балл от -1 (сильно против лонга)
до +1 (сильно за лонг), вес и человекочитаемую причину.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# scope="symbol"  -> считается для каждой монеты отдельно
# scope="market"  -> считается один раз за скан и применяется ко всем монетам
SCOPE_SYMBOL = "symbol"
SCOPE_MARKET = "market"


@dataclass
class Contribution:
    source: str
    score: float          # -1.0 .. +1.0 (положительное = бычье)
    weight: float
    reason: str = ""

    def clamped(self) -> "Contribution":
        self.score = max(-1.0, min(1.0, self.score))
        return self


class DataSource:
    """Базовый источник. Наследники переопределяют analyze()."""

    name: str = "base"
    scope: str = SCOPE_SYMBOL
    requires_key: bool = False

    def __init__(self, cfg, weight: float = 1.0):
        self.cfg = cfg
        self.weight = weight

    def enabled(self) -> bool:
        """Доступен ли источник (например, задан ли API-ключ)."""
        return True

    # Для scope=SCOPE_MARKET
    def analyze_market(self, context: dict) -> Optional[Contribution]:
        return None

    # Для scope=SCOPE_SYMBOL
    def analyze_symbol(
        self, symbol: str, base_asset: str, context: dict
    ) -> Optional[Contribution]:
        return None
