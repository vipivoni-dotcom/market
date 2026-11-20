"""Веб-панель: связки, карточки, заказы, статистика."""

from __future__ import annotations

import hmac
import time
from urllib.parse import urlsplit, parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, RedirectResponse
from pydantic import BaseModel

from .fees import buy_cost, buy_fee_pct, pay_method
from .orders import needs_buyer_data
from .app import App
from .cards import render as render_card_image
from .config import ROOT

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
AUTH_COOKIE = "arb_panel"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class DeliverBody(BaseModel):
    text: str
    confirm_unknown: bool = False


def _hostname(host: str) -> str:
    return urlsplit(f"//{host}").hostname or ""


def _token_ok(given: str | None, token: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), token.encode())


def _given_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(AUTH_COOKIE)



def _order_view(app, o: dict) -> dict:
    """Заказ для панели: сколько платить поставщику и что бот сделает сам."""
    supplier = app.platforms.get(o["source_platform"]) if o["source_platform"] else None
    return {**o,
            "pay": round(buy_cost(app.cfg, o["source_platform"], o["source_price"]), 2)
            if o["source_platform"] and o["source_price"] else None,
            "needs_buyer_data": needs_buyer_data(app.cfg, o["key"] or ""),
            "tracked": supplier is not None and supplier.name != "playerok" and hasattr(supplier, "purchase_chats")}


def _platforms_view(app) -> list[dict]:
    engine, rows = app.engine, []
    counts = {r["platform"]: r["n"] for r in app.db.query("SELECT platform, COUNT(*) n FROM offers GROUP BY platform")}
    for name, p in app.platforms.items():
        snap = getattr(engine, "_snapshots", {}).get(name)
        rows.append({"name": name, "offers": len(snap[1]) if snap else counts.get(name, 0),
                     "scanned_at": snap[0] if snap else None,
                     "seconds": round(getattr(engine, "scan_seconds", {}).get(name, 0)),
                     "slowdown": round(getattr(p, "slowdown", 1.0), 2),
                     "write_slowdown": round(getattr(p, "write_slowdown", 1.0), 2),
                     "buy_fee_pct": buy_fee_pct(app.cfg, name),
                     "pay_checked": bool(getattr(p, "checks_pay_price", False)),
                     "can_sell": bool(getattr(p, "can_sell", False)), "can_buy": bool(getattr(p, "can_buy", False))})
    return rows

def build_web(app: App) -> FastAPI:
    token = str(app.cfg.get_path("web.token") or "")
    host = str(app.cfg.get_path("web.host", "127.0.0.1"))
    if not token and host not in LOCAL_HOSTS:
        raise RuntimeError(f"панель на адресе {host} доступна из сети: задайте web.token в config.yaml")
    web = FastAPI(title="Market arbitrage")
    page = (ROOT / "arb" / "panel.html").read_text(encoding="utf-8")
    login_page = (ROOT / "arb" / "login.html").read_text(encoding="utf-8")
    login_attempts: dict[str, list[float]] = {}

    @web.middleware("http")
    async def guard(request: Request, call_next) -> Response:
        # Обложку забирает страница площадки в браузере, поэтому она открыта.
        if request.url.path.startswith("/cards/") and request.method in SAFE_METHODS:
            return await call_next(request)
        req_host = request.headers.get("host", "")
        if request.url.path == "/login":
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        new_cookie = None
        if token:
            if not _token_ok(_given_token(request), token):
                new_cookie = request.query_params.get("token")
                if not _token_ok(new_cookie, token):
                    if request.url.path == "/" and request.method == "GET":
                        return RedirectResponse("/login", status_code=303)
                    return Response("нужен токен панели", status_code=401)
        elif _hostname(req_host) not in LOCAL_HOSTS:
            # Чужое имя, указывающее на 127.0.0.1 (DNS rebinding), не должно видеть панель.
            return Response("чужой адрес", status_code=403)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != req_host:
                return Response("запрос с чужого сайта", status_code=403)
            if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
                return Response("запрос с чужого сайта", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if new_cookie:
            response.set_cookie(AUTH_COOKIE, new_cookie, httponly=True, samesite="strict",
                                secure=request.url.scheme == "https")
        return response

    @web.get("/login", response_class=HTMLResponse)
    def login_form() -> str:
        return login_page

    @web.post("/login")
    async def login(request: Request) -> Response:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
            return Response("запрос с чужого сайта", status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return Response("запрос с чужого сайта", status_code=403)
        if int(request.headers.get("content-length", "0")) > 4096:
            return Response("слишком большой запрос", status_code=413)
        now = time.monotonic()
        for ip in list(login_attempts):
            login_attempts[ip] = [t for t in login_attempts[ip] if now - t < 300]
            if not login_attempts[ip]:
                del login_attempts[ip]
        ip = request.client.host if request.client else "unknown"
        attempts = login_attempts.setdefault(ip, [])
        if len(attempts) >= 5 or len(login_attempts) > 10000:
            return Response("Слишком много попыток. Повторите через 5 минут.", status_code=429,
                            headers={"Retry-After": "300"})
        body = await request.body()
        if len(body) > 4096:
            return Response("слишком большой запрос", status_code=413)
        given = parse_qs(body.decode("utf-8", errors="replace")).get("password", [""])[0]
        if not _token_ok(given, token):
            attempts.append(now)
            return HTMLResponse(login_page.replace('id="error" hidden', 'id="error"'), status_code=401)
        login_attempts.pop(ip, None)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(AUTH_COOKIE, token, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")
        return response

    @web.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page

    @web.get("/card_render.js")
    def card_js() -> Response:
        return Response((ROOT / "arb" / "card_render.js").read_text(encoding="utf-8"), media_type="application/javascript")

    @web.get("/covers", response_class=HTMLResponse)
    def covers() -> str:
        return (ROOT / "arb" / "covers.html").read_text(encoding="utf-8")

    @web.get("/api/data")
    def data() -> dict:
        db = app.db
        live = {(r["key"], r["platform"]) for r in db.query("SELECT key, platform FROM listings WHERE status IN ('active','dry_run')")}
        saved = db.query("SELECT * FROM opportunities WHERE status IN ('new','listed') ORDER BY profit DESC")
        verified = getattr(app.engine, "verified_opportunity_ids", set())
        cutoff = time.time() - float(app.engine.rule("max_opportunity_age_minutes", 120)) * 60
        current = [o for o in saved if o["id"] in verified and (o["updated_at"] or 0) >= cutoff
                   and (o["sell_platform"], o["key"]) not in app.engine.unverified]
        stats = app.stats()
        stats["opportunities"] = len(current)
        return {
            "stats": stats,
            "mode": {"dry_run": app.cfg.dry_run, "auto_list": app.cfg.get_path("mode.auto_list"),
                     "auto_buy": app.cfg.get_path("mode.auto_buy"), "platforms": list(app.platforms),
                     "auto_deliver": app.cfg.get_path("mode.auto_deliver", False)},
            "last_scan": app.engine.last_scan,
            "next_scan": app.engine.next_scan,
            "scanning": app.engine.scanning,
            "rules": {"min_margin_pct": app.engine.rule("min_margin_pct"), "min_profit_rub": app.engine.rule("min_profit_rub"),
                      "sell_platforms": app.engine.rule("sell_platforms") or [],
                      "interval_minutes": app.cfg.get_path("scan.interval_minutes", 15)},
            # Связка «выставлена», если по её товару на площадке уже есть живая карточка: после пересканирования
            # у связки новый id, и без этого на уже выставленном товаре висела кнопка «Выставить»
            "opportunities": [{**o, "status": "listed" if (o["key"], o["sell_platform"]) in live else o["status"]}
                              for o in current[:300]],
            "unverified_opportunities": len(saved) - len(current),
            # Сначала живые карточки, затем последние снятые
            # У карточки — её поставщик и ожидаемая прибыль из связки
            "listings": db.query(
                "SELECT l.*, o.buy_platform, o.buy_price, o.buy_url, o.profit, o.margin_pct FROM listings l "
                "LEFT JOIN opportunities o ON o.id = l.opportunity_id "
                "ORDER BY l.status IN ('active','dry_run') DESC, l.id DESC LIMIT 300"),
            "orders": [_order_view(app, o) for o in db.query("SELECT * FROM orders ORDER BY id DESC LIMIT 200")],
            "cycle": app.engine.last_cycle,
            "coverage": getattr(app.engine, "last_audit", {}),
            "platforms": _platforms_view(app),
            "pay_method": pay_method(app.cfg),
        }

    @web.get("/api/suppliers")
    def search_suppliers(q: str = "", platform: str = "", amount: float | None = None) -> dict:
        return app.engine.search_suppliers(q, platform, amount)

    @web.get("/api/suppliers/{key}")
    def suppliers(key: str, platform: str = "") -> dict:
        return app.engine.supplier_view(key, platform)

    @web.get("/api/offers/{key}")
    def offers(key: str) -> list[dict]:
        return app.db.query("SELECT * FROM offers WHERE key=? ORDER BY price", (key,))

    @web.post("/api/scan")
    async def scan() -> dict:
        ops = await app.engine.run_cycle()
        return {"offers": len(app.engine.offers), "opportunities": len(ops)}

    @web.post("/api/opportunities/{op_id}/list")
    async def list_op(op_id: int) -> dict:
        return {"result": await app.engine.list_opportunity(op_id)}

    @web.post("/api/opportunities/{op_id}/skip")
    def skip_op(op_id: int) -> dict:
        app.db.set_opportunity_status(op_id, "skipped")
        return {"result": "ok"}

    @web.post("/api/orders/{order_id}/deliver")
    async def deliver(order_id: int, body: DeliverBody) -> dict:
        return {"result": await app.orders.deliver(order_id, body.text, body.confirm_unknown)}

    # Обложка карточки. Разрешаем чтение с любых сайтов: страница площадки в браузере
    # забирает картинку отсюда, чтобы приложить её к карточке.
    card_headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Private-Network": "true",
                    "Access-Control-Allow-Methods": "GET"}

    @web.get("/cards/{key}.png")
    def card_image(key: str) -> Response:
        try:
            path = render_card_image(key)
        except ValueError:
            return Response("нет такого товара", status_code=404, headers=card_headers)
        return FileResponse(path, media_type="image/png", headers=card_headers)

    @web.options("/cards/{key}.png")
    def card_image_preflight(key: str) -> Response:
        return Response(headers=card_headers)

    return web
