"""
Модуль базы данных — SQLite (для старта) / PostgreSQL (для продакшена)
"""

import aiosqlite
import logging
from datetime import date, datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)
DB_PATH = "carpet_bot.db"


class Database:
    def __init__(self):
        self.db_path = DB_PATH

    async def init(self):
        """Создаёт таблицы при первом запуске"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    name        TEXT,
                    username    TEXT,
                    role        TEXT DEFAULT 'client',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS clients (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE,
                    name        TEXT NOT NULL,
                    phone       TEXT,
                    address     TEXT,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS drivers (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    phone       TEXT,
                    telegram_id INTEGER,
                    is_active   INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id   INTEGER,
                    client_name   TEXT NOT NULL,
                    client_phone  TEXT,
                    address       TEXT NOT NULL,
                    rugs_count    INTEGER DEFAULT 1,
                    total_area    REAL DEFAULT 0,
                    price         REAL DEFAULT 0,
                    status        TEXT DEFAULT 'новый',
                    driver_id     INTEGER REFERENCES drivers(id),
                    pickup_date   TEXT,
                    delivery_date TEXT,
                    notes         TEXT,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS notifications (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id   INTEGER REFERENCES orders(id),
                    message    TEXT,
                    sent_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.commit()

            # Добавляем тестовых водителей если нет
            cursor = await db.execute("SELECT COUNT(*) FROM drivers")
            count = (await cursor.fetchone())[0]
            if count == 0:
                await db.executemany(
                    "INSERT INTO drivers (name, phone) VALUES (?, ?)",
                    [("Санжар", "+998901234567"), ("Бахром", "+998907654321")]
                )
                await db.commit()
                logger.info("✅ Добавлены тестовые водители")

    # ─── ПОЛЬЗОВАТЕЛИ ───

    async def ensure_user(self, telegram_id: int, name: str, username: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO users (telegram_id, name, username)
                VALUES (?, ?, ?)
            """, (telegram_id, name, username))
            await db.commit()

    # ─── ЗАКАЗЫ ───

    async def create_order(self, telegram_id: int, data: dict) -> int:
        """Создаёт новый заказ и возвращает его ID"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO orders
                    (telegram_id, client_name, client_phone, address,
                     rugs_count, total_area, price, pickup_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                telegram_id,
                data.get("client_name", ""),
                data.get("client_phone", ""),
                data.get("address", ""),
                data.get("rugs_count", 1),
                data.get("total_area", 0),
                data.get("price", 0),
                data.get("pickup_date", ""),
                data.get("notes", ""),
            ))
            await db.commit()
            return cursor.lastrowid

    async def get_order(self, order_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT o.*, d.name as driver_name
                FROM orders o
                LEFT JOIN drivers d ON o.driver_id = d.id
                WHERE o.id = ?
            """, (order_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_orders(
        self,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                cursor = await db.execute("""
                    SELECT o.*, d.name as driver_name
                    FROM orders o
                    LEFT JOIN drivers d ON o.driver_id = d.id
                    WHERE o.status = ?
                    ORDER BY o.created_at DESC
                    LIMIT ?
                """, (status, limit))
            else:
                cursor = await db.execute("""
                    SELECT o.*, d.name as driver_name
                    FROM orders o
                    LEFT JOIN drivers d ON o.driver_id = d.id
                    WHERE o.status NOT IN ('доставлен', 'отменён')
                    ORDER BY o.created_at DESC
                    LIMIT ?
                """, (limit,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_client_orders(self, telegram_id: int) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM orders
                WHERE telegram_id = ?
                AND status NOT IN ('доставлен', 'отменён')
                ORDER BY created_at DESC
                LIMIT 10
            """, (telegram_id,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def update_order_status(self, order_id: int, new_status: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE orders
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_status, order_id))
            await db.commit()
            logger.info(f"Заказ #{order_id} → статус: {new_status}")

    async def assign_driver(self, order_id: int, driver_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE orders SET driver_id = ? WHERE id = ?",
                (driver_id, order_id)
            )
            await db.commit()

    # ─── ВОДИТЕЛИ ───

    async def get_drivers(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT
                    d.*,
                    COUNT(o.id) as active_orders,
                    CASE WHEN COUNT(o.id) = 0 THEN 1 ELSE 0 END as is_free
                FROM drivers d
                LEFT JOIN orders o
                    ON o.driver_id = d.id
                    AND o.status NOT IN ('доставлен', 'отменён')
                WHERE d.is_active = 1
                GROUP BY d.id
            """)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_free_driver(self) -> Optional[Dict]:
        drivers = await self.get_drivers()
        for d in drivers:
            if d["is_free"]:
                return d
        return None

    # ─── КЛИЕНТЫ ───

    async def get_recent_clients(self, limit: int = 10) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT
                    client_name as name,
                    client_phone as phone,
                    COUNT(*) as orders_count,
                    MAX(created_at) as last_order
                FROM orders
                GROUP BY client_phone
                ORDER BY last_order DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ─── СТАТИСТИКА ───

    async def get_stats(self) -> Dict:
        today = date.today().isoformat()
        month_start = date.today().replace(day=1).isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            async def fetch_one(sql, params=()):
                cur = await db.execute(sql, params)
                row = await cur.fetchone()
                return row[0] if row else 0

            today_orders   = await fetch_one("SELECT COUNT(*) FROM orders WHERE DATE(created_at) = ?", (today,))
            today_revenue  = await fetch_one("SELECT COALESCE(SUM(price),0) FROM orders WHERE DATE(created_at) = ? AND status != 'отменён'", (today,))
            month_orders   = await fetch_one("SELECT COUNT(*) FROM orders WHERE DATE(created_at) >= ?", (month_start,))
            month_revenue  = await fetch_one("SELECT COALESCE(SUM(price),0) FROM orders WHERE DATE(created_at) >= ? AND status != 'отменён'", (month_start,))
            total_clients  = await fetch_one("SELECT COUNT(DISTINCT client_phone) FROM orders")
            status_new     = await fetch_one("SELECT COUNT(*) FROM orders WHERE status = 'новый'")
            status_picked  = await fetch_one("SELECT COUNT(*) FROM orders WHERE status = 'забрали'")
            status_cleaning= await fetch_one("SELECT COUNT(*) FROM orders WHERE status = 'в чистке'")
            status_ready   = await fetch_one("SELECT COUNT(*) FROM orders WHERE status = 'готов к доставке'")

        return {
            "today_orders":    today_orders,
            "today_revenue":   int(today_revenue),
            "month_orders":    month_orders,
            "month_revenue":   int(month_revenue),
            "total_clients":   total_clients,
            "status_new":      status_new,
            "status_picked":   status_picked,
            "status_cleaning": status_cleaning,
            "status_ready":    status_ready,
        }

    # ─── СОТРУДНИКИ ───

    async def add_employee(self, name: str, phone: str, role: str, telegram_id: int = None) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            # Добавляем колонки если их нет (миграция)
            try:
                await db.execute("ALTER TABLE drivers ADD COLUMN role TEXT DEFAULT 'driver'")
                await db.commit()
            except Exception:
                pass
            cursor = await db.execute(
                "INSERT INTO drivers (name, phone, telegram_id, role) VALUES (?, ?, ?, ?)",
                (name, phone, telegram_id, role)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_employees(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT
                    d.*,
                    COALESCE(d.role, 'driver') as role,
                    COUNT(o.id) as active_orders
                FROM drivers d
                LEFT JOIN orders o
                    ON o.driver_id = d.id
                    AND o.status NOT IN ('доставлен', 'отменён')
                WHERE d.is_active = 1
                GROUP BY d.id
                ORDER BY d.name
            """)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def fire_employee(self, emp_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE drivers SET is_active = 0 WHERE id = ?", (emp_id,)
            )
            await db.commit()

    async def get_employee(self, emp_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT *, COALESCE(role,'driver') as role FROM drivers WHERE id = ?", (emp_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_employee_stats(self, emp_id: int) -> Dict:
        month_start = date.today().replace(day=1).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            async def one(sql, p=()):
                cur = await db.execute(sql, p)
                r = await cur.fetchone()
                return r[0] if r else 0

            total    = await one("SELECT COUNT(*) FROM orders WHERE driver_id=?", (emp_id,))
            month    = await one("SELECT COUNT(*) FROM orders WHERE driver_id=? AND DATE(created_at)>=?", (emp_id, month_start))
            active   = await one("SELECT COUNT(*) FROM orders WHERE driver_id=? AND status NOT IN ('доставлен','отменён')", (emp_id,))
            revenue  = await one("SELECT COALESCE(SUM(price),0) FROM orders WHERE driver_id=? AND DATE(created_at)>=?", (emp_id, month_start))
        return {"total": total, "month": month, "active": active, "revenue": int(revenue)}
