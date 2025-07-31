import sqlite3
import telebot
from telebot import types
import barcode
from barcode.writer import ImageWriter
import os
import threading
import time
import logging
from logging.handlers import RotatingFileHandler
from threading import Lock



TOKEN = "8120214959:AAGnIs0aYSk3pQQVAsTTzmRtS_yYhyugyI4"
ADMIN_BOT_ID = "@AdminSupSmorodRestBot"
bot = telebot.TeleBot(TOKEN)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler("user_bot.log", maxBytes=5*1024*1024, backupCount=3),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def user_log(user_id, message, level="info"):
    log_message = f"[User {user_id}] {message}"
    if level.lower() == "info":
        logger.info(log_message)
    elif level.lower() == "warning":
        logger.warning(log_message)
    elif level.lower() == "error":
        logger.error(log_message, exc_info=True if level.lower() == "error" else False)


# Создаем или подключаемся к базе данных
conn = sqlite3.connect('restaurant_bot.db', check_same_thread=False)
cursor = conn.cursor()

# Создаем таблицу users, если её нет
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    last_name TEXT,
    username TEXT,
    phone TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS bonus_cards (
    user_id INTEGER PRIMARY KEY,
    barcode TEXT UNIQUE,
    balance INTEGER DEFAULT 0
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS bonus_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    operation TEXT,  -- "начисление" или "списание"
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
)
''')

# Инициализация БД

cursor.execute("""
CREATE TABLE IF NOT EXISTS support_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_name TEXT,
    message TEXT NOT NULL,
    admin_id INTEGER,
    admin_reply TEXT,
    status TEXT DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

cursor.execute('''
CREATE TABLE IF NOT EXISTS used_barcodes (
    barcode TEXT PRIMARY KEY
)
''')

conn.commit()


def generate_next_barcode():
    conn = sqlite3.connect('restaurant_bot.db')
    cursor = conn.cursor()
    
    # Находим минимальный свободный код (от 000001 до 999999)
    for code in range(1, 1_000_000):
        barcode = f"{code:06d}"  # Форматируем в 6 цифр (000001, 000002, ...)
        
        # Проверяем, не занят ли код
        cursor.execute(
            "SELECT 1 FROM used_barcodes WHERE barcode = ?",
            (barcode,)
        )
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO used_barcodes (barcode) VALUES (?)",
                (barcode,)
            )
            conn.commit()
            conn.close()
            return barcode
    
    conn.close()
    raise ValueError("Все коды заняты!")  # На практике маловероятно




@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    
    try:
        user_log(user_id, "Initiated /start command")
        # Проверяем, есть ли пользователь в базе
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user_data = cursor.fetchone()
    
        if user_data:
            # Если пользователь уже есть в базе → главное меню
            show_main_menu(message)
        else:
            # Если пользователя нет → запрашиваем контакты
            bot.send_message(
                message.chat.id,
                "👋 Добро пожаловать! Для регистрации нам нужны ваши данные."
            )
            ask_for_phone(message)  # Запрашиваем номер телефона
    
    except Exception as e:
        user_log(user_id, f"Error in /start: {str(e)}", "error")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.")

def ask_for_phone(message):

    try:
        user_id = message.from_user.id
        user_log(user_id, "Requesting phone number")
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn_phone = types.KeyboardButton("📱 Отправить номер", request_contact=True)
        markup.add(btn_phone)
        
        bot.send_message(
            message.chat.id,
            "Пожалуйста, поделитесь своим номером телефона:",
            reply_markup=markup
        )
        
        bot.register_next_step_handler(message, process_phone)
        
    except Exception as e:
        user_log(user_id, f"Error in ask_for_phone: {str(e)}", "error")
        bot.send_message(message.chat.id, "⚠️ Ошибка при запросе номера. Пожалуйста, попробуйте позже.")

def process_phone(message):
    user_id = message.from_user.id
    try:
        if message.contact:
            phone = message.contact.phone_number
            user_log(user_id, f"Received phone number: {phone}")
            
            cursor.execute(
                'INSERT INTO users (user_id, phone) VALUES (?, ?)',
                (user_id, phone)
            )
            conn.commit()
            user_log(user_id, "Phone number saved to database")
            
            ask_for_first_name(message)
        else:
            user_log(user_id, "User didn't share phone via button", "warning")
            bot.send_message(message.chat.id, "Пожалуйста, отправьте номер через кнопку.")
            ask_for_phone(message)
            
    except Exception as e:
        user_log(user_id, f"Error processing phone: {str(e)}", "error")
        bot.send_message(message.chat.id, "⚠️ Ошибка при обработке номера. Пожалуйста, начните снова.")

def ask_for_first_name(message):
    try:
        user_id = message.from_user.id
        user_log(user_id, "Requesting first name")
        
        bot.send_message(
            message.chat.id,
            "📝 Теперь введите ваше **имя**:",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(message, process_first_name)
        
    except Exception as e:
        user_log(user_id, f"Error in ask_for_first_name: {str(e)}", "error")
        bot.send_message(message.chat.id, "⚠️ Ошибка при запросе имени. Пожалуйста, попробуйте позже.")

def process_first_name(message):
    user_id = message.from_user.id
    try:
        first_name = message.text.strip()
        if not first_name or len(first_name) < 2:
            user_log(user_id, "Invalid first name provided", "warning")
            bot.send_message(message.chat.id, "❌ Имя слишком короткое. Пожалуйста, введите ваше настоящее имя.")
            return ask_for_first_name(message)
        
        user_log(user_id, f"Received first name: {first_name}")
        
        cursor.execute(
            'UPDATE users SET first_name = ? WHERE user_id = ?',
            (first_name, user_id)
        )
        conn.commit()
        user_log(user_id, "First name saved to database")
        
        ask_for_last_name(message)
        
    except Exception as e:
        user_log(user_id, f"Error processing first name: {str(e)}", "error")
        bot.send_message(message.chat.id, "⚠️ Ошибка при сохранении имени. Пожалуйста, попробуйте позже.")

def ask_for_last_name(message):
    try:
        user_id = message.from_user.id
        user_log(user_id, "Requesting last name")
        
        bot.send_message(
            message.chat.id,
            "📝 Теперь введите вашу **фамилию**:",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(message, process_last_name)
        
    except Exception as e:
        user_log(user_id, f"Error in ask_for_last_name: {str(e)}", "error")
        bot.send_message(message.chat.id, "⚠️ Ошибка при запросе фамилии. Пожалуйста, попробуйте позже.")

def process_last_name(message):
    user_id = message.from_user.id
    try:
        last_name = message.text.strip()
        if not last_name or len(last_name) < 2:
            user_log(user_id, "Invalid last name provided", "warning")
            bot.send_message(message.chat.id, "❌ Фамилия слишком короткая. Пожалуйста, введите вашу настоящую фамилию.")
            return ask_for_last_name(message)
        
        user_log(user_id, f"Received last name: {last_name}")
        
        cursor.execute(
            'UPDATE users SET last_name = ? WHERE user_id = ?',
            (last_name, user_id)
        )
        conn.commit()
        user_log(user_id, "Last name saved to database")
        
        bot.send_message(
            message.chat.id,
            f"✅ Регистрация завершена, {message.from_user.first_name}!",
        )
        user_log(user_id, "Registration completed successfully")
        show_main_menu(message)
        
    except Exception as e:
        user_log(user_id, f"Error processing last name: {str(e)}", "error")
        bot.send_message(message.chat.id, "⚠️ Ошибка при сохранении фамилии. Пожалуйста, попробуйте позже.")





@bot.message_handler(func=lambda msg: msg.text == "Бонусная карта")
def bonus_card(message):
    user_id = message.from_user.id
    conn = sqlite3.connect('restaurant_bot.db')
    cursor = conn.cursor()
    
    try:
        # Проверяем, есть ли у пользователя бонусная карта
        cursor.execute("SELECT barcode FROM bonus_cards WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        
        if not result:
            # Генерируем новый код
            barcode = generate_next_barcode()
            
            # Сохраняем в бонусные карты
            cursor.execute(
                "INSERT INTO bonus_cards (user_id, barcode) VALUES (?, ?)",
                (user_id, barcode)
            )
            conn.commit()
            
            # Отправляем сообщение с новым кодом
            bot.send_message(
                message.chat.id,
                f"🎉 Вам создана бонусная карта!\n\n"
                f"🔢 Ваш код: <b>{barcode}</b>\n"
                f"Покажите этот код официанту для получения бонусов.",
                parse_mode="HTML"
            )
        else:
            barcode = result[0]
            # Отправляем сообщение с существующим кодом
            bot.send_message(
                message.chat.id,
                f"🔖 Ваша бонусная карта:\n\n"
                f"🔢 Код: <b>{barcode}</b>\n"
                f"Покажите этот код официанту для получения бонусов.",
                parse_mode="HTML"
            )
            
    except sqlite3.Error as e:
        bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка при обработке вашего запроса. Попробуйте позже."
        )
        print(f"Database error: {e}")
        
    finally:
        conn.close()
    



@bot.message_handler(func=lambda msg: msg.text == "Обратиться в поддержку")
def ask_support_request(message):
    try:
        user_id = message.chat.id
        logger.info(f"User {user_id} initiated support request")
        msg = bot.send_message(message.chat.id, "Опишите проблему:")
        bot.register_next_step_handler(msg, save_support_request)
    except Exception as e:
        logger.error(f"Error in ask_support_request: {str(e)}", exc_info=True)
        bot.send_message(message.chat.id, "⚠️ Ошибка при создании обращения")

def save_support_request(message):
    user_id = message.chat.id
    user_name = message.from_user.first_name
    request_text = message.text
    
    try:
        logger.info(f"Processing support request from {user_id} ({user_name})")
        
        conn = sqlite3.connect('restaurant_bot.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO support_tickets (user_id, user_name, message, status) VALUES (?, ?, ?, 'open')",
            (user_id, user_name, request_text)
        )
        conn.commit()
        conn.close()
        
        logger.info(f"Support request saved for user {user_id}")
        bot.send_message(user_id, "✅ Ваше обращение отправлено!")
        
    except Exception as e:
        logger.error(f"Error saving support request for {user_id}: {str(e)}", exc_info=True)
        bot.send_message(user_id, "⚠️ Ошибка при сохранении обращения")

def get_admin_reply(user_id):
    try:
        conn = sqlite3.connect("restaurant_bot.db")
        cursor = conn.cursor()
        
        cursor.execute(
            """SELECT admin_reply FROM support_tickets 
            WHERE user_id = ? AND status = 'answered'
            ORDER BY id DESC LIMIT 1""",
            (user_id,)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            logger.debug(f"Found admin reply for user {user_id}")
        else:
            logger.debug(f"No admin replies for user {user_id}")
            
        return result[0] if result else None
        
    except Exception as e:
        logger.error(f"Error getting admin reply for {user_id}: {str(e)}", exc_info=True)
        return None

def send_admin_reply_to_user(user_id):
    try:
        admin_reply = get_admin_reply(user_id)
        if not admin_reply:
            logger.info(f"No replies to send to user {user_id}")
            return
        
        logger.info(f"Sending reply to user {user_id}")
        bot.send_message(
            user_id,
            f"🔔 Вам ответили на обращение!\n\n"
            f"💬 Ответ поддержки:\n{admin_reply}"
        )
        mark_reply_as_delivered(user_id)
        logger.info(f"Reply successfully sent to user {user_id}")
        
    except Exception as e:
        logger.error(f"Error sending reply to {user_id}: {str(e)}", exc_info=True)

def mark_reply_as_delivered(user_id):
    try:
        conn = sqlite3.connect("restaurant_bot.db")
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE support_tickets 
            SET status = 'delivered' 
            WHERE user_id = ? AND status = 'answered'""",
            (user_id,)
        )
        conn.commit()
        conn.close()
        logger.debug(f"Marked replies as delivered for user {user_id}")
    except Exception as e:
        logger.error(f"Error marking reply as delivered for {user_id}: {str(e)}", exc_info=True)

def check_replies_periodically():
    logger.info("Starting periodic reply checking")
    while True:
        try:
            conn = sqlite3.connect("restaurant_bot.db")
            cursor = conn.cursor()
            cursor.execute(
                """SELECT DISTINCT user_id FROM support_tickets 
                WHERE status = 'answered'"""
            )
            users = cursor.fetchall()
            conn.close()
            
            logger.debug(f"Found {len(users)} users with pending replies")
            
            for user in users:
                send_admin_reply_to_user(user[0])
            
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"Error in reply checking loop: {str(e)}", exc_info=True)
            time.sleep(60)


# Запуск в отдельном потоке
try:
    thread = threading.Thread(target=check_replies_periodically)
    thread.daemon = True
    thread.start()
    logger.info("Reply checking thread started successfully")
except Exception as e:
    logger.error(f"Failed to start reply checking thread: {str(e)}", exc_info=True)


def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)

    btn_reserve = types.KeyboardButton("Забронировать столик")
    btn_bonus = types.KeyboardButton("Бонусная карта")
    btn_deliv = types.KeyboardButton("Доставка")
    btn_rules = types.KeyboardButton("Правила программы лояльности")
    btn_coop = types.KeyboardButton("Сотрудничество")
    btn_sup_sys = types.KeyboardButton("Обратиться в поддержку")
    btn_rest_info = types.KeyboardButton("Больше про заведение")

    markup.add(btn_bonus)
    markup.row(btn_deliv, btn_reserve)
    markup.add(btn_rules)
    markup.row(btn_coop,btn_sup_sys)
    markup.add(btn_rest_info)

    bot.send_message(
        message.chat.id,
        "Главное меню:",
        reply_markup=markup
    )


@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    user_id = message.from_user.id
    user_log(user_id, f"Unknown command received: '{message.text}'", "warning")
    
    bot.reply_to(
        message,
        f"Извините, я пока не умею обрабатывать запрос \"{message.text}\"\n\n"
        "Попробуйте выбрать один из вариантов меню:",
        reply_markup=show_main_menu(message)  # Ваша функция создания клавиатуры
    )



bot.infinity_polling()