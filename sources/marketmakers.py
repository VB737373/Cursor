"""Отслеживание маркет-мейкеров Hyperliquid (бесплатно, публичный API).

Маркет-мейкеры / HFT — крупнейшие счета по ОБОРОТУ (объёму торгов). Их выбираем
с публичного лидерборда Hyperliquid по месячному объёму (vlm). Можно добавить
адреса вручную в market_makers.txt (например, известные MM-кошельки).

Логика: маркет-мейкеры структурно почти всегда в нетто-ШОРТЕ (шортят, давая
ликвидность покупателям) — это НЕ медвежий сигнал, поэтому шорт игнорируем.
А вот когда ММ необычно набирают нетто-ЛОНГ по монете — это показательно
(накапливают длинный инвентарь) → мягкий сигнал за лонг. Вес небольшой.

Именованные институции (Wintermute, Auros Global и т.д. из market_makers.txt в
формате «0xАДРЕС Имя») отслеживаются отдельно: если такая фирма набрала ЛОНГ по
монете — это весомый контекст, показываем её по имени прямо в сигнале.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from . import hl_leaderboard as hl
from .base import SCOPE_SYMBOL, Contribution, DataSource

log = logging.getLogger("marketmakers")

_MIN_NOTIONAL = 100_000   # у MM позиции крупные — порог выше, чем у китов
_NAMED_MIN = 200_000      # порог для именованных институций (Wintermute/Auros)
_sel_cache: dict = {"ts": 0.0, "addr": []}


def _auto_addresses(top_n: int, min_volume: float) -> list:
    """Топ-N счетов по месячному обороту (кэш на срок жизни лидерборда)."""
    now = time.time()
    if _sel_cache["addr"] and now - _sel_cache["ts"] < hl._LB_TTL:
        return _sel_cache["addr"]
    rows = hl.leaderboard_rows()
    if not rows:
        return _sel_cache["addr"]
    picked = []
    for r in rows:
        try:
            vlm = float(dict(r["windowPerformances"])["month"]["vlm"])
        except (KeyError, TypeError, ValueError):
            continue
        if vlm >= min_volume:
            picked.append((vlm, r["ethAddress"]))
    picked.sort(reverse=True)
    addresses = [a for _, a in picked[:top_n]]
    if addresses:
        _sel_cache["addr"] = addresses
        _sel_cache["ts"] = now
        log.info("Маркет-мейкеры Hyperliquid: отобрано %d счетов по обороту",
                 len(addresses))
    return _sel_cache["addr"]


def _resolve_addresses(cfg) -> list:
    manual = list(getattr(cfg, "mm_addresses", None) or [])
    if getattr(cfg, "mm_auto", True):
        auto = _auto_addresses(getattr(cfg, "mm_top_n", 20),
                               getattr(cfg, "mm_min_volume", 50_000_000.0))
        seen = {a.lower() for a in manual}
        manual += [a for a in auto if a.lower() not in seen]
    return manual


class HyperliquidMarketMakers(DataSource):
    name = "Hyperliquid Market Makers"
    scope = SCOPE_SYMBOL
    requires_key = False

    def enabled(self) -> bool:
        return bool(getattr(self.cfg, "mm_addresses", None)) or \
            bool(getattr(self.cfg, "mm_auto", True))

    def _named_longs(self, base_asset: str) -> list:
        """Именованные институции (Wintermute/Auros...) в ЛОНГЕ по монете."""
        labels = getattr(self.cfg, "mm_labels", None) or {}
        out = []
        for addr, name in labels.items():
            pos = hl.position_on(addr, base_asset)
            if pos and pos[0] > 0 and pos[1] >= _NAMED_MIN:
                out.append((name, pos[1]))
        out.sort(key=lambda x: -x[1])
        return out

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        addresses = _resolve_addresses(self.cfg)
        if not addresses:
            return None
        info = hl.aggregate(addresses).get(base_asset)

        # Именованные MM-институции, набравшие ЛОНГ по монете — сильный контекст.
        named = self._named_longs(base_asset)

        net = 0.0
        pool_note = None
        if info:
            total = info["long"] + info["short"]
            if total >= _MIN_NOTIONAL:
                net = (info["long"] - info["short"]) / total   # -1..1
                if net > 0.15:
                    pool_note = (f"ММ набирают лонг (инвентарь): {info['n_long']} поз. "
                                 f"${info['long']/1e6:.1f}M vs шорт ${info['short']/1e6:.1f}M")

        # ММ структурно в шорте — это не медвежий сигнал. Сигнал даём, только если
        # пул ММ необычно в нетто-лонге ИЛИ именованная институция набрала лонг.
        if not pool_note and not named:
            return None

        score = net * 0.4 if net > 0.15 else 0.0
        if named:
            score = max(score, 0.35)   # именованная институция в лонге — весомо

        parts = []
        if pool_note:
            parts.append(pool_note)
        for name, notional in named:
            parts.append(f"🏛 {name}: лонг ${notional/1e6:.1f}M")
        note = "; ".join(parts)
        return Contribution(self.name, score, self.weight, note).clamped()
