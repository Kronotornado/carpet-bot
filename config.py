import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задан!")

_admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = set(
    int(x.strip()) for x in _admin_ids_str.split(",") if x.strip().isdigit()
)
if not ADMIN_IDS:
    raise ValueError("❌ ADMIN_IDS не задан!")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
if not GROQ_API_KEY:
    raise ValueError("❌ GROQ_API_KEY не задан! Получите бесплатно на console.groq.com")

PRICE_PER_SQM = float(os.getenv("PRICE_PER_SQM", "300"))
MIN_ORDER_PRICE = float(os.getenv("MIN_ORDER_PRICE", "500"))
COMPANY_NAME = os.getenv("COMPANY_NAME", "КовёрМастер")
