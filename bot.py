"""
🤖 BotHelper - Telegram Business Bot
📦 SaveMod Style с автоответчиком и модерацией
"""

import os
import sys
import json
import asyncio
import logging
import sqlite3
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any, Tuple

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, BotCommand,
    BotCommandScopeDefault, BotCommandScopeChat,
    BusinessConnection, BusinessMessagesDeleted
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

# Загрузка .env
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "support")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "channel")
OFFICIAL_TG = os.getenv("OFFICIAL_TG", "telegram")

# База данных
DB_PATH = "bothelper.db"

# ==================== БАЗА ДАННЫХ ====================

class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def init_database(self):
        """Инициализация базы данных с проверкой столбцов"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_connected BOOLEAN DEFAULT FALSE,
                    is_banned BOOLEAN DEFAULT FALSE
                )
            """)
            
            # Проверка и добавление столбцов в users
            self._ensure_columns(cursor, "users", [
                ("username", "TEXT"),
                ("first_name", "TEXT"),
                ("last_name", "TEXT"),
                ("joined_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
                ("is_connected", "BOOLEAN DEFAULT FALSE"),
                ("is_banned", "BOOLEAN DEFAULT FALSE")
            ])
            
            # Таблица мутов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mutes (
                    owner_id INTEGER,
                    target_id INTEGER,
                    muted_until TIMESTAMP,
                    PRIMARY KEY (owner_id, target_id)
                )
            """)
            
            # Таблица автоответчика
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS autoresponder (
                    owner_id INTEGER PRIMARY KEY,
                    is_enabled BOOLEAN DEFAULT FALSE,
                    response_mode TEXT DEFAULT 'simple',
                    custom_text TEXT,
                    delay INTEGER DEFAULT 0
                )
            """)
            
            self._ensure_columns(cursor, "autoresponder", [
                ("is_enabled", "BOOLEAN DEFAULT FALSE"),
                ("response_mode", "TEXT DEFAULT 'simple'"),
                ("custom_text", "TEXT"),
                ("delay", "INTEGER DEFAULT 0")
            ])
            
            # Таблица истории сообщений (для отслеживания изменений/удалений)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS message_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER,
                    chat_id INTEGER,
                    message_id INTEGER,
                    user_id INTEGER,
                    text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            self._ensure_columns(cursor, "message_history", [
                ("owner_id", "INTEGER"),
                ("chat_id", "INTEGER"),
                ("message_id", "INTEGER"),
                ("user_id", "INTEGER"),
                ("text", "TEXT"),
                ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            ])
            
            conn.commit()
            logger.info("✅ База данных инициализирована")
    
    def _ensure_columns(self, cursor, table: str, columns: List[Tuple[str, str]]):
        """Проверка и добавление отсутствующих столбцов"""
        cursor.execute(f"PRAGMA table_info({table})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        for col_name, col_type in columns:
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                    logger.info(f"✅ Добавлен столбец {col_name} в таблицу {table}")
                except sqlite3.OperationalError as e:
                    logger.warning(f"⚠️ Не удалось добавить столбец {col_name}: {e}")
    
    # Пользователи
    def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            """, (user_id, username, first_name, last_name))
            cursor.execute("""
                UPDATE users SET 
                    username = COALESCE(?, username),
                    first_name = COALESCE(?, first_name),
                    last_name = COALESCE(?, last_name)
                WHERE user_id = ?
            """, (username, first_name, last_name, user_id))
            conn.commit()
    
    def update_connection_status(self, user_id: int, is_connected: bool):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_connected = ? WHERE user_id = ?", (is_connected, user_id))
            conn.commit()
    
    def get_all_users(self) -> List[Tuple]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users")
            return cursor.fetchall()
    
    def get_connected_users(self) -> List[int]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE is_connected = TRUE")
            return [row[0] for row in cursor.fetchall()]
    
    def get_unconnected_users(self) -> List[int]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE is_connected = FALSE")
            return [row[0] for row in cursor.fetchall()]
    
    def get_stats(self) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_connected = TRUE")
            connected = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_connected = FALSE")
            unconnected = cursor.fetchone()[0]
            return {"total": total, "connected": connected, "unconnected": unconnected}
    
    # Муты
    def add_mute(self, owner_id: int, target_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO mutes (owner_id, target_id, muted_until)
                VALUES (?, ?, ?)
            """, (owner_id, target_id, None))
            conn.commit()
    
    def remove_mute(self, owner_id: int, target_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM mutes WHERE owner_id = ? AND target_id = ?", (owner_id, target_id))
            conn.commit()
    
    def is_muted(self, owner_id: int, target_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM mutes WHERE owner_id = ? AND target_id = ?", (owner_id, target_id))
            return cursor.fetchone() is not None
    
    # Автоответчик
    def set_autoresponder(self, owner_id: int, enabled: bool, mode: str = "simple", custom_text: str = None, delay: int = 0):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO autoresponder (owner_id, is_enabled, response_mode, custom_text, delay)
                VALUES (?, ?, ?, ?, ?)
            """, (owner_id, enabled, mode, custom_text, delay))
            conn.commit()
    
    def get_autoresponder(self, owner_id: int) -> Optional[Tuple]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_enabled, response_mode, custom_text, delay FROM autoresponder WHERE owner_id = ?", (owner_id,))
            return cursor.fetchone()
    
    # История сообщений
    def save_message(self, owner_id: int, chat_id: int, message_id: int, user_id: int, text: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO message_history (owner_id, chat_id, message_id, user_id, text)
                VALUES (?, ?, ?, ?, ?)
            """, (owner_id, chat_id, message_id, user_id, text))
            conn.commit()
    
    def get_message(self, owner_id: int, chat_id: int, message_id: int) -> Optional[str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT text FROM message_history 
                WHERE owner_id = ? AND chat_id = ? AND message_id = ?
                ORDER BY created_at DESC LIMIT 1
            """, (owner_id, chat_id, message_id))
            row = cursor.fetchone()
            return row[0] if row else None
    
    def delete_message_record(self, owner_id: int, chat_id: int, message_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM message_history WHERE owner_id = ? AND chat_id = ? AND message_id = ?", 
                          (owner_id, chat_id, message_id))
            conn.commit()

# Инициализация БД
db = Database()

# ==================== FSM СОСТОЯНИЯ ====================

class BroadcastStates(StatesGroup):
    waiting_for_broadcast_message = State()
    waiting_for_confirm = State()

class AutoresponderStates(StatesGroup):
    waiting_for_mode = State()
    waiting_for_text = State()
    waiting_for_delay = State()

# ==================== КЛАВИАТУРЫ ====================

def get_start_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Главное меню с проверкой на владельца"""
    buttons = [
        [InlineKeyboardButton(text="ℹ️ Информация о боте", callback_data="info")],
        [InlineKeyboardButton(text="📖 Инструкция установки", callback_data="install")],
        [InlineKeyboardButton(text="🆘 Поддержка / Помощь", callback_data="support")],
        [InlineKeyboardButton(text="📢 Telegram канал", url=f"https://t.me/{CHANNEL_USERNAME}")]
    ]
    
    if user_id == OWNER_ID:
        buttons.append([InlineKeyboardButton(text="⚙️ Управление", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура панели управления"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]
    ])

def get_broadcast_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор типа рассылки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Всем пользователям", callback_data="broadcast_all")],
        [InlineKeyboardButton(text="✅ Подключенным", callback_data="broadcast_connected")],
        [InlineKeyboardButton(text="❌ Неподключенным", callback_data="broadcast_unconnected")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel")]
    ])

def get_autoresponder_keyboard(enabled: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура управления автоответчиком"""
    status_text = "🟢 Включен" if enabled else "🔴 Выключен"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Статус: {status_text}", callback_data="auto_status")],
        [InlineKeyboardButton(text="🔄 Вкл/Выкл", callback_data="auto_toggle")],
        [InlineKeyboardButton(text="📝 Режим ответа", callback_data="auto_mode")],
        [InlineKeyboardButton(text="✏️ Свой текст", callback_data="auto_custom")],
        [InlineKeyboardButton(text="⏱ Задержка", callback_data="auto_delay")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]
    ])

def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]
    ])

# ==================== КОМАНДЫ БОТА ====================

async def set_bot_commands(bot: Bot):
    """Установка красивого меню команд"""
    
    # Основные команды для всех
    main_commands = [
        BotCommand(command="start", description="🚀 Старт / Главное меню"),
        BotCommand(command="me", description="👤 Мой профиль"),
        BotCommand(command="support", description="🆘 Поддержка"),
        BotCommand(command="tg", description="📢 Официальный Telegram"),
        BotCommand(command="help", description="❓ Помощь по командам"),
    ]
    await bot.set_my_commands(main_commands, scope=BotCommandScopeDefault())
    
    # Команды для владельца
    if OWNER_ID:
        owner_commands = main_commands + [
            BotCommand(command="admin", description="⚙️ Панель управления"),
            BotCommand(command="stats", description="📊 Статистика бота"),
            BotCommand(command="broadcast", description="📨 Рассылка"),
        ]
        await bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=OWNER_ID))
    
    logger.info("✅ Команды бота установлены")

# ==================== ФИЛЬТРЫ ====================

class IsOwnerFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id == OWNER_ID

class IsBusinessChatFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.business_connection_id is not None

# ==================== ОБРАБОТЧИКИ ====================

dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ==================== БАЗОВЫЕ КОМАНДЫ ====================

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    user = message.from_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    
    welcome_text = f"""
<b>👋 Привет, {user.first_name}!</b>

Добро пожаловать в <b>BotHelper</b> — твоего персонального помощника с функциями модерации и автоответчика!

<b>🔹 Основные возможности:</b>
• Сохранение удалённых и изменённых сообщений
• Модерация чатов (.mute / .unmute)
• Автоответчик с настраиваемыми режимами
• Love-команды и красивые эффекты

<b>📌 Для начала работы подключи бота как Telegram Business:</b>
1. Открой настройки Telegram
2. Перейди в Telegram Business
3. Выбери этого бота как бизнес-инструмент

Выбери нужный раздел ниже 👇
"""
    
    await message.answer(
        welcome_text,
        reply_markup=get_start_keyboard(user.id),
        parse_mode=ParseMode.HTML
    )

@router.message(Command("me"))
async def cmd_me(message: Message):
    """Профиль пользователя"""
    user = message.from_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    
    # Получаем статус подключения
    is_connected = user.id in db.get_connected_users()
    ar_settings = db.get_autoresponder(user.id)
    
    status_emoji = "🟢" if is_connected else "🔴"
    status_text = "Подключен" if is_connected else "Не подключен"
    ar_status = "🟢 Включен" if ar_settings and ar_settings[0] else "🔴 Выключен"
    
    profile_text = f"""
<b>👤 Профиль пользователя</b>

<b>📋 Информация:</b>
├ <b>ID:</b> <code>{user.id}</code>
├ <b>Имя:</b> {user.first_name}
├ <b>Username:</b> @{user.username or 'не указан'}
├ <b>Статус:</b> {status_emoji} {status_text}
└ <b>Автоответчик:</b> {ar_status}

<b>📊 Статистика:</b>
├ Зарегистрирован: {datetime.now().strftime('%d.%m.%Y')}
└ Премиум: {'✅' if user.is_premium else '❌'}

<i>Для подключения бота используй Telegram Business в настройках</i>
"""
    
    await message.answer(profile_text, parse_mode=ParseMode.HTML)

@router.message(Command("support"))
async def cmd_support(message: Message):
    """Поддержка"""
    support_text = f"""
<b>🆘 Поддержка BotHelper</b>

Если у тебя возникли вопросы или проблемы:
• Напиши в поддержку: @{SUPPORT_USERNAME}
• Официальный канал: @{CHANNEL_USERNAME}

<b>📝 Часто задаваемые вопросы:</b>
• Как подключить бота?
• Как работает .mute?
• Как настроить автоответчик?

Выбери раздел в меню или напиши свой вопрос 👇
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать в поддержку", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(text="📢 Канал", url=f"https://t.me/{CHANNEL_USERNAME}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]
    ])
    
    await message.answer(support_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

@router.message(Command("tg"))
async def cmd_tg(message: Message):
    """Официальный Telegram"""
    await message.answer(
        f"📢 <b>Официальный Telegram канал</b>\n\nПодписывайся, чтобы быть в курсе обновлений: @{OFFICIAL_TG}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Перейти в канал", url=f"https://t.me/{OFFICIAL_TG}")]
        ]),
        parse_mode=ParseMode.HTML
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Помощь по командам"""
    help_text = """
<b>❓ Помощь по командам BotHelper</b>

<b>📱 Команды в боте:</b>
/start — Главное меню
/me — Твой профиль
/support — Поддержка
/tg — Официальный канал
/help — Это сообщение

<b>💬 Команды в чатах (при подключенном бизнесе):</b>
<b>.mute</b> — Замутить пользователя (только для вас)
<b>.unmute</b> — Размутить пользователя
<b>.love</b> — Отправить красивое love-сообщение
<b>.help</b> — Показать эту справку в чате

<b>⚙️ Команды автоответчика:</b>
/autoresponder — Настройка автоответчика

<i>Для полной функциональности подключи бота как Telegram Business!</i>
"""
    
    await message.answer(help_text, parse_mode=ParseMode.HTML)

# ==================== АДМИН КОМАНДЫ ====================

@router.message(Command("admin"), IsOwnerFilter())
async def cmd_admin(message: Message):
    """Панель управления для владельца"""
    stats = db.get_stats()
    
    admin_text = f"""
<b>⚙️ Панель управления BotHelper</b>

<b>📊 Общая статистика:</b>
├ Всего пользователей: <b>{stats['total']}</b>
├ Подключено: <b>{stats['connected']}</b>
└ Не подключено: <b>{stats['unconnected']}</b>

Выбери действие:
"""
    
    await message.answer(admin_text, reply_markup=get_admin_keyboard(), parse_mode=ParseMode.HTML)

@router.message(Command("stats"), IsOwnerFilter())
async def cmd_stats(message: Message):
    """Статистика бота"""
    stats = db.get_stats()
    
    stats_text = f"""
<b>📊 Статистика BotHelper</b>

<b>👥 Пользователи:</b>
├ Всего: {stats['total']}
├ Подключенных: {stats['connected']}
├ Неподключенных: {stats['unconnected']}
└ Конверсия: {(stats['connected']/stats['total']*100 if stats['total'] > 0 else 0):.1f}%

<b>🤖 Автоответчики:</b>
└ Активных: 0

<b>📅 За сегодня:</b>
└ Новых: 0
"""
    
    await message.answer(stats_text, parse_mode=ParseMode.HTML)

@router.message(Command("broadcast"), IsOwnerFilter())
async def cmd_broadcast(message: Message, state: FSMContext):
    """Начало рассылки"""
    await message.answer(
        "<b>📨 Рассылка сообщений</b>\n\nВыбери тип рассылки:",
        reply_markup=get_broadcast_type_keyboard(),
        parse_mode=ParseMode.HTML
    )

# ==================== CALLBACK ОБРАБОТЧИКИ ====================

@router.callback_query(F.data == "info")
async def callback_info(callback: CallbackQuery):
    """Информация о боте"""
    info_text = """
<b>ℹ️ О боте BotHelper</b>

<b>BotHelper</b> — это мощный Telegram Business бот с функциями:
• 📝 Сохранение удалённых и изменённых сообщений
• 🔇 Модерация чатов (.mute / .unmute)
• 💬 Умный автоответчик
• ❤️ Love-команды и эффекты
• 📊 Статистика и аналитика

<b>🔧 Технические особенности:</b>
• Работает через Telegram Business API
• SQLite база данных
• Асинхронная обработка
• Полная конфиденциальность

<b>📌 Версия:</b> 1.0.0
<b>📅 Обновлено:</b> 17.04.2026
"""
    
    await callback.message.edit_text(
        info_text,
        reply_markup=get_back_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "install")
async def callback_install(callback: CallbackQuery):
    """Инструкция по установке"""
    bot_username = (await callback.bot.me()).username
    
    install_text = f"""
<b>📖 Инструкция по подключению BotHelper</b>

<b>1️⃣ Шаг 1: Подготовка</b>
• Убедись, что у тебя есть Telegram Premium
• Открой настройки Telegram

<b>2️⃣ Шаг 2: Подключение</b>
• Перейди в раздел "Telegram Business"
• Нажми "Добавить бота"
• Найди @{bot_username}

<b>3️⃣ Шаг 3: Настройка</b>
• Выбери, в каких чатах бот будет работать
• Настрой права доступа
• Готово!

<b>💡 Доступные команды в чатах:</b>
• <code>.mute</code> — замутить собеседника
• <code>.unmute</code> — размутить
• <code>.love</code> — love-сообщение
• <code>.help</code> — справка

<i>После подключения бот начнёт отслеживать изменения сообщений и выполнять команды!</i>
"""
    
    await callback.message.edit_text(
        install_text,
        reply_markup=get_back_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "support")
async def callback_support(callback: CallbackQuery):
    """Поддержка через callback"""
    await callback.message.edit_text(
        f"<b>🆘 Поддержка</b>\n\nНапиши нам: @{SUPPORT_USERNAME}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать", url=f"https://t.me/{SUPPORT_USERNAME}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_start")
async def callback_back_to_start(callback: CallbackQuery):
    """Возврат в главное меню"""
    user = callback.from_user
    
    welcome_text = f"""
<b>👋 Привет, {user.first_name}!</b>

Добро пожаловать в <b>BotHelper</b> — твоего персонального помощника с функциями модерации и автоответчика!

Выбери нужный раздел ниже 👇
"""
    
    await callback.message.edit_text(
        welcome_text,
        reply_markup=get_start_keyboard(user.id),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

# ==================== АДМИН CALLBACKS ====================

@router.callback_query(F.data == "admin_panel", IsOwnerFilter())
async def callback_admin_panel(callback: CallbackQuery):
    """Панель управления"""
    stats = db.get_stats()
    
    admin_text = f"""
<b>⚙️ Панель управления BotHelper</b>

<b>📊 Общая статистика:</b>
├ Всего пользователей: <b>{stats['total']}</b>
├ Подключено: <b>{stats['connected']}</b>
└ Не подключено: <b>{stats['unconnected']}</b>

Выбери действие:
"""
    
    await callback.message.edit_text(
        admin_text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "admin_stats", IsOwnerFilter())
async def callback_admin_stats(callback: CallbackQuery):
    """Статистика"""
    stats = db.get_stats()
    users = db.get_all_users()
    
    stats_text = f"""
<b>📊 Подробная статистика</b>

<b>👥 Пользователи:</b>
├ Всего: {stats['total']}
├ Подключенных: {stats['connected']}
└ Неподключенных: {stats['unconnected']}

<b>📋 Последние 5 пользователей:</b>
"""
    
    for user in users[-5:]:
        status = "🟢" if user[5] else "🔴"
        stats_text += f"\n{status} {user[2] or 'Без имени'} (ID: {user[0]})"
    
    await callback.message.edit_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast", IsOwnerFilter())
async def callback_admin_broadcast(callback: CallbackQuery):
    """Меню рассылки"""
    await callback.message.edit_text(
        "<b>📨 Рассылка сообщений</b>\n\nВыбери тип рассылки:",
        reply_markup=get_broadcast_type_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "admin_users", IsOwnerFilter())
async def callback_admin_users(callback: CallbackQuery):
    """Список пользователей"""
    users = db.get_all_users()
    
    if not users:
        await callback.message.edit_text(
            "👥 Список пользователей пуст",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
            ])
        )
        await callback.answer()
        return
    
    # Формируем текст по 10 пользователей
    page = 0
    per_page = 10
    total_pages = (len(users) - 1) // per_page + 1
    
    start = page * per_page
    end = start + per_page
    page_users = users[start:end]
    
    text = f"<b>👥 Список пользователей (страница {page + 1}/{total_pages})</b>\n\n"
    for user in page_users:
        status = "🟢" if user[5] else "🔴"
        text += f"{status} <code>{user[0]}</code> — {user[2] or 'Без имени'}"
        if user[1]:
            text += f" (@{user[1]})"
        text += "\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data.startswith("broadcast_"), IsOwnerFilter())
async def callback_broadcast_type(callback: CallbackQuery, state: FSMContext):
    """Выбор типа рассылки и запрос сообщения"""
    broadcast_type = callback.data.replace("broadcast_", "")
    
    type_names = {
        "all": "всем пользователям",
        "connected": "подключенным пользователям",
        "unconnected": "неподключенным пользователям"
    }
    
    await state.update_data(broadcast_type=broadcast_type)
    await state.set_state(BroadcastStates.waiting_for_broadcast_message)
    
    await callback.message.edit_text(
        f"<b>📨 Рассылка для: {type_names.get(broadcast_type, broadcast_type)}</b>\n\n"
        "Отправь сообщение для рассылки (можно с фото, видео, форматированием):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.message(BroadcastStates.waiting_for_broadcast_message, IsOwnerFilter())
async def process_broadcast_message(message: Message, state: FSMContext, bot: Bot):
    """Обработка сообщения для рассылки"""
    data = await state.get_data()
    broadcast_type = data.get("broadcast_type", "all")
    
    # Сохраняем сообщение в state
    await state.update_data(broadcast_message=message.model_dump())
    await state.set_state(BroadcastStates.waiting_for_confirm)
    
    type_names = {
        "all": "всем пользователям",
        "connected": "подключенным",
        "unconnected": "неподключенным"
    }
    
    confirm_text = f"""
<b>📨 Подтверждение рассылки</b>

<b>Тип:</b> {type_names.get(broadcast_type, broadcast_type)}

Отправить рассылку?
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")
        ]
    ])
    
    await message.answer(confirm_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "broadcast_confirm", IsOwnerFilter())
async def callback_broadcast_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Подтверждение и отправка рассылки (прогресс виден только владельцу)"""
    data = await state.get_data()
    broadcast_type = data.get("broadcast_type", "all")
    msg_data = data.get("broadcast_message", {})
    
    # Получаем список получателей
    if broadcast_type == "all":
        recipients = [u[0] for u in db.get_all_users()]
    elif broadcast_type == "connected":
        recipients = db.get_connected_users()
    else:
        recipients = db.get_unconnected_users()
    
    # Сообщение с прогрессом (видно только владельцу)
    progress_text = f"""
📨 <b>Рассылка запущена</b>

├ Тип: <b>{broadcast_type}</b>
├ Получателей: <b>{len(recipients)}</b>
└ Прогресс: 0/{len(recipients)} (0%)
"""
    
    progress_msg = await callback.message.edit_text(
        progress_text,
        parse_mode=ParseMode.HTML
    )
    
    success = 0
    failed = 0
    
    for i, user_id in enumerate(recipients):
        try:
            # Пересылаем сохранённое сообщение
            if msg_data.get("text"):
                await bot.send_message(
                    user_id,
                    msg_data["text"],
                    parse_mode=ParseMode.HTML if msg_data.get("entities") else None
                )
            elif msg_data.get("photo"):
                await bot.send_photo(
                    user_id,
                    msg_data["photo"][-1]["file_id"],
                    caption=msg_data.get("caption")
                )
            elif msg_data.get("video"):
                await bot.send_video(
                    user_id,
                    msg_data["video"]["file_id"],
                    caption=msg_data.get("caption")
                )
            elif msg_data.get("animation"):
                await bot.send_animation(
                    user_id,
                    msg_data["animation"]["file_id"],
                    caption=msg_data.get("caption")
                )
            elif msg_data.get("document"):
                await bot.send_document(
                    user_id,
                    msg_data["document"]["file_id"],
                    caption=msg_data.get("caption")
                )
            success += 1
        except Exception as e:
            logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
            failed += 1
        
        # Обновляем прогресс каждые 5 отправок или в конце (видно только владельцу)
        if (i + 1) % 5 == 0 or i == len(recipients) - 1:
            percent = round((i + 1) / len(recipients) * 100)
            progress_text = f"""
📨 <b>Рассылка в процессе</b>

├ Тип: <b>{broadcast_type}</b>
├ Всего: <b>{len(recipients)}</b>
├ Прогресс: <b>{i + 1}/{len(recipients)}</b> ({percent}%)
├ ✅ Успешно: <b>{success}</b>
└ ❌ Ошибок: <b>{failed}</b>
"""
            try:
                await progress_msg.edit_text(progress_text, parse_mode=ParseMode.HTML)
            except:
                pass
            
            await asyncio.sleep(0.3)
    
    # Итоговый отчёт (виден только владельцу)
    final_text = f"""
✅ <b>Рассылка завершена!</b>

📊 <b>Результаты:</b>
├ Тип рассылки: <b>{broadcast_type}</b>
├ Всего получателей: <b>{len(recipients)}</b>
├ ✅ Успешно доставлено: <b>{success}</b>
└ ❌ Ошибок доставки: <b>{failed}</b>
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В панель управления", callback_data="admin_panel")],
        [InlineKeyboardButton(text="📨 Новая рассылка", callback_data="admin_broadcast")]
    ])
    
    await progress_msg.edit_text(final_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
    await state.clear()
    await callback.answer("✅ Рассылка завершена!")

# ==================== АВТООТВЕТЧИК ====================

@router.message(Command("autoresponder"))
async def cmd_autoresponder(message: Message):
    """Настройка автоответчика"""
    user_id = message.from_user.id
    ar_settings = db.get_autoresponder(user_id)
    
    if not ar_settings:
        db.set_autoresponder(user_id, False, "simple", None, 0)
        ar_settings = (False, "simple", None, 0)
    
    enabled, mode, custom_text, delay = ar_settings
    
    status = "🟢 Включен" if enabled else "🔴 Выключен"
    modes = {
        "simple": "Простой ответ",
        "random": "Случайный ответ",
        "echo": "Эхо (повтор)",
        "custom": "Свой текст"
    }
    
    text = f"""
<b>💬 Настройка автоответчика</b>

<b>📊 Текущие настройки:</b>
├ Статус: {status}
├ Режим: {modes.get(mode, mode)}
├ Задержка: {delay} сек
└ Свой текст: {custom_text or 'не задан'}

Выбери действие:
"""
    
    await message.answer(
        text,
        reply_markup=get_autoresponder_keyboard(enabled),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data == "auto_toggle")
async def callback_auto_toggle(callback: CallbackQuery):
    """Включение/выключение автоответчика"""
    user_id = callback.from_user.id
    ar_settings = db.get_autoresponder(user_id)
    
    if ar_settings:
        new_enabled = not ar_settings[0]
        db.set_autoresponder(user_id, new_enabled, ar_settings[1], ar_settings[2], ar_settings[3])
    else:
        db.set_autoresponder(user_id, True, "simple", None, 0)
        new_enabled = True
    
    status = "🟢 включен" if new_enabled else "🔴 выключен"
    await callback.answer(f"Автоответчик {status}")
    
    # Обновляем сообщение
    ar_settings = db.get_autoresponder(user_id)
    if ar_settings:
        enabled, mode, custom_text, delay = ar_settings
    else:
        enabled, mode, custom_text, delay = False, "simple", None, 0
    
    modes = {"simple": "Простой", "random": "Случайный", "echo": "Эхо", "custom": "Свой"}
    status_text = "🟢 Включен" if enabled else "🔴 Выключен"
    
    text = f"""
<b>💬 Настройка автоответчика</b>

<b>📊 Текущие настройки:</b>
├ Статус: {status_text}
├ Режим: {modes.get(mode, mode)}
├ Задержка: {delay} сек
└ Свой текст: {custom_text or 'не задан'}

Выбери действие:
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_autoresponder_keyboard(enabled),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data == "auto_mode")
async def callback_auto_mode(callback: CallbackQuery, state: FSMContext):
    """Выбор режима автоответчика"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Простой ответ", callback_data="auto_mode_simple")],
        [InlineKeyboardButton(text="🎲 Случайный ответ", callback_data="auto_mode_random")],
        [InlineKeyboardButton(text="🔄 Эхо (повтор)", callback_data="auto_mode_echo")],
        [InlineKeyboardButton(text="✏️ Свой текст", callback_data="auto_mode_custom")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_auto_settings")]
    ])
    
    await callback.message.edit_text(
        "<b>Выбери режим автоответчика:</b>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "auto_custom")
async def callback_auto_custom(callback: CallbackQuery, state: FSMContext):
    """Установка своего текста"""
    await state.set_state(AutoresponderStates.waiting_for_text)
    await callback.message.edit_text(
        "<b>✏️ Введи свой текст для автоответчика:</b>\n\n"
        "<i>Этот текст будет отправляться в ответ на любое сообщение</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_auto_settings")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.message(AutoresponderStates.waiting_for_text)
async def process_custom_text(message: Message, state: FSMContext):
    """Обработка своего текста"""
    user_id = message.from_user.id
    custom_text = message.text
    
    ar_settings = db.get_autoresponder(user_id)
    if ar_settings:
        db.set_autoresponder(user_id, ar_settings[0], "custom", custom_text, ar_settings[3])
    else:
        db.set_autoresponder(user_id, False, "custom", custom_text, 0)
    
    await state.clear()
    await message.answer(
        f"✅ Текст автоответчика установлен:\n\n<i>{custom_text}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К настройкам", callback_data="back_to_auto_settings")]
        ])
    )

@router.callback_query(F.data == "auto_delay")
async def callback_auto_delay(callback: CallbackQuery, state: FSMContext):
    """Установка задержки"""
    await state.set_state(AutoresponderStates.waiting_for_delay)
    await callback.message.edit_text(
        "<b>⏱ Введи задержку в секундах (0-60):</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_auto_settings")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.message(AutoresponderStates.waiting_for_delay)
async def process_delay(message: Message, state: FSMContext):
    """Обработка задержки"""
    user_id = message.from_user.id
    
    try:
        delay = int(message.text)
        if delay < 0 or delay > 60:
            raise ValueError
    except:
        await message.answer("❌ Введи число от 0 до 60")
        return
    
    ar_settings = db.get_autoresponder(user_id)
    if ar_settings:
        db.set_autoresponder(user_id, ar_settings[0], ar_settings[1], ar_settings[2], delay)
    else:
        db.set_autoresponder(user_id, False, "simple", None, delay)
    
    await state.clear()
    await message.answer(
        f"✅ Задержка установлена: {delay} сек",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К настройкам", callback_data="back_to_auto_settings")]
        ])
    )

@router.callback_query(F.data.startswith("auto_mode_"))
async def callback_auto_mode_set(callback: CallbackQuery, state: FSMContext):
    """Установка режима автоответчика"""
    mode = callback.data.replace("auto_mode_", "")
    user_id = callback.from_user.id
    ar_settings = db.get_autoresponder(user_id)
    
    mode_names = {
        "simple": "Простой ответ",
        "random": "Случайный ответ", 
        "echo": "Эхо",
        "custom": "Свой текст"
    }
    
    if ar_settings:
        db.set_autoresponder(user_id, ar_settings[0], mode, ar_settings[2], ar_settings[3])
    else:
        db.set_autoresponder(user_id, False, mode, None, 0)
    
    await callback.answer(f"Режим изменён на: {mode_names.get(mode, mode)}")
    await callback.message.edit_text(
        f"✅ Режим автоответчика изменён на: <b>{mode_names.get(mode, mode)}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад к настройкам", callback_data="back_to_auto_settings")]
        ]),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data == "auto_status")
async def callback_auto_status(callback: CallbackQuery):
    """Показ текущего статуса"""
    await callback.answer("Используй кнопку Вкл/Выкл для изменения")
    await callback_back_to_auto_settings(callback)

@router.callback_query(F.data == "back_to_auto_settings")
async def callback_back_to_auto_settings(callback: CallbackQuery):
    """Возврат к настройкам автоответчика"""
    user_id = callback.from_user.id
    ar_settings = db.get_autoresponder(user_id)
    
    if not ar_settings:
        ar_settings = (False, "simple", None, 0)
    
    enabled, mode, custom_text, delay = ar_settings
    modes = {"simple": "Простой", "random": "Случайный", "echo": "Эхо", "custom": "Свой"}
    status_text = "🟢 Включен" if enabled else "🔴 Выключен"
    
    text = f"""
<b>💬 Настройка автоответчика</b>

<b>📊 Текущие настройки:</b>
├ Статус: {status_text}
├ Режим: {modes.get(mode, mode)}
├ Задержка: {delay} сек
└ Свой текст: {custom_text or 'не задан'}

Выбери действие:
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_autoresponder_keyboard(enabled),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

# ==================== TELEGRAM BUSINESS ОБРАБОТЧИКИ ====================

@router.business_connection()
async def on_business_connection(business_connection: BusinessConnection, bot: Bot):
    """Обработчик подключения/отключения бизнес-аккаунта"""
    user_id = business_connection.user.id
    is_enabled = not business_connection.is_disabled
    
    db.update_connection_status(user_id, is_enabled)
    
    if is_enabled:
        # Отправляем приветственное сообщение в ЛС
        welcome_text = f"""
<b>✅ BotHelper успешно подключен как Telegram Business!</b>

<b>🎉 Теперь тебе доступны все функции:</b>

<b>💬 Команды в чатах:</b>
• <code>.mute</code> — замутить собеседника (только для тебя)
• <code>.unmute</code> — размутить
• <code>.love</code> — красивое love-сообщение
• <code>.help</code> — справка по командам

<b>📝 Функции:</b>
• Отслеживание изменённых сообщений
• Сохранение удалённых сообщений
• Автоответчик

<b>⚙️ Настройки:</b>
/autoresponder — настроить автоответчик
/me — твой профиль

<i>Приятного использования! 🚀</i>
"""
        try:
            await bot.send_message(user_id, welcome_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Не удалось отправить приветствие пользователю {user_id}: {e}")

@router.business_message(IsBusinessChatFilter())
async def on_business_message(message: Message, bot: Bot):
    """Обработчик бизнес-сообщений"""
    if not message.business_connection_id:
        return
    
    owner_id = message.from_user.id
    chat_id = message.chat.id
    user = message.from_user if message.from_user else None
    
    # Сохраняем сообщение в историю
    if message.text:
        db.save_message(owner_id, chat_id, message.message_id, user.id if user else 0, message.text)
    
    # Проверяем на команды с точкой
    if message.text and message.text.startswith('.'):
        await handle_dot_command(message, bot)
        return
    
    # Проверяем мут
    if user and db.is_muted(owner_id, user.id):
        try:
            await message.delete()
            logger.info(f"Удалено сообщение от замученного пользователя {user.id} для {owner_id}")
        except Exception as e:
            logger.error(f"Ошибка удаления сообщения: {e}")
        return
    
    # Автоответчик
    ar_settings = db.get_autoresponder(owner_id)
    if ar_settings and ar_settings[0]:  # если включен
        await handle_autoresponder(message, bot, ar_settings)

@router.edited_business_message()
async def on_business_message_edited(message: Message, bot: Bot):
    """Обработчик изменённых бизнес-сообщений"""
    owner_id = message.from_user.id
    chat_id = message.chat.id
    user = message.from_user
    
    # Получаем старое сообщение из БД
    old_text = db.get_message(owner_id, chat_id, message.message_id)
    
    if old_text and old_text != message.text:
        # Отправляем уведомление владельцу
        user_info = f"@{user.username}" if user.username else user.first_name
        notification = f"""
<b>📝 Изменение произошло в чате</b>

<b>👤 Пользователь:</b> {user_info}
<b>🆔 ID:</b> <code>{user.id}</code>

<b>📋 Было:</b>
{old_text[:500] + '...' if len(old_text) > 500 else old_text}

<b>📋 Стало:</b>
{message.text[:500] + '...' if len(message.text) > 500 else message.text}
"""
        try:
            await bot.send_message(owner_id, notification, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления об изменении: {e}")
    
    # Обновляем в БД
    if message.text:
        db.save_message(owner_id, chat_id, message.message_id, user.id, message.text)

@router.business_messages_deleted()
async def on_business_messages_deleted(event: BusinessMessagesDeleted, bot: Bot):
    """Обработчик удалённых бизнес-сообщений"""
    owner_id = event.business_connection_id
    chat_id = event.chat.id
    message_ids = event.message_ids
    
    for msg_id in message_ids:
        old_text = db.get_message(owner_id, chat_id, msg_id)
        if old_text:
            notification = f"""
<b>🗑 Сообщение удалено в чате</b>

<b>📋 Содержимое:</b>
{old_text[:500] + '...' if len(old_text) > 500 else old_text}
"""
            try:
                await bot.send_message(owner_id, notification, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления об удалении: {e}")

async def handle_dot_command(message: Message, bot: Bot):
    """Обработка команд с точкой (.mute, .unmute, .love, .help)"""
    if not message.text:
        return
    
    command = message.text.lower().split()[0]
    owner_id = message.from_user.id
    
    if command == ".mute":
        # Определяем цель (ответ на сообщение)
        target_id = None
        if message.reply_to_message:
            target_id = message.reply_to_message.from_user.id
            target_name = message.reply_to_message.from_user.first_name
        
        if target_id:
            db.add_mute(owner_id, target_id)
            await message.delete()
            
            # Отправляем уведомление (только владелец видит)
            try:
                await bot.send_message(
                    owner_id,
                    f"🔇 <b>Молчать.</b> Пользователь {target_name} замучен для вас.",
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
    
    elif command == ".unmute":
        target_id = None
        if message.reply_to_message:
            target_id = message.reply_to_message.from_user.id
            target_name = message.reply_to_message.from_user.first_name
        
        if target_id:
            db.remove_mute(owner_id, target_id)
            await message.delete()
            
            try:
                await bot.send_message(
                    owner_id,
                    f"🔈 <b>Говори.</b> Пользователь {target_name} размучен.",
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
    
    elif command == ".love":
        # Красивое love-сообщение
        target_name = "тебя"
        if message.reply_to_message:
            target_name = message.reply_to_message.from_user.first_name
        
        love_messages = [
            f"❤️ {target_name} ❤️",
            f"💕 {target_name} 💕",
            f"💗 {target_name} 💗",
            f"💓 {target_name} 💓",
            f"💖 {target_name} 💖",
            f"💘 {target_name} 💘",
            f"💝 {target_name} 💝",
            f"🌸 {target_name} 🌸",
            f"✨ {target_name} ✨",
            f"🦋 {target_name} 🦋",
        ]
        
        love_text = random.choice(love_messages)
        
        # Отправляем и оставляем сообщение
        await message.answer(love_text)
        await message.delete()
    
    elif command == ".help":
        help_text = """
<b>💬 Команды BotHelper в чатах:</b>

<b>.mute</b> — замутить пользователя (только для вас)
<b>.unmute</b> — размутить пользователя  
<b>.love</b> — отправить красивое love-сообщение
<b>.help</b> — показать эту справку

<i>Команды работают только при подключенном Telegram Business!</i>
"""
        try:
            await bot.send_message(owner_id, help_text, parse_mode=ParseMode.HTML)
            await message.delete()
        except:
            pass

async def handle_autoresponder(message: Message, bot: Bot, ar_settings: Tuple):
    """Обработка автоответчика"""
    enabled, mode, custom_text, delay = ar_settings
    
    if not enabled:
        return
    
    # Задержка
    if delay > 0:
        await asyncio.sleep(delay)
    
    responses = {
        "simple": ["Привет!", "Я сейчас занят, отвечу позже", "Спасибо за сообщение!", "👍"],
        "random": ["👋", "👍", "❤️", "😊", "Скоро отвечу", "Ок", "Понял"],
        "echo": [f"Вы написали: {message.text[:100]}"],
        "custom": [custom_text or "Автоответчик"]
    }
    
    response = random.choice(responses.get(mode, ["Автоответчик"]))
    
    try:
        await message.reply(response)
    except Exception as e:
        logger.error(f"Ошибка автоответчика: {e}")

# ==================== ЗАПУСК ====================

async def main():
    """Главная функция запуска"""
    logger.info("🤖 BotHelper запускается...")
    
    # Проверяем токен
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден в .env файле!")
        sys.exit(1)
    
    # Инициализируем бота
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Устанавливаем команды
    await set_bot_commands(bot)
    
    # Запускаем polling
    logger.info("✅ Бот запущен и готов к работе!")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
