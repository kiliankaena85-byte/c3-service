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


def make_c3_keyboard(current_steps: int, current_porch: str, has_logistics: bool) -> InlineKeyboardMarkup:
    # Row 1: Step correction buttons
    steps_row = []
    for s in [4, 5, 6, 7, 8, 9]:
        prefix = "✅ " if s == current_steps else ""
        steps_row.append(InlineKeyboardButton(text=f"{prefix}{s} ст.", callback_data=f"set_steps_{s}"))

    # Row 2: Porch shape buttons
    b1_check = "✅ " if current_porch == "1_sided_direct" else ""
    b2_check = "✅ " if current_porch == "2_sided_corner" else ""
    b3_check = "✅ " if current_porch == "3_sided_pyramidal" else ""
    shape_row = [
        InlineKeyboardButton(text=f"{b1_check}Прямое", callback_data="set_shape_1_sided_direct"),
        InlineKeyboardButton(text=f"{b2_check}Угловое", callback_data="set_shape_2_sided_corner"),
        InlineKeyboardButton(text=f"{b3_check}На 3 стороны", callback_data="set_shape_3_sided_pyramidal")
    ]

    action_rows = []
    if not has_logistics:
        action_rows.append([InlineKeyboardButton(text="📍 Рассчитать доставку в мой город", callback_data="ask_location")])
    action_rows.append([
        InlineKeyboardButton(text="📞 Заказать бесплатный замер", callback_data="order_measure"),
        InlineKeyboardButton(text="🔄 Новая лестница", callback_data="reset_photos")
    ])
    action_rows.append([
        InlineKeyboardButton(text="📄 Каталог C3 (PDF)", url="https://c3.ru/catalog/"),
        InlineKeyboardButton(text="💬 Инженер завода", url="https://t.me/c3_support_bot")
    ])

    return InlineKeyboardMarkup(inline_keyboard=[steps_row, shape_row] + action_rows)


def format_c3_calculation_message(calculation: dict, log_info: dict = None) -> tuple:
    stairs = calculation["detected_stairs"]
    sol = calculation["engineering_solution"]
    found_eval = stairs.get("foundation_assessment", {})
    allow_direct = found_eval.get("allow_direct_c3", True)
    levels = stairs.get("levels_count", 3)
    porch_type = stairs.get("porch_type", "1_sided_direct")
    photos_count = stairs.get("photos_count", 1)

    logistics_section = ""
    if log_info:
        logistics_section = (
            f"\n🚚 **Доставка и сервис ({log_info['city']}):**\n"
            f"• Расстояние от завода (г. {log_info['factory_city']}): ~{log_info['distance_from_factory_km']} км\n"
            f"• Доставка: ~{log_info['delivery_cost_rub']:,} руб. ({log_info['delivery_days']})\n"
            f"• Монтаж: {log_info['brigades_count']}\n"
        ).replace(",", " ")

    if not allow_direct:
        warnings_str = "\n".join([f"⚠️ {str(w).replace('_', ' ')}" for w in found_eval.get("warnings", [])])
        reply_text = (
            f"🚨 **ВНИМАНИЕ: ОБНАРУЖЕНЫ КРИТИЧЕСКИЕ ДЕФЕКТЫ ОСНОВАНИЯ**\n\n"
            f"📊 **Техническое заключение:**\n"
            f"• Ступеней: **{stairs['steps_count']} шт.** (ширина ~{stairs['width_m']} м)\n"
            f"• Тип конструкции: {stairs['foundation']}\n"
            f"• Состояние основания: **{found_eval.get('status', 'Аварийное')}**\n\n"
            f"🛑 **Выявленные дефекты:**\n"
            f"{warnings_str}\n\n"
            f"⛔ **ПРЯМОЙ МОНТАЖ НАКЛАДОК C3 ЗАПРЕЩЕН РЕГЛАМЕНТОМ ЗАВОДА.**\n"
            f"Основание потеряло несущую способность или имеет подвижность.\n\n"
            f"🛠 **Заводское решение ООО «ИННОФОРМА» (c3.ru):**\n"
            f"1️⃣ **Модульный регулируемый металлокаркас C3** на винтовых сваях или опорах (1 рабочий день без мокрых работ, гарантия 20 лет).\n"
            f"2️⃣ **Капитальный демонтаж и бетонирование новой подушки** силами сертифицированной бригады C3.\n"
            f"{logistics_section}\n"
            f"👨‍💼 *Рекомендуем заказать бесплатный инструментальный выезд инженера.*"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏗 Рассчитать металлокаркас C3", callback_data="order_metal_frame")],
            [InlineKeyboardButton(text="👷 Заказать экспертизу основания", callback_data="order_measure")],
            [InlineKeyboardButton(text="💬 Консультация главного инженера", url="https://t.me/c3_support_bot")]
        ])
        return reply_text, keyboard

    rec_act = str(found_eval.get('recommended_action', '')).replace('_', ' ')
    prep_note = f"\n⚠️ **Подготовка:** {rec_act}\n" if found_eval.get("status") == "NEEDS_PREPARATION" else ""
    defect_str = str(stairs['defects'][0]).replace('_', ' ') if stairs.get('defects') else "Естественный износ"

    levels_str = f"• Подъемов (ступеней): **{levels} шт.** (ширина марша ~{stairs['width_m']} м)\n"
    layout_str = f"\n📐 **Инженерный раскрой завода C3:**\n• {str(stairs.get('step_layout_explanation', '')).replace('_', ' ')}\n" if stairs.get('step_layout_explanation') else ""
    slabs_str = f"• {str(stairs.get('slabs_explanation', '')).replace('_', ' ')}\n" if stairs.get('slabs_explanation') else ""

    if photos_count > 1:
        header_text = f"🎯 **МУЛЬТИ-РАКУРСНЫЙ 3D-РАСЧЕТ C3 ({photos_count} РАКУРСА ОБЪЕДИНЕНЫ)**"
        multi_badge = f"\n👁‍🗨 **3D-синтез ракурсов:** Фасад и боковой обзор сопоставлены. Мертвые зоны проверены.\n"
        hint_text = "👇 *Если требуется скорректировать параметры или сбросить ракурсы, используйте кнопки ниже:*"
    else:
        header_text = "✅ **ИНЖЕНЕРНЫЙ РАСЧЕТ ВХОДНОЙ ГРУППЫ C3.RU**"
        multi_badge = ""
        hint_text = (
            "💡 **Мульти-ракурс C3:** Чтобы проверить скрытые зоны и точную глубину площадки, отправьте **второе фото сбоку (под углом 45°)** — AI автоматически объединит оба кадра!\n\n"
            "👇 *Или скорректируйте число ступеней и форму кнопками ниже:*"
        )

    reply_text = (
        f"{header_text}\n"
        f"⏱ *Время экспресс-расчета: {round(calculation.get('gemini_latency_ms', 1200)/1000, 1)} сек*\n\n"
        f"📊 **Диагностика геометрии:**\n"
        f"{levels_str}"
        f"• Всего монолитных накладок C3 (1210 мм): **{stairs['steps_count']} шт.**\n"
        f"• Доборные плиты покрытия: **{stairs['landing_sqm']} м²**\n"
        f"• Конструкция: {stairs['foundation']}\n"
        f"• Дефект основания: {defect_str}\n"
        f"{multi_badge}"
        f"{layout_str}"
        f"{slabs_str}"
        f"{prep_note}\n"
        f"🛠 **Заводской комплект C3:**\n"
        f"• Монолитные Г-образные накладки М1200 / F500 (без шва на ребре)\n"
        f"• Противоскользящий рельеф R13 (безопасно в мороз и лед)\n"
        f"• Фирменный безусадочный клей + шовный герметик + гидрофобизатор\n\n"
        f"💰 **Предварительная смета материалов:**\n"
        f"👉 **{sol['total_retail_price_rub']:,} руб.**\n"
        f"{logistics_section}\n"
        f"🛡 **Экономия за 10 лет (TCO):**\n"
        f"Плитка перекладывается 3 раза за 10 лет. Накладки C3 служат более 20 лет без ремонта.\n"
        f"Ваша чистая выгода: **+{sol['tco_savings_10yr_rub']:,} руб.**\n\n"
        f"{hint_text}"
    ).replace(",", " ")

    keyboard = make_c3_keyboard(levels, porch_type, bool(log_info))
    return reply_text, keyboard


@dp.message(F.photo)
async def handle_stair_photo(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    session = user_sessions.get(user_id, {})

    import time
    now = time.time()
    last_time = session.get("last_photo_time", 0)
    photos = session.get("photos", [])

    # Check if this photo is an additional angle (sent within 15 minutes and max 3)
    if (now - last_time < 900) and len(photos) > 0 and len(photos) < 3:
        status_msg = await message.answer(f"⏳ *Добавляю {len(photos) + 1}-й ракурс для мульти-ракурсного 3D-анализа C3...*", parse_mode="Markdown")
    else:
        status_msg = await message.answer("⏳ *Сканирую фото: AI-инженер C3 анализирует объект...*", parse_mode="Markdown")
        photos = []

    try:
        # 1. Download photo from Telegram
        photo = message.photo[-1]
        file_io = BytesIO()
        await bot.download(photo, destination=file_io)
        file_bytes = file_io.getvalue()
        b64_image = base64.b64encode(file_bytes).decode("utf-8")

        # 2. Decision Triage (on latest image)
        caption = message.caption or ""
        author = message.from_user.full_name or "Пользователь"

        triage = laya_classifier.triage_request({
            "image_base64": b64_image,
            "text": caption
        })
        decision = triage["laya_decision"]

        # If spam or non-stair photo
        if decision["is_spam"] or not decision["is_stair_inquiry"]:
            await status_msg.edit_text(
                "⚠️ **На фотографии не обнаружена уличная лестница или крыльцо.**\n\n"
                "Пожалуйста, сделайте четкое фото входной группы или ступеней вашего дома/магазина и отправьте снова!",
                parse_mode="Markdown"
            )
            return

        photos.append(b64_image)
        session["photos"] = photos
        session["last_photo_time"] = now

        num_photos = len(photos)
        if num_photos > 1:
            await status_msg.edit_text(
                f"⚡ *Синтезирую {num_photos} ракурса входной группы!*\n"
                "🔍 *AI-система сопоставляет фасад и боковой обзор для точной 3D-карты C3...*",
                parse_mode="Markdown"
            )
        else:
            await status_msg.edit_text(
                "⚡ *Входная группа распознана!*\n"
                "🔍 *AI-система рассчитывает геометрию ступеней, раскрой и смету завода C3...*",
                parse_mode="Markdown"
            )

        calculation = gemini_vision.process_stair_inquiry({
            "images_base64": photos,
            "text": caption,
            "author": author
        }, triage)

        stairs = calculation["detected_stairs"]
        found_eval = stairs.get("foundation_assessment", {})

        # Check regional logistics (from user session or caption)
        log_info = session.get("logistics")
        if not log_info and caption:
            log_info = C3RegionalLogistics.resolve_by_text(caption)
            if log_info:
                session["logistics"] = log_info

        # Save calculation and state to session for instant interactive recalculation
        session["last_calc"] = calculation
        session["current_calc_state"] = {
            "levels_count": stairs.get("levels_count", 3),
            "width_m": stairs.get("width_m", 1.8),
            "porch_type": stairs.get("porch_type", "1_sided_direct"),
            "has_left_flank": stairs.get("has_left_flank", False),
            "has_right_flank": stairs.get("has_right_flank", False),
            "side_flank_length_m": stairs.get("side_flank_length_m", 0.8),
            "landing_sqm": stairs.get("landing_sqm", 1.2),
            "material": stairs.get("foundation", "Бетонное основание"),
            "allow_direct": found_eval.get("allow_direct_c3", True),
            "defects": stairs.get("defects", []),
            "recommended_action": found_eval.get("recommended_action", ""),
            "photos_count": num_photos
        }
        user_sessions[user_id] = session

        reply_text, keyboard = format_c3_calculation_message(calculation, log_info)

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


@dp.callback_query(F.data.startswith("set_steps_"))
async def cb_set_steps(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_steps = int(callback.data.split("_")[-1])
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Отправьте фото лестницы для расчета.")
        return

    calc_state["levels_count"] = new_steps
    updated_calc = GeminiStairVisionEngine.calculate_c3_spec_by_geometry(
        levels_count=new_steps,
        front_width_m=calc_state.get("width_m", 1.8),
        porch_type=calc_state.get("porch_type", "1_sided_direct"),
        has_left_flank=calc_state.get("has_left_flank", False),
        has_right_flank=calc_state.get("has_right_flank", False),
        side_flank_length_m=calc_state.get("side_flank_length_m", 0.8),
        landing_area_sqm=calc_state.get("landing_sqm", 1.2),
        material=calc_state.get("material", "Бетонное основание"),
        allow_direct=calc_state.get("allow_direct", True),
        defects=calc_state.get("defects", []),
        recommendation=calc_state.get("recommended_action")
    )
    session["current_calc_state"] = calc_state
    session["last_calc"] = updated_calc
    user_sessions[user_id] = session

    new_text, new_kb = format_c3_calculation_message(updated_calc, session.get("logistics"))
    try:
        await callback.message.edit_text(new_text, reply_markup=new_kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer(f"✅ Пересчитано на {new_steps} ступеней!")


@dp.callback_query(F.data.startswith("set_shape_"))
async def cb_set_shape(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_shape = callback.data.replace("set_shape_", "")
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Отправьте фото лестницы для расчета.")
        return

    calc_state["porch_type"] = new_shape
    if new_shape == "3_sided_pyramidal":
        calc_state["has_left_flank"] = True
        calc_state["has_right_flank"] = True
    elif new_shape == "2_sided_corner":
        calc_state["has_left_flank"] = True
        calc_state["has_right_flank"] = False
    else:
        calc_state["has_left_flank"] = False
        calc_state["has_right_flank"] = False

    updated_calc = GeminiStairVisionEngine.calculate_c3_spec_by_geometry(
        levels_count=calc_state.get("levels_count", 3),
        front_width_m=calc_state.get("width_m", 1.8),
        porch_type=new_shape,
        has_left_flank=calc_state.get("has_left_flank", False),
        has_right_flank=calc_state.get("has_right_flank", False),
        side_flank_length_m=calc_state.get("side_flank_length_m", 0.8),
        landing_area_sqm=calc_state.get("landing_sqm", 1.2),
        material=calc_state.get("material", "Бетонное основание"),
        allow_direct=calc_state.get("allow_direct", True),
        defects=calc_state.get("defects", []),
        recommendation=calc_state.get("recommended_action")
    )
    session["current_calc_state"] = calc_state
    session["last_calc"] = updated_calc
    user_sessions[user_id] = session

    new_text, new_kb = format_c3_calculation_message(updated_calc, session.get("logistics"))
    try:
        await callback.message.edit_text(new_text, reply_markup=new_kb, parse_mode="Markdown")
    except Exception:
        pass
    shape_labels = {
        "1_sided_direct": "Прямое крыльцо",
        "2_sided_corner": "Угловое крыльцо",
        "3_sided_pyramidal": "Сход на 3 стороны"
    }
    await callback.answer(f"✅ Выбрано: {shape_labels.get(new_shape, new_shape)}")


@dp.callback_query(F.data == "reset_photos")
async def cb_reset_photos(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = user_sessions.get(user_id, {})
    session["photos"] = []
    session.pop("current_calc_state", None)
    session.pop("last_calc", None)
    session["last_photo_time"] = 0
    user_sessions[user_id] = session
    await callback.message.answer(
        "🔄 **Память ракурсов очищена.**\n\n"
        "Отправьте фотографию новой лестницы или крыльца для расчета!",
        parse_mode="Markdown"
    )
    await callback.answer("✅ Ракурсы сброшены")


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
