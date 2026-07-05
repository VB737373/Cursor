"""Скоринг: объединение вкладов источников в итоговое решение."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sources import Contribution

TA_NAME = "Technical Analysis"


@dataclass
class Decision:
    symbol: str
    base: str
    price: float
    verdict: str                 # "LONG" | "SKIP"
    confidence: float            # 0..100
    final_score: float           # -1..1
    contributions: List[Contribution] = field(default_factory=list)
    entry: Optional[float] = None
    stop: Optional[float] = None
    take: Optional[float] = None
    exchanges: List[str] = field(default_factory=list)
    source_exchange: Optional[str] = None
    pct_change_24h: Optional[float] = None
    total_volume: Optional[float] = None
    exchange_symbols: dict = field(default_factory=dict)  # {биржа: символ на бирже}

    @property
    def reasons(self) -> List[str]:
        return [f"{c.source}: {c.reason}" for c in self.contributions if c.reason]


def decide(symbol: str, base: str, price: float,
           contributions: List[Contribution],
           threshold: float) -> Decision:
    contributions = [c for c in contributions if c is not None]
    total_w = sum(c.weight for c in contributions)
    final_score = (
        sum(c.score * c.weight for c in contributions) / total_w
        if total_w > 0 else 0.0
    )
    # Нормировка в человеческую шкалу: -1 -> 0%, 0 (нейтрально) -> 50%, +1 -> 100%.
    # Так порог остаётся осмысленным независимо от числа источников,
    # а сигналы появляются на любом рынке (в слабом — только сильнейшие).
    confidence = round((max(-1.0, min(1.0, final_score)) + 1) / 2 * 100, 1)

    # Тех.анализ — гейткипер: не входим в лонг против явного нисходящего тренда.
    ta = next((c for c in contributions if c.source == TA_NAME), None)
    ta_ok = ta is None or ta.score >= 0

    verdict = "LONG" if (confidence >= threshold and ta_ok) else "SKIP"

    return Decision(
        symbol=symbol,
        base=base,
        price=price,
        verdict=verdict,
        confidence=confidence,
        final_score=round(final_score, 3),
        contributions=sorted(contributions, key=lambda c: c.weight, reverse=True),
    )
