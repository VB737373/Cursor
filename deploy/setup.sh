#!/usr/bin/env bash
# Установка бота на сервер (Ubuntu). Запускать из папки проекта: bash deploy/setup.sh
set -e

cd "$(dirname "$0")/.."
PROJ_DIR="$(pwd)"
RUN_USER="$(whoami)"

echo "==> Обновляю систему и ставлю Python..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip

echo "==> Создаю виртуальное окружение и ставлю зависимости..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> Устанавливаю systemd-сервис (автозапуск 24/7)..."
sudo bash -c "sed \
  -e 's|/home/ubuntu/crypto-bot|${PROJ_DIR}|g' \
  -e 's|^User=ubuntu|User=${RUN_USER}|' \
  -e 's|\r$||' \
  '${PROJ_DIR}/deploy/crypto-signals.service' > /etc/systemd/system/crypto-signals.service"

sudo systemctl daemon-reload
sudo systemctl enable crypto-signals
sudo systemctl restart crypto-signals

echo ""
echo "==> Готово! Бот запущен и будет работать даже после перезагрузки сервера."
echo "    Логи в реальном времени:  sudo journalctl -u crypto-signals -f"
echo "    Статус:                   sudo systemctl status crypto-signals"
echo ""
sudo systemctl status crypto-signals --no-pager || true
