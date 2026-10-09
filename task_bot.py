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
# Database helper (Neon PostgreSQL Connection Pool)
# -------------------------------------------------------------
try:
    from db import get_db_connection, get_db
except ImportError:
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
    get_db = get_db_connection


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
                ALTER TABLE user_tasks ADD COLUMN IF NOT EXISTS is_mit BOOLEAN DEFAULT FALSE;
                ALTER TABLE user_tasks ADD COLUMN IF NOT EXISTS checkin_sent BOOLEAN DEFAULT FALSE;

                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id BIGINT NOT NULL DEFAULT 268747191,
                    key VARCHAR(128) NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (user_id, key)
                );

                CREATE TABLE IF NOT EXISTS focus_sessions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL DEFAULT 268747191,
                    task_title TEXT NOT NULL,
                    duration_minutes INT NOT NULL,
                    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    ends_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    status VARCHAR(32) DEFAULT 'active',
                    alert_sent BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)
            conn.commit()
        conn.close()
        print("[DB] Initialized Neon PostgreSQL user_tasks, user_settings, and focus_sessions tables.")


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


def db_start_focus_session(user_id: int, task_title: str, duration_minutes: int = 45):
    """Starts a Deep Work Focus Session for Artem."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE focus_sessions 
                SET status = 'cancelled' 
                WHERE user_id = %s AND status = 'active';
            """, (user_id,))
            
            cur.execute("""
                INSERT INTO focus_sessions (user_id, task_title, duration_minutes, ends_at)
                VALUES (%s, %s, %s, NOW() + INTERVAL '%s minutes')
                RETURNING id, ends_at;
            """, (user_id, task_title, duration_minutes, duration_minutes))
            row = cur.fetchone()
            conn.commit()
            return {"id": row[0], "ends_at": row[1]}
    except Exception as e:
        print(f"[DB Focus] Error starting session: {e}")
        return None
    finally:
        conn.close()


def db_get_active_focus_session(user_id: int):
    """Retrieves current active focus session if any."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, task_title, duration_minutes, started_at, ends_at 
                FROM focus_sessions
                WHERE user_id = %s AND status = 'active' AND ends_at > NOW()
                ORDER BY id DESC LIMIT 1;
            """, (user_id,))
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0],
                    "task_title": row[1],
                    "duration_minutes": row[2],
                    "started_at": row[3],
                    "ends_at": row[4]
                }
            return None
    finally:
        conn.close()


def db_cancel_focus_session(user_id: int):
    """Cancels active focus session."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE focus_sessions 
                SET status = 'cancelled' 
                WHERE user_id = %s AND status = 'active';
            """, (user_id,))
            updated = cur.rowcount > 0
            conn.commit()
            return updated
    finally:
        conn.close()


def db_get_expired_focus_sessions():
    """Finds focus sessions that reached completion and need celebration/alarm."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, task_title, duration_minutes, ends_at
                FROM focus_sessions
                WHERE status = 'active' AND alert_sent = FALSE AND ends_at <= NOW();
            """)
            return cur.fetchall()
    except Exception as e:
        print(f"[DB Focus] Error checking expired: {e}")
        return []
    finally:
        conn.close()


def db_mark_focus_alert_sent(session_id: int):
    """Marks focus session as finished and alert delivered."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE focus_sessions 
                SET status = 'completed', alert_sent = TRUE 
                WHERE id = %s;
            """, (session_id,))
            conn.commit()
    finally:
        conn.close()


def db_get_tasks_needing_checkin():
    """Finds overdue tasks that have not yet had an accountability check-in."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, title, category, due_at
                FROM user_tasks
                WHERE status = 'pending'
                  AND checkin_sent = FALSE
                  AND due_at IS NOT NULL
                  AND due_at <= NOW() - INTERVAL '25 minutes';
            """)
            return cur.fetchall()
    except Exception as e:
        print(f"[DB Checkin] Error fetching: {e}")
        return []
    finally:
        conn.close()


def db_mark_task_checkin_sent(task_id: int):
    """Marks accountability check-in as sent for this task."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE user_tasks SET checkin_sent = TRUE WHERE id = %s;", (task_id,))
            conn.commit()
    finally:
        conn.close()


def db_postpone_task_minutes(task_id: int, minutes: int = 30):
    """Postpones a task by N minutes and resets checkin_sent flag."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE user_tasks 
                SET due_at = NOW() + INTERVAL '%s minutes',
                    remind_at = NOW() + INTERVAL '%s minutes' - INTERVAL '10 minutes',
                    reminder_sent = FALSE,
                    checkin_sent = FALSE,
                    updated_at = NOW()
                WHERE id = %s;
            """, (minutes, minutes, task_id))
            conn.commit()
            return True
    finally:
        conn.close()


def db_postpone_task_to_evening(task_id: int):
    """Postpones task to today evening (19:00 MSK)."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        now_msk = datetime.datetime.now(MSK)
        evening_msk = now_msk.replace(hour=19, minute=0, second=0, microsecond=0)
        if evening_msk <= now_msk:
            evening_msk = (now_msk + datetime.timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE user_tasks 
                SET due_at = %s,
                    remind_at = %s - INTERVAL '15 minutes',
                    reminder_sent = FALSE,
                    checkin_sent = FALSE,
                    updated_at = NOW()
                WHERE id = %s;
            """, (evening_msk, evening_msk, task_id))
            conn.commit()
            return True
    finally:
        conn.close()


def db_get_mit_tasks(user_id: int):
    """Retrieves tasks flagged as Most Important Tasks (MIT) for today."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, category, due_at, priority
                FROM user_tasks
                WHERE user_id = %s AND status = 'pending' AND is_mit = TRUE
                ORDER BY due_at ASC NULLS LAST, id DESC
                LIMIT 3;
            """, (user_id,))
            return cur.fetchall()
    finally:
        conn.close()


def db_set_task_mit(task_id: int, is_mit: bool = True):
    """Flags or unflags a task as MIT."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE user_tasks SET is_mit = %s, updated_at = NOW() WHERE id = %s;", (is_mit, task_id))
            conn.commit()
            return True
    finally:
        conn.close()


def db_get_completed_today_tasks(user_id: int):
    """Retrieves tasks completed today for the evening review."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, category, updated_at
                FROM user_tasks
                WHERE user_id = %s AND status = 'completed' AND updated_at >= CURRENT_DATE
                ORDER BY updated_at DESC;
            """, (user_id,))
            return cur.fetchall()
    finally:
        conn.close()


def db_get_user_setting(user_id: int, key: str) -> Optional[str]:
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM user_settings WHERE user_id = %s AND key = %s;", (user_id, key))
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def db_set_user_setting(user_id: int, key: str, value: str):
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_settings (user_id, key, value, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (user_id, key) DO UPDATE 
                SET value = EXCLUDED.value, updated_at = NOW();
            """, (user_id, key, value))
            conn.commit()
    finally:
        conn.close()


# -------------------------------------------------------------
# Telegram UI & Keyboards
# -------------------------------------------------------------
def get_main_reply_keyboard():
    """
    Persistent 1-touch Reply Keyboard.
    Ergonomic executive layout with immediate time-management controls.
    """
    return {
        "keyboard": [
            [
                {"text": "📅 Открыть Календарь", "web_app": {"url": CALENDAR_URL}},
                {"text": "📋 Мои задачи"}
            ],
            [
                {"text": "🎯 Режим фокуса (45м)"},
                {"text": "🌅 3 Главных дела (MIT)"}
            ],
            [
                {"text": "🌙 Итоги дня"},
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

    # Fallback to Laya hints & local rule-based parsing when Gemini is unavailable
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

    fallback_title = clean_title_fallback(user_text) if user_text else None
    fallback_dt = extract_fallback_datetime(user_text)
    due_at = fallback_dt.isoformat() if fallback_dt else None
    remind_at = (fallback_dt - datetime.timedelta(minutes=15)).isoformat() if fallback_dt else None

    chosen_title = fallback_title if (fallback_title and len(fallback_title) > 2) else (user_text if (user_text and len(user_text.strip()) > 3) else None)
    return {
        "title": chosen_title,
        "category": cat,
        "due_at": due_at,
        "remind_at": remind_at,
        "priority": prio,
        "confirmation_message": f"Задача принята: {chosen_title}" if chosen_title else "Приветствую, Артём!"
    }


def extract_fallback_datetime(text: str) -> Optional[datetime.datetime]:
    """Extracts due datetime from Russian text when Gemini is slow or unavailable."""
    if not text:
        return None
    now = datetime.datetime.now(MSK)
    t = text.lower()

    # через X минут
    m = re.search(r'через\s+(\d+)\s+мин', t)
    if m:
        return now + datetime.timedelta(minutes=int(m.group(1)))

    # через X часов / часа / час
    m = re.search(r'через\s+(\d+)\s+час', t)
    if m:
        return now + datetime.timedelta(hours=int(m.group(1)))
    if 'через час' in t:
        return now + datetime.timedelta(hours=1)

    # через X дней / дня / день
    m = re.search(r'через\s+(\d+)\s+дн', t)
    if m:
        return now + datetime.timedelta(days=int(m.group(1)))

    # завтра в HH:MM
    m = re.search(r'завтра(?:\s+в)?\s+(\d{1,2})[:.](\d{2})', t)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        return (now + datetime.timedelta(days=1)).replace(hour=h, minute=mn, second=0, microsecond=0)

    # завтра (без времени -> 10:00)
    if 'завтра' in t and not re.search(r'завтра.*в\s+\d', t):
        return (now + datetime.timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    # сегодня в HH:MM
    m = re.search(r'сегодня(?:\s+в)?\s+(\d{1,2})[:.](\d{2})', t)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        return now.replace(hour=h, minute=mn, second=0, microsecond=0)

    # в HH:MM
    m = re.search(r'(?:^|\s)в\s+(\d{1,2})[:.](\d{2})', t)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        cand = now.replace(hour=h, minute=mn, second=0, microsecond=0)
        if cand <= now:
            cand += datetime.timedelta(days=1)
        return cand

    return None


def clean_title_fallback(text: str) -> str:
    """Strips trigger keywords and time expressions to formulate a crisp task title."""
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r'^(напомни|напомнить|создай задачу|задача|поставь задачу|надо|нужно|не забыть|запиши)\s*:?\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'(через\s+\d+\s+(?:минут\w*|час\w*|дн\w*))', '', t, flags=re.IGNORECASE)
    t = re.sub(r'(завтра(?:\s+в)?\s+\d{1,2}[:.]\d{2})', '', t, flags=re.IGNORECASE)
    t = re.sub(r'(сегодня(?:\s+в)?\s+\d{1,2}[:.]\d{2})', '', t, flags=re.IGNORECASE)
    t = re.sub(r'(?:^|\s)в\s+\d{1,2}[:.]\d{2}', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\b(завтра|сегодня)\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip(' ,.-')
    if t:
        return t[0].upper() + t[1:]
    return text.strip()


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


def handle_focus_command(chat_id, user_id, text=""):
    """
    Pillar 2: Deep Work Focus Session (Pomodoro / Smart Timer).
    """
    active = db_get_active_focus_session(user_id)
    if active:
        ends_msk = to_msk(active["ends_at"])
        now_msk = datetime.datetime.now(MSK)
        rem_mins = max(1, int((ends_msk - now_msk).total_seconds() // 60))
        send_message(
            chat_id,
            f"🎯 **У вас уже активен фокус-режим!**\n\n"
            f"📌 **Задача:** «{active['task_title']}»\n"
            f"⏳ **Осталось:** ~{rem_mins} мин (до {ends_msk.strftime('%H:%M МСК')})\n\n"
            f"📵 Сохраняйте концентрацию. По окончании телефон громко просигнализирует!",
            reply_markup={
                "inline_keyboard": [
                    [{"text": "⏹ Прервать фокус", "callback_data": "focus_cancel"}],
                    [{"text": "✅ Задача выполнена", "callback_data": "focus_cancel"}]
                ]
            }
        )
        return

    # Check if text contains custom duration or specific task title
    clean = text.lower().strip()
    m_dur = re.search(r'(\d+)\s*(?:мин|m|минут)', clean)
    duration = int(m_dur.group(1)) if m_dur else 45

    # Extract target task name if provided
    clean_task = re.sub(r'^(?:/focus|фокус|помодоро|глубокий\s+фокус|спринт)\s*', '', text, flags=re.IGNORECASE).strip()
    clean_task = re.sub(r'(?:на\s+)?\d+\s*(?:мин\w*|минут\w*)\s*', '', clean_task, flags=re.IGNORECASE).strip()
    clean_task = re.sub(r'^на\s+', '', clean_task, flags=re.IGNORECASE).strip()

    if clean_task and len(clean_task) > 2:
        res = db_start_focus_session(user_id, clean_task, duration)
        if res:
            ends_msk = to_msk(res["ends_at"])
            send_message(
                chat_id,
                f"🎯 **РЕЖИМ ГЛУБОКОГО ФОКУСА ВКЛЮЧЕН!**\n\n"
                f"📌 **Задача:** «{clean_task}»\n"
                f"⏳ **Таймер:** {duration} минут (до {ends_msk.strftime('%H:%M МСК')})\n\n"
                f"📵 **Правило чистой концентрации:**\n"
                f"1. Закройте все лишние вкладки и мессенджеры.\n"
                f"2. Положите телефон экраном вниз.\n"
                f"3. Работайте ТОЛЬКО над этой задачей.\n\n"
                f"По окончании раздастся громкий сигнал на телефоне!",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "⏹ Прервать фокус", "callback_data": "focus_cancel"}]
                    ]
                }
            )
            return

    # Interactive duration chooser
    send_message(
        chat_id,
        "🎯 **РЕЖИМ ГЛУБОКОГО ФОКУСА (DEEP WORK)**\n\n"
        "Выберите длительность спринта непрерывной работы:\n"
        "• **25 минут (Спринт):** быстрый старт для преодоления прокрастинации\n"
        "• **45 минут (Глубокая работа):** стандарт максимальной продуктивности\n"
        "• **60 минут (Погружение):** для сложных аналитических расчетов\n\n"
        "💡 *По окончании таймера телефон издаст громкий сигнал даже в беззвучном режиме.*",
        reply_markup={
            "inline_keyboard": [
                [{"text": "⏱ 25 минут (Спринт)", "callback_data": "focus_start_25"}],
                [{"text": "⏱ 45 минут (Стандарт)", "callback_data": "focus_start_45"}],
                [{"text": "⏱ 60 минут (Погружение)", "callback_data": "focus_start_60"}]
            ]
        }
    )


def handle_morning_mit_command(chat_id, user_id):
    """
    Pillar 1: Morning Briefing & 3 Most Important Tasks (MIT).
    """
    mit_tasks = db_get_mit_tasks(user_id)
    all_active = db_get_active_tasks(user_id)

    if mit_tasks:
        lines = ["🌅 **ВАШИ 3 ГЛАВНЫЕ ЦЕЛИ НА СЕГОДНЯ (MIT):**\n", "«Сделайте эти 3 дела — и день станет победным».\n"]
        buttons = []
        for i, t in enumerate(mit_tasks, 1):
            tid, title, cat, due_at, prio = t
            due_msk = to_msk(due_at)
            due_str = due_msk.strftime('%H:%M') if due_msk else "сегодня"
            lines.append(f"**{i}. ⭐️ #{tid} {title}**\n   📂 *{cat}* | ⏰ {due_str}")
            buttons.append([{"text": f"🎯 Фокус на цель #{i}", "callback_data": f"mit_focus_{tid}"}])

        buttons.append([{"text": "📅 Открыть Календарь", "web_app": {"url": CALENDAR_URL}}])
        send_message(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": buttons})
        return

    if all_active:
        lines = [
            "🌅 **УТРЕННИЙ ФОКУС: ВЫБЕРИТЕ 3 ГЛАВНЫХ ДЕЛА (MIT)**\n",
            "Чтобы не распыляться на десятки мелких дел, выберите **до 3 ключевых задач**, которые дадут максимальный результат сегодня:\n"
        ]
        buttons = []
        for t in all_active[:6]:
            tid = t["id"]
            title = t["title"]
            lines.append(f"• **#{tid} {title}**")
            buttons.append([{"text": f"⭐️ Выбрать #{tid} {title[:25]}", "callback_data": f"mit_select_{tid}"}])

        send_message(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": buttons})
        return

    send_message(
        chat_id,
        "🌅 **Доброе утро, Артём!**\n\n"
        "На сегодня в списке пока нет активных задач.\n"
        "Надиктуйте голосом или напишите 1–3 главные цели на день — я сразу зафиксирую их в расписании!",
        reply_markup=get_main_reply_keyboard()
    )


def handle_evening_review_command(chat_id, user_id):
    """
    Pillar 4: Evening Debriefing & Brain Dump.
    """
    completed_today = db_get_completed_today_tasks(user_id)
    active_tasks = db_get_active_tasks(user_id)

    if completed_today:
        c_lines = [f"🎉 **СЕГОДНЯ ВЫПОЛНЕНО ({len(completed_today)} задач):**"]
        for ct in completed_today:
            cid, ctitle, ccat, cupd = ct
            c_lines.append(f"  ✅ **{ctitle}** [{ccat}]")
        completed_str = "\n".join(c_lines) + "\n\n"
    else:
        completed_str = "Сегодня закрытых задач не зафиксировано.\n\n"

    pending_count = len(active_tasks)
    pending_str = f"⏳ В списке ожидания: {pending_count} задач.\n\n" if pending_count > 0 else "✅ Все текущие дела закрыты!\n\n"

    brain_dump_prompt = (
        "🧠 **ВЕЧЕРНЯЯ РАЗГРУЗКА ГОЛОВЫ (Brain Dump)**\n"
        "Не держите мысли и планы в голове на ночь — это мешает качественному сну.\n\n"
        "Надиктуйте всё, что нужно сделать завтра или на неделе, **одним голосовым сообщением**:\n"
        "• Встречи, звонки, дела по C3\n"
        "• Бытовые задачи и покупки\n\n"
        "Я разложу всё по времени и категориям. Вы сможете спокойно отдохнуть!"
    )

    full_text = (
        "🌙 **ИТОГИ ДНЯ И ВЕЧЕРНЯЯ РАЗГРУЗКА**\n\n"
        f"{completed_str}"
        f"{pending_str}"
        f"{brain_dump_prompt}"
    )

    send_message(
        chat_id,
        full_text,
        reply_markup={
            "inline_keyboard": [
                [{"text": "📅 Открыть Календарь на завтра", "web_app": {"url": CALENDAR_URL}}]
            ]
        }
    )


def send_morning_briefing(user_id, chat_id):
    """Dispatches 09:00 Morning MIT briefing and Alice speaker prompt."""
    handle_morning_mit_command(chat_id, user_id)
    try:
        from yandex_alice import trigger_scenario
        trigger_scenario()
    except Exception as e:
        print(f"[Morning Briefing] Alice trigger error: {e}")


def send_evening_review(user_id, chat_id):
    """Dispatches 21:00 Evening review."""
    handle_evening_review_command(chat_id, user_id)


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

    # 7. Deep Work Focus Command / Button
    if (
        text in ["/focus", "🎯 Режим фокуса (45м)", "фокус", "помодоро", "спринт", "глубокий фокус"]
        or text.startswith("/focus")
        or (text.lower().startswith("фокус") and not any(w in text.lower() for w in ["утренний", "дня"]))
    ):
        handle_focus_command(chat_id, user_id, text)
        return

    # 8. Morning MIT Command / Button
    if text in ["/morning", "/mit", "🌅 3 Главных дела (MIT)", "утренний фокус", "3 главных дела", "главные дела", "3 цели"]:
        handle_morning_mit_command(chat_id, user_id)
        return

    # 9. Evening Review Command / Button
    if text in ["/evening", "/review", "🌙 Итоги дня", "итоги дня", "итоги", "дебрифинг"]:
        handle_evening_review_command(chat_id, user_id)
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
    if laya["laya_intent"] == "FOCUS_SESSION":
        handle_focus_command(chat_id, user_id, raw_input_text)
        return

    if laya["laya_intent"] == "MORNING_MIT":
        handle_morning_mit_command(chat_id, user_id)
        return

    if laya["laya_intent"] == "EVENING_REVIEW":
        handle_evening_review_command(chat_id, user_id)
        return

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

    elif data.startswith("focus_start_"):
        mins = int(data.split("_")[2])
        res = db_start_focus_session(user_id, "Глубокая концентрация", mins)
        if res:
            ends_msk = to_msk(res["ends_at"])
            send_message(
                chat_id,
                f"🎯 **РЕЖИМ ГЛУБОКОГО ФОКУСА ВКЛЮЧЕН!**\n\n"
                f"📌 **Цель:** Глубокая концентрация\n"
                f"⏳ **Таймер:** {mins} минут (до {ends_msk.strftime('%H:%M МСК')})\n\n"
                f"📵 Положите телефон экраном вниз. По окончании таймера прозвучит громкий сигнал!",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "⏹ Прервать фокус", "callback_data": "focus_cancel"}]
                    ]
                }
            )

    elif data == "focus_cancel":
        db_cancel_focus_session(user_id)
        send_message(chat_id, "⏹ **Фокус-сессия остановлена.** Возвращайтесь к работе, когда будете готовы!")

    elif data.startswith("checkin_done_"):
        task_id = int(data.split("_")[2])
        db_complete_task(task_id)
        send_message(chat_id, f"🎉 **Отлично!** Задача #{task_id} выполнена и закрыта.")

    elif data.startswith("checkin_postpone_"):
        parts = data.split("_")
        task_id = int(parts[2])
        mode = parts[3]
        if mode == "30":
            db_postpone_task_minutes(task_id, 30)
            send_message(chat_id, f"⏳ Задача #{task_id} продлена на 30 минут.")
        elif mode == "evening":
            db_postpone_task_to_evening(task_id)
            send_message(chat_id, f"🌙 Задача #{task_id} перенесена на вечер (19:00 МСК).")

    elif data.startswith("mit_select_"):
        task_id = int(data.split("_")[2])
        db_set_task_mit(task_id, True)
        send_message(chat_id, f"⭐️ **Задача #{task_id} закреплена как одна из 3 Главных целей дня (MIT)!**")
        handle_morning_mit_command(chat_id, user_id)

    elif data.startswith("mit_focus_"):
        task_id = int(data.split("_")[2])
        tasks = db_get_active_tasks(user_id)
        t_title = next((t["title"] for t in tasks if t["id"] == task_id), f"Задача #{task_id}")
        res = db_start_focus_session(user_id, t_title, 45)
        if res:
            ends_msk = to_msk(res["ends_at"])
            send_message(
                chat_id,
                f"🎯 **Фокус 45 минут запущен по главной цели #{task_id}:**\n«{t_title}»\n\n"
                f"⏳ До {ends_msk.strftime('%H:%M МСК')}. Работаем только над ней!",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "⏹ Прервать фокус", "callback_data": "focus_cancel"}]
                    ]
                }
            )

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
# Background Reminder & Habit Loop
# -------------------------------------------------------------
def reminder_worker():
    """Continuously checks for due reminders, expired focus timers, and scheduled coaching."""
    print("[Reminder Worker] Started monitoring scheduled tasks, focus sessions, and check-ins...")
    while True:
        try:
            # 1. Standard Due Task Reminders
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

            # 2. Expired Deep Work Focus Sessions
            try:
                expired_sessions = db_get_expired_focus_sessions()
                for s in expired_sessions:
                    sid, uid, s_title, s_dur, s_ends = s
                    print(f"[Reminder Worker] Focus session #{sid} expired: '{s_title}'")
                    db_mark_focus_alert_sent(sid)

                    try:
                        from phone_notify import send_phone_alarm
                        send_phone_alarm(
                            title="🎯 Фокус завершен!",
                            message=f"{s_dur} минут работы над «{s_title}» окончены. Время сделать перерыв 10 минут!",
                            priority=5,
                            category="Здоровье"
                        )
                    except Exception as fe:
                        print(f"[Focus Alert] Phone alarm error: {fe}")

                    focus_end_kb = {
                        "inline_keyboard": [
                            [{"text": "☕ Перерыв 10 мин", "callback_data": "focus_start_10"}, {"text": "🎯 Еще фокус (45м)", "callback_data": "focus_start_45"}]
                        ]
                    }
                    send_message(
                        uid,
                        f"🎉 **ВРЕМЯ ВЫШЛО! СЕССИЯ ГЛУБОКОГО ФОКУСА ЗАВЕРШЕНА!**\n\n"
                        f"Вы отлично поработали {s_dur} минут над целью:\n"
                        f"📌 **«{s_title}»**\n\n"
                        f"☕ **Правило отдыха:** обязательно встаньте из-за стола, разомнитесь, выпейте воды и дайте глазам 5–10 минут отдыха!",
                        reply_markup=focus_end_kb
                    )
            except Exception as fe:
                print(f"[Reminder Worker] Focus check error: {fe}")

            # 3. Proactive Accountability Check-in
            try:
                checkin_tasks = db_get_tasks_needing_checkin()
                for ct in checkin_tasks:
                    cid, cuid, ctitle, ccat, cdue = ct
                    due_msk = to_msk(cdue)
                    due_str = due_msk.strftime('%H:%M') if due_msk else "ранее"
                    print(f"[Reminder Worker] Sending proactive check-in for Task #{cid}: '{ctitle}'")
                    db_mark_task_checkin_sent(cid)

                    checkin_kb = {
                        "inline_keyboard": [
                            [{"text": "✅ Выполнено!", "callback_data": f"checkin_done_{cid}"}],
                            [{"text": "⏳ Еще 30 минут", "callback_data": f"checkin_postpone_{cid}_30"}],
                            [{"text": "🌙 На вечер (19:00)", "callback_data": f"checkin_postpone_{cid}_evening"}]
                        ]
                    }
                    send_message(
                        cuid,
                        f"🤝 **КОНТРОЛЬ ФОКУСА ОТ АССИСТЕНТА**\n\n"
                        f"Артём, как продвигается задача:\n"
                        f"📌 **#{cid} {ctitle}** *(дедлайн был в {due_str} МСК)*?\n\n"
                        f"Удалось закрыть или нужно дополнительное время?",
                        reply_markup=checkin_kb
                    )
            except Exception as che:
                print(f"[Reminder Worker] Checkin check error: {che}")

            # 4. Daily Morning MIT Briefing (08:50 - 09:30 MSK)
            try:
                now_msk = datetime.datetime.now(MSK)
                today_str = now_msk.date().isoformat()
                if now_msk.hour == 9 and 0 <= now_msk.minute <= 30:
                    flag_key = f"MORNING_BRIEFING_{today_str}"
                    if not db_get_user_setting(AUTHORIZED_USER_ID, flag_key):
                        db_set_user_setting(AUTHORIZED_USER_ID, flag_key, "sent")
                        print(f"[Reminder Worker] Triggering Morning Briefing for {today_str}")
                        send_morning_briefing(AUTHORIZED_USER_ID, AUTHORIZED_USER_ID)
            except Exception as me:
                print(f"[Reminder Worker] Morning briefing error: {me}")

            # 5. Daily Evening Review (21:00 - 21:30 MSK)
            try:
                now_msk = datetime.datetime.now(MSK)
                today_str = now_msk.date().isoformat()
                if now_msk.hour == 21 and 0 <= now_msk.minute <= 30:
                    flag_key = f"EVENING_REVIEW_{today_str}"
                    if not db_get_user_setting(AUTHORIZED_USER_ID, flag_key):
                        db_set_user_setting(AUTHORIZED_USER_ID, flag_key, "sent")
                        print(f"[Reminder Worker] Triggering Evening Review for {today_str}")
                        send_evening_review(AUTHORIZED_USER_ID, AUTHORIZED_USER_ID)
            except Exception as ee:
                print(f"[Reminder Worker] Evening review error: {ee}")

        except Exception as e:
            print(f"[Reminder Worker] Error: {e}")

        time.sleep(20)


# -------------------------------------------------------------
# Telegram Webhook & Update Processing
# -------------------------------------------------------------
def process_telegram_update(upd: dict):
    """
    Processes a single Telegram update dict received via direct Webhook or Polling.
    Safe wrapper preventing unhandled exceptions from crashing callers.
    """
    try:
        if "message" in upd:
            handle_message(upd["message"])
        elif "callback_query" in upd:
            handle_callback_query(upd["callback_query"])
    except Exception as e:
        print(f"[Telegram Update Processor] Error processing update {upd.get('update_id')}: {e}")


def set_telegram_webhook(webhook_url: str, secret_token: Optional[str] = None) -> bool:
    """Configures Telegram to deliver updates directly via Webhook to server.py."""
    params = {
        "url": webhook_url,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": False
    }
    if secret_token:
        params["secret_token"] = secret_token
    res = tg_api_call("setWebhook", params)
    print(f"[Telegram] Webhook registered at: {webhook_url} (Result: {res})")
    return bool(res and res.get("ok"))


def delete_telegram_webhook(drop_pending_updates: bool = False) -> bool:
    """Deletes existing webhook for polling mode."""
    res = tg_api_call("deleteWebhook", {"drop_pending_updates": drop_pending_updates})
    print(f"[Telegram] Webhook deleted (Result: {res})")
    return bool(res and res.get("ok"))


# -------------------------------------------------------------
# Standalone Polling Loop (Local Debugging / Standalone Fallback)
# -------------------------------------------------------------
def run_polling():
    print("=" * 60)
    print("🤖 MAX & PERSONAL ASSISTANT BOT (STANDALONE POLLING MODE)")
    print(f"Authorized User: Artem (ID {AUTHORIZED_USER_ID})")
    print(f"Target Bot: @c3_ru_bot")
    print(f"Mini App: {CALENDAR_URL}")
    print("=" * 60)

    init_db()
    setup_bot_interface()

    # Clear any active webhooks before starting polling
    delete_telegram_webhook(drop_pending_updates=False)

    # Start reminder daemon thread
    reminder_thread = threading.Thread(target=reminder_worker, daemon=True, name="ReminderThread")
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
                process_telegram_update(upd)

        except Exception as e:
            time.sleep(2)


if __name__ == "__main__":
    run_polling()
