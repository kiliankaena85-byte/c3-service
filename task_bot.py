"""
MAX & Personal Assistant Bot (Telegram @c3_ru_bot)
Autonomous AI assistant for Artem (@Artmspektr, ID 268747191)

Dual-Model Architecture:
- LAYA AI (System 1): Sub-millisecond intent triage, urgency scoring (1-5), and multi-channel routing
- Gemini 3.8 Flash (System 2): Voice-to-text transcription, ISO-8601 date parsing, and natural dialogue synthesis
- Persistent Neon PostgreSQL storage (table user_tasks)
- Telegram Mini App (Calendar WebApp): https://c3-service-il4m.onrender.com/calendar
- Proactive multi-channel alerts: Telegram, Samsung Galaxy A35 (ntfy.sh), Yandex Station (Alice)
"""

import os
import sys
import time
import json
import re
import base64
import datetime
import zoneinfo
import threading
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

MSK = zoneinfo.ZoneInfo("Europe/Moscow")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
AUTHORIZED_USER_ID = int(os.getenv("AUTHORIZED_USER_ID", "268747191"))
CALENDAR_URL = os.getenv("CALENDAR_URL", "https://c3-service-il4m.onrender.com/calendar")


def to_msk(dt_val):
    """Safely converts string, date, or datetime into MSK (Europe/Moscow) datetime."""
    if not dt_val:
        return None
    if isinstance(dt_val, str):
        try:
            val = dt_val.replace("Z", "+00:00")
            dt_obj = datetime.datetime.fromisoformat(val)
            if dt_obj.tzinfo is None:
                return dt_obj.replace(tzinfo=MSK)
            return dt_obj.astimezone(MSK)
        except Exception:
            return None
    elif isinstance(dt_val, datetime.datetime):
        if dt_val.tzinfo is None:
            dt_val = dt_val.replace(tzinfo=datetime.timezone.utc)
        return dt_val.astimezone(MSK)
    elif isinstance(dt_val, datetime.date):
        dt_val = datetime.datetime.combine(dt_val, datetime.time.min).replace(tzinfo=MSK)
        return dt_val
    return None

# Import Laya Assistant Decision Engine
try:
    from laya_assistant import LayaAssistantDecisionEngine
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from laya_assistant import LayaAssistantDecisionEngine


# -------------------------------------------------------------
# Database helper (Neon PostgreSQL)
# -------------------------------------------------------------
def get_db_connection():
    try:
        import psycopg2
        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
            conn.set_client_encoding('UTF8')
            return conn
    except Exception as e:
        print(f"[DB] Neon connection error: {e}")
    return None


def init_db():
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_tasks (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL DEFAULT 268747191,
                    title TEXT NOT NULL,
                    raw_input TEXT NOT NULL,
                    category VARCHAR(64) DEFAULT 'Общее',
                    priority VARCHAR(32) DEFAULT 'medium',
                    due_at TIMESTAMP WITH TIME ZONE,
                    remind_at TIMESTAMP WITH TIME ZONE,
                    reminder_sent BOOLEAN DEFAULT FALSE,
                    status VARCHAR(32) DEFAULT 'pending',
                    source VARCHAR(32) DEFAULT 'telegram_text',
                    target_channels TEXT[] DEFAULT ARRAY['telegram'],
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id BIGINT NOT NULL DEFAULT 268747191,
                    key VARCHAR(128) NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (user_id, key)
                );
            """)
            conn.commit()
        conn.close()
        print("[DB] Initialized Neon PostgreSQL user_tasks and user_settings tables.")


def db_create_task(user_id, title, raw_input, category, due_at, remind_at, priority="medium", source="telegram_text", channels=None):
    conn = get_db_connection()
    if not conn:
        return None
    if channels is None:
        channels = ['telegram']
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_tasks (user_id, title, raw_input, category, priority, due_at, remind_at, source, target_channels)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (user_id, title, raw_input, category, priority, due_at, remind_at, source, channels))
            task_id = cur.fetchone()[0]
            conn.commit()
            return task_id
    except Exception as e:
        print(f"[DB] Insert task error: {e}")
        return None
    finally:
        conn.close()


def db_get_active_tasks(user_id):
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, category, due_at, remind_at, priority, reminder_sent, target_channels
                FROM user_tasks
                WHERE user_id = %s AND status = 'pending'
                ORDER BY due_at ASC NULLS LAST, id DESC;
            """, (user_id,))
            rows = cur.fetchall()
            tasks = []
            for r in rows:
                tasks.append({
                    "id": r[0],
                    "title": r[1],
                    "category": r[2],
                    "due_at": r[3],
                    "remind_at": r[4],
                    "priority": r[5],
                    "reminder_sent": r[6],
                    "target_channels": r[7] if len(r) > 7 else ['telegram']
                })
            return tasks
    finally:
        conn.close()


def db_complete_task(task_id):
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE user_tasks SET status = 'completed', updated_at = NOW() WHERE id = %s;", (task_id,))
            updated = cur.rowcount > 0
            conn.commit()
            return updated
    finally:
        conn.close()


def db_postpone_task(task_id, hours=1):
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE user_tasks 
                SET remind_at = NOW() + INTERVAL '%s hour', reminder_sent = FALSE, updated_at = NOW() 
                WHERE id = %s;
            """, (hours, task_id))
            updated = cur.rowcount > 0
            conn.commit()
            return updated
    finally:
        conn.close()


def db_get_due_reminders():
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, title, category, due_at, target_channels
                FROM user_tasks
                WHERE status = 'pending' 
                  AND reminder_sent = FALSE 
                  AND remind_at IS NOT NULL 
                  AND remind_at <= NOW();
            """)
            return cur.fetchall()
    except Exception as e:
        print(f"[DB] Error checking reminders: {e}")
        return []
    finally:
        conn.close()


def db_mark_reminder_sent(task_id):
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE user_tasks SET reminder_sent = TRUE, updated_at = NOW() WHERE id = %s;", (task_id,))
            conn.commit()
    finally:
        conn.close()


# -------------------------------------------------------------
# Telegram UI & Keyboards
# -------------------------------------------------------------
def get_main_reply_keyboard():
    """
    Persistent 1-touch Reply Keyboard.
    No need to remember or type any commands.
    """
    return {
        "keyboard": [
            [
                {"text": "📅 Открыть Календарь задач", "web_app": {"url": CALENDAR_URL}}
            ],
            [
                {"text": "📋 Мои задачи"},
                {"text": "📊 Сводка MAX"}
            ],
            [
                {"text": "🔊 Яндекс Алиса"},
                {"text": "📱 Проверить телефон"}
            ]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }


def get_task_inline_keyboard(task_id):
    """Inline quick action buttons under a specific task card."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Выполнено", "callback_data": f"done_{task_id}"},
                {"text": "⏰ +1 час", "callback_data": f"postpone_{task_id}"}
            ],
            [
                {"text": "📅 Открыть в Календаре", "web_app": {"url": CALENDAR_URL}}
            ]
        ]
    }


# -------------------------------------------------------------
# Telegram API Wrappers
# -------------------------------------------------------------
def tg_api_call(method, payload=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    if payload:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[Telegram API] Error in {method}: {e}")
        return None


def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup

    res = tg_api_call("sendMessage", payload)
    if not res and parse_mode:
        payload.pop("parse_mode", None)
        res = tg_api_call("sendMessage", payload)
    return res


def download_telegram_file(file_id):
    """Downloads voice or audio file from Telegram and returns raw bytes."""
    res = tg_api_call("getFile", {"file_id": file_id})
    if not res or not res.get("ok"):
        return None
    file_path = res["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    try:
        with urllib.request.urlopen(download_url, timeout=30) as resp:
            return resp.read()
    except Exception as e:
        print(f"[Telegram] Error downloading file: {e}")
        return None


def setup_bot_interface():
    """Configures Telegram Chat Menu Button and command menu."""
    try:
        tg_api_call("setChatMenuButton", {
            "menu_button": {
                "type": "web_app",
                "text": "📅 Календарь",
                "web_app": {"url": CALENDAR_URL}
            }
        })
        tg_api_call("setMyCommands", {
            "commands": [
                {"command": "start", "description": "Главное меню и клавиатура"},
                {"command": "tasks", "description": "Список активных задач"},
                {"command": "max", "description": "Сводка переписок MAX"},
                {"command": "alice", "description": "Статус и привязка Яндекс Станции"},
                {"command": "phone", "description": "Тест громкого будильника (Samsung)"}
            ]
        })
        print("[Telegram Setup] Menu button and commands configured.")
    except Exception as e:
        print(f"[Telegram Setup] Warning: {e}")


# -------------------------------------------------------------
# Audio Transcription Engine (Gemini 3.8 Flash)
# -------------------------------------------------------------
def transcribe_voice_bytes(audio_bytes, mime_type="audio/ogg"):
    """
    Direct voice-to-text transcription via Gemini 3.8 Flash (with 3.5 Flash fallback).
    """
    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
    payload = {
        "contents": [
            {
                "parts": [
                    {"inlineData": {"mimeType": mime_type, "data": b64_audio}},
                    {"text": "Пожалуйста, расшифруй эту аудиозапись слово в слово на русском языке. Верни только распознанный текст без каких-либо вводных слов и кавычек."}
                ]
            }
        ]
    }

    for model in ["gemini-3.8-flash", "gemini-3.5-flash"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text:
                    print(f"[AI Voice] Transcribed via {model}: '{text}'")
                    return text
        except Exception as e:
            print(f"[AI Voice] Error with {model}: {e}")

    return None


# -------------------------------------------------------------
# AI Task Extraction Engine (Gemini 3.8 Flash + LAYA AI)
# -------------------------------------------------------------
def parse_task_text_gemini(user_text, laya_hints=None):
    """
    Extracts structured task JSON from natural language text using Gemini 3.8 Flash.
    Enriched with Laya Decision Engine hints.
    """
    now = datetime.datetime.now(MSK)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    hints_str = ""
    if laya_hints:
        hints_str = f"Подсказка LAYA AI: Категория={laya_hints.get('category')}, Срочность={laya_hints.get('urgency_score')}/5, Интент={laya_hints.get('laya_intent')}."

    prompt = f"""Ты — персональный ИИ-ассистент руководителя (Артёма).
Текущее точное время и дата: {now_str} (МСК, Europe/Moscow, UTC+3).
Сегодняшний день недели: {['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье'][now.weekday()]}.
{hints_str}

Пользователь передал текст:
"{user_text}"

Твоя цель — извлечь параметры задачи или ответить на реплику:
- title: короткая, ёмкая формулировка задачи (например: "Забрать ножницы для бабушки из Ozon").
  КРИТИЧЕСКИ ВАЖНО: Если текст НЕ содержит конкретного поручения, задачи или действия (например: приветствие "Привет", "Здравствуйте", благодарность "Спасибо", согласие "Ок", вопрос "Как дела?", светская реплика), верни строго "title": null.
- category: Работа / Заказчики, Быт / Семья, Покупки / Ozon, Здоровье, Авто, Личные дела
- due_at: ISO-8601 строка даты и времени дедлайна с таймзоной (+03:00). Если сказано "сегодня в 18:00", поставь сегодняшнюю дату и 18:00:00+03:00. Если срок не указан, верни null.
- remind_at: когда отправить напоминание (ISO-8601). Если не указано отдельно, сделай за 15 минут до due_at (или в момент due_at). Если due_at null, верни null.
- priority: high / medium / low
- confirmation_message: живой, вежливый ответ от первого лица (если задачи нет — вежливо поприветствуй или ответь Артёму; если задача зафиксирована — подтверди принятие).

ВЕРНИ ТОЛЬКО ЧИСТЫЙ ВАЛИДНЫЙ JSON:
{{
  "title": null,
  "category": "...",
  "due_at": "YYYY-MM-DDTHH:MM:SS+03:00",
  "remind_at": "YYYY-MM-DDTHH:MM:SS+03:00",
  "priority": "medium",
  "confirmation_message": "..."
}}
"""

    req_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }

    if GEMINI_API_KEY:
        for model in ["gemini-3.8-flash", "gemini-3.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
                data = json.dumps(req_body).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    ans_text = res["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(ans_text)
            except Exception as e:
                print(f"[AI Task] Error with {model}: {e}")

    # Fallback to Laya hints when Gemini is unavailable
    if laya_hints and laya_hints.get("laya_intent") in ["GREETING", "EMPTY"]:
        return {
            "title": None,
            "category": "Общее",
            "due_at": None,
            "remind_at": None,
            "priority": "low",
            "confirmation_message": "Приветствую, Артём! Чем могу помочь?"
        }
    cat = laya_hints.get("category", "Общее") if laya_hints else "Общее"
    prio = laya_hints.get("priority", "medium") if laya_hints else "medium"
    return {
        "title": user_text if (user_text and len(user_text.strip()) > 3) else None,
        "category": cat,
        "due_at": None,
        "remind_at": None,
        "priority": prio,
        "confirmation_message": f"Задача принята: {user_text}" if user_text else "Приветствую, Артём!"
    }


def extract_task_id(text: str) -> Optional[int]:
    """
    Extracts an explicit task ID from user text when completing tasks.
    Guards against misinterpreting time expressions (e.g. '18:00', '21.30') as task IDs.
    """
    if not text:
        return None
    # Remove time patterns like 18:00, 18.30
    clean = re.sub(r'\b\d{1,2}[:.]\d{2}\b', '', text)
    # 1. Explicit task markers: #12, №12, задачу 12, номер 12, id 12
    m = re.search(r'(?:#|№|задач\w*\s*#?|номер\s*#?|id\s*#?)\s*(\d+)', clean, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # 2. Command + single number: "выполнил 5", "сделал 14", "закрыл 3"
    m = re.search(r'^\s*(?:выполнил|сделал|закрыл|готово)\s+#?(\d+)\s*$', clean, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


# -------------------------------------------------------------
# Telegram Message Processor
# -------------------------------------------------------------
def handle_message(msg):
    chat_id = msg["chat"]["id"]
    from_user = msg.get("from", {})
    user_id = from_user.get("id")

    if user_id != AUTHORIZED_USER_ID:
        send_message(chat_id, "⛔ Доступ ограничен. Этот бот настроен как персональный агент Артёма.")
        return

    text = (msg.get("text") or msg.get("caption") or "").strip()
    voice = msg.get("voice")

    # Detect forwarded messages
    fwd = msg.get("forward_from") or msg.get("forward_from_chat")
    if fwd and text:
        fwd_title = fwd.get("title") or fwd.get("first_name") or "переписки"
        text = f"Переслано от {fwd_title}: {text}"

    # 1. Main Menu / Start Command
    if text in ["/start", "/help", "меню", "старт"]:
        help_text = (
            "👋 **Привет, Артём! Я ваш автономный ИИ-ассистент.**\n\n"
            "🧠 **Система управления:**\n"
            "• **LAYA AI (System 1):** мгновенная маршрутизация и оценка важности\n"
            "• **Gemini 3.8 Flash (System 2):** распознавание речи и дат\n"
            "• **Календарь (Mini App):** удобное визуальное расписание прямо в Telegram\n"
            "• **Будильник на телефоне:** Samsung Galaxy A35 (ntfy.sh)\n"
            "• **Голос в комнате:** Яндекс Станция (Алиса)\n\n"
            "👇 **Команды больше вводить не нужно!** Используйте кнопки внизу экрана или просто отправьте голосовое сообщение:"
        )
        send_message(chat_id, help_text, reply_markup=get_main_reply_keyboard())
        return

    # 2. View Active Tasks
    if text in ["/tasks", "📋 Мои задачи", "задачи", "список задач"]:
        tasks = db_get_active_tasks(user_id)
        if not tasks:
            inline_cal = {
                "inline_keyboard": [
                    [{"text": "📅 Открыть Календарь", "web_app": {"url": CALENDAR_URL}}]
                ]
            }
            send_message(chat_id, "✅ На данный момент активных задач нет. Всё чисто!", reply_markup=inline_cal)
            return

        msg_lines = ["📋 **ВАШИ АКТИВНЫЕ ЗАДАЧИ:**\n"]
        for t in tasks:
            due_msk = to_msk(t['due_at'])
            due_str = due_msk.strftime('%d.%m в %H:%M (МСК)') if due_msk else "без срока"
            msg_lines.append(f"• **#{t['id']} {t['title']}**\n   📂 *{t['category']}* | ⏰ {due_str} | Важность: {t['priority']}")

        inline_cal = {
            "inline_keyboard": [
                [{"text": "📅 Открыть интерактивный Календарь", "web_app": {"url": CALENDAR_URL}}]
            ]
        }
        send_message(chat_id, "\n\n".join(msg_lines), reply_markup=inline_cal)
        return

    # 3. MAX Messenger Summary
    if text in ["/max", "📊 Сводка MAX", "сводка max", "сводка"]:
        try:
            from max_agent import run_max_agent
            send_message(chat_id, "⏳ **Запускаю сбор и анализ переписок MAX...**\nСейчас подключусь к web.max.ru и подготовлю выжимку.")
            run_max_agent()
        except (ImportError, ModuleNotFoundError):
            send_message(
                chat_id,
                "📊 **Сводка мессенджера MAX**\n\n"
                "💡 Облачный бот на Render работает 24/7 автономно для управления задачами, будильниками и календарем.\n\n"
                "Сбор личных переписок из **web.max.ru** привязан к вашей локальной сессии Яндекс Браузера на рабочем компьютере:\n"
                "• При включенном компьютере утренний дайджест собирается автоматически в **08:30** и отправляется сюда.\n"
                "• Для ручного запуска на компьютере можно нажать `START_SYSTEM.bat` в папке проекта."
            )
        except Exception as e:
            send_message(chat_id, f"❌ Ошибка запуска агента MAX: {e}")
        return

    # 4. Yandex Station (Alice) Status & OAuth
    if text in ["/alice", "/test_alice", "🔊 Яндекс Алиса", "алиса", "станция", "проверь алису"]:
        try:
            from yandex_alice import get_yandex_token, get_smart_home_devices, get_user_scenarios, trigger_scenario, YANDEX_OAUTH_URL
            tok = get_yandex_token(user_id)
            speakers = get_smart_home_devices(tok) if tok else []
            if speakers:
                sp_names = ", ".join([f"«{s['name']}» ({s['room']})" for s in speakers])
                scenarios = get_user_scenarios(tok)
                sc_lines = []
                for sc in scenarios:
                    status_emoji = "🟢 Включен" if sc.get("is_active") else "⚪ Выключен"
                    sc_lines.append(f"• **{sc.get('name', 'Без имени')}** ({status_emoji})")
                sc_str = "\n".join(sc_lines) if sc_lines else "• Нет созданных сценариев"

                alice_kb = {
                    "inline_keyboard": [
                        [{"text": "🗣️ Запустить проверку Алисы", "callback_data": "test_alice"}]
                    ]
                }
                send_message(
                    chat_id,
                    f"🔊 **Яндекс Станция подключена!**\n\n"
                    f"Колонка: {sp_names}\n"
                    f"Сценарии в «Дом с Алисой»:\n{sc_str}\n\n"
                    f"💡 *Для голосового ответа*: включите сценарий в приложении «Дом с Алисой» на телефоне и нажмите кнопку ниже:",
                    reply_markup=alice_kb
                )
            else:
                alice_kb = {
                    "inline_keyboard": [
                        [{"text": "🔗 Авторизовать Яндекс Станцию", "url": YANDEX_OAUTH_URL}]
                    ]
                }
                send_message(
                    chat_id,
                    "🔊 **Подключение Яндекс Станции (Алисы)**\n\n"
                    "Чтобы колонка напоминала вам о задачах голосом:\n"
                    "1. Нажмите кнопку ниже и дайте разрешение Умному дому Яндекса.\n"
                    "2. Скопируйте полученный токен (начинается на `y0_...`).\n"
                    "3. Просто отправьте его сюда в чат!",
                    reply_markup=alice_kb
                )
        except Exception as ae:
            send_message(chat_id, f"❌ Ошибка проверки Яндекс Станции: {ae}")
        return

    # 5. Phone Alarm Test (Samsung Galaxy A35)
    text_clean = text.lower().strip()
    is_phone_cmd = (
        text in ["/phone", "📱 Проверить телефон"]
        or text_clean in ["телефон", "будильник", "проверить телефон", "проверка телефона", "проверь телефон", "тест телефона", "проверить будильник"]
        or ("провер" in text_clean and "телефон" in text_clean)
        or ("тест" in text_clean and "телефон" in text_clean)
    )
    if is_phone_cmd:
        try:
            from phone_notify import send_phone_alarm
            send_phone_alarm(
                title="Тестовый будильник Samsung Galaxy A35",
                message="Связь с телефоном активна! Громкий сигнал, вибрация и пробуждение экрана работают.",
                priority=5,
                category="Здоровье"
            )
            phone_kb = {
                "inline_keyboard": [
                    [{"text": "🚨 Повторить громкий сигнал на телефон", "callback_data": "test_phone"}]
                ]
            }
            send_message(
                chat_id,
                "🚨 **Тестовый громкий будильник отправлен на Samsung Galaxy A35!**\n\n"
                "Сигнал отправлен сразу в каналы `artem_spektr_tasks_2026` и `artem_spektr_task_2026`.\n\n"
                "Телефон должен издать громкий звук будильника, завибрировать и зажечь экран даже в беззвучном режиме.\n\n"
                "Если звука нет, проверьте в приложении `ntfy` на телефоне:\n"
                "1. Добавлен ли канал `artem_spektr_tasks_2026`?\n"
                "2. В настройках телефона (Приложения ➔ ntfy ➔ Батарея) выбрано ли «Не ограничено»?",
                reply_markup=phone_kb
            )
        except Exception as pe:
            send_message(chat_id, f"❌ Ошибка отправки на телефон: {pe}")
        return

    # 6. Yandex OAuth Token Submission (handles raw token, /token command, or copied redirect URL)
    tok_match = re.search(r'(y0_[A-Za-z0-9_\-]+)', text)
    if tok_match or text.startswith("/token"):
        clean_tok = tok_match.group(1) if tok_match else text.replace("/token", "").strip()
        if clean_tok.startswith("y0_"):
            try:
                from yandex_alice import save_yandex_token, get_smart_home_devices
                save_yandex_token(clean_tok, user_id=user_id)
                speakers = get_smart_home_devices(clean_tok)
                if speakers:
                    sp_names = ", ".join([f"«{s['name']}» ({s['room']})" for s in speakers])
                    send_message(chat_id, f"🎉 **Яндекс Станция успешно подключена!**\n\nОбнаружены колонки: {sp_names}.\nТеперь агент будет проговаривать напоминания голосом в комнате.")
                else:
                    send_message(chat_id, "✅ Токен сохранен! (Колонки пока не обнаружены или привязаны к другому аккаунту).")
            except Exception as te:
                send_message(chat_id, f"❌ Ошибка сохранения токена: {te}")
            return

    raw_input_text = text

    # Step 1: Voice transcription (Gemini 3.8 Flash Speech-to-Text)
    if voice:
        send_message(chat_id, "🎧 *Распознаю голосовое сообщение...*")
        audio_bytes = download_telegram_file(voice["file_id"])
        if not audio_bytes:
            send_message(chat_id, "❌ Не удалось загрузить голосовой файл.")
            return
        
        transcribed = transcribe_voice_bytes(audio_bytes, mime_type="audio/ogg")
        if not transcribed:
            send_message(chat_id, "⚠️ Не удалось чётко разобрать слова в аудио. Пожалуйста, повторите или напишите текстом.")
            return

        raw_input_text = transcribed
        print(f"[Bot] Voice transcribed successfully: '{raw_input_text}'")

    # Step 2: LAYA System 1 Evaluation (~25ms decision)
    laya = LayaAssistantDecisionEngine.evaluate_intent_and_routing(raw_input_text)
    print(f"[LAYA Decision] Intent: {laya['laya_intent']} | Urgency: {laya['urgency_score']}/5 | Channels: {laya['target_channels']} ({laya['laya_latency_ms']}ms)")

    # Fast routing based on Laya intent
    if laya["laya_intent"] == "GREETING":
        clean_lower = raw_input_text.lower()
        if any(w in clean_lower for w in ["спасибо", "благодарю"]):
            reply_greeting = "Всегда пожалуйста, Артём! Рад помочь."
        elif any(w in clean_lower for w in ["пока", "до свидания", "доброй ночи"]):
            reply_greeting = "Хорошего отдыха, Артём! На связи."
        else:
            reply_greeting = "Приветствую, Артём! Чем могу помочь по делам или расписанию?"
        send_message(chat_id, reply_greeting)
        return

    if laya["laya_intent"] == "MAX_SUMMARY":
        send_message(chat_id, "⏳ LAYA перенаправила запрос: запускаю сбор и анализ переписок MAX...")
        try:
            from max_agent import run_max_agent
            run_max_agent()
        except Exception as e:
            send_message(chat_id, f"❌ Ошибка: {e}")
        return

    if laya["laya_intent"] == "COMPLETE_TASK" or any(w in raw_input_text.lower() for w in ["выполнил", "сделал", "закрыл", "готово", "удали задачу"]):
        target_id = extract_task_id(raw_input_text)
        if target_id is not None:
            if db_complete_task(target_id):
                send_message(chat_id, f"🎉 **Отлично!** Задача #{target_id} помечена как выполненная.")
            else:
                send_message(chat_id, f"⚠️ Не удалось обновить задачу #{target_id}. Возможно, она уже закрыта.")
            return
        else:
            tasks = db_get_active_tasks(user_id)
            if not tasks:
                send_message(chat_id, "✅ На данный момент у вас нет активных задач для завершения.")
                return
            elif len(tasks) == 1:
                t = tasks[0]
                db_complete_task(t["id"])
                send_message(chat_id, f"🎉 **Отлично!** Задача #{t['id']} («{t['title']}») помечена как выполненная.")
                return
            else:
                kb_buttons = [
                    [{"text": f"✅ #{t['id']} {t['title'][:28]}", "callback_data": f"done_{t['id']}"}]
                    for t in tasks[:6]
                ]
                send_message(chat_id, "Какую из активных задач вы выполнили? Выберите из списка:", reply_markup={"inline_keyboard": kb_buttons})
                return

    if laya["laya_intent"] == "LIST_TASKS":
        tasks = db_get_active_tasks(user_id)
        if not tasks:
            send_message(chat_id, "✅ На данный момент активных задач нет. Всё чисто!")
            return
        msg_lines = ["📋 **ВАШИ АКТИВНЫЕ ЗАДАЧИ:**\n"]
        for t in tasks:
            due_msk = to_msk(t['due_at'])
            due_str = due_msk.strftime('%d.%m в %H:%M (МСК)') if due_msk else "без срока"
            msg_lines.append(f"• **#{t['id']} {t['title']}** [{t['category']}] — ⏰ *{due_str}*")
        inline_cal = {
            "inline_keyboard": [
                [{"text": "📅 Открыть интерактивный Календарь", "web_app": {"url": CALENDAR_URL}}]
            ]
        }
        send_message(chat_id, "\n".join(msg_lines), reply_markup=inline_cal)
        return

    # Step 3: Gemini 3.8 Flash Task Parameters Parsing (System 2)
    parsed = parse_task_text_gemini(raw_input_text, laya_hints=laya)

    title = parsed.get("title")
    # Prevent phantom tasks: if Gemini returns title: null or empty, send conversational reply and do NOT insert into DB
    if not title or str(title).strip().lower() in ["null", "none", "", "нет", "нет задачи"]:
        confirm_text = parsed.get("confirmation_message") or "Приветствую, Артём! Чем могу помочь?"
        send_message(chat_id, confirm_text)
        return

    category = parsed.get("category") or laya.get("category") or "Общее"
    due_at = parsed.get("due_at")
    remind_at = parsed.get("remind_at")
    priority = laya.get("priority") or parsed.get("priority") or "medium"
    confirm_text = parsed.get("confirmation_message") or f"Задача сохранена: {title}"

    # Determine active channels from Laya decision
    active_channels = [k for k, v in laya["target_channels"].items() if v]

    # Store in Neon PostgreSQL
    task_id = db_create_task(
        user_id=user_id,
        title=title,
        raw_input=raw_input_text,
        category=category,
        due_at=due_at,
        remind_at=remind_at,
        priority=priority,
        source="telegram_voice" if voice else "telegram_text",
        channels=active_channels
    )

    reply_markup = get_task_inline_keyboard(task_id) if task_id else None

    due_display = ""
    if due_at:
        due_msk = to_msk(due_at)
        if due_msk:
            due_display = f"\n⏰ **Срок:** {due_msk.strftime('%d.%m.%Y в %H:%M (МСК)')}"
        else:
            due_display = f"\n⏰ **Срок:** {due_at}"

    # Human-readable channel labels
    channel_labels = []
    if "telegram" in active_channels:
        channel_labels.append("Telegram")
    if "yandex_alice" in active_channels:
        channel_labels.append("Алиса (Станция)")
    if "samsung_calendar" in active_channels:
        channel_labels.append("Календарь Samsung")
    if "loud_alarm" in active_channels:
        channel_labels.append("🚨 Громкий Будильник")

    channels_str = ", ".join(channel_labels)

    voice_prefix = f"🎙 *Распознано:* «_{raw_input_text}_»\n\n" if voice else ""
    task_header = f"🎯 **Задача #{task_id} сохранена!**" if task_id else "🎯 **Задача сохранена!**"

    urgency_dots = "🔴" if laya["urgency_score"] >= 5 else ("🟠" if laya["urgency_score"] >= 4 else "🟢")

    full_reply = (
        f"{voice_prefix}"
        f"{task_header}\n"
        f"📝 *{title}*\n"
        f"📂 *Категория:* {category}{due_display}\n"
        f"{urgency_dots} *Приоритет:* {priority.upper()} (Срочность {laya['urgency_score']}/5)\n"
        f"📡 *Каналы оповещения (LAYA):* {channels_str}\n\n"
        f"💬 _{confirm_text}_"
    )
    send_message(chat_id, full_reply, reply_markup=reply_markup)


def handle_callback_query(cq):
    cq_id = cq["id"]
    data = cq.get("data", "")
    from_user = cq.get("from", {})
    user_id = from_user.get("id")
    chat_id = cq.get("message", {}).get("chat", {}).get("id", AUTHORIZED_USER_ID)

    if user_id != AUTHORIZED_USER_ID:
        return

    tg_api_call("answerCallbackQuery", {"callback_query_id": cq_id})

    if data.startswith("done_"):
        task_id = int(data.split("_")[1])
        db_complete_task(task_id)
        send_message(chat_id, f"🎉 **Отлично!** Задача #{task_id} помечена как выполненная.")

    elif data.startswith("postpone_"):
        task_id = int(data.split("_")[1])
        db_postpone_task(task_id, hours=1)
        send_message(chat_id, f"⏳ Задача #{task_id} отложена на 1 час.")

    elif data == "test_alice":
        try:
            from yandex_alice import trigger_scenario
            ok, msg = trigger_scenario()
            if ok:
                send_message(chat_id, f"🗣️ **Команда отправлена на Яндекс Лайт!**\n\n{msg}")
            else:
                send_message(
                    chat_id,
                    f"⚠️ **Не удалось запустить воспроизведение на колонке:**\n{msg}\n\n"
                    f"📱 **Что нужно сделать (1 раз):**\n"
                    f"1. Откройте приложение **«Дом с Алисой»** на телефоне.\n"
                    f"2. Во вкладке «Сценарии» включите переключатель у сценария (например, «Погода» или создайте сценарий со своей фразой: «Яндекс Лайт -> Прочитать текст»).\n"
                    f"3. Нажмите кнопку **[🗣️ Запустить проверку Алисы]** снова!"
                )
        except Exception as e:
            send_message(chat_id, f"❌ Ошибка проверки Алисы: {e}")

    elif data == "test_phone":
        try:
            from phone_notify import send_phone_alarm
            send_phone_alarm(
                title="Повторный тест будильника",
                message="Тестовый громкий сигнал Samsung Galaxy A35 доставлен!",
                priority=5,
                category="Здоровье"
            )
            send_message(chat_id, "🚨 **Громкий сигнал повторно отправлен на ваш телефон!**")
        except Exception as e:
            send_message(chat_id, f"❌ Ошибка отправки: {e}")


# -------------------------------------------------------------
# Background Reminder Loop
# -------------------------------------------------------------
def reminder_worker():
    """Continuously checks for due reminders and fires notifications."""
    print("[Reminder Worker] Started monitoring scheduled tasks...")
    while True:
        try:
            due_tasks = db_get_due_reminders()
            for t in due_tasks:
                task_id, user_id, title, category, due_at, target_channels = t
                print(f"[Reminder Worker] Firing reminder for Task #{task_id}: '{title}' | Channels: {target_channels}")
                
                due_msk = to_msk(due_at)
                if due_msk:
                    now_msk = datetime.datetime.now(MSK)
                    if due_msk.date() == now_msk.date():
                        due_str = due_msk.strftime('%H:%M (МСК)')
                    else:
                        due_str = due_msk.strftime('%d.%m в %H:%M (МСК)')
                else:
                    due_str = "сейчас"
                text = (
                    f"⏰ **НАПОМИНАНИЕ!**\n\n"
                    f"🔔 **{title}**\n"
                    f"📂 *Категория:* {category}\n"
                    f"⌛ *Время выполнения:* {due_str}\n\n"
                    f"Пора приступать! Нажмите кнопку после выполнения:"
                )
                reply_markup = get_task_inline_keyboard(task_id)

                # 1. Deliver to Telegram
                send_message(user_id, text, reply_markup=reply_markup)

                # 2. Trigger Phone Alarm (Samsung Galaxy A35 via ntfy)
                try:
                    from phone_notify import send_phone_alarm
                    send_phone_alarm(
                        title=f"Напоминание: {title}",
                        message=f"Время: {due_str} | Категория: {category}",
                        priority=5,
                        category=category
                    )
                except Exception as pe:
                    print(f"[Reminder Worker] Phone alarm error: {pe}")

                # 3. Trigger Yandex Station (Alice Voice in Room)
                if target_channels and any(ch in target_channels for ch in ["yandex_alice", "Алиса (Станция)"]):
                    try:
                        from yandex_alice import speak_on_station
                        phrase = f"Артём, напоминаю: {title}"
                        speak_on_station(phrase)
                    except Exception as ae:
                        print(f"[Reminder Worker] Alice TTS error: {ae}")

                db_mark_reminder_sent(task_id)
        except Exception as e:
            print(f"[Reminder Worker] Error: {e}")

        time.sleep(20)


# -------------------------------------------------------------
# Main Long-Polling Loop
# -------------------------------------------------------------
def run_polling():
    print("=" * 60)
    print("🤖 MAX & PERSONAL ASSISTANT BOT (LAYA AI + GEMINI 3.8 FLASH)")
    print(f"Authorized User: Artem (ID {AUTHORIZED_USER_ID})")
    print(f"Target Bot: @c3_ru_bot")
    print(f"Mini App: {CALENDAR_URL}")
    print("=" * 60)

    init_db()
    setup_bot_interface()

    # Clear any leftover webhooks
    tg_api_call("deleteWebhook", {"drop_pending_updates": False})

    # Start reminder daemon thread
    reminder_thread = threading.Thread(target=reminder_worker, daemon=True)
    reminder_thread.start()

    offset = None
    print("[Bot] Polling Telegram for messages and voice notes...")

    while True:
        try:
            params = {"timeout": 25}
            if offset:
                params["offset"] = offset

            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            data = json.dumps(params).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            
            with urllib.request.urlopen(req, timeout=35) as resp:
                updates = json.loads(resp.read().decode("utf-8")).get("result", [])

            for upd in updates:
                offset = upd["update_id"] + 1

                if "message" in upd:
                    handle_message(upd["message"])
                elif "callback_query" in upd:
                    handle_callback_query(upd["callback_query"])

        except Exception as e:
            time.sleep(2)


if __name__ == "__main__":
    run_polling()
