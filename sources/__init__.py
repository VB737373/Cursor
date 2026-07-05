"""Пакет источников данных и фабрика их сборки."""
from __future__ import annotations

import logging
from typing import List

from .base import Contribution, DataSource, SCOPE_MARKET, SCOPE_SYMBOL
from .binance_ta import BinanceTA
from .coinglass import CoinGlass
from .coinmarketcap import CoinMarketCap
from .defillama import DefiLlama
from .derivatives import Derivatives
from .fear_greed import FearGreed
from .liquidations import Liquidations
from .liquidation_zones import LiquidationZones
from .lunarcrush import LunarCrush
from .marketregime import MarketRegime
from .multitimeframe import MultiTimeframe
from .news import News
from .orderflow import OrderFlow
from .telegram_social import TelegramSocial
from .volumeprofile import VolumeProfile
from .whales import HyperliquidWhales
from .onchain import Arkham, CryptoQuant, DeBank, DropsTab, Glassnode, Nansen

log = logging.getLogger("sources")


def build_sources(cfg) -> List[DataSource]:
    """Создаёт все источники и оставляет только включённые (enabled())."""
    w = cfg.weights
    candidates: List[DataSource] = [
        BinanceTA(cfg, w.get("Technical Analysis", 3.0)),
        MultiTimeframe(cfg, w.get("Multi-Timeframe", 2.5)),
        Derivatives(cfg, w.get("Derivatives (Funding/OI)", 2.5)),
        OrderFlow(cfg, w.get("Order Flow (стакан/дельта)", 2.0)),
        VolumeProfile(cfg, w.get("Volume Profile (POC)", 2.0)),
        Liquidations(cfg, w.get("Liquidations", 1.5)),
        LiquidationZones(cfg, w.get("Liquidation Zones (оценка)", 1.5)),
        HyperliquidWhales(cfg, w.get("Hyperliquid Whales", 2.0)),
        MarketRegime(cfg, w.get("Market Regime", 1.0)),
        News(cfg, w.get("News", 1.5)),
        TelegramSocial(cfg, w.get("Telegram Social", 1.5)),
        LunarCrush(cfg, w.get("LunarCrush (соцсети)", 1.5)),
        FearGreed(cfg, w.get("Fear & Greed", 1.0)),
        DefiLlama(cfg, w.get("DefiLlama", 1.0)),
        CoinGlass(cfg, w.get("CoinGlass", 2.0)),
        CoinMarketCap(cfg, w.get("CoinMarketCap", 1.0)),
        Glassnode(cfg, w.get("Glassnode", 1.5)),
        CryptoQuant(cfg, w.get("CryptoQuant", 1.5)),
        Nansen(cfg, w.get("Nansen", 2.0)),
        Arkham(cfg, w.get("Arkham", 1.5)),
        DeBank(cfg, w.get("DeBank", 1.0)),
        DropsTab(cfg, w.get("DropsTab", 1.0)),
    ]
    enabled = [s for s in candidates if s.enabled()]
    for s in candidates:
        state = "ВКЛ" if s in enabled else "выкл (нет ключа)"
        log.info("Источник %-20s %s", s.name, state)
    return enabled


__all__ = [
    "Contribution",
    "DataSource",
    "SCOPE_MARKET",
    "SCOPE_SYMBOL",
    "build_sources",
]
