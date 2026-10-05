"""
C3.RU REGIONAL LOGISTICS & GEOLOCATION ENGINE
Calculates distances from C3 Innoforma Factory (Tver), shipping costs,
nearest authorized installation teams, and local delivery ETAs.
"""

import math
import re
import urllib.request
import json
from typing import Dict, Any, Optional

# C3 Central Manufacturing Plant & Head Office
C3_FACTORY_CITY = "Тверь"
C3_FACTORY_COORDS = (56.8587, 35.9176)  # Tver, Industrialnaya st.

# C3 Hubs, Regional Warehouses & Certified Installation Brigades
C3_REGIONS_DATABASE = {
    "tver": {
        "name": "Тверь и Тверская область",
        "city": "Тверь",
        "coords": (56.8587, 35.9176),
        "distance_km": 0,
        "delivery_days": "1 день (в день заказа)",
        "delivery_cost_rub": 1500,
        "brigades_count": "Заводской шеф-монтаж (3 бригады)",
        "free_survey": True,
        "delivery_type": "Прямая доставка с завода / Самовывоз",
        "keywords": ["тверь", "тверск", "конаково", "торжок", "ржев", "вышний волочек", "кимры", "осташков", "завидово"]
    },
    "moscow": {
        "name": "Москва и Московская область",
        "city": "Москва",
        "coords": (55.7558, 37.6173),
        "distance_km": 165,
        "delivery_days": "1–2 рабочих дня",
        "delivery_cost_rub": 3800,
        "brigades_count": "5 сертифицированных бригад C3",
        "free_survey": True,
        "delivery_type": "Манипулятор / Доставка до объекта",
        "keywords": ["москва", "московск", "подмосков", "химки", "зеленоград", "клин", "солнечногорск", 
                     "красногорск", "одинцово", "мытищи", "балашиха", "люберцы", "подольск", "домодедово", "дмитров", "серпухов"]
    },
    "spb": {
        "name": "Санкт-Петербург и Ленинградская область",
        "city": "Санкт-Петербург",
        "coords": (59.9343, 30.3351),
        "distance_km": 530,
        "delivery_days": "2–3 рабочих дня",
        "delivery_cost_rub": 4800,
        "brigades_count": "3 сертифицированные бригады C3",
        "free_survey": True,
        "delivery_type": "ТК Деловые Линии (жесткая упаковка) / попутный транспорт",
        "keywords": ["санкт-петербург", "петербург", "питер", "спб", "ленинградск", "гатчина", "выборг", "всеволожск", "пушкин"]
    },
    "yaroslavl": {
        "name": "Ярославль и Золотое Кольцо",
        "city": "Ярославль",
        "coords": (57.6261, 39.8845),
        "distance_km": 310,
        "delivery_days": "2 рабочих дня",
        "delivery_cost_rub": 4200,
        "brigades_count": "2 аккредитованных партнера",
        "free_survey": True,
        "delivery_type": "ТК / Региональная доставка",
        "keywords": ["ярославль", "рыбинск", "кострома", "иваново", "переславль", "ростов"]
    },
    "nizhny": {
        "name": "Нижний Новгород и область",
        "city": "Нижний Новгород",
        "coords": (56.3269, 44.0059),
        "distance_km": 520,
        "delivery_days": "2–3 рабочих дня",
        "delivery_cost_rub": 5200,
        "brigades_count": "2 сертифицированные бригады",
        "free_survey": True,
        "delivery_type": "ТК Деловые Линии / ПЭК",
        "keywords": ["нижний новгород", "новгородск", "дзержинск", "арзамас", "бор", "кстово", "владимир", "ковров", "муром"]
    },
    "kazan": {
        "name": "Казань и Республика Татарстан",
        "city": "Казань",
        "coords": (55.7961, 49.1064),
        "distance_km": 920,
        "delivery_days": "3–4 рабочих дня",
        "delivery_cost_rub": 6500,
        "brigades_count": "2 региональные бригады C3",
        "free_survey": True,
        "delivery_type": "ТК с паллетным бортом",
        "keywords": ["казань", "татарстан", "челны", "набережные челны", "нижнекамск", "альметьевск", "чебоксары", "йошкар-ола"]
    },
    "voronezh": {
        "name": "Воронеж и Черноземье",
        "city": "Воронеж",
        "coords": (51.6755, 39.2089),
        "distance_km": 640,
        "delivery_days": "2–3 рабочих дня",
        "delivery_cost_rub": 5400,
        "brigades_count": "2 бригады монтажников C3",
        "free_survey": True,
        "delivery_type": "ТК Деловые Линии / Автодоставка",
        "keywords": ["воронеж", "тула", "липецк", "белгород", "курск", "орёл", "рязань", "тамбов", "калуга"]
    },
    "krasnodar": {
        "name": "Краснодар, Ростов и ЮФО",
        "city": "Краснодар",
        "coords": (45.0355, 38.9753),
        "distance_km": 1420,
        "delivery_days": "3–5 рабочих дней",
        "delivery_cost_rub": 7800,
        "brigades_count": "Официальное представительство C3 Юг (4 бригады)",
        "free_survey": True,
        "delivery_type": "Филиал C3 Юг / Доставка до объекта",
        "keywords": ["краснодар", "ростов", "ростов-на-дону", "сочи", "новороссийск", "анапа", "ставрополь", "севастополь", "симферополь", "крым"]
    },
    "ekaterinburg": {
        "name": "Екатеринбург и Урал",
        "city": "Екатеринбург",
        "coords": (56.8389, 60.6057),
        "distance_km": 1820,
        "delivery_days": "5–6 рабочих дней",
        "delivery_cost_rub": 8900,
        "brigades_count": "Уральский филиал C3 (2 бригады)",
        "free_survey": True,
        "delivery_type": "ТК Деловые Линии (жесткая обрешетка)",
        "keywords": ["екатеринбург", "челябинск", "пермь", "уфа", "тюмень", "тагил", "курган"]
    },
    "novosibirsk": {
        "name": "Новосибирск и Сибирь",
        "city": "Новосибирск",
        "coords": (55.0084, 82.9357),
        "distance_km": 3400,
        "delivery_days": "7–9 рабочих дней",
        "delivery_cost_rub": 11800,
        "brigades_count": "Авторизованные партнеры C3 Сибирь",
        "free_survey": False,
        "delivery_type": "Сборный ж/д и автоконтейнер ТК",
        "keywords": ["новосибирск", "омск", "красноярск", "томск", "барнаул", "кемерово", "новокузнецк", "иркутск"]
    }
}

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates spherical distance between two coordinates in kilometers"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 1)


class C3RegionalLogistics:
    """Handles reverse geocoding, regional routing, freight quotes, and installation brigade mapping"""

    @classmethod
    def resolve_by_coordinates(cls, lat: float, lon: float) -> Dict[str, Any]:
        """Resolves city, region, distance from Tver factory and logistics for exact coordinates"""
        dist_from_tver = haversine_km(C3_FACTORY_COORDS[0], C3_FACTORY_COORDS[1], lat, lon)

        # 1. Reverse geocoding via OpenStreetMap Nominatim
        city_name = None
        region_name = None
        try:
            req = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=ru",
                headers={"User-Agent": "C3StairsBot/1.0 (info@c3.ru)"}
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                addr = data.get("address", {})
                city_name = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("suburb")
                region_name = addr.get("state") or addr.get("county") or city_name
        except Exception:
            pass

        # 2. Find closest registered C3 regional hub
        best_hub = "moscow"
        min_hub_dist = 999999.0
        for hub_key, hub_info in C3_REGIONS_DATABASE.items():
            h_dist = haversine_km(hub_info["coords"][0], hub_info["coords"][1], lat, lon)
            if h_dist < min_hub_dist:
                min_hub_dist = h_dist
                best_hub = hub_key

        hub_data = C3_REGIONS_DATABASE[best_hub]
        resolved_city = city_name or hub_data["city"]
        resolved_region = region_name or hub_data["name"]

        # Calculate estimated shipping cost based on actual km from Tver
        if dist_from_tver <= 50:
            est_cost = 1500
            est_days = "1 день (в день заказа)"
        elif dist_from_tver <= 250:
            est_cost = 3800
            est_days = "1–2 рабочих дня"
        elif dist_from_tver <= 600:
            est_cost = 4800 + int((dist_from_tver - 250) * 3.5)
            est_days = "2–3 рабочих дня"
        else:
            est_cost = 6000 + int((dist_from_tver - 600) * 2.2)
            est_days = f"{max(3, int(dist_from_tver / 400))}–{max(4, int(dist_from_tver / 300))} рабочих дней"

        return {
            "source": "gps_coordinates",
            "city": resolved_city,
            "region": resolved_region,
            "distance_from_factory_km": dist_from_tver,
            "factory_city": C3_FACTORY_CITY,
            "delivery_days": est_days,
            "delivery_cost_rub": round(est_cost, -2),
            "delivery_type": hub_data["delivery_type"],
            "brigades_count": hub_data["brigades_count"],
            "free_survey": hub_data["free_survey"]
        }

    @classmethod
    def resolve_by_text(cls, text: str) -> Optional[Dict[str, Any]]:
        """Scans client message for mentions of cities/regions"""
        if not text:
            return None
        text_lower = text.lower()

        # Check in C3 regional database
        for hub_key, hub_info in C3_REGIONS_DATABASE.items():
            for kw in hub_info["keywords"]:
                if re.search(r'\b' + re.escape(kw), text_lower):
                    return {
                        "source": "text_extracted",
                        "city": hub_info["city"],
                        "region": hub_info["name"],
                        "distance_from_factory_km": hub_info["distance_km"],
                        "factory_city": C3_FACTORY_CITY,
                        "delivery_days": hub_info["delivery_days"],
                        "delivery_cost_rub": hub_info["delivery_cost_rub"],
                        "delivery_type": hub_info["delivery_type"],
                        "brigades_count": hub_info["brigades_count"],
                        "free_survey": hub_info["free_survey"]
                    }
        return None

    @classmethod
    def format_logistics_message(cls, log_info: Dict[str, Any]) -> str:
        """Formats attractive Markdown section for Telegram or Web"""
        survey_text = "Бесплатный выезд инженера с образцами накладок C3" if log_info.get("free_survey") else "Дистанционный замер по фото и чертежам"
        return (
            f"📍 **Регион доставки:** {log_info['city']} ({log_info['region']})\n"
            f"🏭 **Расстояние от завода C3 (г. {log_info['factory_city']}):** ~{log_info['distance_from_factory_km']} км\n"
            f"🚚 **Доставка:** ~{log_info['delivery_cost_rub']:,} руб. ({log_info['delivery_days']})\n"
            f"👷 **Монтаж в вашем регионе:** {log_info['brigades_count']}\n"
            f"📐 **Замер:** {survey_text}"
        ).replace(",", " ")
