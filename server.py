"""
Starlette + Uvicorn Web Server for C3.ru AI Leadgen Prototype
Serves interactive live demonstration and REST API endpoints.
"""

import os
import sys
import json
import asyncio
import requests
import uvicorn
from contextlib import asynccontextmanager
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


async def api_mrg_summary(request):
    """
    On-demand trigger for MRG daily summary generation and Telegram delivery
    """
    try:
        from mrg_daily_daemon import execute_daily_cycle
        summary = await execute_daily_cycle(send_dm=True)
        return JSONResponse({"status": "ok", "delivered": True, "length": len(summary)})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(keep_alive_loop())
    yield
    task.cancel()


async def keep_alive_loop():
    public_url = os.getenv("RENDER_EXTERNAL_URL", "https://c3-service-il4m.onrender.com")
    health_url = f"{public_url.rstrip('/')}/api/health"
    print(f"[*] Keep-Alive loop активирован для: {health_url}")
    await asyncio.sleep(60)
    while True:
        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, lambda: requests.get(health_url, timeout=15))
            print(f"[Keep-Alive] Ping {health_url} -> status {res.status_code}")
        except Exception as e:
            print(f"[Keep-Alive] Ping warning: {e}")
        await asyncio.sleep(540)  # Ping every 9 minutes (Render free timeout is 15 minutes)


def get_db():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            import psycopg2
            return psycopg2.connect(db_url)
        except Exception as e:
            print(f"[DB Server] Connect error: {e}")
    return None


async def calendar_page(request):
    cal_file = os.path.join(BASE_DIR, "static", "calendar.html")
    if os.path.exists(cal_file):
        with open(cal_file, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Calendar Mini App is loading...</h1>")


async def api_get_tasks(request):
    conn = get_db()
    if not conn:
        return JSONResponse([])
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, category, priority, due_at, remind_at, status, target_channels
                FROM user_tasks
                ORDER BY due_at ASC NULLS LAST, id DESC;
            """)
            tasks = []
            for r in cur.fetchall():
                tasks.append({
                    "id": r[0],
                    "title": r[1],
                    "category": r[2],
                    "priority": r[3],
                    "due_at": r[4].isoformat() if r[4] else None,
                    "remind_at": r[5].isoformat() if r[5] else None,
                    "status": r[6],
                    "target_channels": r[7] if len(r) > 7 else []
                })
            return JSONResponse(tasks)
    finally:
        conn.close()


async def api_toggle_task(request):
    task_id = request.path_params.get("task_id")
    conn = get_db()
    if not conn:
        return JSONResponse({"status": "error"})
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE user_tasks 
                SET status = CASE WHEN status = 'completed' THEN 'pending' ELSE 'completed' END,
                    updated_at = NOW()
                WHERE id = %s;
            """, (task_id,))
            conn.commit()
            return JSONResponse({"status": "ok"})
    finally:
        conn.close()


async def api_postpone_task(request):
    task_id = request.path_params.get("task_id")
    conn = get_db()
    if not conn:
        return JSONResponse({"status": "error"})
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE user_tasks 
                SET remind_at = NOW() + INTERVAL '1 hour', reminder_sent = FALSE, updated_at = NOW()
                WHERE id = %s;
            """, (task_id,))
            conn.commit()
            return JSONResponse({"status": "ok"})
    finally:
        conn.close()


async def api_create_task(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    title = body.get("title", "Новая задача")
    category = body.get("category", "Личные дела")
    conn = get_db()
    if not conn:
        return JSONResponse({"status": "error"})
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_tasks (user_id, title, raw_input, category, due_at, remind_at)
                VALUES (268747191, %s, %s, %s, NOW() + INTERVAL '2 hour', NOW() + INTERVAL '1 hour')
                RETURNING id;
            """, (title, title, category))
            tid = cur.fetchone()[0]
            conn.commit()
            return JSONResponse({"status": "ok", "task_id": tid})
    finally:
        conn.close()


async def api_max_digest(request):
    return JSONResponse({
        "status": "ok",
        "digest": "📊 Сводка MAX формируется автоматически в 09:00 и 21:00 МСК, а также по команде /max в боте."
    })


routes = [
    Route("/", endpoint=index),
    Route("/calendar", endpoint=calendar_page, methods=["GET"]),
    Route("/api/health", endpoint=api_health, methods=["GET"]),
    Route("/api/tasks", endpoint=api_get_tasks, methods=["GET"]),
    Route("/api/tasks", endpoint=api_create_task, methods=["POST"]),
    Route("/api/tasks/{task_id}/toggle", endpoint=api_toggle_task, methods=["POST"]),
    Route("/api/tasks/{task_id}/postpone", endpoint=api_postpone_task, methods=["POST"]),
    Route("/api/max/digest", endpoint=api_max_digest, methods=["GET"]),
    Route("/api/analyze", endpoint=api_analyze, methods=["POST"]),
    Route("/api/roi", endpoint=api_roi, methods=["POST"]),
    Route("/api/logistics", endpoint=api_logistics, methods=["GET", "POST"]),
    Route("/api/mrg/summary", endpoint=api_mrg_summary, methods=["GET", "POST"]),
]

app = Starlette(debug=True, routes=routes, lifespan=lifespan)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    print(f"[*] Запуск интерактивного прототипа C3: http://localhost:{port}")
    uvicorn.run("server:app", host=os.getenv("HOST", "0.0.0.0"), port=port, reload=False, log_level="info")
