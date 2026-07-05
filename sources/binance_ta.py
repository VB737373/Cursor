"""Технический анализ по свечам Binance.

Это "TradingView-часть": RSI, EMA-тренд, MACD, объём — считаем сами,
не нарушая правил TradingView. Самый весомый источник сигнала.
"""
from __future__ import annotations

from typing import Optional

import indicators as ind

from .base import SCOPE_SYMBOL, Contribution, DataSource


class BinanceTA(DataSource):
    name = "Technical Analysis"
    scope = SCOPE_SYMBOL
    requires_key = False

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        k = context.get("klines")
        if not k or len(k["close"]) < 60:
            return None

        closes = k["close"]
        highs = k["high"]
        lows = k["low"]
        vols = k["volume"]
        cfg = self.cfg

        ema_fast = ind.ema(closes, cfg.ema_fast)
        ema_slow = ind.ema(closes, cfg.ema_slow)
        ema_trend = ind.ema(closes, cfg.ema_trend)
        rsi = ind.rsi(closes, cfg.rsi_period)
        _, _, hist = ind.macd(closes, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
        atr = ind.atr(highs, lows, closes, cfg.atr_period)

        price = closes[-1]
        ema_f = ind.last_valid(ema_fast)
        ema_s = ind.last_valid(ema_slow)
        ema_t = ind.last_valid(ema_trend)
        rsi_v = ind.last_valid(rsi)
        hist_v = ind.last_valid(hist)
        atr_v = ind.last_valid(atr)

        if None in (ema_f, ema_s, rsi_v):
            return None

        # Сохраняем данные для расчёта уровней входа/стопа/тейка
        context["price"] = price
        context["atr"] = atr_v

        score = 0.0
        reasons = []

        # 1) EMA fast vs slow (тренд краткосрочный)
        if ema_f > ema_s:
            score += 0.35
            reasons.append("EMA9>EMA21 (бычий кросс)")
        else:
            score -= 0.35

        # 2) Цена выше долгого тренда
        if ema_t is not None:
            if price > ema_t:
                score += 0.20
                reasons.append("цена выше EMA50 (аптренд)")
            else:
                score -= 0.20

        # 3) RSI в зоне импульса вверх, но без перекупленности
        if rsi_v is not None:
            if cfg.rsi_long_min <= rsi_v <= cfg.rsi_long_max:
                score += 0.25
                reasons.append(f"RSI {rsi_v:.0f} (импульс)")
            elif rsi_v > cfg.rsi_long_max:
                score -= 0.15
                reasons.append(f"RSI {rsi_v:.0f} (перекупл.)")
            elif rsi_v < 40:
                score -= 0.20

        # 4) MACD-гистограмма положительна
        if hist_v is not None:
            if hist_v > 0:
                score += 0.15
                reasons.append("MACD>0")
            else:
                score -= 0.10

        # 5) Всплеск объёма
        if len(vols) >= 20:
            avg_vol = sum(vols[-20:]) / 20
            if avg_vol > 0 and vols[-1] > avg_vol * 1.5:
                score += 0.10
                reasons.append("рост объёма")

        reason = ", ".join(reasons) if reasons else "нейтрально"
        return Contribution(self.name, score, self.weight, reason).clamped()
