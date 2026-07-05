"""Бэктест стратегии на истории свечей Binance (расширенный).

Прогоняет стратегию «в прошлом» методом walk-forward и считает реальную
статистику лонгов: win rate, средний профит/убыток, profit factor, матожидание.

Используются ТОЛЬКО источники, которые честно доступны по бесплатной истории:
  * Technical Analysis (RSI/EMA/MACD/ATR)          — вес 3.0
  * Multi-Timeframe (тренд старшего ТФ, ресемплинг) — вес 2.5
  * Volume Profile (POC / Value Area)              — вес 2.0
  * Derivatives → Funding (история funding rate)   — вес 2.5
  * Order Flow → CVD/дельта (taker buy из фьюч-свечей) — вес 2.0
  * Market Regime (тренд BTC)                       — вес 1.0
  * Fear & Greed (историческая история индекса)     — вес 1.0

НЕдоступны по бесплатной истории (в бэктест не входят, но в живом боте работают):
  стакан (orderbook), ликвидации, история OI/Long-Short (>21 дня платно),
  новости/Telegram/LunarCrush сентимент.

Запуск:
    python backtest.py                       # топ-40, интервал из .env
    python backtest.py --symbols 120 --threshold 60 --hold 48
    python backtest.py --no-regime-filter    # без запрета лонгов в даунтренде BTC
"""
from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import indicators as ind
from config import Config
from engine.scoring import decide
from sources import Contribution
from sources.binance_ta import BinanceTA
from sources.http import get_json
from sources.liquidation_zones import LiquidationZones
from sources.volumeprofile import VolumeProfile

logging.basicConfig(level=logging.WARNING, format="%(message)s")

_FBASE = "https://fapi.binance.com"

# Младший ТФ -> (имя старшего ТФ, во сколько раз он крупнее)
HTF_FACTOR = {
    "1m": ("15m", 15), "5m": ("1h", 12), "15m": ("1h", 4), "30m": ("4h", 8),
    "1h": ("4h", 4), "2h": ("1d", 12), "4h": ("1d", 6), "6h": ("1d", 4),
    "12h": ("1d", 2),
}

WINDOW = 200  # столько свечей видит бот в реальном времени


@dataclass
class Trade:
    symbol: str
    outcome: str
    r_multiple: float
    pnl_pct: float


# ----------------------------------------------------------------------------
# Загрузка данных
# ----------------------------------------------------------------------------
def fetch_futures_klines(symbol: str, interval: str, limit: int) -> Optional[dict]:
    """Фьюч-свечи с таймстемпами и taker buy volume (для CVD)."""
    data = get_json(f"{_FBASE}/fapi/v1/klines",
                    params={"symbol": symbol, "interval": interval, "limit": limit})
    if not isinstance(data, list) or not data:
        return None
    try:
        return {
            "time": [int(c[0]) for c in data],
            "open": [float(c[1]) for c in data],
            "high": [float(c[2]) for c in data],
            "low": [float(c[3]) for c in data],
            "close": [float(c[4]) for c in data],
            "volume": [float(c[5]) for c in data],
            "taker_buy": [float(c[9]) for c in data],
        }
    except (TypeError, ValueError, IndexError):
        return None


def fetch_funding(symbol: str, limit: int = 1000) -> List[tuple]:
    """История funding rate: [(fundingTime_ms, rate_pct), ...] по возрастанию."""
    data = get_json(f"{_FBASE}/fapi/v1/fundingRate",
                    params={"symbol": symbol, "limit": limit})
    out = []
    if isinstance(data, list):
        for d in data:
            try:
                out.append((int(d["fundingTime"]), float(d["fundingRate"]) * 100))
            except (KeyError, TypeError, ValueError):
                continue
    out.sort(key=lambda x: x[0])
    return out


def build_regime_lookup(cfg: Config, interval: str, limit: int) -> Dict[int, float]:
    """Оценка режима рынка по тренду BTC для каждого таймстемпа свечи."""
    k = fetch_futures_klines("BTCUSDT", interval, limit)
    if not k:
        return {}
    closes = k["close"]
    ema_f = ind.ema(closes, 50)
    ema_s = ind.ema(closes, 200)
    lookup: Dict[int, float] = {}
    for i, t in enumerate(k["time"]):
        ef, es, price = ema_f[i], ema_s[i], closes[i]
        if ef is None or es is None:
            continue
        if price > ef > es:
            lookup[t] = 0.4
        elif price > es:
            lookup[t] = 0.1
        elif price < ef < es:
            lookup[t] = -0.4
        else:
            lookup[t] = -0.1
    return lookup


def build_fng_lookup() -> Dict[str, int]:
    """История Fear & Greed: {'YYYY-MM-DD': value}."""
    data = get_json("https://api.alternative.me/fng/", params={"limit": 0})
    lookup: Dict[str, int] = {}
    if isinstance(data, dict):
        for item in data.get("data", []):
            try:
                ts = int(item["timestamp"])
                val = int(item["value"])
                lookup[time.strftime("%Y-%m-%d", time.gmtime(ts))] = val
            except (KeyError, TypeError, ValueError):
                continue
    return lookup


# ----------------------------------------------------------------------------
# Скоринг доп-источников (воспроизводит логику живых источников)
# ----------------------------------------------------------------------------
def resample_closes(closes: List[float], factor: int) -> List[float]:
    out = []
    for j in range(0, len(closes), factor):
        end = min(j + factor - 1, len(closes) - 1)
        out.append(closes[end])
    return out


def htf_contribution(closes_full: List[float], cfg: Config, factor: int,
                     htf_name: str, weight: float) -> Optional[Contribution]:
    htf_closes = resample_closes(closes_full, factor)
    if len(htf_closes) < 60:
        return None
    ema_f = ind.last_valid(ind.ema(htf_closes, cfg.ema_fast))
    ema_s = ind.last_valid(ind.ema(htf_closes, cfg.ema_slow))
    ema_t = ind.last_valid(ind.ema(htf_closes, cfg.ema_trend))
    if None in (ema_f, ema_s, ema_t):
        return None
    price = htf_closes[-1]
    up, above = ema_f > ema_s, price > ema_t
    if up and above:
        score, note = 0.4, f"{htf_name}-тренд вверх"
    elif up or above:
        score, note = 0.1, f"{htf_name}-тренд смешанный"
    else:
        score, note = -0.4, f"{htf_name}-тренд вниз"
    return Contribution("Multi-Timeframe", score, weight, note).clamped()


def funding_contribution(funding: List[tuple], candle_time: int,
                         weight: float) -> Optional[Contribution]:
    fr = None
    for t, rate in funding:  # funding отсортирован по возрастанию
        if t <= candle_time:
            fr = rate
        else:
            break
    if fr is None:
        return None
    if fr < -0.05:
        score, note = 0.30, f"funding {fr:+.3f}% (шорты платят)"
    elif fr <= 0.03:
        score, note = 0.15, f"funding {fr:+.3f}% (норма)"
    elif fr <= 0.08:
        score, note = -0.10, f"funding {fr:+.3f}% (повышен)"
    else:
        score, note = -0.35, f"funding {fr:+.3f}% (перегрев)"
    return Contribution("Derivatives (Funding/OI)", score, weight, note).clamped()


def cvd_contribution(taker_buy: List[float], volume: List[float],
                     closes: List[float], end_idx: int,
                     weight: float) -> Optional[Contribution]:
    lo = max(0, end_idx - 47)
    tb = taker_buy[lo:end_idx + 1]
    vol = volume[lo:end_idx + 1]
    cl = closes[lo:end_idx + 1]
    if len(tb) < 12:
        return None
    deltas = [2 * b - v for b, v in zip(tb, vol)]
    cvd_total = sum(deltas)
    cvd_recent = sum(deltas[-12:])
    pcr = None
    if cl[-12] > 0:
        pcr = (cl[-1] - cl[-12]) / cl[-12] * 100

    score = 0.0
    reasons = []
    if cvd_total > 0 and cvd_recent > 0:
        score += 0.30
        reasons.append("CVD растёт")
    elif cvd_total < 0 and cvd_recent < 0:
        score -= 0.30
        reasons.append("CVD падает")
    elif cvd_recent > 0:
        score += 0.10
        reasons.append("дельта вверх")
    if pcr is not None:
        if pcr < -0.5 and cvd_recent > 0:
            score += 0.20
            reasons.append("бычья CVD-дивергенция")
        elif pcr > 0.5 and cvd_recent < 0:
            score -= 0.20
            reasons.append("медвежья CVD-дивергенция")
    note = ", ".join(reasons) if reasons else "CVD нейтрален"
    return Contribution("Order Flow (стакан/дельта)", score, weight, note).clamped()


def fng_contribution(fng: Dict[str, int], candle_time: int,
                     weight: float) -> Optional[Contribution]:
    date = time.strftime("%Y-%m-%d", time.gmtime(candle_time / 1000))
    value = fng.get(date)
    if value is None:
        return None
    if value <= 20:
        score, note = 0.3, "выход из страха"
    elif value <= 45:
        score, note = 0.1, "осторожность"
    elif value <= 55:
        score, note = 0.0, "нейтрально"
    elif value <= 75:
        score, note = 0.25, "аппетит к риску"
    else:
        score, note = -0.2, "перегрев"
    return Contribution("Fear & Greed", score, weight, f"F&G {value} — {note}").clamped()


# ----------------------------------------------------------------------------
# Уровни и симуляция сделки
# ----------------------------------------------------------------------------
def levels(price: float, atr: Optional[float], val: Optional[float],
           stop_mult: float, take_mult: float) -> tuple:
    if atr and atr > 0:
        atr_stop = price - atr * stop_mult
        take = price + atr * take_mult
    else:
        atr_stop, take = price * 0.97, price * 1.06
    stop = atr_stop
    if val and val < price and (price - val) / price < 0.15:
        stop = min(atr_stop, val * 0.997)
    return stop, take


def simulate_trade(k: dict, entry_idx: int, entry: float, stop: float,
                   take: float, max_hold: int) -> tuple:
    highs, lows, closes = k["high"], k["low"], k["close"]
    end = min(entry_idx + max_hold, len(closes) - 1)
    for j in range(entry_idx + 1, end + 1):
        if lows[j] <= stop:
            return "loss", stop, j
        if highs[j] >= take:
            return "win", take, j
    return "timeout", closes[end], end


# ----------------------------------------------------------------------------
# Расчёт сигналов (переиспользуется бэктестом и оптимизатором)
# ----------------------------------------------------------------------------
def compute_signals(cfg: Config, symbol: str, k: dict, funding: List[tuple],
                    regime: Dict[int, float], fng: Dict[str, int],
                    regime_filter: bool, use_regime: bool,
                    ta: BinanceTA, vp: VolumeProfile,
                    lz: LiquidationZones) -> List[dict]:
    """Для каждой свечи считает confidence и данные для уровней (один раз)."""
    htf = HTF_FACTOR.get(cfg.interval)
    W = cfg.weights
    closes = k["close"]
    times = k["time"]
    n = len(closes)
    base = symbol[:-4]
    out: List[dict] = []

    for i in range(WINDOW, n):
        ct = times[i]
        reg = regime.get(ct) if use_regime else None
        if regime_filter and reg is not None and reg <= -0.4:
            continue

        lo = max(0, i - WINDOW + 1)
        window = {kk: k[kk][lo:i + 1] for kk in ("open", "high", "low", "close", "volume")}
        context: dict = {"klines": window}

        contribs: List[Contribution] = []
        c_ta = ta.analyze_symbol(symbol, base, context)
        if c_ta is None:
            continue
        contribs.append(c_ta)

        c_vp = vp.analyze_symbol(symbol, base, context)
        if c_vp:
            contribs.append(c_vp)
        c_lz = lz.analyze_symbol(symbol, base, context)
        if c_lz:
            contribs.append(c_lz)
        if htf:
            c_htf = htf_contribution(closes[:i + 1], cfg, htf[1], htf[0],
                                     W.get("Multi-Timeframe", 2.5))
            if c_htf:
                contribs.append(c_htf)
        c_fund = funding_contribution(funding, ct, W.get("Derivatives (Funding/OI)", 2.5))
        if c_fund:
            contribs.append(c_fund)
        c_cvd = cvd_contribution(k["taker_buy"], k["volume"], closes, i,
                                 W.get("Order Flow (стакан/дельта)", 2.0))
        if c_cvd:
            contribs.append(c_cvd)
        if reg is not None:
            contribs.append(Contribution("Market Regime", reg, W.get("Market Regime", 1.0),
                                         "режим BTC").clamped())
        c_fng = fng_contribution(fng, ct, W.get("Fear & Greed", 1.0))
        if c_fng:
            contribs.append(c_fng)

        d = decide(symbol, base, context["price"], contribs, 0)
        out.append({
            "idx": i,
            "confidence": d.confidence,
            "ta_ok": c_ta.score >= 0,
            "price": context["price"],
            "atr": context.get("atr"),
            "val": context.get("val"),
        })
    return out


def simulate_signals(k: dict, signals: List[dict], threshold: float,
                     stop_mult: float, take_mult: float, max_hold: int,
                     symbol: str) -> List[Trade]:
    """Проигрывает сделки по заранее посчитанным сигналам (быстро, для grid search)."""
    trades: List[Trade] = []
    pos = 0
    m = len(signals)
    while pos < m:
        s = signals[pos]
        if s["confidence"] < threshold or not s["ta_ok"]:
            pos += 1
            continue
        entry = s["price"]
        stop, take = levels(entry, s["atr"], s["val"], stop_mult, take_mult)
        if stop >= entry:
            pos += 1
            continue
        outcome, exit_price, exit_idx = simulate_trade(k, s["idx"], entry, stop, take, max_hold)
        risk = entry - stop
        r_mult = (exit_price - entry) / risk if risk > 0 else 0.0
        pnl_pct = (exit_price - entry) / entry * 100
        trades.append(Trade(symbol, outcome, r_mult, pnl_pct))
        while pos < m and signals[pos]["idx"] <= exit_idx:
            pos += 1
    return trades


def backtest_symbol(cfg: Config, symbol: str, k: dict, funding: List[tuple],
                    regime: Dict[int, float], fng: Dict[str, int],
                    threshold: float, max_hold: int, regime_filter: bool,
                    use_regime: bool, ta: BinanceTA, vp: VolumeProfile,
                    lz: LiquidationZones) -> List[Trade]:
    signals = compute_signals(cfg, symbol, k, funding, regime, fng,
                              regime_filter, use_regime, ta, vp, lz)
    return simulate_signals(k, signals, threshold, cfg.stop_atr_mult,
                            cfg.take_atr_mult, max_hold, symbol)


def summarize(trades: List[Trade]) -> None:
    if not trades:
        print("\nСделок не найдено — снизьте --threshold или возьмите больше монет.")
        return
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    win_rate = len(wins) / len(trades) * 100
    avg_win = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0
    gross_win = sum(t.pnl_pct for t in wins)
    gross_loss = abs(sum(t.pnl_pct for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    exp_r = sum(t.r_multiple for t in trades) / len(trades)
    total = sum(t.pnl_pct for t in trades)
    tp = sum(1 for t in trades if t.outcome == "win")
    sl = sum(1 for t in trades if t.outcome == "loss")
    to = sum(1 for t in trades if t.outcome == "timeout")

    print("\n" + "=" * 52)
    print("РЕЗУЛЬТАТЫ БЭКТЕСТА (расширенный)")
    print("=" * 52)
    print(f"Всего сделок:        {len(trades)}")
    print(f"Win rate:            {win_rate:.1f}%  ({len(wins)} / {len(losses)})")
    print(f"Исходы:              тейк {tp} | стоп {sl} | по времени {to}")
    print(f"Средний профит:      {avg_win:+.2f}%")
    print(f"Средний убыток:      {avg_loss:+.2f}%")
    print(f"Profit factor:       {pf:.2f}")
    print(f"Матожидание:         {exp_r:+.2f}R на сделку")
    print(f"Суммарный P&L:       {total:+.1f}%")
    print("=" * 52)
    if pf > 1.3 and exp_r > 0:
        print("Вывод: стратегия прибыльна на этом периоде.")
    elif exp_r > 0 or pf > 1.0:
        print("Вывод: положительная, есть перевес.")
    else:
        print("Вывод: убыточна на этом периоде.")


def main() -> None:
    p = argparse.ArgumentParser(description="Расширенный бэктест лонг-стратегии")
    p.add_argument("--symbols", type=int, default=40)
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--hold", type=int, default=48)
    p.add_argument("--threshold", type=float, default=None)
    p.add_argument("--no-regime-filter", action="store_true",
                   help="не запрещать лонги в даунтренде BTC")
    p.add_argument("--no-regime", action="store_true",
                   help="полностью исключить фактор BTC/режима рынка")
    args = p.parse_args()

    cfg = Config.load()
    threshold = args.threshold if args.threshold is not None else cfg.signal_threshold
    use_regime = not args.no_regime
    regime_filter = not args.no_regime_filter and use_regime
    ta = BinanceTA(cfg, cfg.weights.get("Technical Analysis", 3.0))
    vp = VolumeProfile(cfg, cfg.weights.get("Volume Profile (POC)", 2.0))
    lz = LiquidationZones(cfg, cfg.weights.get("Liquidation Zones (оценка)", 1.5))

    print(f"Интервал: {cfg.interval} | порог: {threshold} | удержание: {args.hold} | "
          f"BTC-режим: {'ВКЛ' if use_regime else 'ВЫКЛ'} | "
          f"режим-фильтр: {'ВКЛ' if regime_filter else 'выкл'}")
    print("Гружу режим рынка (BTC) и Fear&Greed…")
    regime = build_regime_lookup(cfg, cfg.interval, args.limit)
    fng = build_fng_lookup()
    print(f"  режим BTC: {len(regime)} точек | F&G: {len(fng)} дней")

    print(f"Гружу топ-{args.symbols} перпетуалов Binance…")
    tickers = get_json(f"{_FBASE}/fapi/v1/ticker/24hr")
    if not isinstance(tickers, list):
        print("Не удалось получить список фьючерсов.")
        return
    usdt = [t for t in tickers if t.get("symbol", "").endswith("USDT")]
    usdt.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
    symbols = [t["symbol"] for t in usdt[:args.symbols]]

    all_trades: List[Trade] = []
    for idx, symbol in enumerate(symbols, 1):
        k = fetch_futures_klines(symbol, cfg.interval, args.limit)
        if not k or len(k["close"]) < WINDOW + 5:
            continue
        funding = fetch_funding(symbol)
        trades = backtest_symbol(cfg, symbol, k, funding, regime, fng,
                                 threshold, args.hold, regime_filter, use_regime,
                                 ta, vp, lz)
        all_trades.extend(trades)
        print(f"[{idx}/{len(symbols)}] {symbol:<12} сделок: {len(trades):>3} "
              f"(всего {len(all_trades)})")

    summarize(all_trades)


if __name__ == "__main__":
    main()
