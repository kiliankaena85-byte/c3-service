# -*- coding: utf-8 -*-
"""
Universal Multi-Vertical Telegram Scout & Lead Router (Telethon Daemon)
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
from c3_supabase_sync import SupabaseSync
from laya_gatekeeper import LayaGatekeeper

logging.basicConfig(
    format='[%(asctime)s] %(levelname)s [UniversalScout]: %(message)s',
    level=logging.INFO,
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Universal_Scout")

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")

supabase_sync = SupabaseSync()
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
                "🚀 **Универсальный Скаут-Роутер запущен!**\n\n"
                "📡 **10 активных категорий мониторинга:**\n"
                "1. 🪜 C3 Лестницы и крыльцо\n"
                "2. 🏡 Дома, дачи и участки\n"
                "3. 🏢 Квартиры (аренда / покупка)\n"
                "4. 🚗 Авторынок и выкуп авто\n"
                "5. 🎁 Отдам даром / барахолка\n"
                "6. ⚖️ Банкротство физлиц (БФЛ) / долги\n"
                "7. 📜 Юридические услуги и адвокаты\n"
                "8. 📱 SMM, маркетинг и реклама\n"
                "9. 💼 Вакансии работодателей\n"
                "10. 📝 Анкеты соискателей / резюме\n\n"
                "⚡️ **База данных:** Supabase pgvector подключена (автообучение семантики включено).\n"
                "• Источники: все группы, городские чаты и каналы вашего аккаунта.\n"
                "• Обратная связь: отвечайте `+` или `-` на карточки лидов прямо в Избранном."
            )
            await client.send_message('me', startup_msg)
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление в 'me': {e}")

        @client.on(events.NewMessage)
        async def handler(event):
            try:
                # Handle interactive feedback in Saved Messages ('me')
                if event.chat_id == me.id:
                    if event.is_reply:
                        try:
                            reply_msg = await event.get_reply_message()
                            if reply_msg and reply_msg.text and "🚨 **[СКАУТ-ЛИД:" in reply_msg.text:
                                import re
                                m = re.search(r'🆔\s*\*\*ID:\*\*\s*`?([a-f0-9\-]+)`?', reply_msg.text)
                                lead_prefix = m.group(1) if m else None
                                user_cmd = (event.message.message or "").strip()
                                if lead_prefix:
                                    if user_cmd.startswith(("+", "ок", "Ок", "OK", "ok", "принят", "топ")):
                                        supabase_sync.record_feedback(lead_prefix, accepted=True)
                                        await event.reply(f"✅ Лид `{lead_prefix}` подтвержден! Рейтинг ключа повышен в Supabase.")
                                    elif user_cmd.startswith(("-", "спам", "Спам", "мусор", "мимо", "нет")):
                                        reason = user_cmd.lstrip("-").strip() or "Отклонено оператором"
                                        supabase_sync.record_feedback(lead_prefix, accepted=False, rejection_reason=reason)
                                        await event.reply(f"🛑 Лид `{lead_prefix}` отклонен ({reason}). Добавлены минус-токены в Supabase.")
                        except Exception as fe:
                            logger.error(f"Ошибка обработки обратной связи: {fe}")
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

                chat = await event.get_chat()
                chat_title = getattr(chat, 'title', 'Городской чат')
                chat_username = getattr(chat, 'username', '') or str(event.chat_id)

                # Record scanned channel activity
                try:
                    supabase_sync.update_channel_stats(chat_username, chat_title, scanned_inc=1)
                except Exception:
                    pass

                # Classify against all 10 verticals
                match = classify_message(msg_text)
                if not match:
                    return

                cat_id, cat_cfg = match
                cat_title = cat_cfg["title"]
                persona_prompt = cat_cfg["prompt_persona"]
                fallback_reply = cat_cfg["fallback_reply"]

                # LAYA Gatekeeper: Anti-Spam & True Customer Demand Triage
                gate_res = LayaGatekeeper.evaluate(msg_text, cat_id)
                if not gate_res["is_lead"]:
                    logger.info(f"🛡 [LAYA GATE] Отсеян мусорный/рекламный пост ({gate_res['intent']}): {gate_res['reason']}")
                    return

                logger.info(f"🎯 Настоящий лид обнаружен! Категория: [{cat_title}] | Инвент: {gate_res['intent']}")
                logger.info(f"Текст: {msg_text[:100]}...")

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

                # Save lead in Supabase
                lead_id = None
                try:
                    lead_id = supabase_sync.save_lead({
                        "source": "telegram",
                        "channel_title": chat_title,
                        "channel_username": chat_username,
                        "sender_name": sender_name,
                        "sender_username": sender_handle.lstrip("@"),
                        "raw_text": msg_text,
                        "category_id": cat_id,
                        "category_title": cat_title,
                        "match_type": f"laya_{gate_res['intent'].lower()}",
                        "confidence_score": gate_res.get("confidence", 0.95),
                        "generated_pitch": draft_text,
                        "humanity_score": round(human_score / 100.0, 2),
                        "status": "new",
                        "message_link": msg_link
                    })
                    supabase_sync.update_channel_stats(chat_username, chat_title, scanned_inc=0, leads_inc=1)
                except Exception as dbe:
                    logger.error(f"Ошибка сохранения лида в Supabase: {dbe}")

                lead_short_id = lead_id[:8] if lead_id else "local"

                alert_text = (
                    f"🚨 **[СКАУТ-ЛИД: {cat_title}]**\n"
                    f"🆔 **ID:** `{lead_short_id}`\n\n"
                    f"📍 **Чат:** {chat_title}\n"
                    f"👤 **Автор:** {sender_name} {sender_handle}\n"
                    f"💬 **Сообщение:**\n"
                    f"«_{msg_text}_»\n\n"
                    f"💡 **Черновик ответа (нажмите скопировать):**\n"
                    f"```{draft_text}```\n\n"
                    f"📊 **Аудит LAYA:** Человечность: `{human_score}%` | Тип: `{gate_res['intent']}`\n"
                    f"🔗 **Открыть сообщение:** [Перейти в чат]({msg_link})\n\n"
                    f"⚡️ *Ответьте на это сообщение для обратной связи:*\n"
                    f"• `+` или `ок` — принять лид (повышает вес ключа в Supabase)\n"
                    f"• `-` или `спам [причина]` — отклонить и обучить минус-слова"
                )

                await client.send_message('me', alert_text, link_preview=False)
                logger.info(f"✅ Карточка лида [{cat_title}] (ID: {lead_short_id}) отправлена в 'Избранное'!")

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
