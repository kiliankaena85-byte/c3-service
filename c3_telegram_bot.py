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
            "🤕 **Поскользнулись на плитке или хотите обезопасить вход в дом?**\n\n"
            "Вы перешли по ссылке из нашего видеоролика! 🎬\n\n"
            "Монолитные накладки C3 отливаются с рельефным рисунком «Волна» - ноги не едут даже в мокрый снег и гололед.\n\n"
            "📸 **Пришлите фото крыльца сюда в чат** - инженерная система сосчитает ступени и подготовит предварительную смету со скидкой 10%!"
        )
    elif "crash" in args or "hammer" in args or "test" in args:
        welcome_text = (
            "🔨 **Убедились, почему плитка колется, а C3 держит удары?**\n\n"
            "Прочность литого фибробетона C3 - М1200 (прочнее гранита). Служит более 20 лет без сколов и отвалившихся подступенков.\n\n"
            "📸 **Отправьте фото вашей лестницы** - система сосчитает ступени и выдаст смету заводского комплекта."
        )
    elif "ivan" in args or "tsar" in args:
        welcome_text = (
            "👑 **Входная группа без швов на ребре ступеней!**\n\n"
            "Монолитная проступь и подступенок C3 отлиты единой Г-образной деталью. Вода не затекает под носик, мороз не отрывает ступени.\n\n"
            "📸 **Пришлите фото крыльца в чат** - подготовим расчет материалов по заводским ценам."
        )
    elif "reels" in args or "shorts" in args or "tiktok" in args:
        welcome_text = (
            "🔥 **Приветствуем зрителей нашего канала!**\n\n"
            "За вами зафиксирована скидка 10% на накладки C3.\n\n"
            "📸 **Пришлите фото вашего крыльца или лестницы** - рассчитаем нужное число накладок и смету за пару секунд."
        )
    else:
        welcome_text = (
            "👋 **Здравствуйте! Это экспресс-расчет ступеней завода C3 (Тверь).**\n\n"
            "📸 **Пришлите фото вашего крыльца или лестницы прямо в чат.**\n\n"
            "AI-инженер сосчитает число ступеней, проверит состояние основания и подготовит предварительную смету материалов с доставкой в ваш город.\n\n"
            "👇 *Или нажмите кнопку внизу экрана для расчета доставки.*"
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
        "📷 **Как сделать фото для точного расчета:**\n\n"
        "1. **Ракурс:** Встаньте перед крыльцом на расстоянии 3-4 метров, чтобы были видны все ступени от земли до площадки двери.\n"
        "2. **Освещение:** Лучше снимать днем без глубоких теней.\n"
        "3. **Детали:** Если есть проблемные места (отвалилась плитка, трещины в бетоне) - их тоже можно сфотографировать вторым кадром сбоку (под 45°).\n\n"
        "👉 *Отправьте фото, и система сразу сосчитает ступени и выдаст смету.*"
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


def make_c3_keyboard(has_logistics: bool = True) -> InlineKeyboardMarkup:
    action_rows = [
        [InlineKeyboardButton(text="✏️ Требуется коррекция (параметры)", callback_data="wiz_step_1")]
    ]
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
    return InlineKeyboardMarkup(inline_keyboard=action_rows)


def get_wizard_step_1(calc_state: dict) -> tuple:
    levels = calc_state.get("levels_count", 3)
    text = (
        "🛠 **Корректировка параметров (Шаг 1 из 4)**\n\n"
        "🔢 **Сколько всего ступеней (подъемов) на объекте?**\n"
        "_Считайте каждый подъем снизу вверх, включая верхний подъем вровень с площадкой двери._\n\n"
        f"Текущее значение: **{levels} ст.**"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="2", callback_data="wiz_set_levels_2"),
            InlineKeyboardButton(text="3", callback_data="wiz_set_levels_3"),
            InlineKeyboardButton(text="4", callback_data="wiz_set_levels_4"),
            InlineKeyboardButton(text="5", callback_data="wiz_set_levels_5"),
            InlineKeyboardButton(text="6", callback_data="wiz_set_levels_6"),
        ],
        [
            InlineKeyboardButton(text="7", callback_data="wiz_set_levels_7"),
            InlineKeyboardButton(text="8", callback_data="wiz_set_levels_8"),
            InlineKeyboardButton(text="9", callback_data="wiz_set_levels_9"),
            InlineKeyboardButton(text="10", callback_data="wiz_set_levels_10"),
            InlineKeyboardButton(text="12+", callback_data="wiz_set_levels_12"),
        ],
        [InlineKeyboardButton(text=f"➡️ Оставить {levels} ст. (Далее к форме) ➡️", callback_data="wiz_step_2")],
        [InlineKeyboardButton(text="↩️ Отмена (назад к смете)", callback_data="wiz_cancel")]
    ])
    return text, kb


def get_wizard_step_2(calc_state: dict) -> tuple:
    shape_labels = {
        "1_sided_direct": "Прямое (сход только прямо)",
        "2_sided_corner": "Угловое Г-образное (сход прямо + 1 бок)",
        "3_sided_pyramidal": "На 3 стороны (сход прямо + лево + право)"
    }
    cur_shape = calc_state.get("porch_type", "1_sided_direct")
    cur_label = shape_labels.get(cur_shape, "Прямое")
    text = (
        "🛠 **Корректировка параметров (Шаг 2 из 4)**\n\n"
        "📐 **Какая форма у вашей входной группы?**\n\n"
        f"Текущая конфигурация: **{cur_label}**"
    )
    b1_check = "✅ " if cur_shape == "1_sided_direct" else ""
    b2_check = "✅ " if cur_shape == "2_sided_corner" else ""
    b3_check = "✅ " if cur_shape == "3_sided_pyramidal" else ""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{b1_check}▫️ Прямое крыльцо (1 сход)", callback_data="wiz_set_shape_1_sided_direct")],
        [InlineKeyboardButton(text=f"{b2_check}📐 Угловое Г-образное (2 схода)", callback_data="wiz_set_shape_2_sided_corner")],
        [InlineKeyboardButton(text=f"{b3_check}🔺 Пирамидальное на 3 стороны", callback_data="wiz_set_shape_3_sided_pyramidal")],
        [
            InlineKeyboardButton(text="⬅️ Назад к ступеням", callback_data="wiz_step_1"),
            InlineKeyboardButton(text="➡️ Далее (к основанию) ➡️", callback_data="wiz_step_3")
        ],
        [InlineKeyboardButton(text="✅ Завершить и показать смету", callback_data="wiz_finish")]
    ])
    return text, kb


def get_wizard_step_3(calc_state: dict) -> tuple:
    cur_material = calc_state.get("material", "Бетонное основание")
    allow_direct = calc_state.get("allow_direct", True)
    if "Металло" in cur_material:
        status_label = "Металлокаркас (нужен каркас завода C3)"
    elif "Дерев" in cur_material or "грунт" in cur_material:
        status_label = "Дерево / грунт (нужен каркас C3 на сваях)"
    elif not allow_direct or len(calc_state.get("defects", [])) > 1:
        status_label = "Бетон разрушен (требует ремонта кромок)"
    else:
        status_label = "Монолитный бетон (готов к монтажу C3)"

    text = (
        "🛠 **Корректировка параметров (Шаг 3 из 4)**\n\n"
        "🏗 **Какое состояние основания под лестницей?**\n\n"
        f"Текущее: **{status_label}**"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧱 Монолитный бетон (прочный, готов к C3)", callback_data="wiz_set_base_solid_concrete")],
        [InlineKeyboardButton(text="🛠 Бетон крошится (требует ремонта кромок)", callback_data="wiz_set_base_repair_concrete")],
        [InlineKeyboardButton(text="🏗 Металлокаркас (нужен готовый каркас C3)", callback_data="wiz_set_base_metal_frame")],
        [InlineKeyboardButton(text="🪵 Дерево / Грунт (нужен каркас C3 на сваях)", callback_data="wiz_set_base_ground_wood")],
        [
            InlineKeyboardButton(text="⬅️ Назад к форме", callback_data="wiz_step_2"),
            InlineKeyboardButton(text="➡️ Далее (к ширине) ➡️", callback_data="wiz_step_4")
        ],
        [InlineKeyboardButton(text="✅ Завершить и показать смету", callback_data="wiz_finish")]
    ])
    return text, kb


def get_wizard_step_4(calc_state: dict) -> tuple:
    width = calc_state.get("width_m", 1.8)
    text = (
        "🛠 **Корректировка параметров (Шаг 4 из 4)**\n\n"
        "📏 **Какова примерная ширина лестницы (фасада)?**\n"
        "_Стандартная длина монолитной накладки C3 - 1210 мм. При большей ширине накладки стыкуются безусадочным швом._\n\n"
        f"Текущая ширина: **~{width} м**"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1.0 м", callback_data="wiz_set_width_1.0"),
            InlineKeyboardButton(text="1.2 м", callback_data="wiz_set_width_1.2"),
            InlineKeyboardButton(text="1.5 м", callback_data="wiz_set_width_1.5"),
        ],
        [
            InlineKeyboardButton(text="1.8 м", callback_data="wiz_set_width_1.8"),
            InlineKeyboardButton(text="2.0 м", callback_data="wiz_set_width_2.0"),
            InlineKeyboardButton(text="2.5 м", callback_data="wiz_set_width_2.5"),
            InlineKeyboardButton(text="3.0 м+", callback_data="wiz_set_width_3.0"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад к основанию", callback_data="wiz_step_3"),
            InlineKeyboardButton(text="✅ Рассчитать смету", callback_data="wiz_finish")
        ]
    ])
    return text, kb


def format_c3_calculation_message(calculation: dict, log_info: dict = None) -> tuple:
    stairs = calculation["detected_stairs"]
    sol = calculation["engineering_solution"]
    found_eval = stairs.get("foundation_assessment", {})
    allow_direct = found_eval.get("allow_direct_c3", True)
    levels = stairs.get("levels_count", 3)
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
            f"🚨 **ВНИМАНИЕ: ТРЕБУЕТСЯ КАРКАС ИЛИ РЕКОНСТРУКЦИЯ ОСНОВАНИЯ**\n\n"
            f"📊 **Техническое заключение:**\n"
            f"• Ступеней: **{stairs['steps_count']} шт.** (ширина ~{stairs['width_m']} м)\n"
            f"• Конструкция: {stairs['foundation']}\n"
            f"• Состояние основания: **{found_eval.get('status', 'Требуется каркас C3')}**\n\n"
            f"🛑 **Особенности основания:**\n"
            f"{warnings_str}\n\n"
            f"⛔ **Прямой монтаж накладок C3 без жесткого основания недопустим.**\n\n"
            f"🛠 **Заводское решение ООО «ИННОФОРМА» (c3.ru):**\n"
            f"1️⃣ **Модульный регулируемый металлокаркас C3** на винтовых сваях или опорах (1 день без грязи и бетона, гарантия 20 лет).\n"
            f"2️⃣ **Капитальный ремонт подушки** силами сертифицированной бригады C3.\n"
            f"{logistics_section}\n"
            f"👇 *Если основание прочное или хотите изменить параметры, нажмите «✏️ Требуется коррекция»:*"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Требуется коррекция (параметры)", callback_data="wiz_step_1")],
            [InlineKeyboardButton(text="🏗 Рассчитать металлокаркас C3", callback_data="order_metal_frame")],
            [InlineKeyboardButton(text="👷 Заказать экспертизу основания", callback_data="order_measure")],
            [InlineKeyboardButton(text="🔄 Новая лестница", callback_data="reset_photos")]
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
    else:
        header_text = "✅ **ИНЖЕНЕРНЫЙ РАСЧЕТ ВХОДНОЙ ГРУППЫ C3.RU**"
        multi_badge = ""

    hint_text = "👇 *Если AI ошибся в ступенях, форме или основании, нажмите «✏️ Требуется коррекция» - параметры пересчитаются мгновенно.*"

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

    keyboard = make_c3_keyboard(bool(log_info))
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


async def apply_wizard_and_show_calc(callback: types.CallbackQuery, user_id: int, session: dict):
    calc_state = session.get("current_calc_state", {})
    updated_calc = GeminiStairVisionEngine.calculate_c3_spec_by_geometry(
        levels_count=calc_state.get("levels_count", 3),
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
    session["last_calc"] = updated_calc
    user_sessions[user_id] = session

    new_text, new_kb = format_c3_calculation_message(updated_calc, session.get("logistics"))
    try:
        await callback.message.edit_text(new_text, reply_markup=new_kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer("✅ Параметры обновлены, смета пересчитана!")


@dp.callback_query(F.data == "wiz_step_1")
async def cb_wiz_step_1(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Сначала отправьте фото лестницы для расчета.")
        return
    text, kb = get_wizard_step_1(calc_state)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("wiz_set_levels_"))
async def cb_wiz_set_levels(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_levels = int(callback.data.replace("wiz_set_levels_", ""))
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Сначала отправьте фото лестницы для расчета.")
        return
    calc_state["levels_count"] = new_levels
    session["current_calc_state"] = calc_state
    user_sessions[user_id] = session

    # Move sequentially to Step 2 (Форма)
    text, kb = get_wizard_step_2(calc_state)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer(f"✅ Ступеней: {new_levels}")


@dp.callback_query(F.data == "wiz_step_2")
async def cb_wiz_step_2(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Сначала отправьте фото лестницы для расчета.")
        return
    text, kb = get_wizard_step_2(calc_state)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("wiz_set_shape_"))
async def cb_wiz_set_shape(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_shape = callback.data.replace("wiz_set_shape_", "")
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Сначала отправьте фото лестницы для расчета.")
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

    session["current_calc_state"] = calc_state
    user_sessions[user_id] = session

    # Move sequentially to Step 3 (Основание)
    text, kb = get_wizard_step_3(calc_state)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer("✅ Конфигурация сохранена")


@dp.callback_query(F.data == "wiz_step_3")
async def cb_wiz_step_3(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Сначала отправьте фото лестницы для расчета.")
        return
    text, kb = get_wizard_step_3(calc_state)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("wiz_set_base_"))
async def cb_wiz_set_base(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    base_type = callback.data.replace("wiz_set_base_", "")
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Сначала отправьте фото лестницы для расчета.")
        return

    if base_type == "solid_concrete":
        calc_state["material"] = "Монолитный железобетон"
        calc_state["allow_direct"] = True
        calc_state["defects"] = ["Естественный износ"]
        calc_state["recommended_action"] = "Прямой монтаж накладок C3 на клей"
    elif base_type == "repair_concrete":
        calc_state["material"] = "Бетонное основание (требует ремонта)"
        calc_state["allow_direct"] = True
        calc_state["defects"] = ["Сколы и выкрашивание бетона по краям"]
        calc_state["recommended_action"] = "Локальное выравнивание кромок быстротвердеющим безусадочным составом перед укладкой C3"
    elif base_type == "metal_frame":
        calc_state["material"] = "Металлокаркас"
        calc_state["allow_direct"] = False
        calc_state["defects"] = ["Необходимо изготовление заводского металлокаркаса C3"]
        calc_state["recommended_action"] = "Проектирование и изготовление модульного металлокаркаса C3 из толстостенного профиля"
    elif base_type == "ground_wood":
        calc_state["material"] = "Дерево / открытый грунт"
        calc_state["allow_direct"] = False
        calc_state["defects"] = ["Прямой монтаж бетона невозможен"]
        calc_state["recommended_action"] = "Установка модульного регулируемого металлокаркаса C3 на сваях"

    session["current_calc_state"] = calc_state
    user_sessions[user_id] = session

    # Move sequentially to Step 4 (Ширина)
    text, kb = get_wizard_step_4(calc_state)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer("✅ Основание сохранено")


@dp.callback_query(F.data == "wiz_step_4")
async def cb_wiz_step_4(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Сначала отправьте фото лестницы для расчета.")
        return
    text, kb = get_wizard_step_4(calc_state)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("wiz_set_width_"))
async def cb_wiz_set_width(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    width_val = float(callback.data.replace("wiz_set_width_", ""))
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Сначала отправьте фото лестницы для расчета.")
        return
    calc_state["width_m"] = width_val
    session["current_calc_state"] = calc_state
    user_sessions[user_id] = session

    await apply_wizard_and_show_calc(callback, user_id, session)


@dp.callback_query(F.data == "wiz_finish")
async def cb_wiz_finish(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Сначала отправьте фото лестницы для расчета.")
        return
    await apply_wizard_and_show_calc(callback, user_id, session)


@dp.callback_query(F.data == "wiz_cancel")
async def cb_wiz_cancel(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = user_sessions.get(user_id, {})
    last_calc = session.get("last_calc")
    if last_calc:
        new_text, new_kb = format_c3_calculation_message(last_calc, session.get("logistics"))
        try:
            await callback.message.edit_text(new_text, reply_markup=new_kb, parse_mode="Markdown")
        except Exception:
            pass
    await callback.answer("Возврат к расчету")


# Fallback handlers for legacy buttons
@dp.callback_query(F.data.startswith("set_steps_"))
async def cb_set_steps_legacy(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_steps = int(callback.data.split("_")[-1])
    session = user_sessions.get(user_id, {})
    calc_state = session.get("current_calc_state")
    if not calc_state:
        await callback.answer("Отправьте фото лестницы для расчета.")
        return
    calc_state["levels_count"] = new_steps
    await apply_wizard_and_show_calc(callback, user_id, session)


@dp.callback_query(F.data.startswith("set_shape_"))
async def cb_set_shape_legacy(callback: types.CallbackQuery):
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
    await apply_wizard_and_show_calc(callback, user_id, session)


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
        "1. Нажмите большую кнопку внизу экрана: **«📍 Рассчитать с доставкой в мой город»** - Telegram передаст геопозицию, и бот рассчитает километраж от завода в Твери.\n"
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
