"""Разовый скан рынка без Telegram — для проверки логики.

Запуск:  python scan_once.py
Выводит найденные сигналы на лонг в консоль.
"""
from __future__ import annotations

import logging

from config import Config
from engine import Scanner

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    cfg = Config.load()
    scanner = Scanner(cfg)
    signals = scanner.scan()

    if not signals:
        print("\nСигналов на лонг не найдено (по текущему порогу).")
        return

    print(f"\n=== Найдено сигналов: {len(signals)} ===\n")
    for d in signals:
        print(f"🟢 {d.base:<8} {d.symbol:<12} уверенность {d.confidence:>5.1f}%  "
              f"цена {d.entry}  стоп {d.stop}  тейк {d.take}")
        print(f"     биржи: {', '.join(d.exchanges)}  | данные с: {d.source_exchange}")
        for r in d.reasons:
            print(f"     • {r}")
        print()


if __name__ == "__main__":
    main()
