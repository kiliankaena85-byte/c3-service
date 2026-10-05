"""
C3.RU OFFICIAL TELEGRAM BOT: AI-ENGINEER & STAIR ESTIMATOR
Allows users to upload live photos of stairs directly from their smartphone.
Uses aiogram 3.x + LAYA (System 1) + Gemini 3.8 Flash (System 2) + Regional Logistics.
"""

import os
import sys
import io
import asyncio
import base64
import logging
from io import BytesIO

from dotenv import load_dotenv
load_dotenv()

# Fix Windows console UTF-8 output if needed
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardMarkup, 
    KeyboardButton
)

# Ensure C3 engine and logistics are imported
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from c3_engine import LayaStairClassifier, GeminiStairVisionEngine
from c3_logistics import C3RegionalLogistics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Initialize Dual-Model AI Engine
laya_classifier = LayaStairClassifier()
gemini_vision = GeminiStairVisionEngine()

dp = Dispatcher()

# Memory for user session context (e.g. last photo calculation, user region)
user_sessions = {}

def get_main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Рассчитать с доставкой в мой город", request_location=True)],
            [KeyboardButton(text="📸 Как правильно сфотографировать крыльцо?")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


async def safe_send_markdown(message: types.Message, text: str, reply_markup=None):
    try:
        return await message.reply(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as parse_err:
        logging.warning(f"Markdown send failed ({parse_err}), falling back to plain text...")
        clean = text.replace("**", "").replace("*", "").replace("_", "").replace("`", "")
        return await message.reply(clean, reply_markup=reply_markup)


@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    args = (command.args or "").strip().lower()
    
    if "chert" in args or "poberi" in args or "fall" in args:
        welcome_text = (
            "🤕 **Чёрт побери! Поскользнулись на скользкой плитке или хотите уберечь семью от травм?**\n\n"
            "Вы перешли по ссылке из нашего видеоролика! 🎬\n\n"
            "Монолитные накладки C3 из гранитно-кварцевого фибробетона (М1200) имеют рельефный противоскользящий рисунок «Волна» — на них невозможно поскользнуться даже при ледяном дожде!\n\n"
            "📸 **Сфотографируйте ваше крыльцо прямо сейчас** — искусственный интеллект завода за 5 секунд выявит скрытые дефекты и рассчитает безопасные ступени с заводской скидкой 10%!"
        )
    elif "crash" in args or "hammer" in args or "test" in args:
        welcome_text = (
            "🔨 **Убедились, почему обычная плитка колется в щепки, а C3 держит удар кувалды?**\n\n"
            "Марочная прочность фибробетона C3 — М1200 (прочнее гранита!). Срок службы — более 20 лет без сколов, трещин и отвалившихся подступенков.\n\n"
            "📸 **Отправьте фото вашей лестницы** — AI рассчитает монолитные ступени и точный вес для надежного монтажа!"
        )
    elif "ivan" in args or "tsar" in args:
        welcome_text = (
            "👑 **Лепота! Царское крыльцо без единого шва!**\n\n"
            "Запатентованная технология C3: монолитная проступь и подступенок объединены в единую деталь. Вода не затекает в стык, лёд не разрушает ступени.\n\n"
            "📸 **Пришлите фото крыльца сюда в чат** — моментально рассчитаем царскую смету по заводским ценам!"
        )
    elif "reels" in args or "shorts" in args or "tiktok" in args:
        welcome_text = (
            "🔥 **Приветствуем зрителей нашего видеоканала!**\n\n"
            "За вами закреплена **заводская скидка 10%** на монолитные накладки C3 и приоритетный расчет сметы.\n\n"
            "📸 **Сфотографируйте ваше крыльцо или лестницу** — AI завода C3 определит параметры и пришлет точный расчет за 5 секунд!"
        )
    else:
        welcome_text = (
            "👋 **Добро пожаловать в AI-сервис завода C3.RU!**\n"
            "(Инновационные монолитные ступени из фибробетона, патент РФ №144965U1)\n\n"
            "📸 **Отправьте мне фотографию вашего крыльца или лестницы прямо со смартфона.**\n\n"
            "Наш искусственный интеллект за 5 секунд:\n"
            "1️⃣ Сосчитает точное количество ступеней и выявит скрытые дефекты\n"
            "2️⃣ Подберет монолитные накладки C3 без разрушающихся швов\n"
            "3️⃣ Рассчитает предварительную смету с заводской гарантией 20+ лет\n"
            "4️⃣ Определит ваш регион, расстояние от завода в Твери и стоимость доставки\n\n"
            "👉 *Просто пришлите фото крыльца сюда в чат или нажмите кнопку геопозиции ниже для расчета доставки!*"
        )

    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Сайт завода c3.ru", url="https://c3.ru")],
        [InlineKeyboardButton(text="📞 Связаться с инженером", url="https://t.me/c3_support_bot")]
    ])
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_reply_keyboard())
    await message.answer("🔗 Официальные ресурсы C3:", reply_markup=inline_kb)


@dp.message(F.text == "📸 Как правильно сфотографировать крыльцо?")
async def handle_photo_tips(message: types.Message):
    tips = (
        "📷 **Как сделать фото для идеального AI-расчета:**\n\n"
        "1. **Ракурс:** Встаньте прямо перед крыльцом на расстоянии 3–4 метров, чтобы были видны все ступени от нижней до входной двери.\n"
        "2. **Освещение:** Лучше всего снимать в дневное время без резких теней.\n"
        "3. **Детали:** Если есть проблемные места (отвалилась плитка, трещины в бетоне) — их тоже можно сфотографировать вторым кадром.\n\n"
        "👉 *Отправьте фото, и за 5 секунд вы получите полный расчет с чертежом!*"
    )
    await message.answer(tips, parse_mode="Markdown")


@dp.message(F.location)
async def handle_user_location(message: types.Message):
    """Processes user location shared via native Telegram button"""
    lat = message.location.latitude
    lon = message.location.longitude
    user_id = message.from_user.id
    
    log_info = C3RegionalLogistics.resolve_by_coordinates(lat, lon)
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    user_sessions[user_id]["logistics"] = log_info

    log_text = C3RegionalLogistics.format_logistics_message(log_info)
    
    reply = (
        f"📍 **Ваша геолокация определена!**\n\n"
        f"{log_text}\n\n"
        f"📸 **Теперь пришлите фото вашей лестницы или крыльца**, и AI-инженер рассчитает точную смету материалов с учетом доставки прямо до вашего объекта!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Заказать бесплатный замер на объект", callback_data="order_measure")],
        [InlineKeyboardButton(text="💬 Написать инженеру завода", url="https://t.me/c3_support_bot")]
    ])
    await message.answer(reply, parse_mode="Markdown", reply_markup=kb)


@dp.message(F.photo)
async def handle_stair_photo(message: types.Message, bot: Bot):
    status_msg = await message.answer("⏳ *Сканирую фото: LAYA анализирует объект...*", parse_mode="Markdown")
    user_id = message.from_user.id
    
    try:
        # 1. Download photo from Telegram
        photo = message.photo[-1]
        file_io = BytesIO()
        await bot.download(photo, destination=file_io)
        file_bytes = file_io.getvalue()
        b64_image = base64.b64encode(file_bytes).decode("utf-8")

        # 2. Run LAYA System 1 Decision Triage
        caption = message.caption or ""
        author = message.from_user.full_name or "Пользователь"
        
        triage = laya_classifier.triage_request({
            "image_base64": b64_image,
            "text": caption
        })
        laya_decision = triage["laya_decision"]
        laya_lat = triage["latency_ms"]

        # If spam or non-stair photo
        if laya_decision["is_spam"] or not laya_decision["is_stair_inquiry"]:
            await status_msg.edit_text(
                "⚠️ **Система LAYA определила, что на фото нет уличной лестницы.**\n\n"
                "Пожалуйста, сделайте фото входной группы или ступеней вашего дома/магазина и отправьте снова!",
                parse_mode="Markdown"
            )
            return

        # 3. Run Multimodal Reasoning & Geometry Detection
        await status_msg.edit_text(
            f"⚡ *LAYA классифицировала объект за {laya_lat} ms!*\n"
            f"🔍 *Компьютерное зрение рассчитывает геометрию ступеней и смету C3...*",
            parse_mode="Markdown"
        )

        calculation = gemini_vision.process_stair_inquiry({
            "image_base64": b64_image,
            "text": caption,
            "author": author
        }, triage)

        stairs = calculation["detected_stairs"]
        sol = calculation["engineering_solution"]
        gemini_lat = calculation["gemini_latency_ms"]

        # Check regional logistics (from user session or caption)
        session = user_sessions.get(user_id, {})
        log_info = session.get("logistics")
        if not log_info and caption:
            log_info = C3RegionalLogistics.resolve_by_text(caption)
            if log_info:
                session["logistics"] = log_info
                user_sessions[user_id] = session

        # Save calculation to session
        session["last_calc"] = calculation
        user_sessions[user_id] = session

        # Format Response Message
        logistics_section = ""
        if log_info:
            logistics_section = (
                f"\n🚚 **Доставка и сервис ({log_info['city']}):**\n"
                f"• Расстояние от завода (г. {log_info['factory_city']}): ~{log_info['distance_from_factory_km']} км\n"
                f"• Доставка: ~{log_info['delivery_cost_rub']:,} руб. ({log_info['delivery_days']})\n"
                f"• Монтаж: {log_info['brigades_count']}\n"
            ).replace(",", " ")

        found_eval = stairs.get("foundation_assessment", {})
        allow_direct = found_eval.get("allow_direct_c3", True)

        if not allow_direct:
            warnings_str = "\n".join([f"⚠️ {str(w).replace('_', ' ')}" for w in found_eval.get("warnings", [])])
            reply_text = (
                f"🚨 **ВНИМАНИЕ: ОБНАРУЖЕНЫ КРИТИЧЕСКИЕ ДЕФЕКТЫ ОСНОВАНИЯ**\n"
                f"⏱ *Экспресс-диагностика: Laya {laya_lat} ms + Vision {gemini_lat} ms*\n\n"
                f"📊 **Техническое заключение:**\n"
                f"• Ступеней: **{stairs['steps_count']} шт.** (ширина ~{stairs['width_m']} м)\n"
                f"• Тип конструкции: {stairs['foundation']}\n"
                f"• Состояние основания: **{found_eval.get('status', 'Аварийное')}** (Надежность: {found_eval.get('health_score', 25)}%)\n\n"
                f"🛑 **Выявленные дефекты:**\n"
                f"{warnings_str}\n\n"
                f"⛔ **ПРЯМОЙ МОНТАЖ НАКЛАДОК C3 ЗАПРЕЩЕН РЕГЛАМЕНТОМ ЗАВОДА.**\n"
                f"Основание потеряло несущую способность или имеет подвижность. Если наклеить монолитный фибробетон C3 на такую основу, "
                f"накладки оторвутся или треснут вместе со ступенями при первых морозах.\n\n"
                f"🛠 **Заводское решение ООО «ИННОФОРМА» (c3.ru):**\n"
                f"1️⃣ **Модульный регулируемый металлокаркас C3** на винтовых сваях или регулируемых опорах. "
                f"Монтируется за 1 рабочий день без мокрых работ и усадки бетона. На него сразу устанавливаются накладки C3 с гарантией 20 лет!\n"
                f"2️⃣ **Капитальный демонтаж и бетонирование новой подушки** силами аккредитованной бригады C3.\n"
                f"{logistics_section}\n"
                f"👨‍💼 *Рекомендуем заказать бесплатный инструментальный выезд инженера со склерометром для проверки прочности бетона.*"
            )
            buttons = [
                [InlineKeyboardButton(text="🏗 Рассчитать металлокаркас C3", callback_data="order_metal_frame")],
                [InlineKeyboardButton(text="👷 Заказать экспертизу основания", callback_data="order_measure")],
                [InlineKeyboardButton(text="💬 Консультация главного инженера", url="https://t.me/c3_support_bot")]
            ]
        else:
            rec_act = str(found_eval.get('recommended_action', '')).replace('_', ' ')
            prep_note = f"\n⚠️ **Подготовка:** {rec_act}\n" if found_eval.get("status") == "NEEDS_PREPARATION" else ""
            defect_str = str(stairs['defects'][0]).replace('_', ' ') if stairs.get('defects') else "Естественный износ"
            
            levels_str = f"• Уровней подъема: **{stairs.get('levels_count', 2)}** (ширина марша ~{stairs['width_m']} м)\n" if stairs.get('levels_count') else f"• Ступеней: **{stairs['steps_count']} шт.** (ширина ~{stairs['width_m']} м)\n"
            layout_str = f"\n📐 **Инженерный раскрой завода C3:**\n• {str(stairs.get('step_layout_explanation', '')).replace('_', ' ')}\n" if stairs.get('step_layout_explanation') else ""
            slabs_str = f"• {str(stairs.get('slabs_explanation', '')).replace('_', ' ')}\n" if stairs.get('slabs_explanation') else ""

            reply_text = (
                f"✅ **ИНЖЕНЕРНЫЙ РАСЧЕТ ВХОДНОЙ ГРУППЫ C3.RU**\n"
                f"⏱ *Скорость анализа: Laya {laya_lat} ms + Vision {gemini_lat} ms*\n\n"
                f"📊 **Диагностика геометрии:**\n"
                f"{levels_str}"
                f"• Всего накладок C3 (1210 мм): **{stairs['steps_count']} шт.**\n"
                f"• Доборные плиты покрытия: **{stairs['landing_sqm']} м²**\n"
                f"• Основание: {stairs['foundation']}\n"
                f"• Дефект: {defect_str}\n"
                f"{layout_str}"
                f"{slabs_str}"
                f"{prep_note}\n"
                f"🛠 **Рекомендуемый заводской комплект C3:**\n"
                f"• Монолитные Г-образные накладки М1200 / F500 (без шва на ребре)\n"
                f"• Противоскользящий рельеф R13 (не скользит в мороз и дождь)\n"
                f"• Фирменный безусадочный клей + шовный герметик + гидрофобизатор\n\n"
                f"💰 **Предварительная смета материалов:**\n"
                f"👉 **{sol['total_retail_price_rub']:,} руб.**\n"
                f"{logistics_section}\n"
                f"🛡 **Экономия за 10 лет (TCO):**\n"
                f"Обычная плитка перекладывается 3 раза за 10 лет. Накладки C3 служат более 20 лет без ремонта.\n"
                f"Ваша чистая выгода: **+{sol['tco_savings_10yr_rub']:,} руб.**\n\n"
                f"За вами зафиксирована заводская гарантия 20 лет!"
            ).replace(",", " ")

            buttons = [
                [InlineKeyboardButton(text="📞 Заказать бесплатный замер", callback_data="order_measure")],
                [InlineKeyboardButton(text="📄 Скачать чертежи и каталог C3", url="https://c3.ru/catalog/")],
                [InlineKeyboardButton(text="💬 Написать инженеру завода", url="https://t.me/c3_support_bot")]
            ]
            if not log_info:
                buttons.insert(0, [InlineKeyboardButton(text="📍 Рассчитать с доставкой в мой город", callback_data="ask_location")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        try:
            await status_msg.delete()
        except Exception:
            pass

        await safe_send_markdown(message, reply_text, reply_markup=keyboard)

    except Exception as e:
        logging.error(f"Error handling photo: {e}", exc_info=True)
        try:
            await status_msg.delete()
        except Exception:
            pass
        await message.reply(f"❌ Извините, не удалось сформировать смету: {e}\nПожалуйста, отправьте фото еще раз или напишите параметры текстом.")


@dp.callback_query(F.data == "ask_location")
async def cb_ask_location(callback: types.CallbackQuery):
    await callback.message.answer(
        "📍 **Как рассчитать доставку до вашего объекта:**\n\n"
        "1. Нажмите большую кнопку внизу экрана: **«📍 Рассчитать с доставкой в мой город»** — Telegram передаст геопозицию, и бот рассчитает километраж от завода в Твери.\n"
        "2. Или просто напишите в чат название вашего города (например: *Москва*, *Клин*, *СПб*, *Казань*, *Воронеж*).",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(F.data == "order_measure")
async def cb_order_measure(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = user_sessions.get(user_id, {})
    log_info = session.get("logistics")
    
    city_str = f"в г. {log_info['city']}" if log_info else "в вашем регионе"
    await callback.message.answer(
        f"📝 **Заявка на контрольный замер принята!**\n\n"
        f"Наш сертифицированный представитель {city_str} свяжется с вами в течение 10 минут, "
        f"чтобы согласовать удобное время и привезти образцы фактур (Габбро-диабаз, Гранит, Волна) прямо на ваш объект.",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(F.data == "order_metal_frame")
async def cb_order_metal_frame(callback: types.CallbackQuery):
    await callback.message.answer(
        "🏗 **Заявка на расчет металлокаркаса C3 принята!**\n\n"
        "Конструкторский отдел завода C3 подготовит 3D-чертеж стального каркаса под размеры вашего проема. "
        "Каркас изготавливается на заводе в Твери из толстостенного профиля с антикоррозийным цинковым грунтом "
        "и монтируется на объекте за 1 день без мокрого бетона.",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(F.text)
async def handle_text_question(message: types.Message):
    text = message.text.strip()
    user_id = message.from_user.id
    
    # Check if user mentioned a city / region
    log_info = C3RegionalLogistics.resolve_by_text(text)
    if log_info:
        if user_id not in user_sessions:
            user_sessions[user_id] = {}
        user_sessions[user_id]["logistics"] = log_info
        
        log_text = C3RegionalLogistics.format_logistics_message(log_info)
        reply = (
            f"✅ **Определен регион поставки: {log_info['city']}**\n\n"
            f"{log_text}\n\n"
            f"📸 **Пришлите фото вашего крыльца или лестницы**, и мы сразу сосчитаем ступени и сформируем полную спецификацию с учетом доставки!"
        )
        await message.answer(reply, parse_mode="Markdown")
        return

    # Check if user describes an unfit foundation / structural hazard
    from c3_engine import C3FoundationInspector
    found_check = C3FoundationInspector.inspect([text], foundation_type=text)
    if not found_check["allow_direct_c3"]:
        warnings_str = "\n".join([f"⚠️ _{w}_" for w in found_check["warnings"]])
        reply = (
            f"🚨 **Инженерное предупреждение завода C3:**\n\n"
            f"{warnings_str}\n\n"
            f"⛔ **Прямой монтаж накладок C3 на такое основание запрещен регламентом завода.**\n"
            f"Монолитный фибробетон C3 (М1200) требует жесткого стабильного основания. На подвижном или треснувшем основании накладки лопнут по швам.\n\n"
            f"🛠 **Заводское решение ООО «ИННОФОРМА» (c3.ru):**\n"
            f"Мы изготавливаем **готовый модульный металлокаркас C3** на регулируемых опорах или винтовых сваях. "
            f"Он монтируется за 1 рабочий день без грязи и усадки бетона, а на него идеально ложатся ступени C3 с заводской гарантией 20 лет!\n\n"
            f"📸 *Пришлите фото вашего объекта для точного подбора конструкции:*"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏗 Рассчитать металлокаркас C3", callback_data="order_metal_frame")],
            [InlineKeyboardButton(text="💬 Написать главному инженеру", url="https://t.me/c3_support_bot")]
        ])
        await message.answer(reply, parse_mode="Markdown", reply_markup=kb)
        return

    # LAYA Triage for text intent
    triage = laya_classifier.triage_request({"text": text})
    if triage["laya_decision"]["is_spam"]:
        return

    await message.answer(
        "📸 **Пожалуйста, пришлите фотографию вашей лестницы или крыльца!**\n\n"
        "AI-замерщик сразу сосчитает ступени и подготовит точную раскладку монолитных накладок C3.\n"
        "Вы также можете нажать кнопку внизу для расчета доставки в ваш город.",
        parse_mode="Markdown",
        reply_markup=get_main_reply_keyboard()
    )


async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token and len(sys.argv) > 1:
        token = sys.argv[1]
        
    if not token:
        print("\n" + "=" * 70)
        print("  [!] TELEGRAM BOT TOKEN НЕ УКАЗАН")
        print("=" * 70)
        print("Чтобы запустить бота:")
        print("1. Получите токен у @BotFather в Telegram")
        print("2. Запустите: python c3_telegram_bot.py <ВАШ_ТОКЕН>")
        print("   или укажите TELEGRAM_BOT_TOKEN в файле .env")
        print("=" * 70 + "\n")
        return

    bot = Bot(token=token)
    print(f"[*] Удаляем старые вебхуки...")
    await bot.delete_webhook(drop_pending_updates=True)
    print(f"[*] Telegram-бот завода C3.RU успешно запущен!")
    print(f"[*] Логистический модуль и геопозиционирование активированы.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
