"""
Yandex Station (Alice) Voice Dispatcher
Interacts with official Yandex Smart Home (Quasar) API.
Enables the AI agent to speak task reminders and morning/evening digests out loud.
"""

import os
import sys
import json
import urllib.request
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

try:
    from db import get_db
except ImportError:
    def get_db():
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                conn = psycopg2.connect(db_url)
                conn.set_client_encoding('UTF8')
                return conn
            except Exception as e:
                print(f"[Alice DB] Connection error: {e}")
        return None


def get_yandex_token(user_id: int = 268747191) -> str:
    """Loads Yandex OAuth token dynamically from Neon DB or environment."""
    conn = get_db()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM user_settings WHERE user_id = %s AND key = 'YANDEX_OAUTH_TOKEN';",
                    (user_id,)
                )
                row = cur.fetchone()
                if row and row[0]:
                    return row[0].strip()
        except Exception as e:
            print(f"[Alice DB] Error fetching token: {e}")
        finally:
            conn.close()
    return os.getenv("YANDEX_OAUTH_TOKEN", "")


YANDEX_STATION_ID = os.getenv("YANDEX_STATION_ID")
CLIENT_ID = os.getenv("YANDEX_CLIENT_ID", "afe17649a3e94b7bb8813e8be2e6d68a")
YANDEX_OAUTH_URL = f"https://oauth.yandex.ru/authorize?response_type=token&client_id={CLIENT_ID}"
IOT_API_BASE = "https://api.iot.yandex.net/v1.0"


def get_yandex_auth_url():
    """Returns 1-click URL to authorize Yandex Smart Home."""
    return YANDEX_OAUTH_URL


def get_smart_home_devices(token=None):
    """
    Fetches all devices in Artem's Yandex Smart Home.
    Returns list of smart speakers (Yandex Stations).
    """
    tok = token or get_yandex_token()
    if not tok:
        print("[Alice] ⚠️ YANDEX_OAUTH_TOKEN not configured.")
        return []

    url = f"{IOT_API_BASE}/user/info"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            devices = data.get("devices", [])
            speakers = []
            for d in devices:
                dev_type = d.get("type", "")
                if "smart_speaker" in dev_type or "media_device" in dev_type:
                    speakers.append({
                        "id": d["id"],
                        "name": d["name"],
                        "room": d.get("room_name", "Комната"),
                        "type": dev_type
                    })
            return speakers
    except Exception as e:
        print(f"[Alice] ❌ Error fetching devices: {e}")
        return []


def get_user_scenarios(token: str = None) -> list:
    """
    Fetches all user scenarios configured in Artem's Yandex Smart Home.
    Returns list of scenarios with id, name, and is_active flag.
    """
    tok = token or get_yandex_token()
    if not tok:
        return []
    url = f"{IOT_API_BASE}/user/info"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("scenarios", [])
    except Exception as e:
        print(f"[Alice] ❌ Error fetching scenarios: {e}")
        return []


def trigger_scenario(scenario_id: str = None, scenario_name: str = None, token: str = None) -> tuple:
    """
    Triggers an official Yandex Smart Home Scenario (e.g. speaking a phrase, weather, commands).
    Returns (success: bool, message: str).
    """
    tok = token or get_yandex_token()
    if not tok:
        return False, "YANDEX_OAUTH_TOKEN не найден в базе данных."

    scenarios = get_user_scenarios(tok)
    target_id = scenario_id

    if not target_id:
        if scenario_name:
            for s in scenarios:
                if scenario_name.lower() in s.get("name", "").lower():
                    target_id = s.get("id")
                    break
        if not target_id:
            # Prefer active scenarios
            active_scenarios = [s for s in scenarios if s.get("is_active")]
            if active_scenarios:
                target_id = active_scenarios[0]["id"]
            elif scenarios:
                target_id = scenarios[0]["id"]
            else:
                return False, "В аккаунте пока нет созданных сценариев в приложении «Дом с Алисой»."

    url = f"{IOT_API_BASE}/scenarios/{target_id}/actions"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                return True, "Сценарий успешно выполнен! Алиса проговаривает команду на колонке."
            return False, f"Ошибка API: HTTP {resp.status}"
    except urllib.error.HTTPError as he:
        body = he.read().decode("utf-8", errors="ignore")
        if "scenario is not active" in body:
            return False, "Сценарий выключен в приложении «Дом с Алисой». Включите тумблер у сценария."
        return False, f"HTTP {he.code}: {body}"
    except Exception as e:
        return False, str(e)


def speak_on_station(phrase: str = None, station_id: str = None, token: str = None) -> bool:
    """
    Commands Alice on Yandex Station to speak a phrase or trigger voice reminder.
    In Yandex Smart Home, voice commands on smart speakers are triggered via Scenarios.
    """
    tok = token or get_yandex_token()
    if not tok:
        print("[Alice] Cannot speak: YANDEX_OAUTH_TOKEN missing.")
        return False

    # Try triggering active reminder / test scenario first
    success, msg = trigger_scenario(token=tok)
    if success:
        print(f"[Alice] 🗣️ Scenario triggered on Station: {msg}")
        return True
    else:
        print(f"[Alice] ⚠️ Scenario trigger status: {msg}")
        return False


def save_yandex_token(token: str, user_id: int = 268747191) -> bool:
    """Saves YANDEX_OAUTH_TOKEN into Neon DB user_settings table."""
    clean_token = token.strip()
    if clean_token.startswith("Bearer "):
        clean_token = clean_token[7:].strip()

    conn = get_db()
    if not conn:
        print("[Alice] ❌ Failed to connect to Neon DB to save token")
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id BIGINT NOT NULL DEFAULT 268747191,
                    key VARCHAR(128) NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (user_id, key)
                );
                INSERT INTO user_settings (user_id, key, value, updated_at)
                VALUES (%s, 'YANDEX_OAUTH_TOKEN', %s, NOW())
                ON CONFLICT (user_id, key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
            """, (user_id, clean_token))
            conn.commit()
            print(f"[Alice] ✅ YANDEX_OAUTH_TOKEN successfully saved to Neon DB for user {user_id}")
            return True
    except Exception as e:
        print(f"[Alice] ❌ DB error saving token: {e}")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("🎙️ YANDEX ALICE SMART HOME DISPATCHER")
    print("=" * 60)
    current_tok = get_yandex_token()
    if not current_tok:
        print("\nДля подключения Яндекс Станции требуется однократно получить токен:")
        print(f"1. Перейдите по ссылке:\n   {YANDEX_OAUTH_URL}")
        print("2. Нажмите 'Разрешить' и скопируйте полученный токен.")
        print("3. Отправьте токен боту в Telegram или сохраните командой: python yandex_alice.py <TOKEN>\n")
        if len(sys.argv) > 1:
            save_yandex_token(sys.argv[1])
    else:
        print("[Alice] YANDEX_OAUTH_TOKEN is present in DB/environment.")
        speakers = get_smart_home_devices(current_tok)
        print(f"[Alice] Found {len(speakers)} speaker(s):")
        for s in speakers:
            print(f"  • {s['name']} (Комната: {s['room']}, ID: {s['id']})")
        if len(sys.argv) > 1:
            test_phrase = " ".join(sys.argv[1:])
            speak_on_station(test_phrase)
