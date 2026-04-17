import os
import sqlite3
import asyncio
import logging
from collections import OrderedDict
from datetime import datetime
import aiohttp

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# === НАСТРОЙКИ ===
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")
OFFICIAL_CHANNEL = os.getenv("OFFICIAL_CHANNEL", "")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")

DB_PATH = os.path.join(DATA_DIR, "bot.db")
os.makedirs(DATA_DIR, exist_ok=True)

# Кэш сообщений для отслеживания редактирования (max 500)
message_cache = OrderedDict()
MAX_CACHE_SIZE = 500

# === БАЗА ДАННЫХ ===
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        # users: все пользователи бота
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # business_users: пользователи из бизнес-чатов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS business_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                business_connection_id TEXT,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # muted: замученные пользователи
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS muted (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                muted_by INTEGER,
                muted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reason TEXT
            )
        """)
        # autoreplies: автоответы
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS autoreplies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                response TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # safety: проверенные безопасные пользователи
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS safety (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                checked_by INTEGER,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        """)
        # user_warnings: история предупреждений
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                warned_by INTEGER,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

init_db()

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def add_to_cache(message_id: int, text: str):
    if message_id in message_cache:
        del message_cache[message_id]
    message_cache[message_id] = text
    while len(message_cache) > MAX_CACHE_SIZE:
        message_cache.popitem(last=False)

def is_muted(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM muted WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

def get_muted_info(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT muted_at, reason FROM muted WHERE user_id = ?", (user_id,))
        return cursor.fetchone()

def is_safe(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM safety WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

def get_safety_info(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, first_name, checked_at, notes 
            FROM safety WHERE user_id = ?
        """, (user_id,))
        return cursor.fetchone()

def save_user(user_id: int, username: str, first_name: str, last_name: str):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, last_active) 
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET 
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                last_active=CURRENT_TIMESTAMP
        """, (user_id, username, first_name, last_name))
        conn.commit()

def save_business_user(user_id: int, username: str, first_name: str, last_name: str, biz_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO business_users (user_id, username, first_name, last_name, business_connection_id, last_seen) 
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET 
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                business_connection_id=excluded.business_connection_id,
                last_seen=CURRENT_TIMESTAMP
        """, (user_id, username, first_name, last_name, biz_id))
        conn.commit()

def get_stats():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM business_users")
        biz_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM muted")
        muted_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM safety")
        safety_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM autoreplies")
        autoreplies_count = cursor.fetchone()[0]
    return {
        'users': users_count,
        'business': biz_count,
        'muted': muted_count,
        'safety': safety_count,
        'autoreplies': autoreplies_count,
        'cache_size': len(message_cache)
    }

# === ПОИСК ИНФОРМАЦИИ О ПОЛЬЗОВАТЕЛЕ ===
async def search_user_info(user_id: int, username: str = None) -> dict:
    """Поиск информации о пользователе в разных источниках"""
    info = {
        'in_business': False,
        'in_safety': False,
        'in_muted': False,
        'first_seen': None,
        'warning_count': 0
    }
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Проверка в business_users
        cursor.execute("SELECT last_seen FROM business_users WHERE user_id = ?", (user_id,))
        biz = cursor.fetchone()
        if biz:
            info['in_business'] = True
            info['first_seen'] = biz[0]
        
        # Проверка в safety
        cursor.execute("SELECT checked_at, notes FROM safety WHERE user_id = ?", (user_id,))
        safety = cursor.fetchone()
        if safety:
            info['in_safety'] = True
            info['safety_date'] = safety[0]
            info['safety_notes'] = safety[1]
        
        # Проверка в muted
        cursor.execute("SELECT muted_at, reason FROM muted WHERE user_id = ?", (user_id,))
        muted = cursor.fetchone()
        if muted:
            info['in_muted'] = True
            info['muted_date'] = muted[0]
            info['muted_reason'] = muted[1]
        
        # Количество предупреждений
        cursor.execute("SELECT COUNT(*) FROM user_warnings WHERE user_id = ?", (user_id,))
        info['warning_count'] = cursor.fetchone()[0]
    
    return info

# === БОТ И ДИСПЕТЧЕР ===
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# === ОБРАБОТЧИКИ ===

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    save_user(user.id, user.username, user.first_name, user.last_name)
    
    welcome_text = (
        f"🤖 <b>Добро пожаловать в BotHelper!</b>\n\n"
        f"BotHelper — это профессиональный инструмент для владельцев Telegram Business, "
        f"который помогает управлять личными чатами с клиентами и подписчиками.\n\n"
        f"<b>Возможности:</b>\n"
        f"• 🔇 Мгновенный мут нежелательных пользователей\n"
        f"• ✅ Проверка пользователей на безопасность\n"
        f"• 💬 Автоответы на частые вопросы\n"
        f"• ✏️ Отслеживание изменений сообщений\n"
        f"• 📊 Подробная статистика\n\n"
        f"<b>Как это работает:</b>\n"
        f"Бот подключается к вашему Telegram Business аккаунту и работает "
        f"в личных чатах, помогая модерировать общение."
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 О боте", callback_data="about")],
        [InlineKeyboardButton(text="🔌 Как подключить", callback_data="howto")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help_setup")],
        [InlineKeyboardButton(text="📞 Техподдержка", url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}")],
        [InlineKeyboardButton(text="📢 Наш канал", url=f"https://t.me/{OFFICIAL_CHANNEL.lstrip('@')}")]
    ])
    
    if user.id == OWNER_ID:
        kb.inline_keyboard.extend([
            [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton(text="👑 Панель управления", callback_data="admin_panel")]
        ])
    
    await message.answer(welcome_text, reply_markup=kb)

@dp.callback_query()
async def process_callback(callback: types.CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id
    
    if data == "about":
        text = (
            "📖 <b>О BotHelper</b>\n\n"
            "<b>BotHelper v1.0</b> — умный помощник для Telegram Business\n\n"
            "Создан для того, чтобы сделать управление личными чатами "
            "максимально удобным и безопасным.\n\n"
            "<b>Ключевые функции:</b>\n"
            "• Модерация сообщений в реальном времени\n"
            "• База данных проверенных пользователей\n"
            "• Система автоответов\n"
            "• Отслеживание правок\n\n"
            "Бот работает только через официальное Business API Telegram."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_start")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
    
    elif data == "howto":
        text = (
            "🔌 <b>Как подключить BotHelper</b>\n\n"
            "<b>Требования:</b>\n"
            "• Активная подписка Telegram Premium\n"
            "• Включенный Telegram Business\n\n"
            "<b>Пошаговая инструкция:</b>\n\n"
            "1️⃣ Откройте Настройки Telegram\n"
            "2️⃣ Перейдите в раздел «Telegram Business»\n"
            "3️⃣ Выберите «Боты» → «Подключить бота»\n"
            "4️⃣ Найдите @BotHelper и нажмите «Добавить»\n"
            "5️⃣ В настройках бота включите:\n"
            "   • Чтение сообщений\n"
            "   • Удаление сообщений\n"
            "   • Отправка сообщений\n\n"
            "✅ Готово! Бот начнет работать во всех ваших личных чатах."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_start")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
    
    elif data == "help_setup":
        text = (
            "❓ <b>Помощь по настройке</b>\n\n"
            "<b>Частые вопросы:</b>\n\n"
            "🔹 <b>Бот не реагирует на сообщения</b>\n"
            "Проверьте, что в настройках Business бота включены все необходимые разрешения.\n\n"
            "🔹 <b>Как добавить автоответ?</b>\n"
            "Используйте команду <code>.addauto ключ | ответ</code> в чате с ботом (только для владельца).\n\n"
            "🔹 <b>Как проверить пользователя?</b>\n"
            "Ответьте на его сообщение командой <code>.check</code>\n\n"
            "По всем вопросам обращайтесь в техподдержку."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 Техподдержка", url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_start")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
    
    elif data == "stats" and user_id == OWNER_ID:
        stats = get_stats()
        text = (
            "📊 <b>Статистика BotHelper</b>\n\n"
            f"👥 Всего пользователей: {stats['users']}\n"
            f"💼 Business-пользователей: {stats['business']}\n"
            f"🔇 Замученных: {stats['muted']}\n"
            f"✅ Проверенных: {stats['safety']}\n"
            f"💬 Автоответов: {stats['autoreplies']}\n"
            f"📦 Сообщений в кэше: {stats['cache_size']}\n\n"
            f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="stats")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_start")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
    
    elif data == "admin_panel" and user_id == OWNER_ID:
        text = (
            "👑 <b>Панель управления</b>\n\n"
            "<b>Команды модерации</b> (отправлять ответом на сообщение в бизнес-чате):\n"
            "• <code>.mute</code> — замутить пользователя\n"
            "• <code>.unmute</code> — снять мут\n"
            "• <code>.check</code> — проверить безопасность\n"
            "• <code>.warn [причина]</code> — вынести предупреждение\n\n"
            "<b>Управление автоответами:</b>\n"
            "• <code>.addauto ключ | ответ</code> — добавить автоответ\n"
            "• <code>.delauto ключ</code> — удалить автоответ\n"
            "• <code>.listauto</code> — список автоответов\n\n"
            "<b>Статистика:</b>\n"
            "• <code>.info [user_id]</code> — информация о пользователе"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_start")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
    
    elif data == "back_start":
        await cmd_start(callback.message)
    
    await callback.answer()

@dp.message()
async def handle_all_messages(message: types.Message):
    # Игнорируем НЕ business-сообщения
    if message.business_connection_id is None:
        return
    
    user = message.from_user
    biz_id = message.business_connection_id
    save_business_user(user.id, user.username, user.first_name, user.last_name, biz_id)
    save_user(user.id, user.username, user.first_name, user.last_name)
    
    text = message.text or message.caption or ""
    
    # Кэшируем для отслеживания редактирования
    if text:
        add_to_cache(message.message_id, text)
    
    # Проверяем, не замучен ли пользователь
    if is_muted(user.id):
        try:
            await message.delete()
            muted_info = get_muted_info(user.id)
            reason_text = f"\nПричина: {muted_info[1]}" if muted_info and muted_info[1] else ""
            await message.answer(f"🔇 Вы заблокированы в этом чате.{reason_text}")
        except Exception as e:
            logging.warning(f"Не удалось удалить сообщение: {e}")
        return
    
    # Обработка команд владельца
    if user.id == OWNER_ID and text.startswith("."):
        cmd_parts = text.strip().split(maxsplit=1)
        cmd = cmd_parts[0].lower()
        
        # Удаляем команду
        try:
            await message.delete()
        except:
            pass
        
        # Команды, требующие ответа на сообщение
        if cmd in [".mute", ".unmute", ".check", ".warn"]:
            if not message.reply_to_message:
                await message.answer("❌ Эта команда должна быть отправлена ответом на сообщение пользователя")
                return
            
            target_user = message.reply_to_message.from_user
            target_id = target_user.id
            
            if cmd == ".mute":
                reason = cmd_parts[1] if len(cmd_parts) > 1 else None
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO muted (user_id, username, first_name, muted_by, reason) 
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET 
                            muted_by=excluded.muted_by,
                            muted_at=CURRENT_TIMESTAMP,
                            reason=excluded.reason
                    """, (target_id, target_user.username, target_user.first_name, OWNER_ID, reason))
                    conn.commit()
                await message.answer(f"🔇 Пользователь {target_user.first_name or 'без имени'} замучен")
            
            elif cmd == ".unmute":
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM muted WHERE user_id = ?", (target_id,))
                    conn.commit()
                await message.answer(f"🔊 Пользователь {target_user.first_name or 'без имени'} размучен")
            
            elif cmd == ".check":
                # Поиск информации о пользователе
                info = await search_user_info(target_id, target_user.username)
                
                response = f"🔍 <b>Проверка пользователя:</b>\n"
                response += f"ID: <code>{target_id}</code>\n"
                response += f"Имя: {target_user.first_name or 'Нет'}\n"
                response += f"Username: @{target_user.username or 'Нет'}\n\n"
                
                response += f"📊 <b>Статус в системе:</b>\n"
                response += f"• В бизнес-чатах: {'✅ Да' if info['in_business'] else '❌ Нет'}\n"
                response += f"• Проверен: {'✅ Да' if info['in_safety'] else '❌ Нет'}\n"
                response += f"• Замучен: {'⚠️ Да' if info['in_muted'] else '✅ Нет'}\n"
                response += f"• Предупреждений: {info['warning_count']}\n"
                
                if info['first_seen']:
                    response += f"\n📅 Первая активность: {info['first_seen']}\n"
                
                # Определяем уровень риска
                risk_level = "Низкий ✅"
                if info['in_muted']:
                    risk_level = "Высокий 🔴"
                elif info['warning_count'] > 2:
                    risk_level = "Средний 🟡"
                
                response += f"\n🎯 <b>Уровень риска:</b> {risk_level}"
                
                # Сохраняем в safety если не замучен
                if not info['in_muted']:
                    with sqlite3.connect(DB_PATH) as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO safety (user_id, username, first_name, checked_by, notes) 
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(user_id) DO UPDATE SET 
                                checked_by=excluded.checked_by,
                                checked_at=CURRENT_TIMESTAMP
                        """, (target_id, target_user.username, target_user.first_name, OWNER_ID, f"Проверка {datetime.now().strftime('%d.%m.%Y')}"))
                        conn.commit()
                    response += "\n\n✅ Пользователь добавлен в список проверенных"
                
                await message.answer(response)
            
            elif cmd == ".warn":
                reason = cmd_parts[1] if len(cmd_parts) > 1 else "Нарушение правил"
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO user_warnings (user_id, warned_by, reason) 
                        VALUES (?, ?, ?)
                    """, (target_id, OWNER_ID, reason))
                    conn.commit()
                await message.answer(f"⚠️ Предупреждение вынесено пользователю {target_user.first_name or 'без имени'}\nПричина: {reason}")
        
        # Команды управления автоответами
        elif cmd == ".addauto":
            if len(cmd_parts) < 2:
                await message.answer("❌ Использование: <code>.addauto ключ | ответ</code>")
                return
            
            parts = cmd_parts[1].split("|", 1)
            if len(parts) != 2:
                await message.answer("❌ Использование: <code>.addauto ключ | ответ</code>")
                return
            
            key = parts[0].strip().lower()
            response = parts[1].strip()
            
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO autoreplies (key, response, created_by) 
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET 
                        response=excluded.response,
                        created_by=excluded.created_by,
                        created_at=CURRENT_TIMESTAMP
                """, (key, response, OWNER_ID))
                conn.commit()
            
            await message.answer(f"✅ Автоответ на «{key}» добавлен")
        
        elif cmd == ".delauto":
            if len(cmd_parts) < 2:
                await message.answer("❌ Использование: <code>.delauto ключ</code>")
                return
            
            key = cmd_parts[1].strip().lower()
            
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM autoreplies WHERE key = ?", (key,))
                deleted = cursor.rowcount
                conn.commit()
            
            if deleted:
                await message.answer(f"✅ Автоответ «{key}» удален")
            else:
                await message.answer(f"❌ Автоответ «{key}» не найден")
        
        elif cmd == ".listauto":
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, response, created_at FROM autoreplies ORDER BY key")
                rows = cursor.fetchall()
            
            if not rows:
                await message.answer("📝 Список автоответов пуст")
            else:
                response_text = "📝 <b>Автоответы:</b>\n\n"
                for row in rows[:20]:  # Ограничиваем вывод
                    response_text += f"<code>{row[0]}</code> → {row[1][:50]}...\n"
                if len(rows) > 20:
                    response_text += f"\n... и еще {len(rows) - 20}"
                await message.answer(response_text)
        
        elif cmd == ".info":
            target_id = None
            if len(cmd_parts) > 1:
                try:
                    target_id = int(cmd_parts[1])
                except:
                    if message.reply_to_message:
                        target_id = message.reply_to_message.from_user.id
            elif message.reply_to_message:
                target_id = message.reply_to_message.from_user.id
            
            if not target_id:
                await message.answer("❌ Укажите ID пользователя или ответьте на его сообщение")
                return
            
            info = await search_user_info(target_id)
            
            response = f"📊 <b>Информация о пользователе {target_id}</b>\n\n"
            response += f"• В бизнес-чатах: {'✅' if info['in_business'] else '❌'}\n"
            response += f"• Проверен: {'✅' if info['in_safety'] else '❌'}\n"
            response += f"• Замучен: {'⚠️' if info['in_muted'] else '✅'}\n"
            response += f"• Предупреждений: {info['warning_count']}\n"
            
            if info['first_seen']:
                response += f"\nПервая активность: {info['first_seen']}"
            if info.get('safety_date'):
                response += f"\nПроверен: {info['safety_date']}"
            if info.get('muted_date'):
                response += f"\nЗамучен: {info['muted_date']}"
                if info.get('muted_reason'):
                    response += f"\nПричина мута: {info['muted_reason']}"
            
            await message.answer(response)
        
        elif cmd == ".help":
            help_text = (
                "👑 <b>Команды владельца BotHelper</b>\n\n"
                "<b>Модерация (ответом на сообщение):</b>\n"
                "• <code>.mute [причина]</code> — замутить\n"
                "• <code>.unmute</code> — размутить\n"
                "• <code>.check</code> — проверить безопасность\n"
                "• <code>.warn [причина]</code> — предупреждение\n\n"
                "<b>Автоответы:</b>\n"
                "• <code>.addauto ключ | ответ</code>\n"
                "• <code>.delauto ключ</code>\n"
                "• <code>.listauto</code>\n\n"
                "<b>Информация:</b>\n"
                "• <code>.info [user_id]</code>\n"
                "• <code>.stats</code> — быстрая статистика"
            )
            await message.answer(help_text)
        
        elif cmd == ".stats":
            stats = get_stats()
            response = (
                f"📊 Быстрая статистика:\n"
                f"👥 Пользователей: {stats['users']}\n"
                f"💼 Business: {stats['business']}\n"
                f"🔇 Замучено: {stats['muted']}\n"
                f"✅ Проверено: {stats['safety']}\n"
                f"💬 Автоответов: {stats['autoreplies']}"
            )
            await message.answer(response)
        
        return
    
    # Автоответчик для обычных пользователей
    if user.id != OWNER_ID and not text.startswith(".") and text:
        first_word = text.split()[0].lower()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT response FROM autoreplies WHERE key = ?", (first_word,))
            row = cursor.fetchone()
            if row:
                await message.reply(row[0])

@dp.edited_message()
async def handle_edited_message(message: types.Message):
    if message.business_connection_id is None:
        return
    
    if not message.text:
        return
    
    old_text = message_cache.get(message.message_id)
    new_text = message.text
    
    if old_text and old_text != new_text:
        add_to_cache(message.message_id, new_text)
        
        # Уведомление владельца об изменении
        notification = (
            f"✏️ <b>Сообщение изменено</b>\n"
            f"👤 {message.from_user.first_name} (@{message.from_user.username or 'нет'})\n\n"
            f"<b>Было:</b>\n<code>{old_text[:300]}</code>\n\n"
            f"<b>Стало:</b>\n<code>{new_text[:300]}</code>"
        )
        
        # Отправляем уведомление в тот же чат
        await message.reply(notification)

@dp.errors()
async def error_handler(update: types.Update, exception: Exception):
    if "message is not modified" in str(exception):
        return True
    logging.error(f"Update {update.update_id} caused error: {exception}")
    return True

# === ЗАПУСК ===
async def on_startup():
    try:
        await bot.send_message(
            OWNER_ID, 
            f"🚀 <b>BotHelper запущен!</b>\n\n"
            f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"💾 База данных: {DB_PATH}\n"
            f"📦 Размер кэша: {MAX_CACHE_SIZE}"
        )
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение о запуске: {e}")

async def main():
    await on_startup()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
