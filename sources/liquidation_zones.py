"""Зоны ликвидаций (оценка) — бесплатный аналог хитмапа ликвидаций.

CoinGlass liquidation heatmap показывает, где скопились плечевые позиции и
куда «магнитит» цену. Их API платный, поэтому здесь мы СТРОИМ ПРИБЛИЖЕНИЕ
из бесплатных данных (свечи), без ключей.

Идея: трейдеры открывают позиции возле недавних цен (взвешиваем по объёму и
свежести). Для каждой такой цены проецируем уровни ликвидации по типовым
плечам:
  * лонг с плечом L ликвидируется примерно на  price*(1 - 1/L)  — НИЖЕ;
  * шорт с плечом L ликвидируется примерно на   price*(1 + 1/L)  — ВЫШЕ.

Для входа в ЛОНГ благоприятно:
  * плотный кластер ШОРТ-ликвидаций СВЕРХУ рядом — их срабатывание вызывает
    принудительные покупки (short squeeze) и тянет цену вверх (топливо);
  * НЕТ плотного кластера ЛОНГ-ликвидаций вплотную снизу — иначе небольшой
    пролив может запустить каскад вниз.
"""
from __future__ import annotations

from typing import Optional

from .base import SCOPE_SYMBOL, Contribution, DataSource

_LEVERAGES = (10, 25, 50, 100)
_LOOKBACK = 96          # сколько последних свечей учитываем
_BAND = 0.05            # симметричное окно ±5% вокруг текущей цены
_MIN_SKEW = 0.20        # порог перекоса, ниже которого источник воздерживается


def estimate_zones(closes, volumes, cur_price):
    """Возвращает (short_above, long_below) — взвешенные плотности в ±5%."""
    look = min(len(closes), _LOOKBACK)
    if look < 20 or cur_price <= 0:
        return None
    cs = closes[-look:]
    vs = volumes[-look:]

    short_above = long_below = 0.0
    for idx, (p, v) in enumerate(zip(cs, vs)):
        if p <= 0 or v <= 0:
            continue
        recency = 0.3 + 0.7 * (idx / (look - 1)) if look > 1 else 1.0
        w = v * recency
        for lev in _LEVERAGES:
            long_liq = p * (1 - 1.0 / lev)
            short_liq = p * (1 + 1.0 / lev)
            d_long = (cur_price - long_liq) / cur_price
            if 0 < d_long <= _BAND:
                long_below += w
            d_short = (short_liq - cur_price) / cur_price
            if 0 < d_short <= _BAND:
                short_above += w
    return short_above, long_below


class LiquidationZones(DataSource):
    name = "Liquidation Zones (оценка)"
    scope = SCOPE_SYMBOL
    requires_key = False

    def analyze_symbol(self, symbol, base_asset, context) -> Optional[Contribution]:
        k = context.get("klines")
        if not k or len(k["close"]) < 30:
            return None
        cur = k["close"][-1]
        res = estimate_zones(k["close"], k["volume"], cur)
        if res is None:
            return None
        short_above, long_below = res

        total = short_above + long_below
        if total <= 0:
            return None

        # net > 0: топлива из шорт-ликвидаций сверху больше, чем риска снизу
        net = (short_above - long_below) / total   # -1..1

        # Воздерживаемся, когда зоны примерно сбалансированы (чтобы не шуметь)
        if abs(net) < _MIN_SKEW:
            return None

        score = net * 0.5   # -0.5..0.5
        if net > 0:
            reason = "перекос к шорт-ликвидациям сверху (топливо для роста)"
        else:
            reason = "перекос к лонг-ликвидациям снизу (риск каскада)"

        return Contribution(self.name, score, self.weight, reason).clamped()
