"""
AI-менеджер — Groq API (БЕСПЛАТНО)
Модель: llama-3.1-70b-versatile
"""

import os
import logging
import httpx
from typing import List, Dict

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama3-70b-8192"  # Стабильная бесплатная модель Groq

ADMIN_SYSTEM = """Ты — умный AI-менеджер компании по мойке ковров «КовёрМастер».

Твоя роль: помогать владельцу бизнеса управлять заказами, клиентами, водителями и финансами.

Ты умеешь:
- Анализировать статистику и давать советы
- Рассчитывать стоимость (300 сом/м², минимум 500 сом)
- Планировать маршруты водителей
- Предлагать акции и улучшения бизнеса
- Составлять скрипты звонков клиентам
- Анализировать проблемные заказы

Правила:
- Отвечай коротко, по делу, без лишних слов
- Используй эмодзи для удобства чтения
- Отвечай ТОЛЬКО на русском языке
- Числа форматируй с разрядами (10 000 сом)
"""

CLIENT_SYSTEM = """Ты — вежливый оператор компании «КовёрМастер» по мойке ковров.

О компании:
- Профессиональная чистка ковров любых видов
- Бесплатный забор и доставка на дом
- Срок: 1-3 рабочих дня
- Цена: от 300 сом/м², минимальный заказ 500 сом
- Работаем ежедневно 9:00-20:00

Правила: будь вежлив, отвечай коротко.
Для заявки — команда /order. Для статуса — /status.
После выполнения действия — сообщи результат кратко и по делу.
Используй эмодзи. Отвечай на том языке, на котором написал пользователь (русский, узбекский или другой).


async def _groq_request(system: str, user_message: str, max_tokens: int = 600) -> str:
    """Универсальный запрос к Groq API"""
    if not GROQ_API_KEY:
        return "⚠️ GROQ_API_KEY не задан в .env файле"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_message},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(GROQ_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        err_body = e.response.text[:200]
        logger.error(f"Groq HTTP {e.response.status_code}: {err_body}")
        return f"⚠️ Groq ошибка {e.response.status_code}: {err_body}"
    except httpx.TimeoutException:
        logger.error("Groq timeout")
        return "⚠️ AI не ответил за 20 секунд. Попробуйте ещё раз."
    except Exception as e:
        logger.error(f"Groq неизвестная ошибка: {type(e).__name__}: {e}")
        return f"⚠️ Ошибка: {type(e).__name__}: {str(e)[:100]}"


class AIManager:

    async def answer_admin(self, question: str, stats: Dict, orders: List[Dict]) -> str:
        """Отвечает администратору с контекстом бизнеса"""
        stats_text = (
            f"Статистика: сегодня {stats['today_orders']} заказов, "
            f"выручка {stats['today_revenue']:,} сом. "
            f"За месяц: {stats['month_orders']} заказов, {stats['month_revenue']:,} сом. "
            f"Активных: новых={stats['status_new']}, забрали={stats['status_picked']}, "
            f"в чистке={stats['status_cleaning']}, готово={stats['status_ready']}. "
            f"Всего клиентов: {stats['total_clients']}."
        )
        orders_text = self._format_orders(orders)
        context = f"Данные бизнеса:\n{stats_text}\n\nЗаказы:\n{orders_text}"
        return await _groq_request(ADMIN_SYSTEM, f"{context}\n\nВопрос: {question}", max_tokens=600)

    async def answer_client(self, question: str) -> str:
        """Отвечает клиенту"""
        return await _groq_request(CLIENT_SYSTEM, question, max_tokens=300)

    async def generate_daily_report(self, stats: Dict, orders: List[Dict]) -> str:
        """Генерирует дневной отчёт"""
        prompt = (
            f"Составь краткий дневной отчёт для владельца мойки ковров. "
            f"Данные: заказов сегодня={stats['today_orders']}, "
            f"выручка={stats['today_revenue']:,} сом, "
            f"активных заказов={len(orders)}. "
            "Добавь 1-2 совета на завтра. Максимум 10 строк."
        )
        return await _groq_request(ADMIN_SYSTEM, prompt, max_tokens=400)

    def _format_orders(self, orders: List[Dict]) -> str:
        if not orders:
            return "Нет активных заказов."
        lines = []
        for o in orders[:8]:
            lines.append(
                f"#{o['id']} {o['client_name']} — {o['address']}, "
                f"{o['rugs_count']} ковр., {int(o['price']):,} сом, статус: {o['status']}"
            )
        return "\n".join(lines)
