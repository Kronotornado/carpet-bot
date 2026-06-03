"""
КовёрМастер — AI-бот для управления бизнесом по мойке ковров
Автор: КовёрМастер Team
"""

import logging
import asyncio
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from config import BOT_TOKEN, ADMIN_IDS
from database import Database
from ai_manager import AIManager

# Логи
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()
ai = AIManager()


# ─────────────────────────────────────────────
# КЛАВИАТУРЫ
# ─────────────────────────────────────────────

def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["📋 Заказы", "➕ Новая заявка"],
        ["📊 Статистика", "👥 Клиенты"],
        ["🚗 Водители", "💬 Спросить AI"],
    ], resize_keyboard=True)


def orders_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Новые", callback_data="orders_new"),
         InlineKeyboardButton("🧹 В чистке", callback_data="orders_cleaning")],
        [InlineKeyboardButton("✅ Готовые", callback_data="orders_ready"),
         InlineKeyboardButton("📦 Все активные", callback_data="orders_all")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
    ])


def order_action_keyboard(order_id: int, status: str):
    buttons = []

    status_flow = {
        "новый":             ("забрали",           "🚗 Отметить «Забрали»"),
        "забрали":           ("в чистке",          "🧹 Отметить «В чистке»"),
        "в чистке":          ("готов к доставке",  "✅ Отметить «Готов»"),
        "готов к доставке":  ("доставлен",         "📦 Отметить «Доставлен»"),
    }

    if status in status_flow:
        next_status, label = status_flow[status]
        buttons.append([InlineKeyboardButton(
            label, callback_data=f"status_{order_id}_{next_status}"
        )])

    buttons.append([
        InlineKeyboardButton("📞 Позвонить клиенту", callback_data=f"call_{order_id}"),
        InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{order_id}"),
    ])
    buttons.append([InlineKeyboardButton("🔙 К заказам", callback_data="orders_all")])
    return InlineKeyboardMarkup(buttons)


# ─────────────────────────────────────────────
# ХЕЛПЕРЫ
# ─────────────────────────────────────────────

STATUS_EMOJI = {
    "новый":            "🆕",
    "забрали":          "🚗",
    "в чистке":         "🧹",
    "готов к доставке": "✅",
    "доставлен":        "📦",
    "отменён":          "❌",
}

def format_order(order: dict) -> str:
    emoji = STATUS_EMOJI.get(order["status"], "📋")
    lines = [
        f"*Заказ #{order['id']}* {emoji}",
        f"👤 {order['client_name']}",
        f"📞 {order['client_phone']}",
        f"📍 {order['address']}",
        f"🏠 Ковров: {order['rugs_count']} шт · {order['total_area']} м²",
        f"💰 Сумма: {int(order['price']):,} ₽",
        f"📅 Забор: {order['pickup_date'] or 'не назначен'}",
        f"📅 Доставка: {order['delivery_date'] or 'не назначена'}",
        f"🔄 Статус: *{order['status']}*",
    ]
    if order.get("notes"):
        lines.append(f"📝 {order['notes']}")
    return "\n".join(lines)


async def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ─────────────────────────────────────────────
# КОМАНДЫ
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    await db.ensure_user(uid, user.full_name, user.username)

    if await is_admin(uid):
        text = (
            f"👋 Добро пожаловать, *{user.first_name}*!\n\n"
            "🏠 *КовёрМастер — AI-менеджер*\n\n"
            "Я помогу вам:\n"
            "• Принимать и отслеживать заказы\n"
            "• Управлять водителями\n"
            "• Получать аналитику\n"
            "• Уведомлять клиентов\n\n"
            "Выберите действие ниже 👇"
        )
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    else:
        # Клиент
        text = (
            f"👋 Здравствуйте, *{user.first_name}*!\n\n"
            "🏠 *КовёрМастер* — профессиональная чистка ковров\n"
            "с бесплатным забором и доставкой!\n\n"
            "Используйте /order чтобы оставить заявку\n"
            "Используйте /status чтобы проверить статус\n"
            "Используйте /price для расчёта стоимости"
        )
        await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Клиент оставляет заявку"""
    context.user_data["state"] = "waiting_address"
    await update.message.reply_text(
        "📍 Напишите ваш *адрес* для забора ковра\n"
        "_(улица, дом, квартира)_",
        parse_mode="Markdown"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Клиент проверяет статус своих заказов"""
    uid = update.effective_user.id
    orders = await db.get_client_orders(uid)
    if not orders:
        await update.message.reply_text("У вас нет активных заказов.")
        return
    for order in orders:
        emoji = STATUS_EMOJI.get(order["status"], "📋")
        text = (
            f"Заказ *#{order['id']}* {emoji}\n"
            f"Статус: *{order['status']}*\n"
            f"Сумма: {int(order['price']):,} ₽"
        )
        await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Расчёт стоимости"""
    await update.message.reply_text(
        "💰 *Расчёт стоимости*\n\n"
        "Базовая цена: *300 ₽/м²*\n"
        "Минимальный заказ: *500 ₽*\n"
        "Забор и доставка: *бесплатно*\n\n"
        "Напишите площадь ковра (например: _6_) чтобы рассчитать.",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────
# ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ (МЕНЮ)
# ─────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    state = context.user_data.get("state", "")

    # ── Обработка пошаговых диалогов ──
    if state:
        await handle_state(update, context, state, text)
        return

    # ── Меню для администратора ──
    if await is_admin(uid):
        if text == "📋 Заказы":
            await show_orders_menu(update, context)
        elif text == "➕ Новая заявка":
            await start_new_order(update, context)
        elif text == "📊 Статистика":
            await show_stats(update, context)
        elif text == "👥 Клиенты":
            await show_clients(update, context)
        elif text == "🚗 Водители":
            await show_drivers(update, context)
        elif text == "💬 Спросить AI":
            context.user_data["state"] = "ai_chat"
            await update.message.reply_text(
                "🤖 Режим AI-консультанта активирован.\n"
                "Задайте любой вопрос по бизнесу.\n\n"
                "Напишите /stop чтобы выйти."
            )
        else:
            # Свободный ввод — AI отвечает
            await ai_respond(update, context, text)
    else:
        # Клиент — передаём AI
        await ai_respond_client(update, context, text)


async def handle_state(update, context, state, text):
    """Пошаговый диалог создания заявки"""
    uid = update.effective_user.id

    if text == "/stop":
        context.user_data.clear()
        await update.message.reply_text("✅ Выход из режима. Главное меню.", reply_markup=main_menu_keyboard())
        return

    order_data = context.user_data.get("order_data", {})

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
        await update.message.reply_text("📐 Общая *площадь ковров* (м²)?\nПример: 8.5", parse_mode="Markdown")

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
            f"📅 На какую дату назначить *забор*?\n"
            f"_(Формат: ДД.ММ.ГГГГ, или напишите «сегодня», «завтра»)_",
            parse_mode="Markdown"
        )

    elif state == "waiting_date":
        order_data["pickup_date"] = text
        context.user_data["order_data"] = order_data
        context.user_data["state"] = "waiting_notes"
        await update.message.reply_text(
            "📝 Есть особые пожелания? (или напишите «нет»)"
        )

    elif state == "waiting_notes":
        order_data["notes"] = "" if text.lower() == "нет" else text
        context.user_data.clear()

        # Сохраняем заказ в БД
        order_id = await db.create_order(uid, order_data)

        text_confirm = (
            f"✅ *Заявка #{order_id} создана!*\n\n"
            f"👤 {order_data['client_name']}\n"
            f"📞 {order_data['client_phone']}\n"
            f"📍 {order_data['address']}\n"
            f"🏠 {order_data['rugs_count']} ковр · {order_data['total_area']} м²\n"
            f"💰 Сумма: *{int(order_data['price']):,} ₽*\n"
            f"📅 Забор: {order_data['pickup_date']}"
        )
        await update.message.reply_text(
            text_confirm, parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

        # Назначаем водителя автоматически
        driver = await db.get_free_driver()
        if driver:
            await db.assign_driver(order_id, driver["id"])
            await update.message.reply_text(
                f"🚗 Водитель *{driver['name']}* назначен на заказ #{order_id}",
                parse_mode="Markdown"
            )

    elif state == "ai_chat":
        await ai_respond(update, context, text)


# ─────────────────────────────────────────────
# ФУНКЦИИ МЕНЮ
# ─────────────────────────────────────────────

async def show_orders_menu(update, context):
    await update.message.reply_text(
        "📋 *Управление заказами*\nВыберите фильтр:",
        parse_mode="Markdown",
        reply_markup=orders_keyboard()
    )


async def start_new_order(update, context):
    context.user_data["state"] = "waiting_address"
    context.user_data["order_data"] = {}
    await update.message.reply_text(
        "➕ *Новая заявка*\n\n📍 Введите адрес клиента:",
        parse_mode="Markdown"
    )


async def show_stats(update, context):
    stats = await db.get_stats()
    text = (
        "📊 *Статистика бизнеса*\n\n"
        f"📅 *Сегодня:*\n"
        f"  Новых заявок: {stats['today_orders']}\n"
        f"  Выручка: {stats['today_revenue']:,} ₽\n\n"
        f"📅 *Месяц:*\n"
        f"  Заказов: {stats['month_orders']}\n"
        f"  Выручка: {stats['month_revenue']:,} ₽\n\n"
        f"📦 *Активные заказы:*\n"
        f"  🆕 Новых: {stats['status_new']}\n"
        f"  🚗 Забрали: {stats['status_picked']}\n"
        f"  🧹 В чистке: {stats['status_cleaning']}\n"
        f"  ✅ Готовы к доставке: {stats['status_ready']}\n\n"
        f"👥 Всего клиентов: {stats['total_clients']}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def show_clients(update, context):
    clients = await db.get_recent_clients(10)
    if not clients:
        await update.message.reply_text("Клиентов пока нет.")
        return
    lines = ["👥 *Последние клиенты:*\n"]
    for c in clients:
        lines.append(f"• {c['name']} — {c['phone']} ({c['orders_count']} заказов)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def show_drivers(update, context):
    drivers = await db.get_drivers()
    if not drivers:
        await update.message.reply_text("Водители не добавлены.")
        return
    lines = ["🚗 *Водители:*\n"]
    for d in drivers:
        status = "🟢 Свободен" if d["is_free"] else f"🔴 В маршруте ({d['active_orders']} заказов)"
        lines.append(f"• {d['name']} — {status}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
# CALLBACK КНОПКИ (INLINE)
# ─────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Фильтрация заказов
    if data.startswith("orders_"):
        filter_map = {
            "orders_new":      "новый",
            "orders_cleaning": "в чистке",
            "orders_ready":    "готов к доставке",
            "orders_all":      None,
        }
        status_filter = filter_map.get(data)
        orders = await db.get_orders(status_filter)
        if not orders:
            await query.edit_message_text("Заказов не найдено.", reply_markup=orders_keyboard())
            return

        buttons = []
        for o in orders[:15]:
            emoji = STATUS_EMOJI.get(o["status"], "📋")
            label = f"{emoji} #{o['id']} — {o['client_name']} ({o['rugs_count']} ковр.)"
            buttons.append([InlineKeyboardButton(label, callback_data=f"order_{o['id']}")])
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back_main")])
        await query.edit_message_text(
            f"📋 Заказов: {len(orders)}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # Детали заказа
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

    # Смена статуса
    elif data.startswith("status_"):
        parts = data.split("_", 2)
        order_id = int(parts[1])
        new_status = parts[2]
        await db.update_order_status(order_id, new_status)

        order = await db.get_order(order_id)
        emoji = STATUS_EMOJI.get(new_status, "✅")
        await query.edit_message_text(
            f"{emoji} Статус заказа *#{order_id}* изменён на *{new_status}*\n\n"
            + format_order(order),
            parse_mode="Markdown",
            reply_markup=order_action_keyboard(order_id, new_status)
        )

        # Уведомляем клиента
        await notify_client_status(context, order, new_status)

    # Отмена заказа
    elif data.startswith("cancel_"):
        order_id = int(data.split("_")[1])
        await db.update_order_status(order_id, "отменён")
        await query.edit_message_text(
            f"❌ Заказ #{order_id} отменён.",
            reply_markup=orders_keyboard()
        )

    # Контакт клиента
    elif data.startswith("call_"):
        order_id = int(data.split("_")[1])
        order = await db.get_order(order_id)
        await query.answer(f"Телефон: {order['client_phone']}", show_alert=True)

    elif data == "back_main":
        await query.edit_message_text("Главное меню", reply_markup=orders_keyboard())


# ─────────────────────────────────────────────
# УВЕДОМЛЕНИЯ КЛИЕНТАМ
# ─────────────────────────────────────────────

STATUS_MESSAGES = {
    "забрали":          "✅ Ваш ковёр забрали. Начинаем чистку! Ждите уведомления.",
    "в чистке":         "🧹 Ваш ковёр сейчас в чистке. Срок: 1-2 дня.",
    "готов к доставке": "🎉 Ваш ковёр готов и скоро будет доставлен!",
    "доставлен":        "📦 Ваш ковёр доставлен! Спасибо за доверие 🙏\n\nОставьте отзыв: /review",
}

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
# AI ОТВЕТЫ
# ─────────────────────────────────────────────

async def ai_respond(update, context, text: str):
    """AI отвечает администратору с доступом к данным"""
    stats = await db.get_stats()
    orders = await db.get_orders(None, limit=20)

    await update.message.reply_text("⏳ Думаю...")

    response = await ai.answer_admin(text, stats, orders)
    await update.message.reply_text(response, parse_mode="Markdown")


async def ai_respond_client(update, context, text: str):
    """AI отвечает клиенту"""
    response = await ai.answer_client(text)
    await update.message.reply_text(response, parse_mode="Markdown")


# ─────────────────────────────────────────────
# ЗАПУСК БОТА
# ─────────────────────────────────────────────

async def main():
    # Инициализируем базу данных ПЕРВЫМ делом
    await db.init()
    logger.info("✅ База данных инициализирована")

    app = Application.builder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("order", cmd_order))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("price", cmd_price))

    # Сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Кнопки
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("🚀 КовёрМастер бот запущен!")

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        # Ждём бесконечно пока не нажмут Ctrl+C
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
