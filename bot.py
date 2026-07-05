"""Telegram-бот сигналов на лонг.

Команды:
  /start  — подписаться на сигналы
  /stop   — отписаться
  /scan   — просканировать рынок прямо сейчас
  /status — статус и активные источники
  /help   — справка

Фоновая задача периодически сканирует рынок и рассылает новые сигналы
всем подписчикам (с учётом cooldown, чтобы не спамить).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Set

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import journal
from cloud_scan import trigger_github_scan
from config import Config
from engine import Decision, Scanner
from formatting import DISCLAIMER, format_signal
from sources.liquidations import run_collector
from sources.telegram_social import STORE as TG_STORE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")

SUBSCRIBERS_FILE = Path(__file__).parent / "subscribers.json"


# ---------- Хранилище подписчиков ----------
def load_subscribers() -> Set[int]:
    if SUBSCRIBERS_FILE.exists():
        try:
            return set(json.loads(SUBSCRIBERS_FILE.read_text("utf-8")))
        except (ValueError, OSError):
            return set()
    return set()


def save_subscribers(subs: Set[int]) -> None:
    try:
        SUBSCRIBERS_FILE.write_text(json.dumps(sorted(subs)), "utf-8")
    except OSError as e:
        log.warning("Не удалось сохранить подписчиков: %s", e)


# ---------- Команды ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    subs: Set[int] = context.application.bot_data["subscribers"]
    subs.add(chat_id)
    save_subscribers(subs)
    cfg: Config = context.application.bot_data["cfg"]
    commands_only = context.application.bot_data.get("commands_only", False)
    if commands_only:
        mode = (
            "Режим: <b>команды</b> (автосигналы идут из GitHub Actions).\n"
            "/scan — запустить облачный скан или проверить рынок сейчас.\n\n"
        )
    else:
        mode = (
            f"Сканирую рынок каждые {cfg.check_interval_seconds // 60} мин "
            f"(таймфрейм {cfg.interval}) и пришлю сигнал на лонг, когда "
            f"уверенность ≥ {cfg.signal_threshold:.0f}%.\n\n"
        )
    await update.message.reply_text(
        "✅ Подписка оформлена!\n\n"
        + mode
        + "Команды: /scan — проверить сейчас, /status — статус, /stop — отписаться."
        + DISCLAIMER,
        parse_mode=ParseMode.HTML,
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    subs: Set[int] = context.application.bot_data["subscribers"]
    subs.discard(chat_id)
    save_subscribers(subs)
    await update.message.reply_text("🚫 Вы отписались. /start — чтобы вернуться.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Бот сигналов на лонг</b>\n\n"
        "/start — подписаться\n"
        "/stop — отписаться\n"
        "/scan — просканировать рынок сейчас\n"
        "/stats — статистика по сигналам\n"
        "/status — активные источники и настройки\n"
        "/help — эта справка" + DISCLAIMER,
        parse_mode=ParseMode.HTML,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scanner: Scanner = context.application.bot_data["scanner"]
    cfg: Config = context.application.bot_data["cfg"]
    src_lines = "\n".join(
        f"• {s.name} (вес {s.weight})" for s in scanner.sources
    )
    exch_line = ", ".join(e.name for e in scanner.exchanges)
    await update.message.reply_text(
        f"<b>Статус</b>\n"
        f"Биржи: {exch_line}\n"
        f"Режим: {cfg.scan_mode} | монет: до {cfg.max_symbols}\n"
        f"Таймфрейм: {cfg.interval} | порог: {cfg.signal_threshold:.0f}%\n"
        f"Интервал скана: {cfg.check_interval_seconds // 60} мин\n\n"
        f"<b>Активные источники:</b>\n{src_lines}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await asyncio.to_thread(journal.check_open_trades)
    text = journal.summary()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    commands_only = context.application.bot_data.get("commands_only", False)
    use_cloud = os.getenv("USE_CLOUD_SCAN", "1").lower() in ("1", "true", "yes")

    if commands_only and use_cloud and os.getenv("GITHUB_TOKEN", "").strip():
        await update.message.reply_text("⏳ Запускаю скан в облаке (GitHub)…")
        ok, msg = await asyncio.to_thread(trigger_github_scan)
        if ok:
            await update.message.reply_text(
                "✅ Скан запущен в облаке.\n"
                "Через ~1 мин придёт отчёт в Telegram.\n\n"
                f'<a href="{msg}">Открыть Actions на GitHub</a>',
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        else:
            await update.message.reply_text(
                f"❌ Не удалось запустить облачный скан:\n{msg}"
            )
        return

    scanner: Scanner = context.application.bot_data["scanner"]
    await update.message.reply_text("🔎 Сканирую рынок, подожди немного…")
    signals = await asyncio.to_thread(scanner.scan)
    if not signals:
        await update.message.reply_text(
            "Сейчас нет монет, проходящих порог для лонга. Попробуй позже."
        )
        return
    for d in signals[:5]:
        await update.message.reply_text(
            format_signal(d) + DISCLAIMER, parse_mode=ParseMode.HTML
        )


# ---------- Фоновое сканирование ----------
async def scan_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    app = context.application
    scanner: Scanner = app.bot_data["scanner"]
    cfg: Config = app.bot_data["cfg"]
    subs: Set[int] = app.bot_data["subscribers"]
    cooldown: Dict[str, float] = app.bot_data["cooldown"]

    # Обновляем исходы по ранее отправленным сигналам (даже без подписчиков)
    try:
        await asyncio.to_thread(journal.check_open_trades)
    except Exception as e:
        log.warning("Проверка журнала упала: %s", e)

    if not subs:
        return

    try:
        signals: List[Decision] = await asyncio.to_thread(scanner.scan)
    except Exception as e:
        log.exception("Скан упал: %s", e)
        return

    now = time.time()
    cd_seconds = cfg.cooldown_minutes * 60
    fresh = []
    for d in signals:
        last = cooldown.get(d.symbol, 0)
        if now - last >= cd_seconds:
            fresh.append(d)
            cooldown[d.symbol] = now

    if not fresh:
        return

    for d in fresh[:5]:
        journal.log_signal(d)  # фиксируем сигнал в журнал для статистики
        text = format_signal(d) + DISCLAIMER
        for chat_id in list(subs):
            try:
                await app.bot.send_message(
                    chat_id, text, parse_mode=ParseMode.HTML
                )
            except Exception as e:
                log.warning("Не смог отправить в %s: %s", chat_id, e)


async def collect_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сохраняет текст сообщений из групп/каналов для соц-анализа."""
    msg = update.effective_message
    if msg and msg.text:
        TG_STORE.add(time.time(), msg.text)


async def on_startup(app: Application) -> None:
    log.info("Бот запущен. Подписчиков: %d", len(app.bot_data["subscribers"]))
    if app.bot_data.get("commands_only"):
        log.info("Режим команд: автосигналы отключены (их шлёт GitHub Actions)")
        return
    app.bot_data["liq_task"] = asyncio.create_task(run_collector(app))


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram-бот сигналов на лонг")
    parser.add_argument(
        "--commands-only",
        action="store_true",
        help="Только /scan и /status — без автосигналов (для работы вместе с GitHub Actions)",
    )
    args = parser.parse_args()

    cfg = Config.load()
    if not cfg.telegram_token:
        raise SystemExit(
            "Не задан TELEGRAM_TOKEN.\n"
            "Открой .env и впиши токен бота от @BotFather (тот же, что в секретах GitHub).\n"
            "Затем запусти: python bot.py --commands-only"
        )

    scanner = Scanner(cfg)

    app = Application.builder().token(cfg.telegram_token).post_init(on_startup).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["scanner"] = scanner
    app.bot_data["subscribers"] = load_subscribers()
    app.bot_data["cooldown"] = {}
    app.bot_data["commands_only"] = args.commands_only

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_message))

    if not args.commands_only:
        app.job_queue.run_repeating(
            scan_job,
            interval=cfg.check_interval_seconds,
            first=15,
            name="scan_job",
        )

    log.info("Запуск polling%s…", " (режим команд)" if args.commands_only else "")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
