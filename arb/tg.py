"""Telegram-бот: уведомления, управление ботом (режим, настройки, пауза, карточки), выдача кодов."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .app import App

log = logging.getLogger("arb.tg")

POPUP_LIMIT = 200  # больше Telegram не принимает во всплывающем ответе на кнопку
RETRY_DELAY = 30  # секунд между попытками подключиться к Telegram
CODE_WAIT_SEC = 600  # сколько ждём текст кода после кнопки: позже обычное сообщение покупателю уже не уйдёт

HELP = (
    "Команды:\n"
    "/menu — панель управления кнопками\n"
    "/status — что сейчас делает бот\n"
    "/scan — просканировать площадки сейчас\n"
    "/top — лучшие связки\n"
    "/listings — мои карточки (можно снять с продажи)\n"
    "/orders — заказы\n"
    "/stats — прибыль и статистика\n"
    "/mode — режим работы (переключатели)\n"
    "/settings — правила отбора связок\n"
    "/set <настройка> <значение> — изменить правило, например /set min_margin 3\n"
    "/pause и /resume — остановить и продолжить автоматическое сканирование"
)
COMMANDS = [
    ("menu", "Панель управления"), ("status", "Что сейчас делает бот"), ("scan", "Скан сейчас"),
    ("top", "Лучшие связки"), ("listings", "Мои карточки"), ("orders", "Заказы"), ("stats", "Статистика"),
    ("mode", "Режим работы"), ("settings", "Правила отбора"), ("pause", "Пауза сканирования"),
    ("resume", "Продолжить сканирование"), ("help", "Список команд"),
]

# Переключатели режима: путь в конфиге → подпись.
MODE_FLAGS = {
    "dry_run": "Тестовый режим (на площадках ничего не делает)",
    "auto_list": "Автовыставление карточек",
    "auto_buy": "Автопокупка у поставщика",
    "auto_deliver": "Автовыдача покупателю",
}
# Что можно менять командой /set: имя → (путь в конфиге, тип, подпись, минимум).
SETTINGS = {
    "min_profit": ("rules.min_profit_rub", float, "мин. прибыль, ₽", 0),
    "min_margin": ("rules.min_margin_pct", float, "мин. маржа, %", 0),
    "undercut": ("rules.undercut_rub", float, "дешевле конкурента на, ₽", 0),
    "max_listings": ("rules.max_active_listings", int, "макс. активных карточек", 0),
    "max_buy": ("rules.max_buy_price_rub", float, "макс. цена закупки, ₽", 0),
    "interval": ("scan.interval_minutes", float, "интервал скана, мин", 10),  # чаще — риск блокировки
}

Say = Callable[..., Awaitable[object]]


def on_off(value: object) -> str:
    return "✅ вкл" if value else "⬜ выкл"


def ago(ts: float) -> str:
    if not ts:
        return "ещё не было"
    minutes = int((time.time() - ts) // 60)
    return "только что" if minutes < 1 else f"{minutes} мин назад"


def status_text(app: App) -> str:
    c, e = app.cfg, app.engine
    active = app.db.one("SELECT COUNT(*) AS n FROM listings WHERE status IN ('active','dry_run')")["n"]
    new_ops = app.db.one("SELECT COUNT(*) AS n FROM opportunities WHERE status='new'")["n"]
    if e.scanning:
        scan = "🔎 идёт скан"
    elif e.paused:
        scan = "⏸ на паузе"
    else:
        left = max(0, int((e.next_scan - time.time()) // 60)) if e.next_scan else None
        scan = f"▶️ работает, следующий скан через {left} мин" if left is not None else "▶️ работает"
    platforms = ", ".join(
        f"{p.name}{' (продажа)' if p.can_sell else ''}{' (покупка)' if p.can_buy else ''}" for p in app.platforms.values()
    )
    return (
        f"Режим: {'🧪 тестовый' if c.dry_run else '🔥 боевой'}\n"
        f"Сканирование: {scan}\nПоследний скан: {ago(e.last_scan)}, объявлений {len(e.offers)}\n"
        f"Новых связок: {new_ops}, активных карточек: {active} из {c.get_path('rules.max_active_listings', 30)}\n"
        f"Площадки: {platforms}"
    )


def menu_markup(app: App) -> InlineKeyboardMarkup:
    pause = ("▶️ Продолжить", "menu:resume") if app.engine.paused else ("⏸ Пауза", "menu:pause")
    rows = [
        [("📊 Статус", "menu:status"), ("🔎 Скан", "menu:scan"), pause],
        [("💡 Связки", "menu:top"), ("🗂 Карточки", "menu:listings"), ("📦 Заказы", "menu:orders")],
        [("⚙️ Режим", "menu:mode"), ("🎚 Правила", "menu:settings"), ("📈 Статистика", "menu:stats")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in r] for r in rows])


def mode_markup(app: App) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{on_off(app.cfg.get_path(f'mode.{k}'))} {label}", callback_data=f"mode:{k}")]
            for k, label in MODE_FLAGS.items()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_text(app: App) -> str:
    lines = [f"{name} = {app.cfg.get_path(path)}  ({label})" for name, (path, _, label, _) in SETTINGS.items()]
    return "Правила отбора связок:\n" + "\n".join(lines) + "\n\nИзменить: /set min_margin 3"


def apply_setting(app: App, name: str, raw: str) -> str:
    if name not in SETTINGS:
        return f"Нет такой настройки: {name}. Список: /settings"
    path, kind, label, minimum = SETTINGS[name]
    try:
        value = kind(raw.replace(",", "."))
    except ValueError:
        return f"Нужно число: /set {name} 3"
    if value < minimum:
        return f"{label}: не меньше {minimum}"
    old = app.cfg.get_path(path)
    app.cfg.set_path(path, value)
    log.info("telegram: %s %s → %s", path, old, value)
    return f"✅ {label}: {old} → {value}"


def build_bot(app: App) -> tuple[Bot, Dispatcher] | None:
    token = app.cfg.get_path("telegram.token")
    admins = {int(x) for x in app.cfg.get_path("telegram.admin_ids", []) or []}
    if not token or not admins:
        log.info("telegram: токен или admin_ids не заданы — бот выключен")
        return None
    bot = Bot(token)
    dp = Dispatcher()
    router = Router()
    router.message.filter(F.from_user.id.in_(admins))
    router.callback_query.filter(F.from_user.id.in_(admins))
    waiting_code: dict[int, tuple[int, float]] = {}  # user_id → (order_id, когда нажали кнопку)

    async def sink(text: str, buttons) -> None:
        markup = None
        if buttons:
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in buttons]])
        sent = 0
        error = None
        for admin in admins:
            try:
                await bot.send_message(admin, text[:4000], reply_markup=markup, disable_web_page_preview=True)
                sent += 1
            except Exception as e:  # noqa: BLE001
                error = e
                log.warning("не удалось отправить уведомление администратору %s: %s", admin, e)
        if not sent and error:
            raise error  # никому не ушло — Notifier оставит сообщение в очереди и дошлёт позже

    app.notify.sink = sink

    async def popup(q: CallbackQuery, text: str, alert: bool = False) -> None:
        if len(text) <= POPUP_LIMIT:
            await q.answer(text, show_alert=alert)
            return
        await q.answer()
        await bot.send_message(q.from_user.id, text[:4000], disable_web_page_preview=True)

    def say_to(chat_id: int) -> Say:
        async def say(text: str, reply_markup=None):
            return await bot.send_message(chat_id, text[:4000], reply_markup=reply_markup, disable_web_page_preview=True)
        return say

    # --- экраны: одни и те же для команд и кнопок меню -----------------------

    async def show_menu(say: Say) -> None:
        await say("Панель управления:\n\n" + status_text(app), menu_markup(app))

    async def show_status(say: Say) -> None:
        await say(status_text(app))

    async def run_scan(say: Say) -> None:
        if app.engine.scanning:
            await say("Скан уже идёт, дождитесь его окончания")
            return
        await say("🔎 Сканирую площадки…")
        try:
            ops = await app.engine.run_cycle()
        except Exception as e:  # noqa: BLE001
            log.exception("скан из Telegram упал")
            await say(f"⚠️ Скан не удался: {e}")
            return
        await say(f"Готово: {len(app.engine.offers)} объявлений, {len(ops)} выгодных связок. /top — список")

    async def show_top(say: Say) -> None:
        rows = app.db.query("SELECT * FROM opportunities WHERE status IN ('new','listed') ORDER BY profit DESC LIMIT 10")
        if not rows:
            await say("Связок пока нет. /scan — просканировать")
            return
        for r in rows:
            text = (f"{'🟢' if r['status'] == 'listed' else '💡'} {r['key']} → {r['sell_platform']}\n"
                    f"Купить {r['buy_platform']} {r['buy_price']:.0f} ₽ → продать {r['sell_price']:.0f} ₽ "
                    f"= {r['profit']:.2f} ₽ ({r['margin_pct']}%)\n{r['buy_url']}")
            kb = None
            if r["status"] == "new":
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Выставить", callback_data=f"list:{r['id']}"),
                    InlineKeyboardButton(text="✖ Пропустить", callback_data=f"skip:{r['id']}"),
                ]])
            await say(text, kb)

    async def show_listings(say: Say) -> None:
        rows = app.db.query("SELECT * FROM listings WHERE status IN ('active','dry_run') ORDER BY id DESC LIMIT 30")
        if not rows:
            await say("Активных карточек нет")
            return
        text = "\n".join(f"{r['platform']} | {r['key']} | {r['price']:.0f} ₽ | {r['status']}" for r in rows)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"⏸ Снять {r['key']}", callback_data=f"unlist:{r['id']}")] for r in rows
        ])
        await say(text + "\n\nКнопкой ниже можно снять карточку с продажи:", kb)

    async def show_orders(say: Say) -> None:
        rows = app.db.query("SELECT * FROM orders ORDER BY id DESC LIMIT 15")
        text = "\n".join(f"#{r['id']} {r['platform']} {r['key']} {r['price']:.0f} ₽ — {r['status']}" for r in rows)
        await say(text or "Заказов пока нет")

    async def show_stats(say: Say) -> None:
        await say(app.stats_text())

    async def show_mode(say: Say) -> None:
        await say("Режим работы. Нажмите, чтобы переключить:", mode_markup(app))

    async def show_settings(say: Say) -> None:
        await say(settings_text(app))

    async def pause(say: Say) -> None:
        app.cfg.set_path("mode.paused", True)
        await say("⏸ Автоматическое сканирование на паузе. Заказы и выдача кодов работают. /resume — продолжить")

    async def resume(say: Say) -> None:
        app.cfg.set_path("mode.paused", False)
        await say("▶️ Сканирование продолжится в следующем цикле. /scan — запустить сейчас")

    SCREENS = {"menu": show_menu, "status": show_status, "scan": run_scan, "top": show_top, "listings": show_listings,
               "orders": show_orders, "stats": show_stats, "mode": show_mode, "settings": show_settings,
               "pause": pause, "resume": resume}

    # --- команды ------------------------------------------------------------

    @router.message(Command("start", "help"))
    async def start(m: Message) -> None:
        await m.answer("Бот арбитража цифровых товаров.\n\n" + HELP)
        await show_menu(say_to(m.chat.id))

    @router.message(Command(*SCREENS))
    async def screen(m: Message, command: CommandObject) -> None:
        await SCREENS[command.command](say_to(m.chat.id))

    @router.message(Command("set"))
    async def set_cmd(m: Message, command: CommandObject) -> None:
        parts = (command.args or "").split()
        if len(parts) != 2:
            await m.answer(settings_text(app))
            return
        await m.answer(apply_setting(app, parts[0], parts[1]))

    # --- кнопки -------------------------------------------------------------

    @router.callback_query(F.data.startswith("menu:"))
    async def cb_menu(q: CallbackQuery) -> None:
        screen = SCREENS.get(q.data.split(":", 1)[1])
        await q.answer()
        if screen:
            await screen(say_to(q.from_user.id))

    @router.callback_query(F.data.startswith("mode:"))
    async def cb_mode(q: CallbackQuery) -> None:
        flag = q.data.split(":", 1)[1]
        if flag not in MODE_FLAGS:
            await q.answer()
            return
        if flag == "dry_run" and app.cfg.dry_run:
            # Боевой режим — реальные действия на площадках и траты: только с подтверждением.
            await q.answer()
            await say_to(q.from_user.id)(
                "Включить боевой режим? Бот начнёт по-настоящему выставлять карточки, менять цены"
                " и (если включена автопокупка) тратить деньги в пределах лимитов.",
                InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔥 Да, включить", callback_data="live:on"),
                    InlineKeyboardButton(text="Отмена", callback_data="live:cancel"),
                ]]))
            return
        value = not bool(app.cfg.get_path(f"mode.{flag}"))
        app.cfg.set_path(f"mode.{flag}", value)
        await q.answer(f"{MODE_FLAGS[flag]}: {'вкл' if value else 'выкл'}")
        await q.message.edit_reply_markup(reply_markup=mode_markup(app))

    @router.callback_query(F.data.startswith("live:"))
    async def cb_live(q: CallbackQuery) -> None:
        if q.data == "live:on":
            app.cfg.set_path("mode.dry_run", False)
            await q.answer("Боевой режим включён", show_alert=True)
            await app.notify("🔥 Включён боевой режим (из Telegram)")
        else:
            await q.answer("Отменено")
        await q.message.edit_reply_markup(reply_markup=None)

    @router.callback_query(F.data.startswith("unlist:"))
    async def cb_unlist(q: CallbackQuery) -> None:
        res = await app.engine.pause_listing(int(q.data.split(":")[1]))
        await popup(q, "Снято с продажи" if res == "ok" else res, alert=res != "ok")

    @router.callback_query(F.data.startswith("list:"))
    async def cb_list(q: CallbackQuery) -> None:
        res = await app.engine.list_opportunity(int(q.data.split(":")[1]))
        await popup(q, res if res != "ok" else "Выставлено")

    @router.callback_query(F.data.startswith("skip:"))
    async def cb_skip(q: CallbackQuery) -> None:
        app.db.set_opportunity_status(int(q.data.split(":")[1]), "skipped")
        await q.answer("Пропущено")
        await q.message.edit_reply_markup(reply_markup=None)

    @router.callback_query(F.data.startswith("code:"))
    async def cb_code(q: CallbackQuery) -> None:
        order_id = int(q.data.split(":")[1])
        waiting_code[q.from_user.id] = (order_id, time.time())
        await q.answer()
        await q.message.answer(
            f"Пришлите код/данные для заказа #{order_id} одним сообщением — отправлю покупателю.\n"
            f"Жду {CODE_WAIT_SEC // 60} минут; следующее ваше сообщение уйдёт покупателю как есть.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Отмена", callback_data="nocode")]]))

    @router.callback_query(F.data == "nocode")
    async def cb_nocode(q: CallbackQuery) -> None:
        waiting_code.pop(q.from_user.id, None)
        await q.answer("Отменено")
        await q.message.edit_reply_markup(reply_markup=None)

    @router.callback_query(F.data.startswith("fwd:"))
    async def cb_fwd(q: CallbackQuery) -> None:
        order_id = int(q.data.split(":")[1])
        text = app.orders.supplier_text(order_id)
        if not text:
            await q.answer("Сообщение поставщика не найдено", show_alert=True)
            return
        res = await app.orders.deliver(order_id, text)
        await popup(q, "Отправлено покупателю" if res == "ok" else res, alert=res != "ok")

    # Без фильтра по «/»: код может начинаться с этого знака, известные команды перехвачены выше.
    @router.message(F.text)
    async def got_code(m: Message) -> None:
        order_id, asked = waiting_code.pop(m.from_user.id, (None, 0.0))
        if not order_id:
            await m.answer(HELP)
            return
        if time.time() - asked > CODE_WAIT_SEC:
            # Кнопку нажали давно и забыли: это сообщение, скорее всего, уже не код.
            await m.answer(f"Код для заказа #{order_id} я ждал {CODE_WAIT_SEC // 60} минут и перестал — покупателю "
                           "ничего не отправлено. Нажмите «Отправить код» ещё раз.")
            return
        res = await app.orders.deliver(order_id, m.text)
        await m.answer(f"✅ Заказ #{order_id} выдан" if res == "ok" else f"⚠️ {res}")

    dp.include_router(router)
    return bot, dp


async def run_polling(app: App, bot: Bot, dp: Dispatcher) -> None:
    """Опрос Telegram. Его сбой не должен останавливать панель, сканер и приём заказов."""
    while True:
        try:
            # Меню команд у поля ввода в Telegram.
            await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS])
            await dp.start_polling(bot, handle_signals=False)
            return
        except TelegramUnauthorizedError:
            log.error("telegram: неверный токен — бот выключен, остальное работает")
            app.notify.sink = None
            return
        except Exception as e:  # noqa: BLE001
            log.warning("telegram: нет связи (%s) — повтор через %s с", e, RETRY_DELAY)
            await asyncio.sleep(RETRY_DELAY)
