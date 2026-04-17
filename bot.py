# bot.py
import os
import asyncio
import logging
import sqlite3
from datetime import datetime
from collections import OrderedDict

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv

# ================== НАСТРОЙКИ ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "anti_p0v")
OFFICIAL_CHANNEL = os.getenv("OFFICIAL_CHANNEL", "https://t.me/bothelperix")

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "bot.db")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================== КЭШ ==================
message_cache = OrderedDict()
CACHE_LIMIT = 500

# ================== БД ==================
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

def init_db():
    cursor.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        created_at TEXT,
        is_active INTEGER
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS business_users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        connected_at TEXT
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS muted (
        user_id INTEGER PRIMARY KEY
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS autoreplies (
        user_id INTEGER,
        command TEXT,
        response TEXT
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS safety (
        user_id INTEGER PRIMARY KEY,
        safe INTEGER,
        notes TEXT
    )""")

    conn.commit()

init_db()

# ================== ВСПОМОГАТЕЛЬНОЕ ==================
def is_muted(user_id: int):
    cursor.execute("SELECT 1 FROM muted WHERE user_id=?", (user_id,))
    return cursor.fetchone() is not None

def add_user(msg: Message):
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?, ?)",
                   (msg.from_user.id,
                    msg.from_user.username,
                    msg.from_user.first_name,
                    datetime.now().isoformat(),
                    1))
    conn.commit()

def add_business_user(msg: Message):
    if msg.from_user:
        cursor.execute("INSERT OR IGNORE INTO business_users VALUES (?, ?, ?, ?)",
                       (msg.from_user.id,
                        msg.from_user.username,
                        msg.from_user.first_name,
                        datetime.now().isoformat()))
        conn.commit()

def cache_message(msg: Message):
    if msg.text:
        message_cache[msg.message_id] = msg.text
        if len(message_cache) > CACHE_LIMIT:
            message_cache.popitem(last=False)

# ================== МЕНЮ ==================
def main_menu(user_id):
    buttons = [
        [InlineKeyboardButton(text="📖 О BotHelper", callback_data="about")],
        [InlineKeyboardButton(text="🔌 Как подключить", callback_data="connect")],
        [InlineKeyboardButton(text="📞 Техподдержка", callback_data="support")],
        [InlineKeyboardButton(text="📢 Наш канал", url=OFFICIAL_CHANNEL)]
    ]

    if user_id == OWNER_ID:
        buttons.append([InlineKeyboardButton(text="📊 Статистика", callback_data="stats")])
        buttons.append([InlineKeyboardButton(text="👑 Панель управления", callback_data="admin")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ================== START ==================
@dp.message(Command("start"))
async def start(msg: Message):
    try:
        add_user(msg)
        await msg.answer("👋 BotHelper\nВыберите действие:", reply_markup=main_menu(msg.from_user.id))
    except:
        pass

# ================== CALLBACK ==================
@dp.callback_query()
async def callbacks(cb: CallbackQuery):
    try:
        if cb.data == "stats":
            cursor.execute("SELECT COUNT(*) FROM users")
            users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM business_users")
            business = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM muted")
            muted = cursor.fetchone()[0]

            await cb.message.edit_text(
                f"📊 Статистика\n\n"
                f"👥 {users}\n🔌 {business}\n🔇 {muted}\n🧠 {len(message_cache)}"
            )

        elif cb.data == "admin":
            await cb.message.edit_text("👑 Панель\n/send — рассылка\n/restart")

        elif cb.data == "support":
            await cb.answer(f"@{SUPPORT_USERNAME}", show_alert=True)

        elif cb.data == "about":
            await cb.answer("Business модератор", show_alert=True)

        elif cb.data == "connect":
            await cb.answer("Подключи через Telegram Business", show_alert=True)

    except TelegramBadRequest:
        pass

# ================== ОСНОВНОЙ ХЕНДЛЕР ==================
@dp.message()
async def handler(msg: Message):
    try:
        cache_message(msg)

        # ===== ТОЛЬКО BUSINESS =====
        if msg.business_connection_id is None:
            return

        add_business_user(msg)

        IS_OWNER = msg.from_user.id == OWNER_ID

        # ===== МУТ =====
        if is_muted(msg.from_user.id):
            try:
                await msg.delete()
            except:
                pass
            await msg.answer("🔇 ПОМОЛЧИ. Вы замучены")
            return

        # ===== КОМАНДЫ (ТОЛЬКО ВЛАДЕЛЕЦ) =====
        if IS_OWNER and msg.reply_to_message and msg.text:
            if not msg.reply_to_message.from_user:
                return

            target = msg.reply_to_message.from_user.id
            cmd = msg.text.lower()

            if cmd == ".mute":
                cursor.execute("INSERT OR IGNORE INTO muted VALUES (?)", (target,))
                conn.commit()
                await msg.delete()
                await msg.answer("🔇 ПОМОЛЧИ")

            elif cmd == ".unmute":
                cursor.execute("DELETE FROM muted WHERE user_id=?", (target,))
                conn.commit()
                await msg.answer("🔊 Размучен")

            elif cmd == ".check":
                cursor.execute("INSERT OR REPLACE INTO safety VALUES (?, ?, ?)",
                               (target, 1, "OK"))
                conn.commit()
                await msg.answer("✅ Пользователь безопасен")

        # ===== HELP =====
        if msg.text == ".help" and IS_OWNER:
            await msg.answer(
                "📖 Команды:\n"
                ".mute\n.unmute\n.check\n.auto"
            )

        # ===== АВТООТВЕТ =====
        if msg.text and not msg.text.startswith(".") and not IS_OWNER:
            cursor.execute("SELECT command, response FROM autoreplies")
            for cmd, resp in cursor.fetchall():
                if msg.text.lower().startswith(cmd.lower()):
                    await msg.answer(resp)

    except Exception as e:
        logging.error(e)

# ================== РЕДАКТИРОВАНИЕ ==================
@dp.message(F.edit_date)
async def edited(msg: Message):
    try:
        old = message_cache.get(msg.message_id, "")
        new = msg.text or ""

        if old != new:
            await msg.answer(f"✏️ Было: {old}\nСтало: {new}")

        cache_message(msg)

    except:
        pass

# ================== ЗАПУСК ==================
async def main():
    await bot.send_message(OWNER_ID, "🚀 Bot запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
