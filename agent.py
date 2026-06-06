"""
КовёрМастер АГЕНТ — автономная AI система
- Принимает решения и выполняет действия сам
- Обрабатывает голосовые сообщения
- Ежедневный анализ бизнеса
- Function calling через Groq
"""

import os
import json
import httpx
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "llama-3.3-70b-versatile"

AGENT_SYSTEM = """Ты — автономный AI-агент системы управления бизнесом «КовёрМастер» (мойка ковров с забором и доставкой).

Ты можешь самостоятельно выполнять действия используя инструменты.

ПРАВИЛА ПРИНЯТИЯ РЕШЕНИЙ:
- Если пользователь просит показать заказы — вызови get_orders
- Если просит изменить статус — вызови update_order_status
- Если просит назначить водителя — вызови assign_driver
- Если просит статистику — вызови get_stats
- Если просит создать заказ — вызови create_order
- Если просит список сотрудников — вызови get_employees
- Для сложных запросов вызывай несколько инструментов по очереди

После выполнения действия — сообщи результат кратко и по делу.
Используй эмодзи. Отвечай на том языке, на котором написал пользователь (русский, узбекский или другой).
"""

# ─────────────────────────────────────────────
# ИНСТРУМЕНТЫ АГЕНТА
# ─────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_orders",
            "description": "Получить список заказов. Можно фильтровать по статусу.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Фильтр по статусу: новый, забрали, в чистке, готов к доставке, доставлен. Или пусто — все активные.",
                        "enum": ["новый", "забрали", "в чистке", "готов к доставке", "доставлен", "все"]
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_detail",
            "description": "Получить детальную информацию по конкретному заказу",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer", "description": "Номер заказа"}
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_order_status",
            "description": "Изменить статус заказа",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer", "description": "Номер заказа"},
                    "new_status": {
                        "type": "string",
                        "description": "Новый статус",
                        "enum": ["забрали", "в чистке", "готов к доставке", "доставлен", "отменён"]
                    }
                },
                "required": ["order_id", "new_status"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "assign_driver",
            "description": "Назначить водителя на заказ",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer", "description": "Номер заказа"},
                    "driver_id": {"type": "integer", "description": "ID водителя. Если 0 — назначить свободного автоматически."}
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_stats",
            "description": "Получить статистику бизнеса: выручка, заказы, клиенты",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employees",
            "description": "Получить список сотрудников с их статусом и количеством заказов",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": "Создать новый заказ",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name":  {"type": "string", "description": "Имя клиента"},
                    "client_phone": {"type": "string", "description": "Телефон клиента"},
                    "address":      {"type": "string", "description": "Адрес забора"},
                    "rugs_count":   {"type": "integer", "description": "Количество ковров"},
                    "total_area":   {"type": "number", "description": "Площадь в м²"},
                    "pickup_date":  {"type": "string", "description": "Дата забора"},
                    "notes":        {"type": "string", "description": "Примечания"}
                },
                "required": ["client_name", "client_phone", "address", "rugs_count", "total_area"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_client",
            "description": "Найти клиента по имени или телефону",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Имя или номер телефона"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_price",
            "description": "Рассчитать стоимость заказа",
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {"type": "number", "description": "Площадь ковров в м²"}
                },
                "required": ["area"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "daily_report",
            "description": "Сгенерировать подробный дневной отчёт по бизнесу",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]


# ─────────────────────────────────────────────
# ВЫПОЛНЕНИЕ ИНСТРУМЕНТОВ
# ─────────────────────────────────────────────

async def execute_tool(tool_name: str, args: dict, db) -> str:
    """Выполняет инструмент и возвращает результат в виде строки"""
    try:
        if tool_name == "get_orders":
            status = args.get("status")
            if status == "все":
                status = None
            orders = await db.get_orders(status, limit=20)
            if not orders:
                return "Заказов не найдено."
            lines = [f"Найдено заказов: {len(orders)}\n"]
            for o in orders:
                lines.append(
                    f"#{o['id']} | {o['client_name']} | {o['address']} | "
                    f"{o['rugs_count']} ковр. | {int(o['price']):,} сом | {o['status']}"
                )
            return "\n".join(lines)

        elif tool_name == "get_order_detail":
            order = await db.get_order(args["order_id"])
            if not order:
                return f"Заказ #{args['order_id']} не найден."
            return (
                f"Заказ #{order['id']}\n"
                f"Клиент: {order['client_name']} ({order['client_phone']})\n"
                f"Адрес: {order['address']}\n"
                f"Ковров: {order['rugs_count']} шт., {order['total_area']} м²\n"
                f"Сумма: {int(order['price']):,} сом\n"
                f"Статус: {order['status']}\n"
                f"Дата забора: {order.get('pickup_date', 'не назначена')}\n"
                f"Примечания: {order.get('notes', 'нет')}"
            )

        elif tool_name == "update_order_status":
            order_id = args["order_id"]
            new_status = args["new_status"]
            await db.update_order_status(order_id, new_status)
            return f"✅ Заказ #{order_id} переведён в статус «{new_status}»"

        elif tool_name == "assign_driver":
            order_id = args["order_id"]
            driver_id = args.get("driver_id", 0)
            if not driver_id:
                driver = await db.get_free_driver()
                if not driver:
                    return "❌ Свободных водителей нет."
                driver_id = driver["id"]
                driver_name = driver["name"]
            else:
                emp = await db.get_employee(driver_id)
                driver_name = emp["name"] if emp else f"ID {driver_id}"
            await db.assign_driver(order_id, driver_id)
            return f"✅ Водитель {driver_name} назначен на заказ #{order_id}"

        elif tool_name == "get_stats":
            s = await db.get_stats()
            return (
                f"📊 Статистика:\n"
                f"Сегодня: {s['today_orders']} заказов, выручка {s['today_revenue']:,} сом\n"
                f"Месяц: {s['month_orders']} заказов, выручка {s['month_revenue']:,} сом\n"
                f"Новых: {s['status_new']}, забрали: {s['status_picked']}, "
                f"в чистке: {s['status_cleaning']}, готово: {s['status_ready']}\n"
                f"Всего клиентов: {s['total_clients']}"
            )

        elif tool_name == "get_employees":
            employees = await db.get_employees()
            if not employees:
                return "Сотрудников нет."
            lines = [f"Сотрудников: {len(employees)}\n"]
            role_map = {"driver": "Водитель", "cleaner": "Мойщик", "manager": "Менеджер", "admin": "Администратор"}
            for e in employees:
                role = role_map.get(e.get("role", "driver"), "Сотрудник")
                lines.append(f"{e['name']} | {role} | {e.get('phone','')} | активных заказов: {e.get('active_orders',0)}")
            return "\n".join(lines)

        elif tool_name == "create_order":
            area = args.get("total_area", 0)
            args["price"] = max(500, area * 300)
            order_id = await db.create_order(0, args)
            driver = await db.get_free_driver()
            driver_info = ""
            if driver:
                await db.assign_driver(order_id, driver["id"])
                driver_info = f" Назначен водитель: {driver['name']}."
            return (
                f"✅ Заказ #{order_id} создан!\n"
                f"Клиент: {args['client_name']} ({args['client_phone']})\n"
                f"Адрес: {args['address']}\n"
                f"Ковров: {args['rugs_count']} шт., {area} м²\n"
                f"Сумма: {int(args['price']):,} сом\n"
                f"Дата забора: {args.get('pickup_date', 'не указана')}.{driver_info}"
            )

        elif tool_name == "find_client":
            query = args["query"].lower()
            orders = await db.get_orders(None, limit=100)
            found = [o for o in orders if
                     query in o["client_name"].lower() or
                     query in (o.get("client_phone") or "")]
            if not found:
                return f"Клиент «{args['query']}» не найден."
            lines = [f"Найдено записей: {len(found)}"]
            for o in found[:5]:
                lines.append(f"#{o['id']} | {o['client_name']} | {o['client_phone']} | {o['status']}")
            return "\n".join(lines)

        elif tool_name == "calculate_price":
            area = args["area"]
            price = max(500, area * 300)
            return f"💰 {area} м² × 300 сом = {int(price):,} сом (забор и доставка бесплатно)"

        elif tool_name == "daily_report":
            s = await db.get_stats()
            orders = await db.get_orders(None, limit=50)
            return (
                f"ДАННЫЕ ДЛЯ ОТЧЁТА:\n"
                f"Сегодня заказов: {s['today_orders']}, выручка: {s['today_revenue']:,} сом\n"
                f"Месяц: {s['month_orders']} заказов, {s['month_revenue']:,} сом\n"
                f"Активных заказов всего: {len(orders)}\n"
                f"По статусам: новых={s['status_new']}, забрали={s['status_picked']}, "
                f"чистка={s['status_cleaning']}, готово={s['status_ready']}"
            )

        else:
            return f"Инструмент {tool_name} не найден."

    except Exception as e:
        logger.error(f"Ошибка инструмента {tool_name}: {e}")
        return f"Ошибка при выполнении {tool_name}: {str(e)}"


# ─────────────────────────────────────────────
# ГЛАВНЫЙ АГЕНТ
# ─────────────────────────────────────────────

class CarpetAgent:
    def __init__(self, db):
        self.db = db

    async def run(self, user_message: str, history: List[Dict] = None) -> str:
        """
        Запускает агента: думает → вызывает инструменты → отвечает
        Поддерживает многошаговые цепочки инструментов
        """
        if not GROQ_API_KEY:
            return "⚠️ GROQ_API_KEY не задан"

        messages = [{"role": "system", "content": AGENT_SYSTEM}]
        if history:
            messages.extend(history[-6:])  # Последние 6 сообщений для контекста
        messages.append({"role": "user", "content": user_message})

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }

        max_iterations = 5  # Максимум шагов агента
        for iteration in range(max_iterations):
            payload = {
                "model": MODEL,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "max_tokens": 1000,
            }

            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(GROQ_CHAT_URL, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Groq ошибка {e.response.status_code}: {e.response.text[:200]}")
                return f"⚠️ Ошибка API: {e.response.status_code}"
            except Exception as e:
                logger.error(f"Ошибка агента: {e}")
                return f"⚠️ Ошибка: {str(e)[:100]}"

            choice = data["choices"][0]
            message = choice["message"]
            finish_reason = choice["finish_reason"]

            # Агент закончил — возвращаем ответ
            if finish_reason == "stop":
                return message.get("content", "Готово.")

            # Агент хочет вызвать инструменты
            if finish_reason == "tool_calls" and message.get("tool_calls"):
                messages.append(message)

                for tool_call in message["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    try:
                        args = json.loads(tool_call["function"]["arguments"])
                    except Exception:
                        args = {}

                    logger.info(f"🔧 Агент вызывает: {tool_name}({args})")
                    result = await execute_tool(tool_name, args, self.db)
                    logger.info(f"   Результат: {result[:100]}")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result,
                    })
                continue

            # На случай неожиданного finish_reason
            break

        return "✅ Задача выполнена."


# ─────────────────────────────────────────────
# ГОЛОСОВОЙ ВВОД — Groq Whisper
# ─────────────────────────────────────────────

async def transcribe_voice(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Транскрибирует голосовое сообщение через Groq Whisper (бесплатно)"""
    if not GROQ_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GROQ_AUDIO_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": (filename, audio_bytes, "audio/ogg")},
                data={"model": "whisper-large-v3-turbo", "language": "ru"},
            )
            resp.raise_for_status()
            return resp.json().get("text", "")
    except Exception as e:
        logger.error(f"Ошибка транскрипции: {e}")
        return ""
