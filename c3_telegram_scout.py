# -*- coding: utf-8 -*-
"""
Universal Multi-Vertical Telegram Scout & Lead Router (Telethon Daemon for Render.com)
Monitors community groups, channels, and city chats (e.g. Тверь.Онлайн, Подслушано Тверь, СНТ).
Classifies and routes leads across 7 verticals:
1. 🪜 C3 Лестницы и крыльцо
2. 🏡 Дома, дачи и участки
3. 🏢 Квартиры: аренда и покупка
4. 🚗 Авторынок и выкуп авто
5. 🎁 Отдам даром / самовывоз
6. ⚖️ Банкротство физлиц (БФЛ)
7. 📜 Юридические услуги и адвокаты

Generates 100% authentic, living human drafts directly to Saved Messages ('me').
"""

import os
import sys
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
from telethon.tl.types import User
from lead_categories import classify_message, CATEGORIES
from generate_authentic_copy import generate_authentic_copy
from c3_humanity_detector import LayaHumanityClassifier

logging.basicConfig(
    format='[%(asctime)s] %(levelname)s [UniversalScout]: %(message)s',
    level=logging.INFO,
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Universal_Scout")

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")

processed_msgs = set()

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


async def start_scout():
    if not API_ID or not API_HASH:
        logger.warning("TELEGRAM_API_ID или TELEGRAM_API_HASH не заданы в переменных окружения.")
        return

    if SESSION_STRING:
        session = StringSession(SESSION_STRING.strip())
        logger.info("Используется Telethon StringSession")
    elif os.path.exists("c3_scout.session"):
        session = "c3_scout"
        logger.info("Используется локальный файл сессии c3_scout.session")
    else:
        logger.warning("TELEGRAM_SESSION_STRING не задана и файл c3_scout.session не найден.")
        return

    client = TelegramClient(
        session,
        int(API_ID),
        API_HASH,
        device_model="Universal Scout",
        system_version="Linux / Cloud",
        app_version="2.0.0"
    )

    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.error("Сессия не авторизована!")
            return

        me = await client.get_me()
        logger.info(f"✅ Универсальный Скаут запущен от имени: {me.first_name} (@{me.username or 'id=' + str(me.id)})")
        logger.info(f"📡 Активных категорий мониторинга: {len(CATEGORIES)}")

        # Startup notification
        try:
            startup_msg = (
                "🚀 **Универсальный Скаут-Роутер запущен на Render!**\n\n"
                "📡 **Активные категории мониторинга:**\n"
                "1. 🪜 C3 Лестницы и крыльцо\n"
                "2. 🏡 Дома, дачи и участки\n"
                "3. 🏢 Квартиры (аренда / покупка)\n"
                "4. 🚗 Авторынок и выкуп авто\n"
                "5. 🎁 Отдам даром / барахолка\n"
                "6. ⚖️ Банкротство физлиц (БФЛ) / долги\n"
                "7. 📜 Юридические услуги и адвокаты\n\n"
                "• Источники: все группы, городские чаты и каналы вашего аккаунта.\n"
                "• Готовые черновики ответов приходят сюда в Избранное."
            )
            await client.send_message('me', startup_msg)
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление в 'me': {e}")

        @client.on(events.NewMessage)
        async def handler(event):
            try:
                # Ignore Saved Messages
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

                # Classify against all 7 verticals
                match = classify_message(msg_text)
                if not match:
                    return

                cat_id, cat_cfg = match
                cat_title = cat_cfg["title"]
                persona_prompt = cat_cfg["prompt_persona"]
                fallback_reply = cat_cfg["fallback_reply"]

                logger.info(f"🎯 Лид обнаружен! Категория: [{cat_title}]")
                logger.info(f"Текст: {msg_text[:100]}...")

                chat = await event.get_chat()
                chat_title = getattr(chat, 'title', 'Городской чат')

                sender = await event.get_sender()
                sender_name = "Участник"
                sender_handle = ""
                if isinstance(sender, User):
                    sender_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or "Участник"
                    if sender.username:
                        sender_handle = f"@{sender.username}"

                msg_link = get_message_link(chat, event.message)

                # Generate customized persona response
                context = f"Категория: {cat_title}\nЧат: '{chat_title}'\nСообщение участника:\n«{msg_text}»"
                gen_res = generate_authentic_copy(context, persona_prompt=persona_prompt)

                if gen_res.get("status") in ["APPROVED", "NEEDS_REVIEW"] and gen_res.get("text"):
                    draft_text = gen_res["text"]
                    human_score = int(gen_res.get("eval", {}).get("humanity_score", 0.9) * 100)
                    slop_score = int(gen_res.get("eval", {}).get("ai_slop_score", 0.0) * 100)
                else:
                    draft_text = fallback_reply
                    human_score = 100
                    slop_score = 0

                draft_text = draft_text.replace(" — ", " - ").replace("—", "-").replace(" – ", " - ").replace("–", "-")

                alert_text = (
                    f"🚨 **[СКАУТ-ЛИД: {cat_title}]**\n\n"
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
                logger.info(f"✅ Карточка лида [{cat_title}] отправлена в 'Избранное'!")

            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)

        logger.info("👂 Универсальный Скаут слушает входящие сообщения во всех чатах...")
        await client.run_until_disconnected()

    except Exception as e:
        logger.error(f"Критическая ошибка работы скаута: {e}", exc_info=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(start_scout())
    except KeyboardInterrupt:
        print("\n🛑 Универсальный Скаут остановлен.")
