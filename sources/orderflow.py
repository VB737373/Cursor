"""Order Flow: дисбаланс стакана + дельта/CVD (как в ATAS/Quantower).

Всё считается из ПУБЛИЧНОГО API фьючерсов Binance (без ключей):

  * Стакан (order book) — берём глубину и считаем дисбаланс между суммарным
    объёмом заявок на покупку (bids) и продажу (asks). Перевес bids = давление
    покупателей.
  * Дельта / CVD (Cumulative Volume Delta) — по свечам известен объём покупок
    «по рынку» (taker buy volume). Дельта свечи = покупки - продажи.
    Накопленная дельта (CVD), растущая вместе с ценой, подтверждает лонг.
"""
from __future__ import annotations

from typing import Optional

from .base import SCOPE_SYMBOL, Contribution, DataSource
from .http import get_json

_FBASE = "https://fapi.binance.com"
_KLINE_INTERVALS = {
    "1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d",
}


class OrderFlow(DataSource):
    name = "Order Flow (стакан/дельта)"
    scope = SCOPE_SYMBOL
    requires_key = False

    def _interval(self) -> str:
        return self.cfg.interval if self.cfg.interval in _KLINE_INTERVALS else "1h"

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        perp = f"{base_asset}USDT"

        # --- 1) Дисбаланс стакана ---
        depth = get_json(f"{_FBASE}/fapi/v1/depth",
                         params={"symbol": perp, "limit": 100})
        imbalance = None
        if isinstance(depth, dict) and depth.get("bids") and depth.get("asks"):
            try:
                bid_vol = sum(float(q) for _, q in depth["bids"])
                ask_vol = sum(float(q) for _, q in depth["asks"])
                if bid_vol + ask_vol > 0:
                    imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
            except (TypeError, ValueError):
                pass

        # --- 2) Дельта / CVD из свечей (taker buy volume) ---
        cvd_total = None
        cvd_recent = None
        kl = get_json(f"{_FBASE}/fapi/v1/klines",
                      params={"symbol": perp, "interval": self._interval(),
                              "limit": 48})
        price_change_recent = None
        if isinstance(kl, list) and len(kl) >= 12:
            try:
                deltas = []
                closes = []
                for c in kl:
                    vol = float(c[5])
                    taker_buy = float(c[9])  # объём покупок по рынку
                    deltas.append(2 * taker_buy - vol)  # buy - sell
                    closes.append(float(c[4]))
                cvd_total = sum(deltas)
                cvd_recent = sum(deltas[-12:])
                if closes[-12] > 0:
                    price_change_recent = (closes[-1] - closes[-12]) / closes[-12] * 100
            except (TypeError, ValueError, IndexError):
                pass

        if imbalance is None and cvd_total is None:
            return None  # нет перпетуала / данных

        score = 0.0
        reasons = []

        # --- Стакан ---
        if imbalance is not None:
            if imbalance > 0.15:
                score += 0.25
                reasons.append(f"стакан: перевес покупок {imbalance*100:+.0f}%")
            elif imbalance < -0.15:
                score -= 0.25
                reasons.append(f"стакан: перевес продаж {imbalance*100:+.0f}%")
            else:
                reasons.append("стакан сбалансирован")

        # --- Дельта / CVD ---
        if cvd_total is not None:
            if cvd_total > 0 and cvd_recent is not None and cvd_recent > 0:
                score += 0.30
                reasons.append("CVD растёт (покупатели давят)")
            elif cvd_total < 0 and cvd_recent is not None and cvd_recent < 0:
                score -= 0.30
                reasons.append("CVD падает (продавцы давят)")
            elif cvd_recent is not None and cvd_recent > 0:
                score += 0.10
                reasons.append("дельта развернулась вверх")

        # --- CVD-дивергенция (цена вниз, но покупки растут = разворот) ---
        if price_change_recent is not None and cvd_recent is not None:
            if price_change_recent < -0.5 and cvd_recent > 0:
                score += 0.20
                reasons.append("бычья CVD-дивергенция (продажи выдыхаются)")
            elif price_change_recent > 0.5 and cvd_recent < 0:
                score -= 0.20
                reasons.append("медвежья CVD-дивергенция")

        reason = ", ".join(reasons) if reasons else "order flow нейтрален"
        return Contribution(self.name, score, self.weight, reason).clamped()
