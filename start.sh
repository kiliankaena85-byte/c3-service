#!/bin/bash
set -e

echo "[*] Запуск единого ядра C3 и Ассистента Артёма (server.py) на порту ${PORT:-10000}..."
echo "[*] Режим: Webhooks + Neon Connection Pool + Фоновые напоминания + Keep-Alive"
exec python -u server.py
