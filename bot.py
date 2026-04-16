import asyncio
import sqlite3
import os
import sys
import logging
from datetime import datetime
from typing import Optional, List, Tuple

# ==================== ЛОГГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================
# ЗАПОЛНИ ЭТИ ДАННЫЕ!
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "your_api_hash_here")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))  # Только для статистики, без привилегий!

# Ссылка на официальный Telegram канал
OFFICIAL_CHANNEL = os.environ.get("OFFICIAL_CHANNEL", "https://t.me/your_channel")

# Папки
SESSIONS_DIR = "sessions"
DATABASE_FILE = "database.db"
os.makedirs(SESSIONS_DIR, exist_ok=True)

# Проверка конфига
if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or API_ID == 0 or OWNER_ID == 0:
    logger.error("❌ Заполните BOT_TOKEN, API_ID, API_HASH и OWNER_ID!")
    sys.exit(1)

# ==================== БИБЛИОТЕКИ ====================
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from telethon import TelegramClient, events

# ==================== ИНИЦИАЛИЗАЦИЯ ====================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Userbot
userbot_client: Optional[TelegramClient] = None
userbot_connected = False

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            connected_at TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS muted (
            user_id INTEGER PRIMARY KEY,
            muted_by INTEGER,
            muted_at TEXT,
            reason TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS autoreplies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            command TEXT,
            response TEXT,
            created_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            username TEXT,
            action TEXT,
            old_text TEXT,
            new_text TEXT,
            edited_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS safety_check (
            user_id INTEGER PRIMARY KEY,
            is_safe INTEGER DEFAULT 1,
            last_check TEXT,
            notes TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

# ==================== РАБОТА С БД ====================
class Database:
    @staticmethod
    def add_user(user_id: int, username: str, first_name: str):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, connected_at, is_active)
            VALUES (?, ?, ?, ?, 1)
        ''', (user_id, username, first_name, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_all_users() -> List[Tuple]:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, connected_at FROM users WHERE is_active = 1')
        users = cursor.fetchall()
        conn.close()
        return users
    
    @staticmethod
    def get_user_count() -> int:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    @staticmethod
    def add_mute(user_id: int, muted_by: int, reason: str = ""):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO muted (user_id, muted_by, muted_at, reason)
            VALUES (?, ?, ?, ?)
        ''', (user_id, muted_by, datetime.now().isoformat(), reason))
        conn.commit()
        conn.close()
    
    @staticmethod
    def remove_mute(user_id: int):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM muted WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    @staticmethod
    def is_muted(user_id: int) -> bool:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM muted WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    
    @staticmethod
    def add_autoreply(user_id: int, command: str, response: str):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO autoreplies (user_id, command, response, created_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, command.lower(), response, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    @staticmethod
    def remove_autoreply(user_id: int, command: str):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM autoreplies WHERE user_id = ? AND command = ?', (user_id, command.lower()))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_autoreply(user_id: int, command: str) -> Optional[str]:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT response FROM autoreplies WHERE user_id = ? AND command = ?', (user_id, command.lower()))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    
    @staticmethod
    def get_all_autoreplies(user_id: int) -> List[Tuple]:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT command, response FROM autoreplies WHERE user_id = ?', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    
    @staticmethod
    def set_safety(user_id: int, is_safe: bool, notes: str = ""):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO safety_check (user_id, is_safe, last_check, notes)
            VALUES (?, ?, ?, ?)
        ''', (user_id, 1 if is_safe else 0, datetime.now().isoformat(), notes))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_safety(user_id: int) -> Tuple[Optional[bool], Optional[str]]:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT is_safe, notes FROM safety_check WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return (bool(row[0]), row[1])
        return (None, None)

db = Database()

# ==================== FSM СОСТОЯНИЯ ====================
class BroadcastState(StatesGroup):
    waiting_for_message = State()

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📖 О BotHelper", callback_data="about")],
        [InlineKeyboardButton(text="🔌 Как подключить", callback_data="how_to_connect")],
        [InlineKeyboardButton(text="📞 Техподдержка", callback_data="support")],
        [InlineKeyboardButton(text="📢 Наш канал", url=OFFICIAL_CHANNEL)],
        [InlineKeyboardButton(text="ℹ️ Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="👑 Панель владельца", callback_data="admin_panel")]
    ]
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
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])

# ==================== USERBOT ====================
async def init_userbot():
    global userbot_client, userbot_connected
    session_path = os.path.join(SESSIONS_DIR, "main.session")
    
    userbot_client = TelegramClient(session_path, API_ID, API_HASH)
    
    try:
        await userbot_client.start()
        me = await userbot_client.get_me()
        logger.info(f"✅ Userbot запущен как {me.first_name}")
        userbot_connected = True
        
        @userbot_client.on(events.MessageEdited)
        async def on_edit(event):
            try:
                msg = event.message
                if msg.out or not msg.sender_id:
                    return
                
                user_id = msg.sender_id
                username = msg.sender.username if msg.sender and msg.sender.username else "Unknown"
                old_text = "Не удалось получить предыдущий текст"
                
                db.log_edit(
                    chat_id=msg.chat_id,
                    message_id=msg.id,
                    user_id=user_id,
                    username=username,
                    old_text=old_text,
                    new_text=msg.text or msg.caption or "[медиа]"
                )
                
                await bot.send_message(
                    OWNER_ID,
                    f"✏️ <b>BotHelper | Изменение сообщения</b>\n\n"
                    f"👤 <a href='tg://user?id={user_id}'>@{username}</a>\n"
                    f"📝 <b>Было:</b> {old_text[:200]}\n"
                    f"🔄 <b>Стало:</b> {(msg.text or msg.caption or '[медиа]')[:200]}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"on_edit error: {e}")
        
        @userbot_client.on(events.MessageDeleted)
        async def on_delete(event):
            try:
                await bot.send_message(
                    OWNER_ID,
                    f"🗑️ <b>BotHelper | Удаление сообщения</b>\n\n"
                    f"Чат: {event.chat_id}\n"
                    f"Удалено сообщений: {len(event.deleted_ids)}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"on_delete error: {e}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка userbot: {e}")
        userbot_connected = False
        return False

# ==================== ОБРАБОТЧИКИ БОТА ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        await bot.send_message(
            OWNER_ID, 
            f"🆕 <b>Новый пользователь!</b>\n"
            f"👤 {message.from_user.first_name} (@{message.from_user.username})\n"
            f"🆔 {message.from_user.id}",
            parse_mode="HTML"
        )
    
    await message.answer(
        f"🤖 <b>BotHelper</b> — твой помощник для Telegram Business\n\n"
        f"📌 <b>Возможности:</b>\n"
        f"• Сохранение удалённых и изменённых сообщений\n"
        f"• Мут пользователей в ЛС (.mute @user)\n"
        f"• Автоответчик по командам (.auto)\n"
        f"• Проверка безопасности (.check)\n\n"
        f"🔗 <b>Наш канал:</b> {OFFICIAL_CHANNEL}\n\n"
        f"👇 <b>Выбери действие:</b>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "about")
async def about_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        f"🌟 <b>BotHelper</b>\n\n"
        f"<b>Версия:</b> 1.0\n\n"
        f"<b>Функционал:</b>\n"
        f"✅ Отслеживание удалённых/изменённых сообщений\n"
        f"✅ Мут пользователей в личных чатах\n"
        f"✅ Автоответчик с гибкой настройкой\n"
        f"✅ Проверка пользователей на безопасность\n"
        f"✅ Подключение через Business Chatbots\n\n"
        f"🔗 <b>Официальный канал:</b> {OFFICIAL_CHANNEL}",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "how_to_connect")
async def how_to_connect_callback(callback: CallbackQuery):
    bot_info = await bot.get_me()
    await callback.message.edit_text(
        f"🔌 <b>Как подключить BotHelper</b>\n\n"
        f"<b>Шаг 1:</b>\n"
        f"В настройках Telegram найдите раздел\n"
        f"«Telegram для бизнеса» → «Чат-боты»\n\n"
        f"<b>Шаг 2:</b>\n"
        f"Нажмите «Добавить бота»\n\n"
        f"<b>Шаг 3:</b>\n"
        f"Введите username: <code>@{bot_info.username}</code>\n\n"
        f"<b>Шаг 4:</b>\n"
        f"Выдайте разрешения:\n"
        f"• Читать сообщения\n"
        f"• Отвечать на сообщения\n"
        f"• Отмечать как прочитанные\n\n"
        f"✅ <b>Готово!</b> Бот начнёт работать автоматически.",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "support")
async def support_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        f"📞 <b>Техническая поддержка</b>\n\n"
        f"По всем вопросам обращайтесь:\n"
        f"👤 <a href='https://t.me/bothelper_support'>@bothelper_support</a>\n\n"
        f"📢 Наш канал: {OFFICIAL_CHANNEL}",
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
        f"📊 <b>Статистика BotHelper</b>\n\n"
        f"👥 <b>Всего пользователей:</b> {users_count}\n"
        f"🔇 <b>Замучено:</b> {muted_count}\n"
        f"🟢 <b>Статус userbot:</b> {'✅ Активен' if userbot_connected else '❌ Не активен'}\n\n"
        f"🔗 {OFFICIAL_CHANNEL}",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    # Проверка по ID, но без особых привилегий — только статистика и рассылка
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"👑 <b>Панель управления</b>\n\n"
        f"👥 <b>Пользователей:</b> {db.get_user_count()}\n"
        f"🟢 <b>Userbot:</b> {'Активен' if userbot_connected else 'Не активен'}\n\n"
        f"⚠️ <b>Внимание!</b> Владелец не имеет поблажек.\n"
        f"Вас тоже можно проверить через .check и замутить через .mute.\n\n"
        f"Выберите действие:",
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
    
    text = "👥 <b>Список пользователей BotHelper:</b>\n\n"
    for i, (uid, username, fname, connected_at) in enumerate(users[:30], 1):
        muted_status = "🔇" if db.is_muted(uid) else "🟢"
        owner_mark = " 👑" if uid == OWNER_ID else ""
        text += f"{i}. {muted_status} <a href='tg://user?id={uid}'>{fname}</a>{owner_mark}"
        if username:
            text += f" (@{username})"
        text += f"\n   🕐 Подключён: {connected_at[:10]}\n\n"
    
    if len(users) > 30:
        text += f"\n... и ещё {len(users) - 30} пользователей"
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard(), parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "owner_broadcast")
async def owner_broadcast_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "Отправьте сообщение для рассылки всем пользователям.\n\n"
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
                await bot.send_message(user_id, f"📢 <b>Анонс от BotHelper</b>\n\n{message.text}", parse_mode="HTML")
            elif message.photo:
                await bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                await bot.send_video(user_id, message.video.file_id, caption=message.caption)
            elif message.document:
                await bot.send_document(user_id, message.document.file_id, caption=message.caption)
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Ошибка рассылки {user_id}: {e}")
            fail += 1
    
    await status_msg.edit_text(f"✅ Рассылка завершена!\n📨 Отправлено: {success}\n❌ Ошибок: {fail}")
    await state.clear()

@dp.callback_query(lambda c: c.data == "owner_restart")
async def owner_restart_callback(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text("🔄 <b>Перезапуск бота...</b>\n\nБот будет перезапущен через 2 секунды.", parse_mode="HTML")
    await asyncio.sleep(2)
    os.execv(sys.executable, [sys.executable] + sys.argv)

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        f"🤖 <b>BotHelper</b> — главное меню\n\n"
        f"Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

# ==================== КОМАНДЫ В ЧАТАХ (БЕЗ ИСКЛЮЧЕНИЙ ДЛЯ ВЛАДЕЛЬЦА) ====================
@dp.message(Command("mute"))
async def mute_command(message: Message):
    """Замутить пользователя — можно замутить ЛЮБОГО, включая владельца"""
    if not message.reply_to_message:
        await message.reply("❌ Ответьте на сообщение пользователя, которого хотите замутить.")
        return
    
    target = message.reply_to_message.from_user
    
    # НЕТ проверки на OWNER_ID! Владельца тоже можно замутить
    db.add_mute(target.id, message.from_user.id, "Mute by command")
    
    await message.reply(
        f"🔇 <b>Молчать.</b>\n\n"
        f"Пользователь <a href='tg://user?id={target.id}'>{target.first_name}</a> замучен.",
        parse_mode="HTML"
    )
    
    try:
        await message.delete()
    except:
        pass

@dp.message(Command("unmute"))
async def unmute_command(message: Message):
    """Размутить пользователя — работает для всех"""
    if not message.reply_to_message:
        await message.reply("❌ Ответьте на сообщение пользователя.")
        return
    
    target = message.reply_to_message.from_user
    db.remove_mute(target.id)
    
    await message.reply(
        f"🔊 Пользователь <a href='tg://user?id={target.id}'>{target.first_name}</a> размучен.",
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
            await message.reply("📭 У вас нет настроенных автоответчиков.\n\nИспользуйте: `.auto добавить команда ответ`")
        else:
            text = "📋 <b>Ваши автоответчики:</b>\n\n"
            for cmd, resp in replies:
                text += f"• <code>{cmd}</code> → {resp[:50]}\n"
            await message.reply(text, parse_mode="HTML")
        return
    
    if len(args) >= 3 and args[1] == "добавить":
        cmd = args[2].lower()
        resp = " ".join(args[3:])
        if not resp:
            await message.reply("❌ Укажите ответ: `.auto добавить команда текст ответа`")
            return
        db.add_autoreply(message.from_user.id, cmd, resp)
        await message.reply(f"✅ Автоответчик добавлен!\n<code>{cmd}</code> → {resp}", parse_mode="HTML")
        return
    
    if len(args) >= 3 and args[1] == "удалить":
        cmd = args[2].lower()
        db.remove_autoreply(message.from_user.id, cmd)
        await message.reply(f"✅ Автоответчик <code>{cmd}</code> удалён.", parse_mode="HTML")
        return
    
    await message.reply(
        "📖 <b>Команды .auto</b>\n\n"
        "`.auto list` — список автоответчиков\n"
        "`.auto добавить команда ответ` — добавить\n"
        "`.auto удалить команда` — удалить\n\n"
        "<b>Пример:</b>\n"
        "`.auto добавить привет Здравствуйте! Чем могу помочь?`",
        parse_mode="HTML"
    )

@dp.message(Command("check"))
async def check_command(message: Message):
    """Проверка безопасности пользователя — работает для ВСЕХ, включая владельца"""
    if not message.reply_to_message:
        await message.reply("❌ Ответьте на сообщение пользователя для проверки.")
        return
    
    target = message.reply_to_message.from_user
    is_safe, notes = db.get_safety(target.id)
    
    if is_safe is None:
        db.set_safety(target.id, True, "Автоматическая проверка")
        is_safe = True
    
    if is_safe:
        status = "✅ <b>Безопасный</b>"
        color = "🟢"
    else:
        status = "⚠️ <b>Подозрительный</b>"
        color = "🔴"
    
    # Добавляем пометку, если это владелец
    owner_tag = " 👑 (владелец)" if target.id == OWNER_ID else ""
    
    await message.reply(
        f"🛡️ <b>Проверка безопасности</b>\n\n"
        f"{color} <b>Пользователь:</b> <a href='tg://user?id={target.id}'>{target.first_name}</a>{owner_tag}\n"
        f"{status}\n"
        f"📝 <b>Примечание:</b> {notes or 'Нет'}\n\n"
        f"🤖 Проверено BotHelper",
        parse_mode="HTML"
    )
    
    try:
        await message.delete()
    except:
        pass

@dp.message(Command("check_set"))
async def check_set_command(message: Message):
    """Установка статуса безопасности (доступно всем!)"""
    args = message.text.split()
    if len(args) < 4:
        await message.reply("Использование: `.check_set user_id safe/unsafe причина`\n\nПример: `.check_set 123456789 unsafe Спам`")
        return
    
    try:
        user_id = int(args[1])
        is_safe = args[2].lower() == "safe"
        reason = " ".join(args[3:])
        db.set_safety(user_id, is_safe, reason)
        
        target_name = f"<a href='tg://user?id={user_id}'>пользователя {user_id}</a>"
        await message.reply(
            f"✅ Статус для {target_name} обновлён: {'🟢 безопасен' if is_safe else '🔴 подозрительный'}\n"
            f"📝 Причина: {reason}",
            parse_mode="HTML"
        )
    except ValueError:
        await message.reply("❌ Неверный ID пользователя.")

# ==================== АВТООТВЕТЧИК В ЛС ====================
@dp.message()
async def handle_private_messages(message: Message):
    """Обработка сообщений в ЛС (автоответчик + проверка мута)"""
    if message.from_user.is_bot:
        return
    
    # Проверка на мут — работает для ВСЕХ, включая владельца!
    if db.is_muted(message.from_user.id):
        await message.delete()
        await message.answer("🔇 <b>Молчать.</b> Вы замучены.", parse_mode="HTML")
        return
    
    # Автоответчик
    text = message.text or message.caption
    if text:
        response = db.get_autoreply(message.from_user.id, text.lower().strip())
        if response:
            await message.reply(response)

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Запуск бота в режиме поллинга"""
    # Запускаем userbot в фоне
    asyncio.create_task(init_userbot())
    
    # Запускаем бота
    logger.info("🚀 BotHelper запущен!")
    logger.info(f"👑 ID владельца: {OWNER_ID} (но без привилегий!)")
    logger.info(f"📢 Канал: {OFFICIAL_CHANNEL}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
