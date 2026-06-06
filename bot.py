"""
КовёрМастер — AI-бот с автономным агентом
"""

import logging
import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from config import BOT_TOKEN, ADMIN_IDS
from database import Database
from agent import CarpetAgent, transcribe_voice

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()

ROLE_LABELS = {
    "driver":  "🚗 Водитель",
    "cleaner": "🧹 Мойщик",
    "manager": "📋 Менеджер",
    "admin":   "⚙️ Администратор",
}

STATUS_EMOJI = {
    "новый":            "🆕",
    "забрали":          "🚗",
    "в чистке":         "🧹",
    "готов к доставке": "✅",
    "доставлен":        "📦",
    "отменён":          "❌",
}

STATUS_MESSAGES = {
    "забрали":          "✅ Ваш ковёр забрали. Начинаем чистку!",
    "в чистке":         "🧹 Ваш ковёр в чистке. Срок: 1-2 дня.",
    "готов к доставке": "🎉 Ваш ковёр готов и скоро будет доставлен!",
    "доставлен":        "📦 Ваш ковёр доставлен! Спасибо 🙏",
}

# ─────────────────────────────────────────────
# КЛАВИАТУРЫ
# ─────────────────────────────────────────────

def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["📋 Заказы", "➕ Новая заявка"],
        ["📊 Статистика", "👥 Клиенты"],
        ["👨‍💼 Сотрудники", "🤖 Агент"],
    ], resize_keyboard=True)


def orders_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Новые", callback_data="orders_new"),
         InlineKeyboardButton("🧹 В чистке", callback_data="orders_cleaning")],
        [InlineKeyboardButton("✅ Готовые", callback_data="orders_ready"),
         InlineKeyboardButton("📦 Все активные", callback_data="orders_all")],
    ])


def order_action_keyboard(order_id: int, status: str):
    buttons = []
    status_flow = {
        "новый":            ("забрали",          "🚗 Отметить «Забрали»"),
        "забрали":          ("в чистке",         "🧹 Отметить «В чистке»"),
        "в чистке":         ("готов к доставке", "✅ Отметить «Готов»"),
        "готов к доставке": ("доставлен",        "📦 Отметить «Доставлен»"),
    }
    if status in status_flow:
        next_s, label = status_flow[status]
        buttons.append([InlineKeyboardButton(label, callback_data=f"status_{order_id}_{next_s}")])
    buttons.append([
        InlineKeyboardButton("📞 Телефон", callback_data=f"call_{order_id}"),
        InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{order_id}"),
    ])
    buttons.append([InlineKeyboardButton("🔙 К заказам", callback_data="orders_all")])
    return InlineKeyboardMarkup(buttons)


def employees_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Список сотрудников", callback_data="emp_list")],
        [InlineKeyboardButton("➕ Добавить сотрудника", callback_data="emp_add")],
        [InlineKeyboardButton("📊 Статистика", callback_data="emp_stats_select")],
    ])

# ─────────────────────────────────────────────
# ХЕЛПЕРЫ
# ─────────────────────────────────────────────

def format_order(order: dict) -> str:
    emoji = STATUS_EMOJI.get(order["status"], "📋")
    lines = [
        f"*Заказ #{order['id']}* {emoji}",
        f"👤 {order['client_name']}",
        f"📞 {order['client_phone']}",
        f"📍 {order['address']}",
        f"🏠 {order['rugs_count']} шт · {order['total_area']} м²",
        f"💰 {int(order['price']):,} сом",
        f"📅 Забор: {order['pickup_date'] or 'не назначен'}",
        f"🔄 *{order['status']}*",
    ]
    if order.get("notes"):
        lines.append(f"📝 {order['notes']}")
    return "\n".join(lines)


async def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def notify_client_status(context, order: dict, new_status: str):
    message = STATUS_MESSAGES.get(new_status)
    if message and order.get("telegram_id"):
        try:
            await context.bot.send_message(
                chat_id=order["telegram_id"],
                text=f"*Заказ #{order['id']}*\n\n{message}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Уведомление не отправлено: {e}")

# ─────────────────────────────────────────────
# КОМАНДЫ
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.ensure_user(user.id, user.full_name, user.username)

    if await is_admin(user.id):
        await update.message.reply_text(
            f"👋 Привет, *{user.first_name}*!\n\n"
            "🏠 *КовёрМастер — AI система*\n\n"
            "🤖 Кнопка *«Агент»* — общайся голосом или текстом,\n"
            "агент сам выполнит нужные действия!\n\n"
            "Выбери действие 👇",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            f"👋 Здравствуйте, *{user.first_name}*!\n\n"
            "🏠 *КовёрМастер* — мойка ковров с забором и доставкой\n\n"
            "/order — оставить заявку\n"
            "/status — статус заказа\n"
            "/price — расчёт стоимости",
            parse_mode="Markdown"
        )


async def cmd_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "waiting_address"
    await update.message.reply_text("📍 Напишите ваш *адрес* для забора:", parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    orders = await db.get_client_orders(update.effective_user.id)
    if not orders:
        await update.message.reply_text("У вас нет активных заказов.")
        return
    for order in orders:
        emoji = STATUS_EMOJI.get(order["status"], "📋")
        await update.message.reply_text(
            f"Заказ *#{order['id']}* {emoji}\n*{order['status']}*\n{int(order['price']):,} сом",
            parse_mode="Markdown"
        )


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 *Расчёт стоимости*\n\n300 сом/м², минимум 500 сом\nЗабор и доставка бесплатно",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────────
# ОБРАБОТКА ТЕКСТА
# ─────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    state = context.user_data.get("state", "")

    if text == "/stop":
        context.user_data.clear()
        await update.message.reply_text("Главное меню.", reply_markup=main_menu_keyboard())
        return

    if state:
        await handle_state(update, context, state, text)
        return

    if await is_admin(uid):
        if text == "📋 Заказы":
            await update.message.reply_text(
                "📋 *Управление заказами*", parse_mode="Markdown", reply_markup=orders_keyboard()
            )
        elif text == "➕ Новая заявка":
            context.user_data["state"] = "waiting_address"
            context.user_data["order_data"] = {}
            await update.message.reply_text("📍 Введите адрес клиента:")
        elif text == "📊 Статистика":
            await show_stats(update, context)
        elif text == "👥 Клиенты":
            await show_clients(update, context)
        elif text == "👨‍💼 Сотрудники":
            await update.message.reply_text(
                "👨‍💼 *Сотрудники*", parse_mode="Markdown", reply_markup=employees_keyboard()
            )
        elif text == "🤖 Агент":
            context.user_data["state"] = "agent_chat"
            context.user_data["agent_history"] = []
            await update.message.reply_text(
                "🤖 *Агент активирован!*\n\n"
                "Пишите или отправляйте *голосовые сообщения*.\n"
                "Агент сам выполнит нужные действия.\n\n"
                "Примеры:\n"
                "• «Покажи новые заказы»\n"
                "• «Переведи заказ #5 в статус забрали»\n"
                "• «Назначь водителя на заказ #3»\n"
                "• «Создай заказ: Иванов, +996500000, ул. Ленина 1, 2 ковра, 8м²»\n"
                "• «Дай отчёт за сегодня»\n\n"
                "/stop — выйти из режима агента",
                parse_mode="Markdown"
            )
        else:
            # Свободный ввод — через агента
            await run_agent(update, context, text)
    else:
        await run_agent_client(update, context, text)


async def handle_state(update, context, state, text):
    uid = update.effective_user.id
    order_data = context.user_data.get("order_data", {})
    emp_data = context.user_data.get("emp_data", {})

    # ── Заказ ──
    if state == "waiting_address":
        order_data["address"] = text
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_name"
        await update.message.reply_text("👤 Имя клиента:")

    elif state == "waiting_name":
        order_data["client_name"] = text
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_phone"
        await update.message.reply_text("📞 Телефон:")

    elif state == "waiting_phone":
        order_data["client_phone"] = text
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_rugs"
        await update.message.reply_text("🏠 Сколько ковров?")

    elif state == "waiting_rugs":
        try:
            order_data["rugs_count"] = int(text)
        except ValueError:
            await update.message.reply_text("Введите цифру:")
            return
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_area"
        await update.message.reply_text("📐 Площадь (м²), например: 8.5")

    elif state == "waiting_area":
        try:
            area = float(text.replace(",", "."))
        except ValueError:
            await update.message.reply_text("Введите число:")
            return
        order_data["total_area"] = area
        order_data["price"] = max(500, area * 300)
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_date"
        await update.message.reply_text("📅 Дата забора (или «сегодня», «завтра»):")

    elif state == "waiting_date":
        order_data["pickup_date"] = text
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_notes"
        await update.message.reply_text("📝 Пожелания? (или «нет»)")

    elif state == "waiting_notes":
        order_data["notes"] = "" if text.lower() == "нет" else text
        context.user_data.clear()
        order_id = await db.create_order(uid, order_data)
        await update.message.reply_text(
            f"✅ *Заявка #{order_id} создана!*\n\n"
            f"👤 {order_data['client_name']} ({order_data['client_phone']})\n"
            f"📍 {order_data['address']}\n"
            f"💰 {int(order_data['price']):,} сом",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        driver = await db.get_free_driver()
        if driver:
            await db.assign_driver(order_id, driver["id"])
            await update.message.reply_text(f"🚗 Назначен водитель *{driver['name']}*", parse_mode="Markdown")

    # ── Сотрудник ──
    elif state == "emp_waiting_name":
        emp_data["name"] = text
        context.user_data["emp_data"] = emp_data
        context.user_data["state"] = "emp_waiting_phone"
        await update.message.reply_text("📞 Телефон сотрудника:")

    elif state == "emp_waiting_phone":
        emp_data["phone"] = text
        context.user_data["emp_data"] = emp_data
        context.user_data["state"] = "emp_waiting_role"
        await update.message.reply_text(
            "👔 Должность (цифра):\n1 — Водитель\n2 — Мойщик\n3 — Менеджер\n4 — Администратор"
        )

    elif state == "emp_waiting_role":
        role_map = {"1": "driver", "2": "cleaner", "3": "manager", "4": "admin"}
        role = role_map.get(text.strip(), "driver")
        context.user_data.clear()
        await db.add_employee(emp_data["name"], emp_data["phone"], role)
        await update.message.reply_text(
            f"✅ *{emp_data['name']}* добавлен как {ROLE_LABELS[role]}",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

    # ── Агент ──
    elif state == "agent_chat":
        await run_agent(update, context, text)

# ─────────────────────────────────────────────
# ГОЛОСОВЫЕ СООБЩЕНИЯ
# ─────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text("Голосовые сообщения доступны только для администраторов.")
        return

    await update.message.reply_text("🎙️ Распознаю голос...")

    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    audio_bytes = await file.download_as_bytearray()

    text = await transcribe_voice(bytes(audio_bytes), "voice.ogg")

    if not text:
        await update.message.reply_text("❌ Не удалось распознать голос. Попробуйте ещё раз.")
        return

    await update.message.reply_text(f"📝 Распознано: _{text}_", parse_mode="Markdown")
    await run_agent(update, context, text)

# ─────────────────────────────────────────────
# ЗАПУСК АГЕНТА
# ─────────────────────────────────────────────

async def run_agent(update, context, text: str):
    agent = CarpetAgent(db)
    history = context.user_data.get("agent_history", [])

    thinking_msg = await update.message.reply_text("🤖 Агент думает...")

    response = await agent.run(text, history)

    # Обновляем историю
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": response})
    context.user_data["agent_history"] = history[-10:]  # Храним последние 10

    await thinking_msg.delete()
    await update.message.reply_text(response, parse_mode="Markdown")


async def run_agent_client(update, context, text: str):
    from ai_manager import AIManager
    ai = AIManager()
    response = await ai.answer_client(text)
    await update.message.reply_text(response, parse_mode="Markdown")

# ─────────────────────────────────────────────
# СТАТИСТИКА / КЛИЕНТЫ
# ─────────────────────────────────────────────

async def show_stats(update, context):
    stats = await db.get_stats()
    await update.message.reply_text(
        "📊 *Статистика*\n\n"
        f"Сегодня: {stats['today_orders']} заказов · {stats['today_revenue']:,} сом\n"
        f"Месяц: {stats['month_orders']} заказов · {stats['month_revenue']:,} сом\n\n"
        f"🆕 Новых: {stats['status_new']}\n"
        f"🚗 Забрали: {stats['status_picked']}\n"
        f"🧹 В чистке: {stats['status_cleaning']}\n"
        f"✅ Готовых: {stats['status_ready']}\n\n"
        f"👥 Клиентов: {stats['total_clients']}",
        parse_mode="Markdown"
    )


async def show_clients(update, context):
    clients = await db.get_recent_clients(10)
    if not clients:
        await update.message.reply_text("Клиентов пока нет.")
        return
    lines = ["👥 *Клиенты:*\n"]
    for c in clients:
        lines.append(f"• {c['name']} — {c['phone']} ({c['orders_count']} заказов)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────
# CALLBACK КНОПКИ
# ─────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("orders_"):
        filter_map = {
            "orders_new":      "новый",
            "orders_cleaning": "в чистке",
            "orders_ready":    "готов к доставке",
            "orders_all":      None,
        }
        orders = await db.get_orders(filter_map.get(data))
        if not orders:
            await query.edit_message_text("Заказов не найдено.", reply_markup=orders_keyboard())
            return
        buttons = []
        for o in orders[:15]:
            emoji = STATUS_EMOJI.get(o["status"], "📋")
            buttons.append([InlineKeyboardButton(
                f"{emoji} #{o['id']} — {o['client_name']} ({o['rugs_count']} ковр.)",
                callback_data=f"order_{o['id']}"
            )])
        await query.edit_message_text(
            f"📋 Заказов: {len(orders)}", reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("order_"):
        order_id = int(data.split("_")[1])
        order = await db.get_order(order_id)
        if not order:
            await query.edit_message_text("Заказ не найден.")
            return
        await query.edit_message_text(
            format_order(order), parse_mode="Markdown",
            reply_markup=order_action_keyboard(order_id, order["status"])
        )

    elif data.startswith("status_"):
        parts = data.split("_", 2)
        order_id = int(parts[1])
        new_status = parts[2]
        await db.update_order_status(order_id, new_status)
        order = await db.get_order(order_id)
        await query.edit_message_text(
            f"{STATUS_EMOJI.get(new_status, '✅')} *#{order_id}* → *{new_status}*\n\n" + format_order(order),
            parse_mode="Markdown",
            reply_markup=order_action_keyboard(order_id, new_status)
        )
        await notify_client_status(context, order, new_status)

    elif data.startswith("cancel_"):
        order_id = int(data.split("_")[1])
        await db.update_order_status(order_id, "отменён")
        await query.edit_message_text(f"❌ Заказ #{order_id} отменён.")

    elif data.startswith("call_"):
        order_id = int(data.split("_")[1])
        order = await db.get_order(order_id)
        await query.answer(f"📞 {order['client_phone']}", show_alert=True)

    elif data == "emp_list":
        employees = await db.get_employees()
        if not employees:
            await query.edit_message_text("Сотрудников нет.", reply_markup=employees_keyboard())
            return
        buttons = []
        for e in employees:
            role = ROLE_LABELS.get(e.get("role", "driver"), "👤")
            buttons.append([InlineKeyboardButton(
                f"{role} {e['name']} ({e.get('active_orders',0)} заказ.)",
                callback_data=f"emp_view_{e['id']}"
            )])
        buttons.append([InlineKeyboardButton("➕ Добавить", callback_data="emp_add")])
        await query.edit_message_text(
            f"👨‍💼 *Сотрудников: {len(employees)}*",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("emp_view_"):
        emp_id = int(data.split("_")[2])
        emp = await db.get_employee(emp_id)
        stats = await db.get_employee_stats(emp_id)
        role = ROLE_LABELS.get(emp.get("role", "driver"), "👤")
        await query.edit_message_text(
            f"{role} *{emp['name']}*\n"
            f"📞 {emp.get('phone','—')}\n\n"
            f"За месяц: {stats['month']} заказов · {stats['revenue']:,} сом\n"
            f"Активных: {stats['active']} · Всего: {stats['total']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Уволить", callback_data=f"emp_fire_{emp_id}")],
                [InlineKeyboardButton("🔙 Назад", callback_data="emp_list")],
            ])
        )

    elif data.startswith("emp_fire_"):
        emp_id = int(data.split("_")[2])
        emp = await db.get_employee(emp_id)
        await db.fire_employee(emp_id)
        await query.edit_message_text(
            f"❌ *{emp['name']}* удалён.", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="emp_list")]])
        )

    elif data == "emp_add":
        context.user_data["state"] = "emp_waiting_name"
        context.user_data["emp_data"] = {}
        await query.edit_message_text("➕ Имя нового сотрудника:")

    elif data == "emp_stats_select":
        employees = await db.get_employees()
        if not employees:
            await query.answer("Сотрудников нет", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(e["name"], callback_data=f"emp_view_{e['id']}")] for e in employees]
        await query.edit_message_text("Выберите:", reply_markup=InlineKeyboardMarkup(buttons))

# ─────────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────────

async def main():
    await db.init()
    logger.info("✅ База данных инициализирована")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("order", cmd_order))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("🚀 КовёрМастер бот запущен!")

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
