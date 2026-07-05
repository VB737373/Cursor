"""Отслеживание китов Hyperliquid (бесплатно, публичный API).

Как HypurrScan: следим за позициями крупных прибыльных трейдеров.

Адреса китов подбираются автоматически с публичного лидерборда Hyperliquid
(топ по PnL за месяц среди крупных счётов = «умные деньги»). Дополнительно
можно вручную добавить адреса в whales.txt (они всегда в списке).

Логика для лонга: киты нетто в ЛОНГЕ по монете — подтверждение (умные деньги
набирают), голосуем за лонг. Нетто-шорт — против.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from . import hl_leaderboard as hl
from .base import SCOPE_SYMBOL, Contribution, DataSource

log = logging.getLogger("whales")

_MIN_NOTIONAL = 50_000    # игнорируем монеты с суммарной позицией китов меньше этого
_sel_cache: dict = {"ts": 0.0, "addr": []}


def _auto_addresses(top_n: int, min_account: float) -> list:
    """Топ-N прибыльных китов с лидерборда (кэш выбора на срок жизни лидерборда)."""
    now = time.time()
    if _sel_cache["addr"] and now - _sel_cache["ts"] < hl._LB_TTL:
        return _sel_cache["addr"]
    rows = hl.leaderboard_rows()
    if not rows:
        return _sel_cache["addr"]
    picked = []
    for r in rows:
        try:
            av = float(r["accountValue"])
            month_pnl = float(dict(r["windowPerformances"])["month"]["pnl"])
        except (KeyError, TypeError, ValueError):
            continue
        if av >= min_account and month_pnl > 0:
            picked.append((month_pnl, r["ethAddress"]))
    picked.sort(reverse=True)
    addresses = [a for _, a in picked[:top_n]]
    if addresses:
        _sel_cache["addr"] = addresses
        _sel_cache["ts"] = now
        log.info("Киты Hyperliquid: отобрано %d прибыльных адресов", len(addresses))
    return _sel_cache["addr"]


def _resolve_addresses(cfg) -> list:
    manual = list(getattr(cfg, "whale_addresses", None) or [])
    if getattr(cfg, "whales_auto", True):
        auto = _auto_addresses(getattr(cfg, "whales_top_n", 30),
                               getattr(cfg, "whales_min_account", 2_000_000.0))
        seen = {a.lower() for a in manual}
        manual += [a for a in auto if a.lower() not in seen]
    return manual


class HyperliquidWhales(DataSource):
    name = "Hyperliquid Whales"
    scope = SCOPE_SYMBOL
    requires_key = False

    def enabled(self) -> bool:
        return bool(getattr(self.cfg, "whale_addresses", None)) or \
            bool(getattr(self.cfg, "whales_auto", True))

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        addresses = _resolve_addresses(self.cfg)
        if not addresses:
            return None
        info = hl.aggregate(addresses).get(base_asset)
        if not info:
            return None

        total = info["long"] + info["short"]
        if total < _MIN_NOTIONAL:
            return None

        net = (info["long"] - info["short"]) / total   # -1..1
        score = net * 0.6
        if net > 0.15:
            note = (f"киты в лонге: {info['n_long']} поз. "
                    f"${info['long']/1e6:.1f}M vs шорт ${info['short']/1e6:.1f}M")
        elif net < -0.15:
            note = (f"киты в шорте: {info['n_short']} поз. "
                    f"${info['short']/1e6:.1f}M vs лонг ${info['long']/1e6:.1f}M")
        else:
            note = "киты нейтральны"
        return Contribution(self.name, score, self.weight, note).clamped()
