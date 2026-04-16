#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BotHelper - Рабочая версия (без бизнес-хендлеров)
"""

import asyncio
import sqlite3
import os
import sys
import logging
from datetime import datetime
from typing import Optional, List, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== КОНФИГ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
OFFICIAL_CHANNEL = os.environ.get("OFFICIAL_CHANNEL", "https://t.me/your_channel")
DATABASE_FILE = "database.db"

if not BOT_TOKEN or OWNER_ID == 0:
    logger.error("❌ Заполните BOT_TOKEN и OWNER_ID в .env!")
    sys.exit(1)

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
        cursor.execute('INSERT OR REPLACE INTO users (user_id, username, first_name, connected_at, is_active) VALUES (?, ?, ?, ?, 1)', (user_id, username or "", first_name or "", datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_all_users():
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, connected_at FROM users WHERE is_active = 1')
        return cursor.fetchall()
        conn.close()
    
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
        cursor.execute('INSERT OR REPLACE INTO muted (user_id, muted_by, muted_at, reason) VALUES (?, ?, ?, ?)', (user_id, muted_by, datetime.now().isoformat(), reason))
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
        cursor.execute('INSERT OR REPLACE INTO autoreplies (user_id, command, response, created_at) VALUES (?, ?, ?, ?)', (user_id, command.lower(), response, datetime.now().isoformat()))
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
        cursor.execute('INSERT OR REPLACE INTO safety_check (user_id, is_safe, last_check, notes) VALUES (?, ?, ?, ?)', (user_id, 1 if is_safe else 0, datetime.now().isoformat(), notes))
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
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="📖 О BotHelper", callback_data="about")],
        [InlineKeyboardButton(text="🔌 Как подключить", callback_data="how_to_connect")],
        [InlineKeyboardButton(text="📞 Техподдержка", callback_data="support")],
        [InlineKeyboardButton(text="📢 Наш канал", url=OFFICIAL_CHANNEL)],
        [InlineKeyboardButton(text="ℹ️ Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="👑 Панель владельца", callback_data="admin_panel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_owner_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="owner_users")],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="owner_broadcast")],
        [InlineKeyboardButton(text="🔄 Перезапустить бота", callback_data="owner_restart")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])

# ==================== ОБРАБОТЧИКИ ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    
    await message.answer(
        f"🤖 <b>Здравствуйте! Я BotHelper</b>\n\n"
        f"Я — ваш помощник для <b>Telegram Business</b>.\n\n"
        f"📌 <b>Мои возможности:</b>\n"
        f"• 🔇 Мут пользователей (.mute, .unmute)\n"
        f"• 🤖 Автоответчик (.auto)\n"
        f"• 🛡️ Проверка безопасности (.check)\n"
        f"• 📢 Рассылки (для владельца)\n\n"
        f"👇 <b>Выберите действие:</b>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Нет доступа!")
        return
    
    await message.answer(
        f"👑 <b>Панель владельца</b>\n\n"
        f"👥 Пользователей: {db.get_user_count()}\n\n"
        f"Выберите действие:",
        reply_markup=get_owner_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "about")
async def about_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        f"🌟 <b>О BotHelper</b>\n\n"
        f"<b>Версия:</b> 1.0\n\n"
        f"<b>Функционал:</b>\n"
        f"✅ Мут пользователей (.mute)\n"
        f"✅ Автоответчик (.auto)\n"
        f"✅ Проверка безопасности (.check)\n"
        f"✅ Панель владельца\n"
        f"✅ Рассылки\n\n"
        f"🔗 <b>Канал:</b> {OFFICIAL_CHANNEL}",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "how_to_connect")
async def how_to_connect_callback(callback: CallbackQuery):
    bot_info = await bot.get_me()
    await callback.message.edit_text(
        f"🔌 <b>Как подключить BotHelper</b>\n\n"
        f"<b>Шаг 1:</b>\n"
        f"Настройки Telegram → Telegram Business → Чат-боты\n\n"
        f"<b>Шаг 2:</b>\n"
        f"Нажмите «Добавить бота»\n\n"
        f"<b>Шаг 3:</b>\n"
        f"Введите: <code>@{bot_info.username}</code>\n\n"
        f"<b>Шаг 4:</b>\n"
        f"Выдайте разрешения\n\n"
        f"✅ <b>Готово!</b>",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "support")
async def support_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        f"📞 <b>Техподдержка</b>\n\n"
        f"По всем вопросам: @bothelper_support\n\n"
        f"📢 Канал: {OFFICIAL_CHANNEL}",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "stats")
async def stats_callback(callback: CallbackQuery):
    users_count = db.get_user_count()
    muted_count = 0
    for user in db.get_all_users():
        if db.is_muted(user[0]):
            muted_count += 1
    
    await callback.message.edit_text(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {users_count}\n"
        f"🔇 Замучено: {muted_count}\n\n"
        f"🔗 {OFFICIAL_CHANNEL}",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"👑 <b>Панель владельца</b>\n\n"
        f"👥 Пользователей: {db.get_user_count()}\n\n"
        f"Выберите действие:",
        reply_markup=get_owner_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "owner_users")
async def owner_users_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    users = db.get_all_users()
    if not users:
        await callback.message.edit_text("📭 Список пуст.", reply_markup=get_back_keyboard())
        return
    
    text = "👥 <b>Список пользователей:</b>\n\n"
    for i, (uid, username, fname, connected_at) in enumerate(users[:30], 1):
        muted_status = "🔇" if db.is_muted(uid) else "🟢"
        text += f"{i}. {muted_status} <a href='tg://user?id={uid}'>{fname}</a>\n"
    
    if len(users) > 30:
        text += f"\n... и ещё {len(users) - 30}"
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard(), parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "owner_broadcast")
async def owner_broadcast_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nОтправьте сообщение для рассылки.\nДля отмены: /cancel",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastState.waiting_for_message)

@dp.message(BroadcastState.waiting_for_message)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Нет доступа!")
        return
    
    users = db.get_all_users()
    success = 0
    fail = 0
    
    status_msg = await message.answer("🔄 Рассылка...")
    
    for user_id, username, fname, _ in users:
        try:
            if message.text:
                await bot.send_message(user_id, f"📢 <b>Анонс от BotHelper</b>\n\n{message.text}", parse_mode="HTML")
            else:
                await bot.copy_message(user_id, message.chat.id, message.message_id)
            success += 1
            await asyncio.sleep(0.05)
        except:
            fail += 1
    
    await status_msg.edit_text(f"✅ Отправлено: {success}\n❌ Ошибок: {fail}")
    await state.clear()

@dp.callback_query(lambda c: c.data == "owner_restart")
async def owner_restart_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text("🔄 Перезапуск...", parse_mode="HTML")
    await asyncio.sleep(2)
    os.execv(sys.executable, [sys.executable] + sys.argv)

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🤖 <b>BotHelper</b> — главное меню",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

# ==================== КОМАНДЫ ====================
@dp.message(Command("mute"))
async def mute_command(message: Message):
    if not message.reply_to_message:
        await message.reply("❌ Ответьте на сообщение пользователя.")
        return
    
    target = message.reply_to_message.from_user
    db.add_mute(target.id, message.from_user.id)
    
    await message.reply(f"🔇 <b>Молчать.</b>\n\nПользователь замучен.", parse_mode="HTML")
    try:
        await message.delete()
    except:
        pass

@dp.message(Command("unmute"))
async def unmute_command(message: Message):
    if not message.reply_to_message:
        await message.reply("❌ Ответьте на сообщение.")
        return
    
    target = message.reply_to_message.from_user
    db.remove_mute(target.id)
    
    await message.reply(f"🔊 Пользователь размучен.", parse_mode="HTML")
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
            await message.reply("📭 Нет автоответчиков.\n\n.auto добавить команда ответ")
        else:
            text = "📋 <b>Автоответчики:</b>\n\n"
            for cmd, resp in replies:
                text += f"• <code>{cmd}</code> → {resp[:50]}\n"
            await message.reply(text, parse_mode="HTML")
        return
    
    if len(args) >= 3 and args[1] == "добавить":
        cmd = args[2].lower()
        resp = " ".join(args[3:])
        if not resp:
            await message.reply("❌ Укажите ответ.")
            return
        db.add_autoreply(message.from_user.id, cmd, resp)
        await message.reply(f"✅ Добавлен: <code>{cmd}</code> → {resp}", parse_mode="HTML")
        return
    
    if len(args) >= 3 and args[1] == "удалить":
        cmd = args[2].lower()
        db.remove_autoreply(message.from_user.id, cmd)
        await message.reply(f"✅ Удалён: <code>{cmd}</code>", parse_mode="HTML")
        return
    
    await message.reply(
        "📖 <b>.auto</b>\n\n"
        "`.auto list` — список\n"
        "`.auto добавить команда ответ` — добавить\n"
        "`.auto удалить команда` — удалить",
        parse_mode="HTML"
    )

@dp.message(Command("check"))
async def check_command(message: Message):
    if not message.reply_to_message:
        await message.reply("❌ Ответьте на сообщение пользователя.")
        return
    
    target = message.reply_to_message.from_user
    is_safe, notes = db.get_safety(target.id)
    
    if is_safe is None:
        db.set_safety(target.id, True, "Авто")
        is_safe = True
    
    status = "✅ Безопасный" if is_safe else "⚠️ Подозрительный"
    
    await message.reply(
        f"🛡️ <b>Проверка безопасности</b>\n\n"
        f"👤 <a href='tg://user?id={target.id}'>{target.first_name}</a>\n"
        f"{status}\n"
        f"📝 {notes or 'Нет'}",
        parse_mode="HTML"
    )
    try:
        await message.delete()
    except:
        pass

@dp.message(Command("check_set"))
async def check_set_command(message: Message):
    args = message.text.split()
    if len(args) < 4:
        await message.reply("Использование: `.check_set user_id safe/unsafe причина`")
        return
    
    try:
        user_id = int(args[1])
        is_safe = args[2].lower() == "safe"
        reason = " ".join(args[3:])
        db.set_safety(user_id, is_safe, reason)
        await message.reply(f"✅ Статус обновлён: {'безопасен' if is_safe else 'подозрительный'}")
    except ValueError:
        await message.reply("❌ Неверный ID.")

@dp.message()
async def handle_messages(message: Message):
    if message.from_user.is_bot:
        return
    
    if db.is_muted(message.from_user.id):
        await message.delete()
        await message.answer("🔇 <b>Молчать.</b>", parse_mode="HTML")
        return
    
    text = message.text or message.caption
    if text:
        response = db.get_autoreply(message.from_user.id, text.lower().strip())
        if response:
            await message.reply(response)

# ==================== ЗАПУСК ====================
async def main():
    logger.info("🚀 BotHelper запущен!")
    logger.info(f"👑 Владелец: {OWNER_ID}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
