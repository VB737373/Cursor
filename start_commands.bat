@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  Telegram-команды (/scan, /status)
echo  Автосигналы идут из GitHub Actions — дубликатов не будет.
echo.
echo  Нужен TELEGRAM_TOKEN в файле .env
echo  Для /scan в облако также GITHUB_TOKEN (см. deploy/GITHUB_DEPLOY.md)
echo.
python bot.py --commands-only
pause
