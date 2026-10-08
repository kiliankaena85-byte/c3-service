"""
Phone Notification & Alarm Dispatcher for Samsung Galaxy A35
Sends instant high-priority alerts that can ring as alarms and bypass Do Not Disturb.
Powered by ntfy.sh (Open Source, zero-setup push service).
"""

import urllib.request
import json
import os
import sys
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

# Secure private topic for Artem (uniquely salted against topic scanning)
DEFAULT_TOPIC = "artem_spektr_tasks_a35_sec_9d4f18b"
env_topics = os.getenv("NTFY_TOPICS") or os.getenv("NTFY_TOPIC")
if env_topics:
    NTFY_TOPICS = [t.strip() for t in env_topics.split(",") if t.strip()]
else:
    NTFY_TOPICS = [DEFAULT_TOPIC]

NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")


def send_phone_alarm(title: str, message: str, priority: int = 5, category: str = "Общее", click_url: str = "https://t.me/c3_ru_bot"):
    """
    Sends an urgent push alert to Samsung Galaxy A35.
    Priority 5 = Plays alarm tone, vibrates, turns on screen, bypasses DND.
    """
    url = f"{NTFY_SERVER.rstrip('/')}/"
    
    # Map category to tags / emoji
    tags = ["alarm_clock"]
    if "ozon" in category.lower() or "покупки" in category.lower():
        tags.append("package")
    elif "работа" in category.lower() or "заказчик" in category.lower():
        tags.append("briefcase")
    elif "семья" in category.lower():
        tags.append("house")

    success = False
    for topic in NTFY_TOPICS:
        payload = {
            "topic": topic,
            "title": f"⏰ {title}",
            "message": message,
            "priority": priority,  # 5 = max (alarm)
            "tags": tags,
            "click": click_url,
            "actions": [
                {
                    "action": "view",
                    "label": "Открыть в Telegram",
                    "url": click_url
                }
            ]
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    print(f"[Phone Alarm] ✅ Alert successfully sent to topic '{topic}' (Priority: {priority})")
                    success = True
        except Exception as e:
            print(f"[Phone Alarm] ❌ Error sending push to '{topic}': {e}")

    return success


if __name__ == "__main__":
    print(f"Testing phone alarm dispatch to topics: {NTFY_TOPICS} ...")
    send_phone_alarm(
        title="Тестовый будильник задачи",
        message="Забрать ножницы для бабушки из Ozon сегодня до 18:00!",
        priority=5,
        category="Покупки / Ozon"
    )
