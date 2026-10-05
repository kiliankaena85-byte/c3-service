# -*- coding: utf-8 -*-
"""
C3 Humanity & AI-Detector Engine (Laya Stylometry Module)
Analyzes chat messages, forum posts, and outreach copies for:
  - Real human conversational authenticity (Humanity Score)
  - Artificial intelligence slop & corporate cliché detection (AI-Slop Score)
  - Ground-truth stair terminology vs fake marketing buzzwords
"""

import re
from typing import Dict, Any, List

# 1. Real-world authentic human lexicon (from ForumHouse, SNT/KP chats, Telegram)
REAL_HUMAN_SLANG = {
    # Problems & pains
    "бухтит": 2.5,
    "забухтел": 2.5,
    "бухтят": 2.5,
    "отстрелило": 2.5,
    "носики": 2.0,
    "капинос": 2.0,
    "в труху": 2.0,
    "каток": 2.0,
    "убиться": 2.0,
    "ноги едут": 2.0,
    "скользотища": 2.0,
    "переделывать": 1.5,
    "полопались": 1.5,
    "поотлетала": 2.0,
    "отвалилась": 1.5,
    "отвалились": 1.5,
    "пустоты": 1.5,
    "стяжка": 1.2,
    "плиточник": 1.2,

    # How people actually refer to C3 / Factory in real life
    "с3": 1.5,
    "c3": 1.5,
    "с-три": 2.0,
    "инноформа": 2.0,
    "в твери делают": 2.5,
    "в твери льют": 2.5,
    "завод в твери": 2.0,
    "тверские накладки": 2.5,
    "цельные ступени": 2.0,
    "г-образные": 2.0,
    "литые накладки": 2.0,
    "фибробетонные": 1.5,

    # Real human conversational markers & colloquialisms
    "плюнули": 1.8,
    "полет нормальный": 2.0,
    "ломом": 1.8,
    "лопатой шкрябаю": 2.5,
    "тяжелые": 1.2,
    "еле разгрузили": 2.2,
    "не дешево": 1.5,
    "влетело в копеечку": 2.2,
    "забыли как страшный сон": 2.5,
    "мужики": 1.5,
    "короче": 1.5,
    "в общем": 1.2,
    "в итоге": 1.2,
    "погугли": 1.8,
    "кину в лс": 2.0,
    "кину в личку": 2.0,
    "фотку": 1.5,
}

# 2. AI Slop & Corporate Cliché Markers (Unnatural corporate PR bot language)
AI_SLOP_MARKERS = {
    "парни из твери": 3.0,
    "инновационный": 3.0,
    "запатентованный": 2.5,
    "уникальная технология": 3.0,
    "регламент завода": 3.0,
    "является идеальным решением": 3.5,
    "высокопрочный композитный": 3.0,
    "монолитный фибробетон c3": 3.0,
    "завода инноформа": 2.0,
    "класс противоскольжения r13": 3.5,
    "покрытие r13": 3.0,
    "зашили монолитным": 3.0,
    "гарантирует безупречное": 3.5,
    "непревзойденная прочность": 3.5,
    "обратитесь к нашим специалистам": 3.0,
    "спешите заказать": 3.0,
    "отличное соотношение цены и качества": 3.0,
    "прослужит долгие десятилетия": 2.5,
    "экологически чистый": 2.5,
    "рады вам помочь": 2.5,
    "безусловно, это": 2.5
}


class LayaHumanityClassifier:
    """
    Evaluates whether a text message is:
      - Authentic human speech (from real forum / chat discussions)
      - Corporate AI-generated slop (unnatural promotional spam)
    """

    @classmethod
    def analyze(cls, text: str) -> Dict[str, Any]:
        text_lower = text.lower()

        # 1. Match human lexicon
        matched_human = []
        human_weight = 0.0
        for phrase, weight in REAL_HUMAN_SLANG.items():
            if phrase in text_lower:
                matched_human.append(phrase)
                human_weight += weight

        # 2. Match AI / Corporate clichés & Typographic giveaways
        matched_ai = []
        ai_weight = 0.0
        for phrase, weight in AI_SLOP_MARKERS.items():
            if phrase in text_lower:
                matched_ai.append(phrase)
                ai_weight += weight

        # Typographic giveaway: Em-dash (—) and En-dash (–) are classic LLM book typography
        # Real people on smartphones in Telegram / WhatsApp use short hyphen (-) or commas
        if "—" in text or "–" in text:
            matched_ai.append("полиграфическое длинное тире (—/–)")
            ai_weight += 2.5

        # 3. Syntactic complexity & burstiness checks
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        avg_sentence_len = sum(len(s.split()) for s in sentences) / max(1, len(sentences))
        has_slang_punctuation = any(p in text for p in ["...", "--", " - ", "(", ")", "!", "?", ")))", "))"])

        # Penalize unnaturally long, uniform sentences without colloquial punctuation
        if avg_sentence_len > 18 and not has_slang_punctuation:
            ai_weight += 2.0

        # 4. Compute Scores (0.0 to 1.0)
        # Base humanity score
        total_signals = human_weight + ai_weight + 0.1
        raw_human_ratio = human_weight / total_signals
        raw_ai_ratio = ai_weight / total_signals

        # Normalize to 0..1 scale
        humanity_score = round(min(1.0, max(0.0, (human_weight * 0.25) - (ai_weight * 0.25) + (0.35 if has_slang_punctuation else 0.0))), 2)
        ai_slop_score = round(min(1.0, max(0.0, (ai_weight * 0.25) - (human_weight * 0.12))), 2)

        # 5. Verdict
        if ai_slop_score >= 0.5 or (ai_weight >= 3.0 and human_weight < 2.0):
            verdict = "CORPORATE_AI_SLOP"
            explanation = "Текст перегружен рекламными штампами и звучит как сгенерированная роботом брошюра."
        elif humanity_score >= 0.6:
            verdict = "AUTHENTIC_HUMAN"
            explanation = "Живая естественная речь с характерным строительным сленгом и бытовыми подробностями."
        else:
            verdict = "NEUTRAL_MIXED"
            explanation = "Нейтральный текст без выраженной специфики или умеренно отредактированное сообщение."

        return {
            "verdict": verdict,
            "humanity_score": humanity_score,
            "ai_slop_score": ai_slop_score,
            "matched_human_slang": matched_human,
            "matched_ai_markers": matched_ai,
            "explanation": explanation
        }


if __name__ == "__main__":
    test_cases = [
        {
            "author": "Bot / Прежний ИИ-пример",
            "text": "Мы в прошлом году зашили монолитным фибробетоном C3 завода Инноформа — за зиму ни единой трещины, покрытие R13 вообще не скользит в мороз. Парни из Твери привезли комплект."
        },
        {
            "author": "Реальный сосед в чате КП",
            "text": "Плитку даже не клей заново, бесполезно — вода под носик затекает и отрывает при морозе. Мы три года назад плюнули и поставили тверские накладки (C3 вроде контора называется, цельные ступени). Не дешево вышло, но реально забыли как страшный сон: лопатой шкрябаю — им пофиг, ноги вообще не едут. Если надо, кину в личку фотку."
        },
        {
            "author": "Вопрос с ForumHouse",
            "text": "Привет форумчане! На крыльце опять плитка забухтела и отстрелило капиносы. По швам порвало все. Подскажите, кто ставил литые накладки из Твери? Как они зимой, не каток?"
        }
    ]

    print("=" * 80)
    print("ТЕСТ МОДЕЛИ ОЦЕНКИ ИИ-ШНОСТИ И ЧЕЛОВЕЧНОСТИ (LAYA HUMANITY CLASSIFIER)")
    print("=" * 80)

    for i, tc in enumerate(test_cases, 1):
        res = LayaHumanityClassifier.analyze(tc["text"])
        print(f"\n[{i}] Автор: {tc['author']}")
        print(f"Текст: \"{tc['text']}\"")
        print(f"Вердикт: {res['verdict']}")
        print(f"Индекс человечности: {res['humanity_score'] * 100}% | Индекс ИИ-шности: {res['ai_slop_score'] * 100}%")
        print(f"Найденный живой сленг: {res['matched_human_slang']}")
        print(f"Найденные ИИ-маркеры: {res['matched_ai_markers']}")
        print(f"Заключение: {res['explanation']}")
        print("-" * 80)
