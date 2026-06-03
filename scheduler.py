"""
Планировщик задач — автоматические уведомления и отчёты
"""

import asyncio
import logging
from datetime import datetime, time
from telegram import Bot
from config import BOT_TOKEN, ADMIN_IDS
from database import Database
from ai_manager import AIManager

logger = logging.getLogger(__name__)
db = Database()
ai = AIManager()


async def send_daily_report():
    """Отправляет дневной отчёт администраторам в 20:00"""
    bot = Bot(token=BOT_TOKEN)
    stats = await db.get_stats()
    orders = await db.get_orders(None, limit=50)
    report = await ai.generate_daily_report(stats, orders)

    text = f"📊 *Дневной отчёт — {datetime.now().strftime('%d.%m.%Y')}*\n\n{report}"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Не удалось отправить отчёт {admin_id}: {e}")


async def remind_pending_orders():
    """Напоминает о заказах без движения > 2 дней"""
    bot = Bot(token=BOT_TOKEN)
    orders = await db.get_orders("в чистке")
    # Здесь можно добавить логику проверки времени последнего обновления
    if len(orders) > 5:
        text = f"⚠️ В чистке накопилось {len(orders)} заказов. Проверьте загрузку!"
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text)
            except Exception:
                pass


async def scheduler_loop():
    """Основной цикл планировщика"""
    logger.info("⏰ Планировщик запущен")
    while True:
        now = datetime.now()

        # Дневной отчёт в 20:00
        if now.hour == 20 and now.minute == 0:
            logger.info("📊 Отправка дневного отчёта...")
            await send_daily_report()
            await asyncio.sleep(61)  # Пауза чтобы не отправить дважды

        # Напоминание о заказах в 10:00
        if now.hour == 10 and now.minute == 0:
            await remind_pending_orders()
            await asyncio.sleep(61)

        await asyncio.sleep(30)  # Проверяем каждые 30 секунд


if __name__ == "__main__":
    asyncio.run(scheduler_loop())
