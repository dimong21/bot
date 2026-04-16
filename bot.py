#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ██████╗  ██████╗ ████████╗██╗  ██╗███████╗██╗██████╗     ║
║   ██╔══██╗██╔═══██╗╚══██╔══╝██║  ██║██╔════╝██║██╔══██╗    ║
║   ██████╔╝██║   ██║   ██║   ███████║█████╗  ██║██████╔╝    ║
║   ██╔══██╗██║   ██║   ██║   ██╔══██║██╔══╝  ██║██╔═══╝     ║
║   ██████╔╝╚██████╔╝   ██║   ██║  ██║███████╗██║██║         ║
║   ╚═════╝  ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝╚═╝         ║
║                                                              ║
║                BotHelper v1.0                               ║
║         Telegram Business Moderator                         ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import sqlite3
import os
import sys
import logging
from datetime import datetime
from typing import Optional, List, Tuple, Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "bothelper_support")
OFFICIAL_CHANNEL = os.environ.get("OFFICIAL_CHANNEL", "https://t.me/bothelper_channel")
DATABASE_FILE = "database.db"

if not BOT_TOKEN or OWNER_ID == 0:
    print("❌ Ошибка: Заполните BOT_TOKEN и OWNER_ID в файле .env!")
    sys.exit(1)

# ==================== ЛОГГИРОВАНИЕ ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== БИБЛИОТЕКИ ====================
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, BusinessConnection, BusinessMessagesDeleted
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Кэш сообщений
message_cache: Dict[int, Dict] = {}

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, connected_at TEXT, is_active INTEGER DEFAULT 1)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS muted (user_id INTEGER PRIMARY KEY, muted_by INTEGER, muted_at TEXT, reason TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS autoreplies (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, command TEXT, response TEXT, created_at TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS safety_check (user_id INTEGER PRIMARY KEY, is_safe INTEGER DEFAULT 1, last_check TEXT, notes TEXT)''')
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

class Database:
    @staticmethod
    def add_user(user_id, username, first_name):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO users (user_id, username, first_name, connected_at, is_active) VALUES (?, ?, ?, ?, 1)', 
                       (user_id, username or "", first_name or "", datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_all_users():
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, connected_at FROM users WHERE is_active = 1')
        users = cursor.fetchall()
        conn.close()
        return users
    
    @staticmethod
    def get_user_count():
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    @staticmethod
    def add_mute(user_id, muted_by, reason=""):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO muted (user_id, muted_by, muted_at, reason) VALUES (?, ?, ?, ?)', 
                       (user_id, muted_by, datetime.now().isoformat(), reason))
        conn.commit()
        conn.close()
    
    @staticmethod
    def remove_mute(user_id):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM muted WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    @staticmethod
    def is_muted(user_id):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM muted WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    
    @staticmethod
    def add_autoreply(user_id, command, response):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO autoreplies (user_id, command, response, created_at) VALUES (?, ?, ?, ?)', 
                       (user_id, command.lower(), response, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    @staticmethod
    def remove_autoreply(user_id, command):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM autoreplies WHERE user_id = ? AND command = ?', (user_id, command.lower()))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_autoreply(user_id, command):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT response FROM autoreplies WHERE user_id = ? AND command = ?', (user_id, command.lower()))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    
    @staticmethod
    def get_all_autoreplies(user_id):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT command, response FROM autoreplies WHERE user_id = ?', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    
    @staticmethod
    def set_safety(user_id, is_safe, notes=""):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO safety_check (user_id, is_safe, last_check, notes) VALUES (?, ?, ?, ?)', 
                       (user_id, 1 if is_safe else 0, datetime.now().isoformat(), notes))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_safety(user_id):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT is_safe, notes FROM safety_check WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return (bool(row[0]), row[1])
        return (None, None)

db = Database()

# ==================== FSM ====================
class BroadcastState(StatesGroup):
    waiting_for_message = State()

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard(is_owner: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📖 О BotHelper", callback_data="about")],
        [InlineKeyboardButton(text="🔌 Как подключить", callback_data="how_to_connect")],
        [InlineKeyboardButton(text="📞 Техподдержка", callback_data="support")],
        [InlineKeyboardButton(text="📢 Наш канал", url=OFFICIAL_CHANNEL)],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ]
    if is_owner:
        keyboard.append([InlineKeyboardButton(text="👑 Панель управления", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_owner_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="owner_users")],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="owner_broadcast")],
        [InlineKeyboardButton(text="🔄 Перезапустить бота", callback_data="owner_restart")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])

def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_main")]
    ])

# ==================== BUSINESS MODE ХЕНДЛЕРЫ ====================

@dp.business_connection()
async def on_business_connection(connection: BusinessConnection):
    user_id = connection.user.id
    user = await bot.get_chat(user_id)
    db.add_user(user_id, user.username, user.first_name)
    
    await bot.send_message(
        OWNER_ID,
        f"🔌 <b>🆕 Новое подключение!</b>\n\n"
        f"👤 <b>Пользователь:</b> <a href='tg://user?id={user_id}'>{user.first_name}</a>\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📅 <b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        parse_mode="HTML"
    )
    
    await bot.send_message(
        connection.user_chat_id,
        f"<b>✨ Добро пожаловать в BotHelper!</b>\n\n"
        f"🤖 <b>Я ваш персональный помощник для Telegram Business</b>\n\n"
        f"📌 <b>Что я умею:</b>\n"
        f"• 🔄 Отслеживаю <b>изменённые</b> сообщения\n"
        f"• 🗑️ Отслеживаю <b>удалённые</b> сообщения\n"
        f"• 🔇 Мут пользователей <code>.mute</code>\n"
        f"• 🤖 Автоответчик <code>.auto</code>\n"
        f"• 🛡️ Проверка безопасности <code>.check</code>\n"
        f"• ❓ Справка <code>.help</code>\n\n"
        f"💡 <b>Совет:</b> Ответьте на сообщение пользователя и отправьте команду!",
        parse_mode="HTML"
    )

@dp.edited_business_message()
async def on_edited_business_message(message: Message):
    user = message.from_user
    chat_id = message.chat.id
    
    cached = message_cache.get(message.message_id, {})
    old_text = cached.get("text", "❓ Не удалось получить предыдущий текст")
    new_text = message.text or message.caption or "[📎 Медиафайл]"
    
    message_cache[message.message_id] = {
        "text": new_text,
        "user_id": user.id,
        "username": user.username or user.first_name
    }
    
    await bot.send_message(
        chat_id,
        f"<b>✏️ ИЗМЕНЕНИЕ СООБЩЕНИЯ</b>\n\n"
        f"👤 <b>Пользователь:</b> <a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n\n"
        f"<b>📝 БЫЛО:</b>\n<blockquote>{old_text[:300]}</blockquote>\n\n"
        f"<b>🔄 СТАЛО:</b>\n<blockquote>{new_text[:300]}</blockquote>",
        parse_mode="HTML"
    )

@dp.business_messages_deleted()
async def on_business_messages_deleted(deleted: BusinessMessagesDeleted):
    chat_id = deleted.chat.id
    
    deleted_texts = []
    for msg_id in deleted.message_ids[:5]:
        cached = message_cache.get(msg_id, {})
        if cached:
            user_name = cached.get("username", "Unknown")
            text = cached.get("text", "")
            deleted_texts.append(f"• <b>{user_name}</b>: {text[:100]}")
    
    if deleted_texts:
        text = f"<b>🗑️ УДАЛЕНИЕ СООБЩЕНИЙ</b>\n\n" + "\n".join(deleted_texts)
    else:
        text = f"<b>🗑️ УДАЛЕНИЕ СООБЩЕНИЙ</b>\n\nУдалено сообщений: <b>{len(deleted.message_ids)}</b>"
    
    if len(deleted.message_ids) > 5:
        text += f"\n\n... и ещё {len(deleted.message_ids) - 5} сообщений"
    
    await bot.send_message(chat_id, text, parse_mode="HTML")
    
    for msg_id in deleted.message_ids:
        message_cache.pop(msg_id, None)

@dp.business_message()
async def on_business_message(message: Message):
    if message.from_user.is_bot:
        return
    
    text = message.text or message.caption or ""
    message_cache[message.message_id] = {
        "text": text,
        "user_id": message.from_user.id,
        "username": message.from_user.username or message.from_user.first_name,
        "date": datetime.now().isoformat()
    }
    
    if len(message_cache) > 500:
        oldest_key = min(message_cache.keys())
        del message_cache[oldest_key]

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    is_owner = (message.from_user.id == OWNER_ID)
    
    await message.answer(
        f"<b>🤖 Здравствуйте! Я BotHelper</b>\n\n"
        f"<i>Ваш персональный помощник для Telegram Business</i>\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  ✨ <b>Версия:</b> 1.0              │\n"
        f"└─────────────────────────────────┘\n\n"
        f"<b>📌 Что я умею:</b>\n"
        f"• 🔄 Отслеживаю <b>изменённые</b> сообщения\n"
        f"• 🗑️ Отслеживаю <b>удалённые</b> сообщения\n"
        f"• 🔇 Мут пользователей (<code>.mute</code>)\n"
        f"• 🤖 Автоответчик (<code>.auto</code>)\n"
        f"• 🛡️ Проверка безопасности (<code>.check</code>)\n"
        f"• ❓ Справка (<code>.help</code>)\n\n"
        f"<b>🔗 Полезные ссылки:</b>\n"
        f"• 📢 <a href='{OFFICIAL_CHANNEL}'>Наш канал</a>\n"
        f"• 📞 <a href='https://t.me/{SUPPORT_USERNAME}'>Техподдержка</a>\n\n"
        f"👇 <b>Выберите действие:</b>",
        reply_markup=get_main_keyboard(is_owner),
        parse_mode="HTML"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Справка по командам (работает в чатах с пользователями и в избранном)"""
    await message.answer(
        f"<b>❓ ПОМОЩЬ ПО КОМАНДАМ</b>\n\n"
        f"┌─────────────────────────────────────────────────────┐\n"
        f"│  <b>📋 Доступные команды:</b>                         │\n"
        f"├─────────────────────────────────────────────────────┤\n"
        f"│  🔇 <code>.mute</code>       - Замутить пользователя    │\n"
        f"│  🔊 <code>.unmute</code>     - Размутить пользователя   │\n"
        f"│  🤖 <code>.auto</code>       - Настройка автоответчика  │\n"
        f"│  🛡️ <code>.check</code>      - Проверка безопасности    │\n"
        f"│  ❓ <code>.help</code>       - Эта справка              │\n"
        f"└─────────────────────────────────────────────────────┘\n\n"
        f"<b>📖 Как использовать:</b>\n"
        f"• <b>.mute</b> / <b>.unmute</b> - ответьте на сообщение пользователя\n"
        f"• <b>.auto list</b> - список автоответчиков\n"
        f"• <b>.auto добавить команда ответ</b> - добавить автоответ\n"
        f"• <b>.auto удалить команда</b> - удалить автоответ\n"
        f"• <b>.check</b> - ответьте на сообщение для проверки\n\n"
        f"<i>💡 Все команды работают прямо в чате с пользователем!</i>\n\n"
        f"<b>🔗 Полезные ссылки:</b>\n"
        f"• 📢 <a href='{OFFICIAL_CHANNEL}'>Наш канал</a>\n"
        f"• 📞 <a href='https://t.me/{SUPPORT_USERNAME}'>Техподдержка</a>",
        parse_mode="HTML"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ <b>Доступ запрещён!</b>\n\nУ вас нет прав для использования этой команды.", parse_mode="HTML")
        return
    
    await message.answer(
        f"<b>👑 ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  👥 <b>Пользователей:</b> {db.get_user_count():<12}│\n"
        f"│  💾 <b>Кэш сообщений:</b> {len(message_cache):<9}│\n"
        f"└─────────────────────────────────┘\n\n"
        f"<b>📋 Доступные действия:</b>",
        reply_markup=get_owner_keyboard(),
        parse_mode="HTML"
    )

# ==================== CALLBACK HANDLERS ====================

@dp.callback_query(lambda c: c.data == "about")
async def about_callback(callback: CallbackQuery):
    is_owner = (callback.from_user.id == OWNER_ID)
    await callback.message.edit_text(
        f"<b>🌟 О BotHelper</b>\n\n"
        f"<b>┌─────────────────────────────────┐</b>\n"
        f"<b>│  🤖 Название:</b> BotHelper\n"
        f"<b>│  📌 Версия:</b> 1.0\n"
        f"<b>└─────────────────────────────────┘</b>\n\n"
        f"<b>⚡ Возможности:</b>\n"
        f"✅ Отслеживание удалённых сообщений\n"
        f"✅ Отслеживание изменённых сообщений\n"
        f"✅ Уведомления в реальном времени\n"
        f"✅ Мут пользователей (.mute)\n"
        f"✅ Автоответчик (.auto)\n"
        f"✅ Проверка безопасности (.check)\n\n"
        f"<b>🔗 Ссылки:</b>\n"
        f"• 📢 <a href='{OFFICIAL_CHANNEL}'>Официальный канал</a>\n"
        f"• 📞 <a href='https://t.me/{SUPPORT_USERNAME}'>Техподдержка</a>",
        reply_markup=get_main_keyboard(is_owner),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "how_to_connect")
async def how_to_connect_callback(callback: CallbackQuery):
    is_owner = (callback.from_user.id == OWNER_ID)
    bot_info = await bot.get_me()
    await callback.message.edit_text(
        f"<b>🔌 ПОДКЛЮЧЕНИЕ BOTHELPER</b>\n\n"
        f"<b>📋 Инструкция:</b>\n\n"
        f"<b>1️⃣</b> Откройте <b>Настройки Telegram</b>\n"
        f"<b>2️⃣</b> Перейдите в <b>Telegram Business</b>\n"
        f"<b>3️⃣</b> Выберите <b>Чат-боты</b>\n"
        f"<b>4️⃣</b> Нажмите <b>«Добавить бота»</b>\n"
        f"<b>5️⃣</b> Введите: <code>@{bot_info.username}</code>\n"
        f"<b>6️⃣</b> Выдайте разрешения:\n"
        f"   • ✅ Читать сообщения\n"
        f"   • ✅ Отвечать на сообщения\n"
        f"   • ✅ Отмечать как прочитанные\n\n"
        f"<b>✅ Готово!</b> Бот начнёт работать автоматически.\n\n"
        f"<i>💡 После подключения вы получите приветственное сообщение!</i>",
        reply_markup=get_main_keyboard(is_owner),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "support")
async def support_callback(callback: CallbackQuery):
    is_owner = (callback.from_user.id == OWNER_ID)
    await callback.message.edit_text(
        f"<b>📞 ТЕХНИЧЕСКАЯ ПОДДЕРЖКА</b>\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  👤 <b>Связь:</b> @{SUPPORT_USERNAME}    │\n"
        f"│  📢 <b>Канал:</b> {OFFICIAL_CHANNEL} │\n"
        f"└─────────────────────────────────┘\n\n"
        f"<i>💡 По всем вопросам обращайтесь к нам в поддержку!</i>\n\n"
        f"• <a href='https://t.me/{SUPPORT_USERNAME}'>Написать в поддержку</a>\n"
        f"• <a href='{OFFICIAL_CHANNEL}'>Подписаться на канал</a>",
        reply_markup=get_main_keyboard(is_owner),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "stats")
async def stats_callback(callback: CallbackQuery):
    is_owner = (callback.from_user.id == OWNER_ID)
    users_count = db.get_user_count()
    muted_count = 0
    for user in db.get_all_users():
        if db.is_muted(user[0]):
            muted_count += 1
    
    await callback.message.edit_text(
        f"<b>📊 СТАТИСТИКА</b>\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  👥 <b>Пользователей:</b> {users_count:<13}│\n"
        f"│  🔇 <b>Замучено:</b> {muted_count:<14}│\n"
        f"│  💾 <b>Кэш сообщений:</b> {len(message_cache):<9}│\n"
        f"└─────────────────────────────────┘\n\n"
        f"<b>🔗 Полезные ссылки:</b>\n"
        f"• 📢 <a href='{OFFICIAL_CHANNEL}'>Наш канал</a>\n"
        f"• 📞 <a href='https://t.me/{SUPPORT_USERNAME}'>Техподдержка</a>",
        reply_markup=get_main_keyboard(is_owner),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"<b>👑 ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  👥 <b>Пользователей:</b> {db.get_user_count():<12}│\n"
        f"│  💾 <b>Кэш сообщений:</b> {len(message_cache):<9}│\n"
        f"└─────────────────────────────────┘\n\n"
        f"<b>📋 Доступные действия:</b>",
        reply_markup=get_owner_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "owner_users")
async def owner_users_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    users = db.get_all_users()
    if not users:
        await callback.message.edit_text("📭 Список пользователей пуст.", reply_markup=get_back_keyboard())
        return
    
    text = "<b>👥 СПИСОК ПОЛЬЗОВАТЕЛЕЙ</b>\n\n"
    for i, (uid, username, fname, connected_at) in enumerate(users[:30], 1):
        muted_status = "🔇" if db.is_muted(uid) else "🟢"
        text += f"{i}. {muted_status} <a href='tg://user?id={uid}'>{fname}</a>\n"
        text += f"   📅 Подключён: {connected_at[:10]}\n\n"
    
    if len(users) > 30:
        text += f"\n... и ещё {len(users) - 30} пользователей"
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard(), parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "owner_broadcast")
async def owner_broadcast_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "<b>📢 РАССЫЛКА</b>\n\n"
        "Отправьте сообщение для рассылки всем пользователям.\n\n"
        "Поддерживается: текст, фото, видео, документы.\n\n"
        "Для отмены отправьте /cancel",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastState.waiting_for_message)

@dp.message(BroadcastState.waiting_for_message)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Доступ запрещён!")
        return
    
    users = db.get_all_users()
    success = 0
    fail = 0
    
    status_msg = await message.answer("🔄 Начинаю рассылку...")
    
    for user_id, username, fname, _ in users:
        try:
            if message.text:
                await bot.send_message(user_id, f"<b>📢 Анонс от BotHelper</b>\n\n{message.text}", parse_mode="HTML")
            elif message.photo:
                await bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                await bot.send_video(user_id, message.video.file_id, caption=message.caption)
            elif message.document:
                await bot.send_document(user_id, message.document.file_id, caption=message.caption)
            success += 1
            await asyncio.sleep(0.05)
        except:
            fail += 1
    
    await status_msg.edit_text(f"<b>✅ Рассылка завершена!</b>\n\n📨 Отправлено: {success}\n❌ Ошибок: {fail}", parse_mode="HTML")
    await state.clear()

@dp.callback_query(lambda c: c.data == "owner_restart")
async def owner_restart_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text("<b>🔄 ПЕРЕЗАПУСК</b>\n\nБот будет перезапущен через 2 секунды...", parse_mode="HTML")
    await asyncio.sleep(2)
    os.execv(sys.executable, [sys.executable] + sys.argv)

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_callback(callback: CallbackQuery):
    is_owner = (callback.from_user.id == OWNER_ID)
    await callback.message.edit_text(
        f"<b>🤖 BotHelper</b> — главное меню\n\nВыберите действие:",
        reply_markup=get_main_keyboard(is_owner),
        parse_mode="HTML"
    )

# ==================== КОМАНДЫ В БИЗНЕС-ЧАТЕ ====================

@dp.message(Command("mute"))
async def mute_command(message: Message):
    """Замутить пользователя - команда удаляется, пишется ПОМОЛЧИ"""
    if not message.reply_to_message:
        await message.reply("❌ <b>Ошибка!</b>\n\nОтветьте на сообщение пользователя, которого хотите замутить.", parse_mode="HTML")
        return
    
    target = message.reply_to_message.from_user
    
    # Нельзя замутить самого себя
    if target.id == message.from_user.id:
        await message.reply("❌ <b>Ошибка!</b>\n\nВы не можете замутить самого себя.", parse_mode="HTML")
        await message.delete()
        return
    
    db.add_mute(target.id, message.from_user.id)
    
    # Отправляем сообщение "Помолчи."
    await message.reply(
        f"<b>🔇 ПОМОЛЧИ.</b>\n\n"
        f"Пользователь <a href='tg://user?id={target.id}'>{target.first_name}</a> замучен.",
        parse_mode="HTML"
    )
    
    # Удаляем команду .mute
    try:
        await message.delete()
    except:
        pass

@dp.message(Command("unmute"))
async def unmute_command(message: Message):
    """Размутить пользователя"""
    if not message.reply_to_message:
        await message.reply("❌ <b>Ошибка!</b>\n\nОтветьте на сообщение пользователя.", parse_mode="HTML")
        return
    
    target = message.reply_to_message.from_user
    db.remove_mute(target.id)
    
    await message.reply(
        f"<b>🔊 РАЗМУЧЕН</b>\n\n"
        f"Пользователь <a href='tg://user?id={target.id}'>{target.first_name}</a> размучен.",
        parse_mode="HTML"
    )
    
    try:
        await message.delete()
    except:
        pass

@dp.message(Command("auto"))
async def auto_command(message: Message):
    """Настройка автоответчика"""
    args = message.text.split()
    
    if len(args) == 2 and args[1] == "list":
        replies = db.get_all_autoreplies(message.from_user.id)
        if not replies:
            await message.reply("📭 <b>Нет автоответчиков</b>\n\nИспользуйте: <code>.auto добавить команда ответ</code>", parse_mode="HTML")
        else:
            text = "<b>📋 СПИСОК АВТООТВЕТЧИКОВ</b>\n\n"
            for cmd, resp in replies:
                text += f"• <code>{cmd}</code> → {resp[:50]}\n"
            await message.reply(text, parse_mode="HTML")
        return
    
    if len(args) >= 3 and args[1] == "добавить":
        cmd = args[2].lower()
        resp = " ".join(args[3:])
        if not resp:
            await message.reply("❌ <b>Ошибка!</b>\n\nУкажите ответ: <code>.auto добавить команда текст ответа</code>", parse_mode="HTML")
            return
        db.add_autoreply(message.from_user.id, cmd, resp)
        await message.reply(f"<b>✅ АВТООТВЕТЧИК ДОБАВЛЕН</b>\n\n<code>{cmd}</code> → {resp}", parse_mode="HTML")
        return
    
    if len(args) >= 3 and args[1] == "удалить":
        cmd = args[2].lower()
        db.remove_autoreply(message.from_user.id, cmd)
        await message.reply(f"<b>✅ АВТООТВЕТЧИК УДАЛЁН</b>\n\n<code>{cmd}</code>", parse_mode="HTML")
        return
    
    await message.reply(
        "<b>📖 КОМАНДА .auto</b>\n\n"
        "• <code>.auto list</code> — список автоответчиков\n"
        "• <code>.auto добавить команда ответ</code> — добавить\n"
        "• <code>.auto удалить команда</code> — удалить\n\n"
        "<b>📝 Пример:</b>\n"
        "<code>.auto добавить привет Здравствуйте! Чем могу помочь?</code>",
        parse_mode="HTML"
    )

@dp.message(Command("check"))
async def check_command(message: Message):
    """Проверка безопасности пользователя"""
    if not message.reply_to_message:
        await message.reply("❌ <b>Ошибка!</b>\n\nОтветьте на сообщение пользователя для проверки.", parse_mode="HTML")
        return
    
    target = message.reply_to_message.from_user
    is_safe, notes = db.get_safety(target.id)
    
    if is_safe is None:
        db.set_safety(target.id, True, "Автоматическая проверка")
        is_safe = True
    
    status = "✅ БЕЗОПАСНЫЙ" if is_safe else "⚠️ ПОДОЗРИТЕЛЬНЫЙ"
    color = "🟢" if is_safe else "🔴"
    
    await message.reply(
        f"<b>🛡️ ПРОВЕРКА БЕЗОПАСНОСТИ</b>\n\n"
        f"{color} <b>Пользователь:</b> <a href='tg://user?id={target.id}'>{target.first_name}</a>\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>📝 Примечание:</b> {notes or 'Нет'}\n\n"
        f"<i>🤖 Проверено BotHelper</i>",
        parse_mode="HTML"
    )
    
    try:
        await message.delete()
    except:
        pass

@dp.message()
async def handle_private_messages(message: Message):
    """Обработка сообщений (автоответчик + проверка мута)"""
    if message.from_user.is_bot:
        return
    
    # Проверка на мут
    if db.is_muted(message.from_user.id):
        await message.delete()
        await message.answer("<b>🔇 ПОМОЛЧИ.</b>\n\nВы замучены.", parse_mode="HTML")
        return
    
    # Автоответчик
    text = message.text or message.caption
    if text:
        response = db.get_autoreply(message.from_user.id, text.lower().strip())
        if response:
            await message.reply(response)

# ==================== ЗАПУСК ====================
async def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ██████╗  ██████╗ ████████╗██╗  ██╗███████╗██╗██████╗     ║
║   ██╔══██╗██╔═══██╗╚══██╔══╝██║  ██║██╔════╝██║██╔══██╗    ║
║   ██████╔╝██║   ██║   ██║   ███████║█████╗  ██║██████╔╝    ║
║   ██╔══██╗██║   ██║   ██║   ██╔══██║██╔══╝  ██║██╔═══╝     ║
║   ██████╔╝╚██████╔╝   ██║   ██║  ██║███████╗██║██║         ║
║   ╚═════╝  ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝╚═╝         ║
║                                                              ║
║                BotHelper v1.0                               ║
║         Telegram Business Moderator                         ║
╚══════════════════════════════════════════════════════════════╝
    """)
    logger.info("🚀 BotHelper v1.0 запущен!")
    logger.info(f"👑 Владелец: {OWNER_ID}")
    logger.info(f"📢 Канал: {OFFICIAL_CHANNEL}")
    logger.info(f"📞 Поддержка: @{SUPPORT_USERNAME}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
