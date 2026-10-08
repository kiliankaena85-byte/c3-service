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

ENV_PATH = r"E:\Documents\Lider\.env"
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)

YANDEX_OAUTH_TOKEN = os.getenv("YANDEX_OAUTH_TOKEN")
YANDEX_STATION_ID = os.getenv("YANDEX_STATION_ID")

# Standard Smart Home Quasar Client ID for direct token issuance
YANDEX_OAUTH_URL = "https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b49c3230e3e91"
IOT_API_BASE = "https://api.iot.yandex.net/v1.0"


def get_yandex_auth_url():
    """Returns 1-click URL to authorize Yandex Smart Home."""
    return YANDEX_OAUTH_URL


def get_smart_home_devices(token=None):
    """
    Fetches all devices in Artem's Yandex Smart Home.
    Returns list of smart speakers (Yandex Stations).
    """
    tok = token or YANDEX_OAUTH_TOKEN
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


def speak_on_station(phrase: str, station_id: str = None, token: str = None):
    """
    Commands Alice on Yandex Station to speak a phrase out loud in the room.
    """
    tok = token or YANDEX_OAUTH_TOKEN
    if not tok:
        print(f"[Alice] Cannot speak: YANDEX_OAUTH_TOKEN missing.")
        return False

    target_id = station_id or YANDEX_STATION_ID
    if not target_id:
        # Auto-discover first available speaker
        speakers = get_smart_home_devices(tok)
        if speakers:
            target_id = speakers[0]["id"]
            print(f"[Alice] Auto-selected speaker: '{speakers[0]['name']}' ({target_id})")
        else:
            print("[Alice] ❌ No Yandex Station found in account.")
            return False

    url = f"{IOT_API_BASE}/devices/actions"
    payload = {
        "devices": [
            {
                "id": target_id,
                "actions": [
                    {
                        "type": "devices.capabilities.quasar.server_action",
                        "state": {
                            "instance": "phrase_action",
                            "value": phrase
                        }
                    }
                ]
            }
        ]
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                print(f"[Alice] 🗣️ Command sent to Station: «{phrase}»")
                return True
            else:
                print(f"[Alice] ⚠️ API returned HTTP {resp.status}")
                return False
    except Exception as e:
        print(f"[Alice] ❌ Error triggering speech: {e}")
        return False


def save_yandex_token(token: str):
    """Saves YANDEX_OAUTH_TOKEN into E:\Documents\Lider\.env."""
    clean_token = token.strip()
    if clean_token.startswith("Bearer "):
        clean_token = clean_token[7:].strip()

    env_lines = []
    found = False
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("YANDEX_OAUTH_TOKEN="):
                    env_lines.append(f"YANDEX_OAUTH_TOKEN={clean_token}\n")
                    found = True
                else:
                    env_lines.append(line)

    if not found:
        env_lines.append(f"\nYANDEX_OAUTH_TOKEN={clean_token}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(env_lines)

    print(f"[Alice] ✅ YANDEX_OAUTH_TOKEN successfully saved to {ENV_PATH}")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("🎙️ YANDEX ALICE SMART HOME DISPATCHER")
    print("=" * 60)
    if not YANDEX_OAUTH_TOKEN:
        print("\nДля подключения Яндекс Станции требуется однократно получить токен:")
        print(f"1. Перейдите по ссылке:\n   {YANDEX_OAUTH_URL}")
        print("2. Нажмите 'Разрешить' и скопируйте полученный токен.")
        print("3. Отправьте токен боту в Telegram или сохраните командой: python yandex_alice.py <TOKEN>\n")
        if len(sys.argv) > 1:
            save_yandex_token(sys.argv[1])
    else:
        print("[Alice] YANDEX_OAUTH_TOKEN is present.")
        speakers = get_smart_home_devices()
        print(f"[Alice] Found {len(speakers)} speaker(s):")
        for s in speakers:
            print(f"  • {s['name']} (Комната: {s['room']}, ID: {s['id']})")
        if len(sys.argv) > 1:
            test_phrase = " ".join(sys.argv[1:])
            speak_on_station(test_phrase)
