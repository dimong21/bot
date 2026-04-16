#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
╔══════════════════════════════════════════════════════════════╗
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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
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
    # Все пользователи (кто написал /start)
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, created_at TEXT, is_active INTEGER DEFAULT 1)''')
    # Подключившие бота через Business
    cursor.execute('''CREATE TABLE IF NOT EXISTS business_users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, connected_at TEXT)''')
    # Мут-лист
    cursor.execute('''CREATE TABLE IF NOT EXISTS muted (user_id INTEGER PRIMARY KEY, muted_by INTEGER, muted_at TEXT, reason TEXT)''')
    # Автоответчики
    cursor.execute('''CREATE TABLE IF NOT EXISTS autoreplies (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, command TEXT, response TEXT, created_at TEXT)''')
    # Проверка безопасности
    cursor.execute('''CREATE TABLE IF NOT EXISTS safety_check (user_id INTEGER PRIMARY KEY, is_safe INTEGER DEFAULT 1, last_check TEXT, notes TEXT)''')
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

class Database:
    # ========== ОБЩИЕ ПОЛЬЗОВАТЕЛИ (кто написал /start) ==========
    @staticmethod
    def add_user(user_id, username, first_name):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name, created_at, is_active) VALUES (?, ?, ?, ?, 1)', 
                       (user_id, username or "", first_name or "", datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_all_users():
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, created_at FROM users WHERE is_active = 1')
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
    
    # ========== BUSINESS ПОЛЬЗОВАТЕЛИ (кто подключил бота) ==========
    @staticmethod
    def add_business_user(user_id, username, first_name):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO business_users (user_id, username, first_name, connected_at) VALUES (?, ?, ?, ?)', 
                       (user_id, username or "", first_name or "", datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_all_business_users():
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, connected_at FROM business_users')
        users = cursor.fetchall()
        conn.close()
        return users
    
    @staticmethod
    def get_business_user_count():
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM business_users')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    @staticmethod
    def is_business_user(user_id):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM business_users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    
    # ========== МУТ ==========
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
    def get_muted_count():
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM muted')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    # ========== АВТООТВЕТЧИКИ ==========
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
    
    # ========== БЕЗОПАСНОСТЬ ==========
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
    waiting_for_target = State()  # Кому отправлять рассылку

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard(is_owner: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📖 О BotHelper", callback_data="about")],
        [InlineKeyboardButton(text="🔌 Как подключить", callback_data="how_to_connect")],
        [InlineKeyboardButton(text="📞 Техподдержка", callback_data="support")],
        [InlineKeyboardButton(text="📢 Наш канал", url=OFFICIAL_CHANNEL)]
    ]
    if is_owner:
        keyboard.append([InlineKeyboardButton(text="📊 Статистика", callback_data="stats")])
        keyboard.append([InlineKeyboardButton(text="👑 Панель управления", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_owner_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="owner_users")],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="owner_broadcast")],
        [InlineKeyboardButton(text="🔄 Перезапустить бота", callback_data="owner_restart")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])

def get_broadcast_target_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Всем пользователям", callback_data="broadcast_all")],
        [InlineKeyboardButton(text="🆕 Только первопроходцы", callback_data="broadcast_users")],
        [InlineKeyboardButton(text="🔌 Только подключившие бота", callback_data="broadcast_business")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])

def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_main")]
    ])

# ==================== BUSINESS MODE ХЕНДЛЕРЫ ====================

@dp.business_connection()
async def on_business_connection(connection: types.BusinessConnection):
    """Когда пользователь подключает бота через Business"""
    user_id = connection.user.id
    user = await bot.get_chat(user_id)
    
    # Сохраняем в бизнес-пользователи
    db.add_business_user(user_id, user.username, user.first_name)
    # Также добавляем в общих пользователей (если ещё нет)
    db.add_user(user_id, user.username, user.first_name)
    
    await bot.send_message(
        OWNER_ID,
        f"🔌 <b>🆕 Новое подключение Business!</b>\n\n"
        f"👤 <b>Пользователь:</b> <a href='tg://user?id={user_id}'>{user.first_name}</a>\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📅 <b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        parse_mode="HTML"
    )

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
        f"• 🔊 Размут пользователей (<code>.unmute</code>)\n"
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
        await message.answer("❌ <b>Доступ запрещён!</b>", parse_mode="HTML")
        return
    
    await message.answer(
        f"<b>👑 ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n"
        f"┌─────────────────────────────────┐\n"
        f"│  👥 <b>Пользователей:</b> {db.get_user_count():<12}│\n"
        f"│  🔌 <b>Business:</b> {db.get_business_user_count():<12}│\n"
        f"│  💾 <b>Кэш:</b> {len(message_cache):<16}│\n"
        f"└─────────────────────────────────┘\n\n"
        f"<b>📋 Доступные действия:</b>",
        reply_markup=get_owner_keyboard(),
        parse_mode="HTML"
    )

# ==================== CALLBACK HANDLERS ====================

@dp.callback_query(lambda c: c.data == "about")
async def about_callback(callback: CallbackQuery):
    is_owner = (callback.from_user.id == OWNER_ID)
    try:
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
            f"✅ Размут пользователей (.unmute)\n"
            f"✅ Автоответчик (.auto)\n"
            f"✅ Проверка безопасности (.check)\n\n"
            f"<b>🔗 Ссылки:</b>\n"
            f"• 📢 <a href='{OFFICIAL_CHANNEL}'>Официальный канал</a>\n"
            f"• 📞 <a href='https://t.me/{SUPPORT_USERNAME}'>Техподдержка</a>",
            reply_markup=get_main_keyboard(is_owner),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"about_callback error: {e}")

@dp.callback_query(lambda c: c.data == "how_to_connect")
async def how_to_connect_callback(callback: CallbackQuery):
    is_owner = (callback.from_user.id == OWNER_ID)
    bot_info = await bot.get_me()
    try:
        await callback.message.edit_text(
            f"<b>🔌 ПОДКЛЮЧЕНИЕ BOTHELPER</b>\n\n"
            f"<b>📋 Инструкция:</b>\n\n"
            f"<b>1️⃣</b> Откройте <b>Настройки Telegram</b>\n"
            f"<b>2️⃣</b> Перейдите в <b>Telegram Business</b>\n"
            f"<b>3️⃣</b> Выберите <b>Чат-боты</b>\n"
            f"<b>4️⃣</b> Нажмите <b>«Добавить бота»</b>\n"
            f"<b>5️⃣</b> Введите: <code>@{bot_info.username}</code>\n"
            f"<b>6️⃣</b> Выдайте разрешения\n\n"
            f"<b>✅ Готово!</b>",
            reply_markup=get_main_keyboard(is_owner),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"how_to_connect_callback error: {e}")

@dp.callback_query(lambda c: c.data == "support")
async def support_callback(callback: CallbackQuery):
    is_owner = (callback.from_user.id == OWNER_ID)
    try:
        await callback.message.edit_text(
            f"<b>📞 ТЕХНИЧЕСКАЯ ПОДДЕРЖКА</b>\n\n"
            f"┌─────────────────────────────────┐\n"
            f"│  👤 <b>Связь:</b> @{SUPPORT_USERNAME}    │\n"
            f"│  📢 <b>Канал:</b> {OFFICIAL_CHANNEL} │\n"
            f"└─────────────────────────────────┘\n\n"
            f"• <a href='https://t.me/{SUPPORT_USERNAME}'>Написать в поддержку</a>\n"
            f"• <a href='{OFFICIAL_CHANNEL}'>Подписаться на канал</a>",
            reply_markup=get_main_keyboard(is_owner),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"support_callback error: {e}")

@dp.callback_query(lambda c: c.data == "stats")
async def stats_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    users_count = db.get_user_count()
    business_count = db.get_business_user_count()
    muted_count = db.get_muted_count()
    
    try:
        await callback.message.edit_text(
            f"<b>📊 СТАТИСТИКА</b>\n\n"
            f"┌─────────────────────────────────┐\n"
            f"│  👥 <b>Первопроходцы:</b> {users_count:<13}│\n"
            f"│  🔌 <b>Подключили бота:</b> {business_count:<11}│\n"
            f"│  🔇 <b>Замучено:</b> {muted_count:<16}│\n"
            f"│  💾 <b>Кэш сообщений:</b> {len(message_cache):<9}│\n"
            f"└─────────────────────────────────┘\n\n"
            f"<b>📌 Пояснения:</b>\n"
            f"• <b>Первопроходцы</b> - написали /start\n"
            f"• <b>Подключили бота</b> - через Business\n\n"
            f"<b>🔗 Полезные ссылки:</b>\n"
            f"• 📢 <a href='{OFFICIAL_CHANNEL}'>Наш канал</a>\n"
            f"• 📞 <a href='https://t.me/{SUPPORT_USERNAME}'>Техподдержка</a>",
            reply_markup=get_main_keyboard(True),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"stats_callback error: {e}")

@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    try:
        await callback.message.edit_text(
            f"<b>👑 ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n"
            f"┌─────────────────────────────────┐\n"
            f"│  👥 <b>Пользователей:</b> {db.get_user_count():<12}│\n"
            f"│  🔌 <b>Business:</b> {db.get_business_user_count():<12}│\n"
            f"│  💾 <b>Кэш:</b> {len(message_cache):<16}│\n"
            f"└─────────────────────────────────┘\n\n"
            f"<b>📋 Доступные действия:</b>",
            reply_markup=get_owner_keyboard(),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"admin_panel_callback error: {e}")

@dp.callback_query(lambda c: c.data == "owner_users")
async def owner_users_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    users = db.get_all_users()
    business_users = db.get_all_business_users()
    business_ids = {u[0] for u in business_users}
    
    if not users:
        await callback.message.edit_text("📭 Список пользователей пуст.", reply_markup=get_back_keyboard())
        return
    
    text = "<b>👥 СПИСОК ПОЛЬЗОВАТЕЛЕЙ</b>\n\n"
    for i, (uid, username, fname, created_at) in enumerate(users[:30], 1):
        is_business = "🔌" if uid in business_ids else "📝"
        muted_status = "🔇" if db.is_muted(uid) else "🟢"
        text += f"{i}. {is_business} {muted_status} <a href='tg://user?id={uid}'>{fname}</a>\n"
        text += f"   📅 {created_at[:10]}\n\n"
    
    if len(users) > 30:
        text += f"\n... и ещё {len(users) - 30} пользователей"
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard(), parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "owner_broadcast")
async def owner_broadcast_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "<b>📢 РАССЫЛКА</b>\n\n"
        "Выберите кому отправить сообщение:",
        reply_markup=get_broadcast_target_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data.startswith("broadcast_"))
async def broadcast_target_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    target = callback.data.replace("broadcast_", "")
    await state.update_data(broadcast_target=target)
    
    target_names = {
        "all": "📢 ВСЕМ ПОЛЬЗОВАТЕЛЯМ",
        "users": "🆕 ПЕРВОПРОХОДЦАМ",
        "business": "🔌 ПОДКЛЮЧИВШИМ БОТА"
    }
    
    await callback.message.edit_text(
        f"<b>{target_names.get(target, 'РАССЫЛКА')}</b>\n\n"
        "Отправьте сообщение для рассылки.\n\n"
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
    
    data = await state.get_data()
    target = data.get("broadcast_target", "all")
    
    # Получаем список получателей
    if target == "all":
        users = db.get_all_users()
        target_name = "Всем пользователям"
    elif target == "users":
        users = db.get_all_users()
        target_name = "Первопроходцам"
    elif target == "business":
        users = db.get_all_business_users()
        target_name = "Подключившим бота"
    else:
        users = []
        target_name = "Неизвестная группа"
    
    if not users:
        await message.answer("❌ Нет пользователей для рассылки!")
        await state.clear()
        return
    
    success = 0
    fail = 0
    
    status_msg = await message.answer(f"🔄 Рассылка для {target_name}...\n👥 Всего: {len(users)}")
    
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
    
    await status_msg.edit_text(
        f"<b>✅ Рассылка завершена!</b>\n\n"
        f"📨 Отправлено: {success}\n"
        f"❌ Ошибок: {fail}\n"
        f"👥 Получателей: {len(users)}",
        parse_mode="HTML"
    )
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
    try:
        await callback.message.edit_text(
            f"<b>🤖 BotHelper</b> — главное меню\n\nВыберите действие:",
            reply_markup=get_main_keyboard(is_owner),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"back_to_main_callback error: {e}")

# ==================== КОМАНДЫ (РАБОТАЮТ В ЛЮБЫХ ЧАТАХ) ====================

@dp.message(Command("mute"))
async def mute_command(message: Message):
    if not message.reply_to_message:
        await message.reply("❌ <b>Ошибка!</b>\n\nОтветьте на сообщение пользователя.", parse_mode="HTML")
        return
    
    target = message.reply_to_message.from_user
    
    if target.id == message.from_user.id:
        await message.reply("❌ <b>Ошибка!</b>\n\nНельзя замутить самого себя.", parse_mode="HTML")
        await message.delete()
        return
    
    db.add_mute(target.id, message.from_user.id)
    
    await message.reply(
        f"<b>🔇 ПОМОЛЧИ.</b>\n\n"
        f"Пользователь <a href='tg://user?id={target.id}'>{target.first_name}</a> замучен.",
        parse_mode="HTML"
    )
    
    try:
        await message.delete()
    except:
        pass

@dp.message(Command("unmute"))
async def unmute_command(message: Message):
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
    args = message.text.split()
    
    if len(args) == 2 and args[1] == "list":
        replies = db.get_all_autoreplies(message.from_user.id)
        if not replies:
            await message.reply("📭 <b>Нет автоответчиков</b>\n\n<code>.auto добавить команда ответ</code>", parse_mode="HTML")
        else:
            text = "<b>📋 АВТООТВЕТЧИКИ</b>\n\n"
            for cmd, resp in replies:
                text += f"• <code>{cmd}</code> → {resp[:50]}\n"
            await message.reply(text, parse_mode="HTML")
        return
    
    if len(args) >= 3 and args[1] == "добавить":
        cmd = args[2].lower()
        resp = " ".join(args[3:])
        if not resp:
            await message.reply("❌ Укажите ответ.", parse_mode="HTML")
            return
        db.add_autoreply(message.from_user.id, cmd, resp)
        await message.reply(f"<b>✅ ДОБАВЛЕН</b>\n\n<code>{cmd}</code> → {resp}", parse_mode="HTML")
        return
    
    if len(args) >= 3 and args[1] == "удалить":
        cmd = args[2].lower()
        db.remove_autoreply(message.from_user.id, cmd)
        await message.reply(f"<b>✅ УДАЛЁН</b>\n\n<code>{cmd}</code>", parse_mode="HTML")
        return
    
    await message.reply(
        "<b>📖 .auto</b>\n\n"
        "• <code>.auto list</code> — список\n"
        "• <code>.auto добавить команда ответ</code> — добавить\n"
        "• <code>.auto удалить команда</code> — удалить\n\n"
        "<b>Пример:</b>\n"
        "<code>.auto добавить привет Здравствуйте!</code>",
        parse_mode="HTML"
    )

@dp.message(Command("check"))
async def check_command(message: Message):
    if not message.reply_to_message:
        await message.reply("❌ <b>Ошибка!</b>\n\nОтветьте на сообщение пользователя.", parse_mode="HTML")
        return
    
    target = message.reply_to_message.from_user
    is_safe, notes = db.get_safety(target.id)
    
    if is_safe is None:
        db.set_safety(target.id, True, "Автоматическая проверка")
        is_safe = True
    
    status = "✅ БЕЗОПАСНЫЙ" if is_safe else "⚠️ ПОДОЗРИТЕЛЬНЫЙ"
    
    await message.reply(
        f"<b>🛡️ ПРОВЕРКА БЕЗОПАСНОСТИ</b>\n\n"
        f"👤 <a href='tg://user?id={target.id}'>{target.first_name}</a>\n"
        f"Статус: {status}\n"
        f"📝 {notes or 'Нет'}",
        parse_mode="HTML"
    )
    
    try:
        await message.delete()
    except:
        pass

@dp.message()
async def handle_all_messages(message: Message):
    if message.from_user.is_bot:
        return
    
    if db.is_muted(message.from_user.id):
        await message.delete()
        await message.answer("<b>🔇 ПОМОЛЧИ.</b>\n\nВы замучены.", parse_mode="HTML")
        return
    
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
║                BotHelper v1.0                               ║
║         Telegram Business Moderator                         ║
╚══════════════════════════════════════════════════════════════╝
    """)
    logger.info("🚀 BotHelper v1.0 запущен!")
    logger.info(f"👑 Владелец: {OWNER_ID}")
    logger.info(f"📢 Канал: {OFFICIAL_CHANNEL}")
    logger.info(f"📞 Поддержка: @{SUPPORT_USERNAME}")
    
    try:
        await bot.send_message(OWNER_ID, "<b>✅ BotHelper запущен и работает!</b>\n\nБот готов к работе.", parse_mode="HTML")
    except:
        pass
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
