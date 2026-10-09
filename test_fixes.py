# -*- coding: utf-8 -*-
"""
Automated unit test suite verifying all critical fixes across c3_service_repo:
1. SQL Bug fix and timestamptz casting in server.py
2. Timezone MSK normalization in task_bot.py
3. Phantom task prevention in task_bot.py and laya_assistant.py
4. Telegram initData & token authorization in server.py
5. Yandex Alice dynamic token loading in yandex_alice.py
6. Private secure topic in phone_notify.py
7. Mobile UX and date grouping in calendar.html
"""
import os
import re
import sys
import datetime
import zoneinfo
import psycopg2
from dotenv import load_dotenv

# Load env for database access during tests
load_dotenv('E:/Documents/Lider/.env')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from laya_assistant import LayaAssistantDecisionEngine
from task_bot import to_msk, MSK, extract_task_id, db_complete_task
import yandex_alice
import phone_notify
import server

def test_timezone_msk():
    print("[*] Testing Timezone MSK Normalization...")
    # UTC 21:30 should be 00:30 next day in MSK (UTC+3)
    utc_dt = datetime.datetime(2026, 10, 9, 21, 30, tzinfo=datetime.timezone.utc)
    msk_dt = to_msk(utc_dt)
    assert msk_dt.day == 10, f"Expected day 10, got {msk_dt.day}"
    assert msk_dt.hour == 0, f"Expected hour 0, got {msk_dt.hour}"
    assert msk_dt.minute == 30, f"Expected minute 30, got {msk_dt.minute}"

    # ISO string with UTC 'Z'
    iso_z = "2026-10-09T18:00:00Z"
    msk_z = to_msk(iso_z)
    assert msk_z.hour == 21, f"Expected 21:00 MSK, got {msk_z.hour}"

    print("  -> Passed!")


def test_intent_and_phantom_prevention():
    print("[*] Testing Intent Triage & Phantom Task Prevention...")
    # Greetings / Etiquette
    for phrase in ["Привет", "Добрый день", "Здравствуйте", "Спасибо огромное", "Благодарю"]:
        triage = LayaAssistantDecisionEngine.evaluate_intent_and_routing(phrase)
        assert triage["laya_intent"] == "GREETING", f"Failed for '{phrase}': got {triage['laya_intent']}"

    # Complete Task
    for phrase in ["Выполнил задачу 15", "Сделал #12", "Готово", "закрыл"]:
        triage = LayaAssistantDecisionEngine.evaluate_intent_and_routing(phrase)
        assert triage["laya_intent"] == "COMPLETE_TASK", f"Failed for '{phrase}': got {triage['laya_intent']}"

    # Create Task
    for phrase in ["Забрать ножницы из Ozon сегодня до 18:00", "Купить продукты"]:
        triage = LayaAssistantDecisionEngine.evaluate_intent_and_routing(phrase)
        assert triage["laya_intent"] == "CREATE_TASK", f"Failed for '{phrase}': got {triage['laya_intent']}"

    print("  -> Passed!")


def test_task_id_parsing_vs_time():
    print("[*] Testing Task ID Parsing vs Time Expressions...")
    # Explicit task ID should be extracted
    assert extract_task_id("выполнил #5") == 5
    assert extract_task_id("сделал №12") == 12
    assert extract_task_id("закрыл задачу 7") == 7
    assert extract_task_id("задача 4 готова") == 4
    assert extract_task_id("выполнил 3") == 3

    # Time expressions and counts MUST NOT be misinterpreted as task IDs
    assert extract_task_id("Сделал в 18:00") is None
    assert extract_task_id("выполнил в 20:30") is None
    assert extract_task_id("сделал 2 дела") is None
    assert extract_task_id("выполнил") is None
    assert extract_task_id("сделал задачу") is None

    print("  -> Passed!")


def test_db_complete_task_rowcount():
    print("[*] Testing db_complete_task rowcount guard...")
    # A non-existent task ID must return False, not True
    result = db_complete_task(-999999)
    assert result is False, f"Expected False for non-existent task ID -999999, got {result}"
    print("  -> Passed!")


def test_server_auth():
    print("[*] Testing Server /api/tasks Authentication...")
    class DummyRequest:
        def __init__(self, headers=None, query_params=None):
            self.headers = headers or {}
            self.query_params = query_params or {}

    # Unauthorized without credentials
    req_anon = DummyRequest()
    assert not server.is_authorized_request(req_anon), "Anonymous request should be rejected"

    # Authorized with bot token in header
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        req_token = DummyRequest(headers={"X-Telegram-Init-Data": token})
        assert server.is_authorized_request(req_token), "Request with valid bot token in header should be authorized"

        # Authorized with bot token in query param
        req_query = DummyRequest(query_params={"token": token})
        assert server.is_authorized_request(req_query), "Request with valid bot token in query param should be authorized"

    print("  -> Passed!")


def test_api_create_task_validation():
    print("[*] Testing server.py api_create_task Title Validation...")
    import asyncio
    class MockRequest:
        def __init__(self, json_data, headers=None, query_params=None):
            self._json_data = json_data
            self.headers = headers or {}
            self.query_params = query_params or {}
        async def json(self):
            return self._json_data

    async def _run():
        token = os.getenv("TELEGRAM_BOT_TOKEN") or "test_tok"
        # 1. Empty title -> 400
        req_empty = MockRequest({"title": "   "}, headers={"X-Telegram-Init-Data": token})
        res_empty = await server.api_create_task(req_empty)
        assert res_empty.status_code == 400, f"Expected 400 for empty title, got {res_empty.status_code}"

        # 2. Missing title -> 400
        req_missing = MockRequest({}, headers={"X-Telegram-Init-Data": token})
        res_missing = await server.api_create_task(req_missing)
        assert res_missing.status_code == 400, f"Expected 400 for missing title, got {res_missing.status_code}"

    asyncio.run(_run())
    print("  -> Passed!")


def test_phone_notify_secure_topic():
    print("[*] Testing Phone Notify Secure Topic...")
    assert "artem_spektr_tasks_a35_sec_9d4f18b" in phone_notify.NTFY_TOPICS
    assert "artem_spektr_tasks_2026" in phone_notify.NTFY_TOPICS
    print("  -> Passed!")


def test_yandex_alice_db():
    print("[*] Testing Yandex Alice Neon DB Token Storage...")
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        test_uid = 999999999
        yandex_alice.save_yandex_token("test_alice_token_neon_99", user_id=test_uid)
        loaded = yandex_alice.get_yandex_token(user_id=test_uid)
        assert loaded == "test_alice_token_neon_99", f"Expected test_alice_token_neon_99, got {loaded}"
        # Cleanup test user only
        conn = yandex_alice.get_db()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_settings WHERE user_id = %s;", (test_uid,))
            conn.commit()
        conn.close()
    print("  -> Passed!")


def test_calendar_html_ux():
    print("[*] Testing Calendar HTML UX and Regex Requirements...")
    cal_path = os.path.join(os.path.dirname(__file__), "static", "calendar.html")
    with open(cal_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. safe-area-inset-bottom
    assert "env(safe-area-inset-bottom, 0px)" in html, "Missing safe-area-inset-bottom in calendar.html"

    # 2. touch-action manipulation
    assert "touch-action: manipulation;" in html, "Missing touch-action in calendar.html"

    # 3. BackButton support and proper hide()
    assert "Telegram.WebApp.BackButton" in html or "BackButton" in html, "Missing BackButton in calendar.html"
    assert "BackButton.hide()" in html, "Missing BackButton.hide() in calendar.html"

    # 4. getTaskDateKey
    assert "getTaskDateKey" in html, "Missing getTaskDateKey in calendar.html"

    # 5. X-Telegram-Init-Data header & URL token support
    assert "X-Telegram-Init-Data" in html, "Missing X-Telegram-Init-Data in calendar.html"
    assert "urlParams.get('token')" in html, "Missing urlParams.get('token') in calendar.html"

    # 6. submitNewTask error checking
    assert "!resp.ok" in html, "Missing !resp.ok check in calendar.html"

    print("  -> Passed!")


def test_sql_cast_query():
    print("[*] Testing server.py SQL Query Cast...")
    srv_path = os.path.join(os.path.dirname(__file__), "server.py")
    with open(srv_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "%s::timestamptz" in src, "Missing %s::timestamptz cast in server.py"
    print("  -> Passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING AUTOMATED TEST SUITE FOR C3 SERVICE REPO FIXES")
    print("=" * 60)
    test_timezone_msk()
    test_intent_and_phantom_prevention()
    test_task_id_parsing_vs_time()
    test_db_complete_task_rowcount()
    test_server_auth()
    test_api_create_task_validation()
    test_phone_notify_secure_topic()
    test_yandex_alice_db()
    test_calendar_html_ux()
    test_sql_cast_query()
    print("=" * 60)
    print("✅ ALL TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)
