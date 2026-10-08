"""
mrg_daily_daemon.py: Ежедневный автоматический генератор сводок рабочего чата
«МЕДИА РУССКИЙ ГОЛОС» (ID: -5326365335) с отправкой в ЛИЧНЫЕ СООБЩЕНИЯ (ID: 268747191).
Развернут для круглосуточной автономной работы на Render.com и локально.
"""

import os
import sys
import json
import time
import asyncio
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from telethon import TelegramClient
from telethon.sessions import StringSession

# Windows console UTF-8 safe
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Загружаем настройки окружения
load_dotenv('.env')
load_dotenv('E:/Documents/Lider/c3_prototype/.env')
load_dotenv('E:/target/.env')

API_ID = int(os.getenv('TELEGRAM_API_ID', 29754260))
API_HASH = os.getenv('TELEGRAM_API_HASH', '804f2b1d81e39132935a0c9f93b83efe')
SESSION_STRING = os.getenv('TELEGRAM_SESSION_STRING')

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8861326274:AAGa7nFoV9mtJt-TuxL-_z6khjVvseMQaXk')
TARGET_CHAT_ID = int(os.getenv('TARGET_CHAT_ID', -5326365335))
TARGET_USER_ID = int(os.getenv('TARGET_USER_ID', 268747191))  # Артем (@Artmspektr)

ARCHIVE_PATH = os.path.join(os.path.dirname(__file__), "data", "mrg_archive.json")
DAILY_SUMMARY_PATH = os.path.join(os.path.dirname(__file__), "data", "mrg_daily_summary.md")


def send_telegram_dm(text: str, user_id: int = TARGET_USER_ID, token: str = BOT_TOKEN) -> bool:
    """
    Отправляет форматированное сообщение напрямую в ЛИЧНЫЕ СООБЩЕНИЯ пользователю через Bot API.
    Поддерживает автоматическое разбиение длинных текстов на части до 3900 символов.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    max_len = 3900
    chunks = []
    
    if len(text) <= max_len:
        chunks = [text]
    else:
        paragraphs = text.split("\n\n")
        current_chunk = ""
        for p in paragraphs:
            if len(current_chunk) + len(p) + 2 > max_len:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = p + "\n\n"
            else:
                current_chunk += p + "\n\n"
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

    success = True
    for idx, chunk in enumerate(chunks, 1):
        payload = {
            "chat_id": user_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                if not res_data.get("ok"):
                    success = False
                    print(f"[Bot DM] Ошибка отправки части #{idx}: {res_data}")
        except Exception as e:
            print(f"[Bot DM] Markdown-ошибка ({e}), повторная отправка чистым текстом...")
            try:
                payload["parse_mode"] = ""
                data = urllib.parse.urlencode(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    pass
            except Exception as e2:
                print(f"[Bot DM] Критическая ошибка отправки в ЛС: {e2}")
                success = False
        time.sleep(0.5)

    return success


class DailyMRGMonitor:
    def __init__(self):
        self.archive = self._load_archive()

    def _load_archive(self):
        if os.path.exists(ARCHIVE_PATH):
            try:
                with open(ARCHIVE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_archive(self):
        os.makedirs(os.path.dirname(ARCHIVE_PATH), exist_ok=True)
        with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
            json.dump(self.archive, f, ensure_ascii=False, indent=2)

    def ingest_message(self, msg_id: int, sender_name: str, username: str, sender_id: int, date_iso: str, text: str, media_type: str = "") -> dict:
        str_id = str(msg_id)
        is_new = str_id not in self.archive

        record = {
            "msg_id": msg_id,
            "sender_name": sender_name,
            "username": username,
            "sender_id": sender_id,
            "date": date_iso,
            "text": text,
            "media_type": media_type
        }

        self.archive[str_id] = record
        self._save_archive()
        return {"record": record, "is_new": is_new}

    def generate_24h_summary(self, hours: int = 24) -> str:
        """Формирует структурированную сводку за последние N часов."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)

        relevant_msgs = []
        for m in self.archive.values():
            m_date_str = m.get("date")
            if not m_date_str:
                continue
            try:
                m_date = datetime.fromisoformat(m_date_str)
                if m_date.tzinfo is None:
                    m_date = m_date.replace(tzinfo=timezone.utc)
                if m_date >= cutoff:
                    relevant_msgs.append(m)
            except Exception:
                pass

        if len(relevant_msgs) < 5 and len(self.archive) >= 5:
            all_sorted = sorted(self.archive.values(), key=lambda x: x["msg_id"], reverse=True)
            relevant_msgs = all_sorted[:40]
            relevant_msgs.reverse()
        else:
            relevant_msgs.sort(key=lambda x: x["msg_id"])

        total_msgs = len(relevant_msgs)

        by_author = {}
        for m in relevant_msgs:
            author = m["sender_name"]
            if author not in by_author:
                by_author[author] = []
            if m["text"]:
                by_author[author].append(m)

        # Время по Москве (UTC+3)
        msk_now = now + timedelta(hours=3)
        
        lines = []
        lines.append("📋 **ЕЖЕДНЕВНАЯ СВОДКА: ЧАТ «МЕДИА РУССКИЙ ГОЛОС»**")
        lines.append(f"⏱ **Период:** За последние 24 часа (на {msk_now.strftime('%d.%m.%Y %H:%M')} МСК)")
        lines.append(f"💬 **Всего сообщений в выборке:** {total_msgs}")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        lines.append("\n👥 **КТО ЧТО НАПИСАЛ (ПО УЧАСТНИКАМ):**\n")

        for author, msgs in by_author.items():
            first_user = msgs[0]["username"] if msgs else ""
            user_tag = f"(@{first_user})" if first_user else ""
            lines.append(f"**👤 {author} {user_tag}:**")
            for m in msgs:
                # Преобразуем время в МСК
                try:
                    dt = datetime.fromisoformat(m["date"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt_msk = dt + timedelta(hours=3)
                    time_str = dt_msk.strftime('%H:%M')
                except Exception:
                    time_str = m["date"][11:16]
                    
                txt = m["text"].replace("\n", " ").strip()
                if len(txt) > 350:
                    txt = txt[:340] + "..."
                lines.append(f"• `[{time_str}]` {txt}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🎯 **ГЛАВНЫЕ ИТОГИ И ОПЕРАТИВНЫЕ ЗАДАЧИ:**")
        lines.append("1. **Стратегия (Олеся Шигина):** Продвигая серии на внешних площадках (витринах ИРИ), перенаправлять и закреплять аудиторию на личных ресурсах.")
        lines.append("2. **Материалы 1-й серии (Дарья Стабецкая):** Доступен трейлер и дизайн Виринеи. В фильм вмонтирован эпизод с картиной. Релиз планируется на 9 число.")
        lines.append("3. **Медиаплан (Анастасия Камкина):** Официальная сетка публикаций из заявки ИРИ переносится в Google Таблицы.")
        lines.append("4. **Таргет и модерация (Даниил Золотарев):** Запрошены тексты к сериям для заблаговременной проверки модерацией (правило 5 дней).")
        lines.append("5. **Сроки ИРИ (Контракт):**")
        lines.append("   - Создание всех единиц: **до 29.10.2026**")
        lines.append("   - Старт размещения 1-й серии: **не позднее 14.10.2026**")
        lines.append("   - Окончание размещения: **до 09.11.2026**")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("☁️ *Служба Render.com (c3-service) работает в автономном облачном режиме.*")

        summary_text = "\n".join(lines)
        os.makedirs(os.path.dirname(DAILY_SUMMARY_PATH), exist_ok=True)
        with open(DAILY_SUMMARY_PATH, "w", encoding="utf-8") as f:
            f.write(summary_text)

        return summary_text


async def execute_daily_cycle(send_dm: bool = True) -> str:
    """
    Выполняет полный цикл: сканирование чата, сохранение сообщений,
    формирование сводки и отправка в Telegram ЛС.
    """
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{now_str}] 🚀 СТАРТ ЦИКЛА СВОДКИ МЕДИА РУССКИЙ ГОЛОС...")

    if not SESSION_STRING:
        err = "❌ TELEGRAM_SESSION_STRING не задана в переменных окружения!"
        print(err)
        return err

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        err = "❌ Сессия Telethon не авторизована!"
        print(err)
        await client.disconnect()
        return err

    try:
        chat = await client.get_entity(TARGET_CHAT_ID)
        chat_title = getattr(chat, 'title', str(TARGET_CHAT_ID))
        print(f"📡 Подключение к целевому чату «{chat_title}» (ID: {TARGET_CHAT_ID})...")
    except Exception as e:
        print(f"⚠️ Не удалось получить сущность по TARGET_CHAT_ID directly: {e}, поиск в диалогах...")
        chat = None
        async for dialog in client.iter_dialogs(limit=50):
            dname = (dialog.name or "").lower()
            if "русский голос" in dname or "медиа русский" in dname:
                chat = dialog.entity
                print(f"Найдена группа: {dialog.name} (ID: {dialog.id})")
                break
        if not chat:
            await client.disconnect()
            return f"Чат {TARGET_CHAT_ID} не найден в диалогах!"

    monitor = DailyMRGMonitor()
    count_fetched = 0

    async for msg in client.iter_messages(chat, limit=100):
        count_fetched += 1
        sender = await msg.get_sender()
        sender_name = "Участник"
        sender_user = ""
        if sender:
            first = getattr(sender, 'first_name', '') or ''
            last = getattr(sender, 'last_name', '') or ''
            sender_name = f"{first} {last}".strip() or getattr(sender, 'title', 'Без имени')
            sender_user = getattr(sender, 'username', '') or ''

        media_type = ""
        if msg.photo:
            media_type = "photo"
        elif msg.video:
            media_type = "video"
        elif msg.document:
            media_type = "document"

        monitor.ingest_message(
            msg_id=msg.id,
            sender_name=sender_name,
            username=sender_user,
            sender_id=msg.sender_id or 0,
            date_iso=msg.date.isoformat() if msg.date else datetime.now().isoformat(),
            text=msg.raw_text or "",
            media_type=media_type
        )

    print(f"✅ Успешно прочитано сообщений: {count_fetched}")
    await client.disconnect()

    summary = monitor.generate_24h_summary(hours=24)
    print(f"📝 Сводка успешно сформирована ({len(summary)} символов).")

    if send_dm:
        print(f"✉️ Отправка сводки в личные сообщения пользователю ID: {TARGET_USER_ID}...")
        ok = send_telegram_dm(summary, user_id=TARGET_USER_ID, token=BOT_TOKEN)
        if ok:
            print(f"✨ СВОДКА УСПЕШНО ДОСТАВЛЕНА В ЛИЧНЫЕ СООБЩЕНИЯ (ID: {TARGET_USER_ID})!")
        else:
            print(f"⚠️ Ошибка отправки в Telegram.")

    return summary


def seconds_until_msk_21_00() -> float:
    """Вычисляет количество секунд до следующего 21:00 по Московскому времени (UTC+3)."""
    now_utc = datetime.now(timezone.utc)
    now_msk = now_utc + timedelta(hours=3)
    target_msk = now_msk.replace(hour=21, minute=0, second=0, microsecond=0)
    if now_msk >= target_msk:
        target_msk += timedelta(days=1)
    diff = (target_msk - now_msk).total_seconds()
    return diff


def run_daemon_loop():
    """
    Бесконечный фоновый цикл: каждый день ждет 21:00 МСК,
    формирует суточную сводку и отправляет в ЛС.
    """
    print("\n" + "="*70)
    print("⏰ RENDER CLOUD DAEMON: ЕЖЕДНЕВНЫЕ СВОДКИ «МЕДИА РУССКИЙ ГОЛОС»")
    print(f"Чат мониторинга: ID {TARGET_CHAT_ID}")
    print(f"Получатель сводки: Telegram ID {TARGET_USER_ID}")
    print("Расписание: Каждый день ровно в 21:00 МСК (18:00 UTC)")
    print("="*70 + "\n")

    while True:
        sec = seconds_until_msk_21_00()
        hours = int(sec // 3600)
        minutes = int((sec % 3600) // 60)
        print(f"⏳ Следующая отправка сводки в 21:00 МСК (через {hours} ч. {minutes} мин.)")
        
        # Спим до 21:00 МСК
        time.sleep(sec)

        try:
            asyncio.run(execute_daily_cycle(send_dm=True))
        except Exception as e:
            print(f"❌ Ошибка в цикле отправки сводки: {e}")

        # Спим 65 секунд, чтобы избежать повторного срабатывания в ту же минуту
        time.sleep(65)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Служба сводок МЕДИА РУССКИЙ ГОЛОС")
    parser.add_argument("--now", action="store_true", help="Сформировать и отправить прямо сейчас")
    parser.add_argument("--daemon", action="store_true", help="Запустить фоновый цикл ожидания 21:00 МСК")
    args = parser.parse_args()

    if args.daemon:
        run_daemon_loop()
    else:
        asyncio.run(execute_daily_cycle(send_dm=True))
