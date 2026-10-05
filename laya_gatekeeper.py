# -*- coding: utf-8 -*-
"""
LAYA System 1 Gatekeeper: High-Precision Intent & Anti-Spam Classifier
Performs sub-millisecond triage of incoming Telegram messages.
Separates genuine CUSTOMER DEMAND (Leads) from:
  - Promotional broadcasts, affiliate spam & bots (e.g. VPN, crypto, casino)
  - Competitor self-promotion & agency advertising
  - News, digests & irrelevant noise
"""

import re
from typing import Dict, Any, Tuple, Optional

# 1. High-confidence spam and promotional broadcast markers
SPAM_BOT_PATTERNS = [
    r'@\w*bot\b',                           # @any_bot
    r't\.me/\+[\w\-]+',                     # Private invite link
    r't\.me/joinchat',                      # Joinchat link
    r'пере(ходи|йди|ходите)\s+(в|по)\s+бот', # CTA to bot
    r'бот\s+в\s+описании',
    r'ссылка\s+в\s+(шапке|профиле|описании|комментари)',
    r'vpn\b', r'впн\b', r'proxy\b', r'прокси\b',
    r'shadowsocks', r'vless', r'wireguard',
    r'бесплатн\w+\s+доступ\w*\s+на\s+\d+',  # e.g., 3 дня бесплатного доступа
    r'промокод\b', r'акци[яи]\s+до\b',
    r'розыгрыш\b', r'раздач\w+\s+призов',
    r'заработок\s+в\s+сети', r'доход\s+от\s+\d+\s*(?:руб|т\.р|\$)',
    r'работа\s+для\s+мам', r'удаленка\s+без\s+опыта',
    r'ставки\s+на\s+спорт', r'1xbet', r'казино\b', r'крипт\w+\s+сигнал',
    r'слив\s+курсов', r'складчин\w+',
    r'подписывай(ся|тесь)\s+на\s+канал',
    r'только\s+сегодня\s+скидк',
    r'успе(й|йте)\s+перейти',
    r'очередь\s+по\s+талонам',
]

# 2. Competitor self-promotion markers (Agencies, masters selling their own services)
# Used to filter out advertisers in client-seeking verticals (SMM, stairs, legal, bankruptcy)
COMPETITOR_OFFER_PATTERNS = [
    r'настро(им|ю)\s+рекламу',
    r'настро(им|ю)\s+таргет',
    r'приведе(м|м)\s+клиентов',
    r'гарантируем\s+результат',
    r'наш\w*\s+кейс',
    r'наше\s+агентство',
    r'предлага(ю|ем)\s+услуги\s+(маркетинг|smm|смм|таргет|продвижен)',
    r'оказыва(ю|ем)\s+услуги\s+по\s+продвижен',
    r'возьм(у|ем)\s+на\s+ведение\s+(проект|аккаунт|соцсет)',
    r'пишите\s+в\s+лс\s+для\s+заказа',
    r'прайс[\s\-]лист\s+в\s+лс',
    r'заявки\s+от\s+\d+\s*руб',
    r'комплексн\w+\s+продвижение\s+бизнеса',
    r'помогу\s+с\s+маркетингом',
    r'я\s+(?:маркетолог|таргетолог|сммщик|директолог|юрист|адвокат)\s+с\s+опытом',
]

# 3. Genuine Customer Demand Intent Markers (Seeking help, buying, asking for advice)
CUSTOMER_DEMAND_PATTERNS = [
    r'посоветуйте',
    r'подскажите',
    r'ищу\s+(?:мастер|специалист|компани|человек|юрист|адвокат|таргетолог|маркетолог|риелтор)',
    r'нужен\s+(?:мастер|специалист|юрист|адвокат|маркетолог|таргетолог|ремонт)',
    r'требуется\s+(?:мастер|специалист|юрист|таргетолог)',
    r'кто\s+(?:делал|может|занимается|шарит|сталкивался)',
    r'сколько\s+стоит\s+(?:сделать|отделать|списать|оформить|настроить)',
    r'где\s+(?:купить|заказать|найти|починить)',
    r'чем\s+(?:отделать|облицевать|покрыть|обработать)',
    r'отвалил(?:ась|ись)',
    r'разрушил(?:ось|ись)',
    r'скользк(?:о|ие|ая)',
    r'замучил(?:и|а)\s+долг',
    r'нечем\s+платить\s+(?:кредит|займ|долг)',
    r'арестовали\s+счет',
    r'звонят\s+коллектор',
    r'хочу\s+(?:купить|заказать|переделать|продать)',
]

# 4. Legit C2C Offers (permitted for auto_market, realty, free_giveaway)
LEGIT_C2C_PATTERNS = [
    r'продам\s+(?:свой|свою|машин|авто|ваз|дом|дач|участ|квартир)',
    r'сдам\s+(?:квартир|однушк|комнат|дом)',
    r'сниму\s+(?:квартир|однушк|дом)',
    r'отдам\s+(?:даром|бесплатно|за\s+сок|за\s+шоколад)',
    r'отдаю\s+(?:даром|вещи|диван|холодильник|стенк)',
    r'самовывоз\b',
]


class LayaGatekeeper:
    """
    Sub-millisecond triage engine determining if a message is a valid lead or trash/ad.
    """

    @classmethod
    def evaluate(cls, text: str, category_id: Optional[str] = None) -> Dict[str, Any]:
        if not text or len(text.strip()) < 10:
            return {
                "is_lead": False,
                "is_spam": True,
                "intent": "EMPTY_OR_SHORT",
                "reason": "Слишком короткое сообщение",
                "confidence": 1.0
            }

        clean = text.lower()

        # Check 1: Absolute Spam & Bot Patterns
        for pattern in SPAM_BOT_PATTERNS:
            m = re.search(pattern, clean)
            if m:
                matched_token = m.group(0)
                return {
                    "is_lead": False,
                    "is_spam": True,
                    "intent": "SPAM_AD",
                    "reason": f"Обнаружен рекламный/бот спам ('{matched_token}')",
                    "confidence": 0.99
                }

        # Check 2: Competitor Self-Promotion (for commercial service categories)
        service_categories = {"smm_marketing", "c3_stairs", "bankruptcy", "legal_services"}
        if not category_id or category_id in service_categories:
            for pattern in COMPETITOR_OFFER_PATTERNS:
                m = re.search(pattern, clean)
                if m:
                    matched_token = m.group(0)
                    return {
                        "is_lead": False,
                        "is_spam": True,
                        "intent": "COMPETITOR_OFFER",
                        "reason": f"Реклама своих услуг / самопиар ('{matched_token}')",
                        "confidence": 0.95
                    }

        # Check 3: Genuine Customer Demand
        has_demand = any(re.search(pat, clean) for pat in CUSTOMER_DEMAND_PATTERNS)
        if has_demand:
            return {
                "is_lead": True,
                "is_spam": False,
                "intent": "CUSTOMER_DEMAND",
                "reason": "Явный клиентский спрос / вопрос / проблема",
                "confidence": 0.96
            }

        # Check 4: Legit C2C Offer (valid for realty, auto, giveaway)
        c2c_categories = {"auto_market", "realty_houses", "realty_flats", "free_giveaway", "jobs_vacancies", "jobs_resumes"}
        if category_id in c2c_categories or category_id is None:
            has_c2c = any(re.search(pat, clean) for pat in LEGIT_C2C_PATTERNS)
            if has_c2c:
                return {
                    "is_lead": True,
                    "is_spam": False,
                    "intent": "C2C_OFFER",
                    "reason": "Частное объявление (авто/жилье/даром)",
                    "confidence": 0.92
                }

        # Check 5: General Question in Chat (contains question mark with problem)
        if "?" in text:
            # Questions with some intent or context
            return {
                "is_lead": True,
                "is_spam": False,
                "intent": "QUESTION_INQUIRY",
                "reason": "Вопрос участника в чате",
                "confidence": 0.85
            }

        # Default fallback for service categories: if it has NO demand markers and NO question,
        # it is most likely a statement, news, or generic chatter, NOT a lead.
        if category_id in service_categories:
            return {
                "is_lead": False,
                "is_spam": False,
                "intent": "UNFOCUSED_CHATTER",
                "reason": "Отсутствует явный клиентский запрос или вопрос",
                "confidence": 0.80
            }

        # For bulletin boards / jobs / vacancies
        return {
            "is_lead": True,
            "is_spam": False,
            "intent": "NEUTRAL_LEAD",
            "reason": "Соответствует профилю доски объявлений",
            "confidence": 0.80
        }
