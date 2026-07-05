"""Форматирование сигналов для отправки в Telegram (без зависимостей от фреймворка)."""
from __future__ import annotations

from engine import Decision

DISCLAIMER = (
    "\n\n⚠️ <i>Не финансовый совет. Сигналы носят информационный характер. "
    "Крипта высокорискованна — торгуйте только тем, что готовы потерять.</i>"
)


def fmt_price(x: float) -> str:
    if x is None:
        return "—"
    if x >= 100:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}"
    if x >= 0.01:
        return f"{x:.6f}"
    return f"{x:.8f}"


def fmt_usd(x: float) -> str:
    if x is None:
        return "—"
    if x >= 1_000_000_000:
        return f"${x / 1_000_000_000:.2f}B"
    if x >= 1_000_000:
        return f"${x / 1_000_000:.1f}M"
    if x >= 1_000:
        return f"${x / 1_000:.1f}K"
    return f"${x:.0f}"


def format_signal(d: Decision) -> str:
    exch = ", ".join(d.exchanges) if d.exchanges else "—"
    ch = f"{d.pct_change_24h:+.1f}%" if d.pct_change_24h is not None else "—"
    lines = [
        f"🟢 <b>ЛОНГ: {d.base}</b>  (<code>{d.symbol}</code>)",
        f"Уверенность: <b>{d.confidence:.0f}%</b>",
        f"🏦 Биржи: {exch}",
        f"📊 Данные с: {d.source_exchange or '—'}",
        f"📈 24ч: {ch}  |  Объём: {fmt_usd(d.total_volume)}",
        "",
        f"💵 Вход:  <code>{fmt_price(d.entry)}</code>",
        f"🛑 Стоп:  <code>{fmt_price(d.stop)}</code>",
        f"🎯 Тейк:  <code>{fmt_price(d.take)}</code>",
        "",
        "<b>Почему:</b>",
    ]
    for r in d.reasons:
        lines.append(f"• {r}")
    return "\n".join(lines)
