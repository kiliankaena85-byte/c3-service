#!/bin/bash
set -e

echo "[*] Запуск автономного ассистента-секретаря Артёма (task_bot.py)..."
python -u task_bot.py &

echo "[*] Запуск Web-сервера C3 и Календаря (server.py) на порту ${PORT:-10000}..."
exec python -u server.py
