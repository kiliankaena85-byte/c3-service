"""
Starlette + Uvicorn Web Server for C3.ru AI Leadgen Prototype
Serves interactive live demonstration and REST API endpoints.
"""

import os
import sys
import json
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, HTMLResponse, Response
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

# Add parent directory to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from c3_engine import LayaStairClassifier, GeminiStairVisionEngine
from c3_logistics import C3RegionalLogistics

laya_engine = LayaStairClassifier()
gemini_engine = GeminiStairVisionEngine()


async def api_health(request):
    return JSONResponse({
        "status": "ok",
        "engine": "C3_AI_Dual_Model",
        "laya_native": laya_engine.is_native,
        "gemini_model": gemini_engine.model
    })


async def api_analyze(request):
    """
    Dual-model pipeline endpoint:
    1. Laya evaluates in ~30ms
    2. If qualified, Gemini 3.8 Flash generates full vision calculation
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    # Step 1: LAYA System 1 triage
    laya_result = laya_engine.triage_request(body)
    
    # Step 2: Gemini System 2 reasoning if approved by Laya
    proceed = laya_result["laya_decision"]["proceed_to_gemini"]
    
    if proceed:
        gemini_result = gemini_engine.process_stair_inquiry(body, laya_result)
    else:
        gemini_result = {
            "status": "SKIPPED_BY_LAYA",
            "message": "Запрос классифицирован Laya как спам или нецелевой. Обработка Gemini отменена для экономии ресурсов.",
            "gemini_latency_ms": 0.0
        }

    return JSONResponse({
        "input": body,
        "laya": laya_result,
        "gemini": gemini_result
    })


async def api_roi(request):
    """
    Calculates ROI and financial upside for Innoforma / C3 director
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    ad_budget = float(data.get("ad_budget", 500000))
    cpc = float(data.get("cpc", 150))
    current_cr = float(data.get("current_cr", 0.03))  # 3%
    new_cr = float(data.get("new_cr", 0.065))         # 6.5%
    avg_order_value = float(data.get("avg_order", 75000))
    factory_margin = float(data.get("margin", 0.70))  # 70%
    close_rate = float(data.get("close_rate", 0.15))   # 15% конверсия из расчета в оплату

    clicks = ad_budget / cpc
    current_leads = clicks * current_cr
    new_leads = clicks * new_cr
    extra_leads = new_leads - current_leads

    current_sales = current_leads * close_rate
    new_sales = new_leads * close_rate
    extra_sales = extra_sales = new_sales - current_sales

    extra_revenue_monthly = extra_sales * avg_order_value
    extra_gross_profit_monthly = extra_revenue_monthly * factory_margin
    extra_profit_yearly = extra_gross_profit_monthly * 12

    return JSONResponse({
        "clicks_monthly": round(clicks),
        "current_leads": round(current_leads, 1),
        "new_leads_with_ai": round(new_leads, 1),
        "extra_leads_monthly": round(extra_leads, 1),
        "current_sales_monthly": round(current_sales, 1),
        "new_sales_monthly": round(new_sales, 1),
        "extra_sales_monthly": round(extra_sales, 1),
        "extra_revenue_monthly_rub": round(extra_revenue_monthly),
        "extra_profit_monthly_rub": round(extra_gross_profit_monthly),
        "extra_profit_yearly_rub": round(extra_profit_yearly)
    })


async def index(request):
    index_file = os.path.join(BASE_DIR, "static", "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>C3 AI Prototype Server is running. Static files missing.</h1>")


async def api_logistics(request):
    """
    Calculates regional delivery, factory distance, and installation teams
    """
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
    else:
        body = dict(request.query_params)

    lat = body.get("lat")
    lon = body.get("lon")
    text = body.get("text") or body.get("city")

    if lat and lon:
        try:
            res = C3RegionalLogistics.resolve_by_coordinates(float(lat), float(lon))
            return JSONResponse(res)
        except Exception as e:
            pass

    if text:
        res = C3RegionalLogistics.resolve_by_text(str(text))
        if res:
            return JSONResponse(res)

    # Default to Moscow hub if unspecified
    default_res = C3RegionalLogistics.resolve_by_text("Москва")
    return JSONResponse(default_res)


routes = [
    Route("/", endpoint=index),
    Route("/api/health", endpoint=api_health, methods=["GET"]),
    Route("/api/analyze", endpoint=api_analyze, methods=["POST"]),
    Route("/api/roi", endpoint=api_roi, methods=["POST"]),
    Route("/api/logistics", endpoint=api_logistics, methods=["GET", "POST"]),
]

app = Starlette(debug=True, routes=routes)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 7860))
    print(f"[*] Запуск интерактивного прототипа C3: http://localhost:{port}")
    uvicorn.run("server:app", host=os.getenv("HOST", "0.0.0.0"), port=port, reload=False, log_level="info")
