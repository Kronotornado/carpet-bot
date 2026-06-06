"""
КовёрМастер — AI-бот для управления бизнесом по мойке ковров
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
from ai_manager import AIManager

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()
ai = AIManager()

# ─────────────────────────────────────────────
# РОЛИ И СТАТУСЫ
# ─────────────────────────────────────────────

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
    "в чистке":         "🧹 Ваш ковёр сейчас в чистке. Срок: 1-2 дня.",
    "готов к доставке": "🎉 Ваш ковёр готов и скоро будет доставлен!",
    "доставлен":        "📦 Ваш ковёр доставлен! Спасибо за доверие 🙏",
}

# ─────────────────────────────────────────────
# КЛАВИАТУРЫ
# ─────────────────────────────────────────────

def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["📋 Заказы", "➕ Новая заявка"],
        ["📊 Статистика", "👥 Клиенты"],
        ["👨‍💼 Сотрудники", "💬 Спросить AI"],
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
        InlineKeyboardButton("📞 Телефон клиента", callback_data=f"call_{order_id}"),
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
        f"🏠 Ковров: {order['rugs_count']} шт · {order['total_area']} м²",
        f"💰 Сумма: {int(order['price']):,} сом",
        f"📅 Забор: {order['pickup_date'] or 'не назначен'}",
        f"🔄 Статус: *{order['status']}*",
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
            logger.warning(f"Не удалось уведомить клиента: {e}")

# ─────────────────────────────────────────────
# КОМАНДЫ
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.ensure_user(user.id, user.full_name, user.username)

    if await is_admin(user.id):
        text = (
            f"👋 Добро пожаловать, *{user.first_name}*!\n\n"
            "🏠 *КовёрМастер — AI-менеджер*\n\n"
            "Выберите действие ниже 👇"
        )
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
    else:
        text = (
            f"👋 Здравствуйте, *{user.first_name}*!\n\n"
            "🏠 *КовёрМастер* — профессиональная чистка ковров\n"
            "с бесплатным забором и доставкой!\n\n"
            "/order — оставить заявку\n"
            "/status — статус заказа\n"
            "/price — расчёт стоимости"
        )
        await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "waiting_address"
    await update.message.reply_text(
        "📍 Напишите ваш *адрес* для забора ковра:",
        parse_mode="Markdown"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    orders = await db.get_client_orders(update.effective_user.id)
    if not orders:
        await update.message.reply_text("У вас нет активных заказов.")
        return
    for order in orders:
        emoji = STATUS_EMOJI.get(order["status"], "📋")
        await update.message.reply_text(
            f"Заказ *#{order['id']}* {emoji}\nСтатус: *{order['status']}*\nСумма: {int(order['price']):,} сом",
            parse_mode="Markdown"
        )


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 *Расчёт стоимости*\n\n"
        "Базовая цена: *300 сом/м²*\n"
        "Минимальный заказ: *500 сом*\n"
        "Забор и доставка: *бесплатно*",
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
                "📋 *Управление заказами*\nВыберите фильтр:",
                parse_mode="Markdown",
                reply_markup=orders_keyboard()
            )
        elif text == "➕ Новая заявка":
            context.user_data["state"] = "waiting_address"
            context.user_data["order_data"] = {}
            await update.message.reply_text("📍 Введите адрес клиента:", parse_mode="Markdown")
        elif text == "📊 Статистика":
            await show_stats(update, context)
        elif text == "👥 Клиенты":
            await show_clients(update, context)
        elif text == "👨‍💼 Сотрудники":
            await update.message.reply_text(
                "👨‍💼 *Управление сотрудниками*",
                parse_mode="Markdown",
                reply_markup=employees_keyboard()
            )
        elif text == "💬 Спросить AI":
            context.user_data["state"] = "ai_chat"
            await update.message.reply_text(
                "🤖 Режим AI активирован. Задайте любой вопрос.\nНапишите /stop чтобы выйти."
            )
        else:
            await ai_respond(update, context, text)
    else:
        await ai_respond_client(update, context, text)


async def handle_state(update, context, state, text):
    uid = update.effective_user.id
    order_data = context.user_data.get("order_data", {})
    emp_data = context.user_data.get("emp_data", {})

    # ── Заказ ──
    if state == "waiting_address":
        order_data["address"] = text
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_name"
        await update.message.reply_text("👤 Введите *имя клиента*:", parse_mode="Markdown")

    elif state == "waiting_name":
        order_data["client_name"] = text
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_phone"
        await update.message.reply_text("📞 Введите *номер телефона*:", parse_mode="Markdown")

    elif state == "waiting_phone":
        order_data["client_phone"] = text
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_rugs"
        await update.message.reply_text("🏠 Сколько *ковров* нужно забрать?", parse_mode="Markdown")

    elif state == "waiting_rugs":
        try:
            order_data["rugs_count"] = int(text)
        except ValueError:
            await update.message.reply_text("Введите цифру, например: 2")
            return
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_area"
        await update.message.reply_text("📐 Общая *площадь ковров* (м²)? Пример: 8.5", parse_mode="Markdown")

    elif state == "waiting_area":
        try:
            area = float(text.replace(",", "."))
        except ValueError:
            await update.message.reply_text("Введите число, например: 8.5")
            return
        order_data["total_area"] = area
        order_data["price"] = max(500, area * 300)
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_date"
        await update.message.reply_text(
            "📅 На какую дату назначить *забор*?\n_(Формат: ДД.ММ.ГГГГ или «сегодня», «завтра»)_",
            parse_mode="Markdown"
        )

    elif state == "waiting_date":
        order_data["pickup_date"] = text
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_notes"
        await update.message.reply_text("📝 Есть особые пожелания? (или напишите «нет»)")

    elif state == "waiting_notes":
        order_data["notes"] = "" if text.lower() == "нет" else text
        context.user_data.clear()

        order_id = await db.create_order(uid, order_data)
        await update.message.reply_text(
            f"✅ *Заявка #{order_id} создана!*\n\n"
            f"👤 {order_data['client_name']}\n"
            f"📞 {order_data['client_phone']}\n"
            f"📍 {order_data['address']}\n"
            f"🏠 {order_data['rugs_count']} ковр · {order_data['total_area']} м²\n"
            f"💰 Сумма: *{int(order_data['price']):,} сом*\n"
            f"📅 Забор: {order_data['pickup_date']}",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        driver = await db.get_free_driver()
        if driver:
            await db.assign_driver(order_id, driver["id"])
            await update.message.reply_text(
                f"🚗 Водитель *{driver['name']}* назначен на заказ #{order_id}",
                parse_mode="Markdown"
            )

    # ── Сотрудник ──
    elif state == "emp_waiting_name":
        emp_data["name"] = text
        context.user_data["emp_data"] = emp_data
        context.user_data["state"] = "emp_waiting_phone"
        await update.message.reply_text("📞 Введите номер телефона сотрудника:")

    elif state == "emp_waiting_phone":
        emp_data["phone"] = text
        context.user_data["emp_data"] = emp_data
        context.user_data["state"] = "emp_waiting_role"
        await update.message.reply_text(
            "👔 Выберите должность — напишите цифру:\n\n"
            "1 — 🚗 Водитель\n"
            "2 — 🧹 Мойщик\n"
            "3 — 📋 Менеджер\n"
            "4 — ⚙️ Администратор"
        )

    elif state == "emp_waiting_role":
        role_map = {"1": "driver", "2": "cleaner", "3": "manager", "4": "admin"}
        role = role_map.get(text.strip(), "driver")
        emp_data["role"] = role
        context.user_data.clear()

        await db.add_employee(emp_data["name"], emp_data["phone"], role)
        role_label = ROLE_LABELS.get(role, "👤")
        await update.message.reply_text(
            f"✅ *Сотрудник добавлен!*\n\n"
            f"👤 {emp_data['name']}\n"
            f"📞 {emp_data['phone']}\n"
            f"{role_label}",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

    # ── AI чат ──
    elif state == "ai_chat":
        await ai_respond(update, context, text)

# ─────────────────────────────────────────────
# СТАТИСТИКА / КЛИЕНТЫ
# ─────────────────────────────────────────────

async def show_stats(update, context):
    stats = await db.get_stats()
    await update.message.reply_text(
        "📊 *Статистика бизнеса*\n\n"
        f"📅 *Сегодня:*\n"
        f"  Новых заявок: {stats['today_orders']}\n"
        f"  Выручка: {stats['today_revenue']:,} сом\n\n"
        f"📅 *Месяц:*\n"
        f"  Заказов: {stats['month_orders']}\n"
        f"  Выручка: {stats['month_revenue']:,} сом\n\n"
        f"📦 *Активные заказы:*\n"
        f"  🆕 Новых: {stats['status_new']}\n"
        f"  🚗 Забрали: {stats['status_picked']}\n"
        f"  🧹 В чистке: {stats['status_cleaning']}\n"
        f"  ✅ Готовы: {stats['status_ready']}\n\n"
        f"👥 Всего клиентов: {stats['total_clients']}",
        parse_mode="Markdown"
    )


async def show_clients(update, context):
    clients = await db.get_recent_clients(10)
    if not clients:
        await update.message.reply_text("Клиентов пока нет.")
        return
    lines = ["👥 *Последние клиенты:*\n"]
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

    # ── Заказы ──
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
            label = f"{emoji} #{o['id']} — {o['client_name']} ({o['rugs_count']} ковр.)"
            buttons.append([InlineKeyboardButton(label, callback_data=f"order_{o['id']}")])
        await query.edit_message_text(
            f"📋 Заказов: {len(orders)}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("order_"):
        order_id = int(data.split("_")[1])
        order = await db.get_order(order_id)
        if not order:
            await query.edit_message_text("Заказ не найден.")
            return
        await query.edit_message_text(
            format_order(order),
            parse_mode="Markdown",
            reply_markup=order_action_keyboard(order_id, order["status"])
        )

    elif data.startswith("status_"):
        parts = data.split("_", 2)
        order_id = int(parts[1])
        new_status = parts[2]
        await db.update_order_status(order_id, new_status)
        order = await db.get_order(order_id)
        await query.edit_message_text(
            f"{STATUS_EMOJI.get(new_status, '✅')} Статус заказа *#{order_id}* → *{new_status}*\n\n"
            + format_order(order),
            parse_mode="Markdown",
            reply_markup=order_action_keyboard(order_id, new_status)
        )
        await notify_client_status(context, order, new_status)

    elif data.startswith("cancel_"):
        order_id = int(data.split("_")[1])
        await db.update_order_status(order_id, "отменён")
        await query.edit_message_text(f"❌ Заказ #{order_id} отменён.", reply_markup=orders_keyboard())

    elif data.startswith("call_"):
        order_id = int(data.split("_")[1])
        order = await db.get_order(order_id)
        await query.answer(f"Телефон: {order['client_phone']}", show_alert=True)

    # ── Сотрудники ──
    elif data == "emp_list":
        employees = await db.get_employees()
        if not employees:
            await query.edit_message_text(
                "Сотрудников пока нет. Добавьте первого!",
                reply_markup=employees_keyboard()
            )
            return
        buttons = []
        for e in employees:
            role = ROLE_LABELS.get(e.get("role", "driver"), "👤")
            active = e.get("active_orders", 0)
            buttons.append([InlineKeyboardButton(
                f"{role} {e['name']} ({active} заказ.)",
                callback_data=f"emp_view_{e['id']}"
            )])
        buttons.append([InlineKeyboardButton("➕ Добавить", callback_data="emp_add")])
        await query.edit_message_text(
            f"👨‍💼 *Сотрудников: {len(employees)}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("emp_view_"):
        emp_id = int(data.split("_")[2])
        emp = await db.get_employee(emp_id)
        stats = await db.get_employee_stats(emp_id)
        role = ROLE_LABELS.get(emp.get("role", "driver"), "👤")
        await query.edit_message_text(
            f"{role} *{emp['name']}*\n"
            f"📞 {emp.get('phone', 'не указан')}\n\n"
            f"📊 *Статистика за месяц:*\n"
            f"  Заказов: {stats['month']}\n"
            f"  Выручка: {stats['revenue']:,} сом\n"
            f"  Активных: {stats['active']}\n"
            f"  Всего за всё время: {stats['total']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Уволить", callback_data=f"emp_fire_{emp_id}")],
                [InlineKeyboardButton("🔙 К списку", callback_data="emp_list")],
            ])
        )

    elif data.startswith("emp_fire_"):
        emp_id = int(data.split("_")[2])
        emp = await db.get_employee(emp_id)
        await db.fire_employee(emp_id)
        await query.edit_message_text(
            f"❌ Сотрудник *{emp['name']}* удалён.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 К списку", callback_data="emp_list")]
            ])
        )

    elif data == "emp_add":
        context.user_data["state"] = "emp_waiting_name"
        context.user_data["emp_data"] = {}
        await query.edit_message_text("➕ *Добавление сотрудника*\n\n👤 Введите имя:", parse_mode="Markdown")

    elif data == "emp_stats_select":
        employees = await db.get_employees()
        if not employees:
            await query.answer("Сотрудников нет", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(e["name"], callback_data=f"emp_view_{e['id']}")] for e in employees]
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="emp_back")])
        await query.edit_message_text("Выберите сотрудника:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "emp_back":
        await query.edit_message_text(
            "👨‍💼 *Управление сотрудниками*",
            parse_mode="Markdown",
            reply_markup=employees_keyboard()
        )

# ─────────────────────────────────────────────
# AI ОТВЕТЫ
# ─────────────────────────────────────────────

async def ai_respond(update, context, text: str):
    stats = await db.get_stats()
    orders = await db.get_orders(None, limit=20)
    await update.message.reply_text("⏳ Думаю...")
    response = await ai.answer_admin(text, stats, orders)
    await update.message.reply_text(response, parse_mode="Markdown")


async def ai_respond_client(update, context, text: str):
    response = await ai.answer_client(text)
    await update.message.reply_text(response, parse_mode="Markdown")

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
