"""Walk-forward оптимизация параметров стратегии.

Идея честной оптимизации: делим историю на TRAIN (первые 70%) и TEST
(последние 30%). Перебираем комбинации порога/стопа/тейка на TRAIN, выбираем
лучшую, и проверяем её на TEST (данные, которые оптимизатор «не видел»).
Если на TEST результат тоже хороший — параметры робастны, а не подогнаны.

Оптимизируются параметры, которые реально влияют на живого бота:
  * SIGNAL_THRESHOLD  — порог уверенности,
  * STOP_ATR_MULT     — множитель стопа,
  * TAKE_ATR_MULT     — множитель тейка.

Запуск:
    python optimize.py --symbols 120 --limit 1000
"""
from __future__ import annotations

import argparse
import itertools
from typing import Dict, List, Optional

from backtest import (WINDOW, Trade, build_fng_lookup, build_regime_lookup,
                      compute_signals, fetch_funding, fetch_futures_klines,
                      simulate_signals)
from config import Config
from sources.http import get_json
from sources.binance_ta import BinanceTA
from sources.liquidation_zones import LiquidationZones
from sources.volumeprofile import VolumeProfile

_FBASE = "https://fapi.binance.com"

# Сетка перебора (расширена, чтобы искать и высокий win rate)
THRESHOLDS = [64, 66, 68, 70, 72]
STOP_MULTS = [1.0, 1.5, 2.0, 2.5, 3.0]
TAKE_MULTS = [1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
HOLD = 48
MIN_TRADES = 40  # минимум сделок на train, иначе комбо не рассматриваем
TRAIN_FRAC = 0.70


def metrics(trades: List[Trade]) -> Optional[dict]:
    if not trades:
        return None
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    gross_win = sum(t.pnl_pct for t in wins)
    gross_loss = abs(sum(t.pnl_pct for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    exp_r = sum(t.r_multiple for t in trades) / len(trades)
    return {
        "n": len(trades),
        "win_rate": len(wins) / len(trades) * 100,
        "pf": pf,
        "exp_r": exp_r,
        "total": sum(t.pnl_pct for t in trades),
    }


def evaluate(dataset: List[tuple], signals_key: str, threshold: float,
             stop_mult: float, take_mult: float) -> Optional[dict]:
    """Прогоняет комбинацию по всем монетам, возвращает агрегированные метрики."""
    all_trades: List[Trade] = []
    for symbol, k, train_sig, test_sig in dataset:
        sig = train_sig if signals_key == "train" else test_sig
        all_trades.extend(
            simulate_signals(k, sig, threshold, stop_mult, take_mult, HOLD, symbol))
    return metrics(all_trades)


def main() -> None:
    p = argparse.ArgumentParser(description="Walk-forward оптимизация")
    p.add_argument("--symbols", type=int, default=120)
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--metric", choices=["exp", "winrate"], default="exp",
                   help="что максимизировать: exp (прибыль/R) или winrate (доля побед, оставаясь в плюсе)")
    p.add_argument("--min-winrate", type=float, default=None,
                   help="искать самый прибыльный вариант с win rate не ниже этого % (напр. 65)")
    args = p.parse_args()

    cfg = Config.load()
    ta = BinanceTA(cfg, cfg.weights.get("Technical Analysis", 3.0))
    vp = VolumeProfile(cfg, cfg.weights.get("Volume Profile (POC)", 2.0))
    lz = LiquidationZones(cfg, cfg.weights.get("Liquidation Zones (оценка)", 1.5))

    print(f"Интервал: {cfg.interval} | train/test = {int(TRAIN_FRAC*100)}/{int((1-TRAIN_FRAC)*100)}")
    print("Гружу режим рынка (BTC) и Fear&Greed…")
    regime = build_regime_lookup(cfg, cfg.interval, args.limit)
    fng = build_fng_lookup()

    print(f"Гружу топ-{args.symbols} перпетуалов и считаю сигналы (это дольше всего)…")
    tickers = get_json(f"{_FBASE}/fapi/v1/ticker/24hr")
    usdt = [t for t in tickers if t.get("symbol", "").endswith("USDT")]
    usdt.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
    symbols = [t["symbol"] for t in usdt[:args.symbols]]

    dataset: List[tuple] = []
    for idx, symbol in enumerate(symbols, 1):
        k = fetch_futures_klines(symbol, cfg.interval, args.limit)
        if not k or len(k["close"]) < WINDOW + 20:
            continue
        funding = fetch_funding(symbol)
        signals = compute_signals(cfg, symbol, k, funding, regime, fng,
                                  regime_filter=True, use_regime=True,
                                  ta=ta, vp=vp, lz=lz)
        n = len(k["close"])
        split_idx = WINDOW + int((n - WINDOW) * TRAIN_FRAC)
        train_sig = [s for s in signals if s["idx"] < split_idx]
        test_sig = [s for s in signals if s["idx"] >= split_idx]
        dataset.append((symbol, k, train_sig, test_sig))
        if idx % 20 == 0:
            print(f"  обработано {idx}/{len(symbols)}…")

    print(f"Готово: {len(dataset)} монет. Перебираю "
          f"{len(THRESHOLDS)*len(STOP_MULTS)*len(TAKE_MULTS)} комбинаций на train…\n")

    results = []
    for th, sm, tm in itertools.product(THRESHOLDS, STOP_MULTS, TAKE_MULTS):
        m = evaluate(dataset, "train", th, sm, tm)
        if m and m["n"] >= MIN_TRADES:
            results.append(((th, sm, tm), m))

    if not results:
        print("Не набралось комбинаций с достаточным числом сделок.")
        return

    if args.min_winrate is not None:
        # Самый прибыльный вариант при win rate не ниже заданного
        pool = [r for r in results if r[1]["win_rate"] >= args.min_winrate
                and r[1]["pf"] > 1.05]
        if not pool:
            print(f"Нет прибыльных комбинаций с win rate ≥ {args.min_winrate}%. "
                  "Показываю ближайшие по win rate.")
            pool = sorted(results, key=lambda x: x[1]["win_rate"], reverse=True)
        else:
            pool.sort(key=lambda x: x[1]["exp_r"], reverse=True)
        results = pool
        print(f"ТОП-5 на TRAIN (win rate ≥ {args.min_winrate}%, по прибыльности):")
    elif args.metric == "winrate":
        # Максимальный win rate среди прибыльных комбинаций (PF > 1.05)
        profitable = [r for r in results if r[1]["pf"] > 1.05]
        pool = profitable if profitable else results
        pool.sort(key=lambda x: x[1]["win_rate"], reverse=True)
        results = pool
        print("ТОП-5 комбинаций на TRAIN (по win rate, среди прибыльных):")
    else:
        results.sort(key=lambda x: x[1]["exp_r"], reverse=True)
        print("ТОП-5 комбинаций на TRAIN (по матожиданию):")
    print(f"{'порог':>6} {'стоп':>5} {'тейк':>5} | {'сделок':>6} {'win%':>5} {'PF':>5} {'exp_R':>6}")
    for (th, sm, tm), m in results[:5]:
        pf = "∞" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
        print(f"{th:>6} {sm:>5} {tm:>5} | {m['n']:>6} {m['win_rate']:>5.1f} {pf:>5} {m['exp_r']:>+6.2f}")

    best_params, best_train = results[0]
    th, sm, tm = best_params
    best_test = evaluate(dataset, "test", th, sm, tm)

    print("\n" + "=" * 56)
    print("ЛУЧШИЕ ПАРАМЕТРЫ (выбраны на train)")
    print("=" * 56)
    print(f"SIGNAL_THRESHOLD = {th}")
    print(f"STOP_ATR_MULT    = {sm}")
    print(f"TAKE_ATR_MULT    = {tm}")
    print("-" * 56)

    def show(tag, m):
        if not m:
            print(f"{tag}: сделок нет")
            return
        pf = "∞" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
        print(f"{tag}: сделок {m['n']}, win {m['win_rate']:.1f}%, "
              f"PF {pf}, exp {m['exp_r']:+.2f}R, P&L {m['total']:+.1f}%")

    show("TRAIN (in-sample) ", best_train)
    show("TEST  (out-sample)", best_test)
    print("=" * 56)
    if best_test and best_test["exp_r"] > 0 and best_test["pf"] > 1.05:
        print("Вывод: параметры робастны — плюс и на неподсмотренных данных.")
    else:
        print("Вывод: на TEST перевес слабее — возможна переоптимизация, "
              "лучше выбрать консервативнее.")


if __name__ == "__main__":
    main()
