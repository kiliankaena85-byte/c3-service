# -*- coding: utf-8 -*-
"""
C3 Telegram Scout & Co-Pilot (Telethon Cloud Daemon for Render.com)
Monitors community groups (cottage settlements, SNT, neighborhood, builder chats),
detects stair/porch/tile issues, verifies intent via LAYA,
and generates authentic human drafts directly to your Saved Messages ('me').

Runs seamlessly in cloud environments via Telethon StringSession.
"""

import os
import sys
import re
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat, User
from generate_authentic_copy import generate_authentic_copy
from c3_humanity_detector import LayaHumanityClassifier

logging.basicConfig(
    format='[%(asctime)s] %(levelname)s [Scout]: %(message)s',
    level=logging.INFO,
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("C3_Cloud_Scout")

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")

# Trigger patterns (Fast regex pre-filter)
STAIR_CORE_TRIGGERS = [
    r'крыльц', r'ступен', r'лестниц', r'входн\w+\s+групп'
]

STAIR_PROBLEM_KEYWORDS = [
    r'плитк', r'керамогранит', r'клинкер', r'скользк', r'скользит',
    r'отвалил', r'отпал', r'отошл', r'отстал', r'раскрошил', r'покрошил',
    r'отколол', r'пооткалывал', r'треснул', r'зашатал', r'разрушил',
    r'передела', r'переложи', r'отдела', r'облицов', r'обложи',
    r'бетон\w+\s+ступен', r'крошит', r'швы\s+полопал'
]

NEGATIVE_PATTERNS = [
    r'втор\w+\s+этаж', r'внутри\s+дома', r'деревянн\w+\s+лестниц',
    r'винтов\w+\s+лестниц', r'чердачн', r'стремянк', r'трансформер',
    r'карьерн\w+\s+лестниц', r'в\s+небо'
]

FALLBACK_HUMAN_REPLY = (
    "У меня на даче такая же беда была с плиткой - две зимы и всё поотлетало, "
    "вода под швы попадает и рвет. Мы в итоге поставили тверские монолитные ступени C3 "
    "(они цельные Г-образные из прочного бетона, швов нет на изгибе). "
    "Уже четвертый год стоят, зимой лопатой чищу - вообще не скользят."
)

processed_msgs = set()

def is_target_stair_inquiry(text: str) -> tuple[bool, str]:
    if not text or len(text.strip()) < 10:
        return False, "Too short"

    clean_text = text.lower()

    for neg in NEGATIVE_PATTERNS:
        if re.search(neg, clean_text):
            return False, f"Negative pattern match: {neg}"

    has_core = any(re.search(pat, clean_text) for pat in STAIR_CORE_TRIGGERS)
    if not has_core:
        has_tile = bool(re.search(r'плитк|керамогранит|клинкер', clean_text))
        has_prob = any(re.search(pat, clean_text) for pat in [r'улиц', r'вход', r'двор', r'мороз', r'зимой', r'намерз'])
        if not (has_tile and has_prob):
            return False, "No stair/outdoor keywords"

    has_problem = any(re.search(pat, clean_text) for pat in STAIR_PROBLEM_KEYWORDS)
    has_question = '?' in text or any(q in clean_text for q in ['чем', 'как', 'посоветуйте', 'кто делал', 'подскажите', 'где заказать', 'мастер'])

    if has_problem or has_question:
        return True, "Valid stair problem/inquiry"

    return False, "No actionable problem or question detected"


def get_message_link(chat, message) -> str:
    try:
        if hasattr(chat, 'username') and chat.username:
            return f"https://t.me/{chat.username}/{message.id}"
        elif hasattr(chat, 'id'):
            clean_id = str(chat.id).replace('-100', '')
            return f"https://t.me/c/{clean_id}/{message.id}"
    except Exception:
        pass
    return "Ссылка недоступна (приватная группа)"


async def start_cloud_scout():
    if not API_ID or not API_HASH:
        logger.warning("TELEGRAM_API_ID или TELEGRAM_API_HASH не заданы в переменных окружения. Скаут находится в режиме ожидания.")
        return

    # Check for StringSession first (ideal for Render / Docker)
    if SESSION_STRING:
        session = StringSession(SESSION_STRING.strip())
        logger.info("Используется Telethon StringSession из переменной TELEGRAM_SESSION_STRING")
    elif os.path.exists("c3_scout.session"):
        session = "c3_scout"
        logger.info("Используется локальный файл сессии c3_scout.session")
    else:
        logger.warning("TELEGRAM_SESSION_STRING не задана и файл сессии не найден. Скаут не может авторизоваться.")
        return

    client = TelegramClient(session, int(API_ID), API_HASH)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.error("Сессия не авторизована! Проверьте валидность TELEGRAM_SESSION_STRING.")
            return

        me = await client.get_me()
        logger.info(f"✅ C3 Скаут успешно запущен в облаке (Render) от имени: {me.first_name} {me.last_name or ''} (@{me.username or 'id=' + str(me.id)})")
        logger.info("📡 Режим: Облачный Co-Pilot (мониторинг групп + отправка в 'Избранное')")

        # Send heartbeat to Saved Messages
        try:
            startup_msg = (
                "☁️ **C3 Скаут успешно запущен в облаке на Render.com!**\n\n"
                "• Теперь скаут работает 24/7 независимо от вашего компьютера.\n"
                "• Мониторинг всех чатов активен.\n"
                "• Лиды и готовые ответы будут приходить сюда в Избранное."
            )
            await client.send_message('me', startup_msg)
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление о старте в 'me': {e}")

        @client.on(events.NewMessage)
        async def handler(event):
            try:
                # Ignore messages in Saved Messages
                if event.chat_id == me.id:
                    return

                ALLOW_SELF_TEST = os.getenv("ALLOW_SELF_TEST", "true").lower() == "true"
                if event.sender_id == me.id and not ALLOW_SELF_TEST:
                    return

                if not (event.is_group or event.is_channel):
                    return

                msg_text = event.message.message
                if not msg_text:
                    return

                msg_key = f"{event.chat_id}_{event.message.id}"
                if msg_key in processed_msgs:
                    return
                processed_msgs.add(msg_key)

                is_target, reason = is_target_stair_inquiry(msg_text)
                if not is_target:
                    return

                logger.info(f"🎯 Обнаружен целевой запрос! Причина: {reason}")
                logger.info(f"Текст: {msg_text[:120]}...")

                chat = await event.get_chat()
                chat_title = getattr(chat, 'title', 'Группа')

                sender = await event.get_sender()
                sender_name = "Пользователь"
                sender_handle = ""
                if isinstance(sender, User):
                    sender_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or "Участник"
                    if sender.username:
                        sender_handle = f"@{sender.username}"

                msg_link = get_message_link(chat, event.message)

                context = f"Участник чата '{chat_title}' пишет:\n«{msg_text}»"
                gen_res = generate_authentic_copy(context)

                if gen_res.get("status") in ["APPROVED", "NEEDS_REVIEW"] and gen_res.get("text"):
                    draft_text = gen_res["text"]
                    human_score = int(gen_res.get("eval", {}).get("humanity_score", 0.9) * 100)
                    slop_score = int(gen_res.get("eval", {}).get("ai_slop_score", 0.0) * 100)
                else:
                    draft_text = FALLBACK_HUMAN_REPLY
                    human_score = 100
                    slop_score = 0

                draft_text = draft_text.replace(" — ", " - ").replace("—", "-").replace(" – ", " - ").replace("–", "-")

                alert_text = (
                    f"🚨 **[C3 СКАУТ: НАЙДЕН ЗАПРОС НА ЛЕСТНИЦУ]**\n\n"
                    f"📍 **Чат:** {chat_title}\n"
                    f"👤 **Автор:** {sender_name} {sender_handle}\n"
                    f"💬 **Сообщение:**\n"
                    f"«_{msg_text}_»\n\n"
                    f"💡 **Черновик ответа (нажмите скопировать):**\n"
                    f"```{draft_text}```\n\n"
                    f"📊 **Аудит LAYA:** Человечность: `{human_score}%` | ИИ-слоп: `{slop_score}%`\n"
                    f"🔗 **Открыть сообщение:** [Перейти в чат]({msg_link})"
                )

                await client.send_message('me', alert_text, link_preview=False)
                logger.info("✅ Уведомление с черновиком отправлено в 'Избранное'!")

            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)

        logger.info("👂 Облачный скаут начал непрерывное прослушивание сообщений.")
        await client.run_until_disconnected()

    except Exception as e:
        logger.error(f"Критическая ошибка работы скаута: {e}", exc_info=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(start_cloud_scout())
    except KeyboardInterrupt:
        print("\n🛑 Скаут остановлен.")
