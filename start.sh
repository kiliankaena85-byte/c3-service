#!/bin/bash
set -e

echo "[*] Запуск Telegram-бота завода C3 в фоновом режиме..."
python -u c3_telegram_bot.py &

echo "[*] Запуск Telegram-скаута C3 в фоновом режиме..."
python -u c3_telegram_scout.py &

echo "[*] Запуск Web-сервера C3 на порту ${PORT:-10000}..."
exec python -u server.py
