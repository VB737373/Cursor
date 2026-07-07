"""Журнал сделок: логирует каждый отправленный сигнал и отслеживает исход.

Записывает сигналы в trades.json со статусом open. На каждом скане проверяет
открытые сделки по свечам Binance: задет ли стоп (loss) или тейк (win),
и обновляет статус. Команда /stats в боте показывает живую статистику.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from sources.http import get_json

log = logging.getLogger("journal")

TRADES_FILE = Path(__file__).parent / "trades.json"
_SBASE = "https://api.binance.com"
_MAX_HOLD_HOURS = 72  # через сколько часов закрывать сделку «по времени»


def to_binance_symbol(symbol: str, base: str | None = None) -> str:
    """Символ для Binance spot API: LTC-USDT / LTC_USDT → LTCUSDT."""
    if symbol:
        s = symbol.strip().upper().replace("-", "").replace("_", "")
        if s.endswith("USDT"):
            return s
    b = (base or "").strip().upper()
    if b:
        return f"{b}USDT"
    return symbol.strip().upper().replace("-", "").replace("_", "") if symbol else ""


def _trade_binance_symbol(t: dict) -> str:
    return t.get("binance_symbol") or to_binance_symbol(t.get("symbol", ""), t.get("base"))


def load_trades() -> List[dict]:
    if TRADES_FILE.exists():
        try:
            return json.loads(TRADES_FILE.read_text("utf-8"))
        except (ValueError, OSError):
            return []
    return []


def save_trades(trades: List[dict]) -> None:
    try:
        TRADES_FILE.write_text(json.dumps(trades, ensure_ascii=False, indent=2), "utf-8")
    except OSError as e:
        log.warning("Не удалось сохранить журнал: %s", e)


def log_signal(d) -> None:
    """Добавляет новый сигнал в журнал (статус open)."""
    trades = load_trades()
    trades.append({
        "time": time.time(),
        "symbol": d.symbol,
        "binance_symbol": to_binance_symbol(d.symbol, d.base),
        "base": d.base,
        "confidence": d.confidence,
        "entry": d.entry,
        "stop": d.stop,
        "take": d.take,
        "reasons": list(d.reasons),
        "status": "open",
        "exit_price": None,
        "exit_time": None,
        "pnl_pct": None,
    })
    save_trades(trades)


def _fetch_klines_since(symbol: str, start_ms: int) -> Optional[List[list]]:
    """Свечи 1h Binance с start_ms (нужны high/low/time для проверки исхода)."""
    data = get_json(f"{_SBASE}/api/v3/klines",
                    params={"symbol": symbol, "interval": "1h",
                            "startTime": start_ms, "limit": 200})
    return data if isinstance(data, list) else None


def check_open_trades() -> int:
    """Проверяет открытые сделки, отмечает исход. Возвращает число закрытых."""
    trades = load_trades()
    closed = 0
    changed = False
    now = time.time()

    for t in trades:
        bn = _trade_binance_symbol(t)
        if t.get("binance_symbol") != bn:
            t["binance_symbol"] = bn
            changed = True

        if t.get("status") != "open":
            continue
        entry = t.get("entry")
        stop = t.get("stop")
        take = t.get("take")
        if entry is None or stop is None or take is None:
            continue

        start_ms = int(t["time"] * 1000)
        kl = _fetch_klines_since(bn, start_ms) if bn else None
        if not kl:
            # монета не на Binance или нет данных — закроем по времени, если пора
            if now - t["time"] >= _MAX_HOLD_HOURS * 3600:
                t["status"] = "timeout"
                t["exit_time"] = now
                t["pnl_pct"] = 0.0
                closed += 1
                changed = True
            continue

        outcome = None
        exit_price = None
        exit_ms = None
        for c in kl:
            try:
                high = float(c[2])
                low = float(c[3])
                close_ms = int(c[6])
            except (TypeError, ValueError, IndexError):
                continue
            if low <= stop:          # консервативно: стоп раньше тейка
                outcome, exit_price, exit_ms = "loss", stop, close_ms
                break
            if high >= take:
                outcome, exit_price, exit_ms = "win", take, close_ms
                break

        if outcome:
            t["status"] = outcome
            t["exit_price"] = exit_price
            t["exit_time"] = exit_ms / 1000 if exit_ms else now
            t["pnl_pct"] = (exit_price - entry) / entry * 100
            closed += 1
            changed = True
        elif now - t["time"] >= _MAX_HOLD_HOURS * 3600:
            last_close = float(kl[-1][4])
            t["status"] = "timeout"
            t["exit_price"] = last_close
            t["exit_time"] = now
            t["pnl_pct"] = (last_close - entry) / entry * 100
            closed += 1
            changed = True

    if changed:
        save_trades(trades)
    return closed


def summary() -> str:
    """Текстовая сводка по журналу для команды /stats."""
    trades = load_trades()
    if not trades:
        return "📓 Журнал пуст — сигналов ещё не было."

    closed = [t for t in trades if t.get("status") in ("win", "loss", "timeout")
              and t.get("pnl_pct") is not None]
    open_n = sum(1 for t in trades if t.get("status") == "open")

    if not closed:
        return (f"📓 <b>Статистика сделок</b>\n"
                f"Всего сигналов: {len(trades)}\n"
                f"Открыто (в работе): {open_n}\n"
                f"Закрытых пока нет — статистика появится позже.")

    wins = [t for t in closed if t["pnl_pct"] > 0]
    losses = [t for t in closed if t["pnl_pct"] <= 0]
    win_rate = len(wins) / len(closed) * 100
    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0.0
    gross_win = sum(t["pnl_pct"] for t in wins)
    gross_loss = abs(sum(t["pnl_pct"] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    total = sum(t["pnl_pct"] for t in closed)
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"

    return (f"📓 <b>Статистика живых сигналов</b>\n\n"
            f"Всего сигналов: {len(trades)} (открыто: {open_n})\n"
            f"Закрыто: {len(closed)}\n"
            f"Win rate: <b>{win_rate:.0f}%</b> ({len(wins)}/{len(losses)})\n"
            f"Средний профит: {avg_win:+.2f}%\n"
            f"Средний убыток: {avg_loss:+.2f}%\n"
            f"Profit factor: <b>{pf_str}</b>\n"
            f"Суммарный P&L: {total:+.1f}%")
