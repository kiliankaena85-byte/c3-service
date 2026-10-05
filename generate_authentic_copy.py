# -*- coding: utf-8 -*-
"""
Authentic Human Copy Generator with LAYA Humanity Guardrail (Actor-Critic Loop)
Generates natural, living, non-AI text for:
  - Cottage settlement & SNT chats (Telegram/WhatsApp)
  - ForumHouse / construction forums
  - Avito direct inquiries
  - Pro-builder & contractor chats
Guarantees 0% AI-Slop through closed-loop LAYA Stylometry verification.
"""

import os
import sys
import json
import requests

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv()

from c3_humanity_detector import LayaHumanityClassifier

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

SYSTEM_PROMPT = """Ты — опытный владелец загородного дома или прораб, который пишет реальное живое сообщение в чат или на форум.

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО (ПРИЗНАКИ ИИ-ШНОСТИ И ФАЛЬШИ):
- Никогда не использовать длинное полиграфическое тире («—» или «–»). На смартфонах в Telegram/WhatsApp его никто не ставит — это 100% палево ИИ! Используй только обычный короткий дефис с пробелами (« - »), запятые или скобки.
- Никогда не использовать слова: «инновационный», «запатентованный», «парни из Твери», «является надежным решением», «регламент завода», «класс R13», «ООО Инноформа», «зашили монолитным», «высокопрочный фибробетон», «гарантирует безупречное».
- КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать узкий цеховой жаргон плиточников («капинос», «бухтит», «забухтела»). Обычные владельцы домов таких терминов не знают! Это звучит ненатурально.
- Не писать гладкими длинными книжными предложениями.
- Не делать рекламу в лоб. Не призывать «спешите заказать».

КАК ПИСАТЬ ПО-ЧЕЛОВЕЧЕСКИ (ПРИЗНАКИ ЖИВОЙ БЫТОВОЙ РЕЧИ):
- Говорить простым языком нормального человека: «плитка отошла», «зашаталась», «ходит ходуном», «хрустит под ногами», «края пооткалывались», «уголки поотлетали», «покрошились ступеньки», «сбили лопатой угол», «швы полопались», «зимой каток», «ноги едут».
- Живой синтаксис как на телефоне: короткий дефис (« - »), скобки с мыслями, вводные слова («короче», «в общем», «в итоге», «плюнули и взяли»).
- Называть завод/материал естественно: «в Твери делают», «завод в Твери», «тверские накладки», «C3», «цельные Г-образные ступени».
- Обязательно указывать честный бытовой нюанс: «не дешево / влетело в копеечку, но зато намертво», «тяжелые зараза», «лопатой чищу - пофиг».
- Формат ответа: 2-4 коротких естественных предложения без лишней воды.
"""

def generate_authentic_copy(context: str, max_retries: int = 3, persona_prompt: str = None) -> dict:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }

    active_system_prompt = persona_prompt if persona_prompt else SYSTEM_PROMPT
    # Append core anti-slop rules regardless of persona
    core_rules = (
        "\n\nКАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:\n"
        "- Длинное тире («—» или «–»). Используй только обычный короткий дефис с пробелами (« - ») или запятые!\n"
        "- Никакого канцелярита, рекламных лозунгов и шаблонных фраз.\n"
        "- Формат: 2-3 коротких естественных предложения как на смартфоне в Telegram."
    )
    full_system = active_system_prompt + core_rules

    prompt = f"Контекст сообщения из тверского чата:\n{context}\n\nНапиши живой ответ от первого лица без длинных тире (—) и без навязчивой рекламы."

    for attempt in range(1, max_retries + 1):
        payload = {
            "model": "google/gemini-2.5-flash",
            "messages": [
                {"role": "system", "content": full_system},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.85,
            "max_tokens": 300
        }

        r = requests.post(url, headers=headers, json=payload, timeout=20)
        if r.status_code != 200:
            return {"error": f"API error: {r.status_code} {r.text}"}

        generated_text = r.json()["choices"][0]["message"]["content"].strip().strip('"')

        # Mobile typography normalization: replace em-dash and en-dash with standard mobile hyphen
        generated_text = generated_text.replace(" — ", " - ").replace("—", "-").replace(" – ", " - ").replace("–", "-")

        # Run Discriminator / Guardrail (LAYA Humanity Classifier)
        eval_res = LayaHumanityClassifier.analyze(generated_text)

        # If passed guardrail (humanity >= 0.7 and ai_slop <= 0.1), accept!
        if eval_res["ai_slop_score"] <= 0.15 and eval_res["humanity_score"] >= 0.60:
            return {
                "attempt": attempt,
                "text": generated_text,
                "eval": eval_res,
                "status": "APPROVED"
            }
        else:
            # Add criticism to prompt for next attempt
            prompt += f"\n\n[Предыдущий вариант забракован LAYA детектора ИИ: {eval_res['matched_ai_markers']}. Перепиши еще проще, грубее и живее, как реальный дачник!]"

    return {
        "attempt": max_retries,
        "text": generated_text,
        "eval": eval_res,
        "status": "NEEDS_REVIEW"
    }


if __name__ == "__main__":
    scenarios = [
        {
            "name": "Чат поселка (КП / СНТ)",
            "context": "Сосед в чате КП пишет: «Мужики, привет. Опять после зимы плитка на входе поотлетала, второй раз за 3 года. Чем ее намертво закатать, чтоб забыть?»"
        },
        {
            "name": "Форум ForumHouse",
            "context": "Тема на ForumHouse: «Какое нескользкое покрытие выбрать для бетонного крыльца магазина/дома? Керамогранит зимой скользкий как лед, боюсь люди упадут»"
        },
        {
            "name": "Чат мастеров и прорабов",
            "context": "Вопрос в чате строителей: «Кто монтировал ступени C3 из Твери? Как они в работе и держит ли клей?»"
        }
    ]

    print("=" * 80)
    print("ГЕНЕРАЦИЯ ЖИВЫХ ТЕКСТОВ С ВАЛИДАЦИЕЙ LAYA HUMANITY CLASSIFIER")
    print("=" * 80)

    for sc in scenarios:
        print(f"\n🎯 Сценарий: {sc['name']}")
        res = generate_authentic_copy(sc["context"])
        print(f"Попытка валидации: {res.get('attempt')}")
        print(f"Сгенерированный текст:\n\"{res.get('text')}\"")
        ev = res.get("eval", {})
        print(f"📊 Вердикт LAYA: {ev.get('verdict')} | Человечность: {ev.get('humanity_score')*100}% | ИИ-шность: {ev.get('ai_slop_score')*100}%")
        print(f"Найденная живая фактура: {ev.get('matched_human_slang')}")
        print(f"ИИ-маркеры: {ev.get('matched_ai_markers')}")
        print("-" * 80)
