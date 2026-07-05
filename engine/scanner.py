"""Сканер рынка: прогоняет монеты через все источники и собирает сигналы."""
from __future__ import annotations

import logging
from typing import List

from sources import SCOPE_MARKET, SCOPE_SYMBOL, build_sources
from sources.http import get_json
from sources.market import build_universe, make_exchanges

from .scoring import Decision, decide

log = logging.getLogger("scanner")

_FBASE = "https://fapi.binance.com"


def _binance_perp_bases() -> set:
    """Базовые активы, у которых есть USDT-перпетуал на Binance Futures."""
    data = get_json(f"{_FBASE}/fapi/v1/ticker/24hr")
    bases = set()
    if isinstance(data, list):
        for t in data:
            sym = t.get("symbol", "")
            if sym.endswith("USDT"):
                bases.add(sym[:-4])
    return bases


class Scanner:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sources = build_sources(cfg)
        self.exchanges = make_exchanges(cfg)

    def _market_contributions(self) -> list:
        out = []
        context: dict = {}
        for s in self.sources:
            if s.scope == SCOPE_MARKET:
                try:
                    c = s.analyze_market(context)
                    if c:
                        out.append(c)
                except Exception as e:  # источник не должен ронять скан
                    log.warning("Источник %s (market) упал: %s", s.name, e)
        return out

    def _levels(self, decision: Decision, context: dict) -> None:
        price = context.get("price") or decision.price
        atr = context.get("atr")
        decision.entry = round(price, 8)

        if atr and atr > 0:
            atr_stop = price - atr * self.cfg.stop_atr_mult
            take = price + atr * self.cfg.take_atr_mult
        else:
            atr_stop = price * 0.97
            take = price * 1.06

        # Умный стоп: под уровнем поддержки Value Area (VAL), если он рядом
        val = context.get("val")
        stop = atr_stop
        if val and val < price and (price - val) / price < 0.15:
            stop = min(atr_stop, val * 0.997)

        decision.stop = round(stop, 8)
        decision.take = round(take, 8)

    def scan(self) -> List[Decision]:
        cfg = self.cfg
        universe = build_universe(
            self.exchanges,
            min_volume_usdt=cfg.min_volume_usdt,
            limit=cfg.max_symbols,
            min_exchanges=cfg.min_exchanges,
        )

        # Фильтр тонких монет: оставляем только те, у кого есть перпетуал на
        # Binance (по ним есть funding/OI/ордерфлоу и меньше риск манипуляций).
        if cfg.require_futures:
            perp_bases = _binance_perp_bases()
            if perp_bases:
                before = len(universe)
                universe = [c for c in universe if c.base in perp_bases]
                log.info("Фильтр перпетуалов: %d -> %d монет", before, len(universe))

        log.info("Сканирую %d монет (режим=%s)", len(universe), cfg.scan_mode)
        self._last_universe_size = len(universe)
        market_contribs = self._market_contributions()

        results: List[Decision] = []
        for coin in universe:
            base = coin.base
            kl = coin.klines(cfg.interval, limit=200)
            if not kl:
                continue
            klines, src_exchange = kl

            best = coin.best
            context: dict = {
                "klines": klines,
                "price": klines["close"][-1],
                "exchanges": coin.exchange_names,
                "source_exchange": src_exchange,
                "exchange_client": best.exchange,
                "exchange_symbol": best.symbol,
                "pct_change_24h": best.pct_change,
                "total_volume": coin.total_volume,
            }

            contribs = list(market_contribs)
            for s in self.sources:
                if s.scope != SCOPE_SYMBOL:
                    continue
                try:
                    c = s.analyze_symbol(best.symbol, base, context)
                    if c:
                        contribs.append(c)
                except Exception as e:
                    log.warning("Источник %s на %s упал: %s", s.name, base, e)

            decision = decide(best.symbol, base, context["price"], contribs,
                              cfg.signal_threshold)
            if decision.verdict == "LONG":
                self._levels(decision, context)
                decision.exchanges = coin.exchange_names
                decision.source_exchange = src_exchange
                decision.pct_change_24h = best.pct_change
                decision.total_volume = coin.total_volume
                decision.exchange_symbols = {
                    l.exchange.name: l.symbol for l in coin.listings
                }
                results.append(decision)

        results.sort(key=lambda d: d.confidence, reverse=True)
        log.info("Найдено сигналов на лонг: %d", len(results))
        return results
