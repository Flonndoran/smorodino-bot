import sqlite3
import telebot
from telebot import types
import barcode
from barcode.writer import ImageWriter
import os
import threading
import logging
from logging.handlers import RotatingFileHandler



TOKEN = "7954598876:AAEGe5oDWJrLUXJp2x4zaBmj5LPbmZ3pZ5A"
bot = telebot.TeleBot(TOKEN)
ADMIN_IDS = [1097966097]


conn = sqlite3.connect('restaurant_bot.db', check_same_thread=False)
cursor = conn.cursor()


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler("admin_bot.log", maxBytes=5*1024*1024, backupCount=3),
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

@bot.message_handler(commands=['start'])
def admin_start(message):
    try:
        user_id = message.from_user.id
        logger.info(f"Admin access attempt by user {user_id}")
        
        if user_id not in ADMIN_IDS:
            logger.warning(f"Unauthorized access attempt by {user_id}")
            bot.send_message(message.chat.id, "⛔ У вас нет доступа к этому боту")
            return
    
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        btn_scan = types.KeyboardButton("Управление баллами")
        btn_tickets = types.KeyboardButton("Обращения в поддержку")
        markup.add(btn_scan, btn_tickets)
        
        bot.send_message(
            message.chat.id,
            "Административная панель\n\nВыберите действие:",
            reply_markup=markup
        )
        logger.info(f"Admin panel shown to {user_id}")
        
    except Exception as e:
        logger.error(f"Error in admin_start: {str(e)}", exc_info=True)


# Проверка новых обращений
def check_new_tickets(chat_id):
    try:
        logger.info(f"Checking new tickets for admin {chat_id}")
        
        conn = sqlite3.connect('restaurant_bot.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_name, message FROM support_tickets WHERE status = 'open'")
        tickets = cursor.fetchall()
        conn.close()

        if not tickets:
            logger.debug(f"No new tickets found for admin {chat_id}")
            bot.send_message(chat_id, "🟢 Нет новых обращений.")
        else:
            logger.info(f"Found {len(tickets)} new tickets for admin {chat_id}")
            for ticket in tickets:
                ticket_id, user_name, message_text = ticket
                markup = types.InlineKeyboardMarkup()
                btn_reply = types.InlineKeyboardButton("✉️ Ответить", callback_data=f"reply_{ticket_id}")
                markup.add(btn_reply)

                bot.send_message(
                    chat_id,
                    f"📩 Новое обращение #{ticket_id}\n👤 От: {user_name}\n📝 Текст: {message_text}",
                    reply_markup=markup
                )
                logger.debug(f"Ticket {ticket_id} shown to admin {chat_id}")
                
    except Exception as e:
        logger.error(f"Error checking tickets for admin {chat_id}: {str(e)}", exc_info=True)

# Команда /tickets для проверки обращений
@bot.message_handler(func=lambda msg: msg.text == "Обращения в поддержку")
def handle_tickets_command(message):
    try:
        user_id = message.from_user.id
        logger.info(f"Ticket check requested by {user_id}")
        
        if user_id not in ADMIN_IDS:
            logger.warning(f"Unauthorized ticket access attempt by {user_id}")
            bot.send_message(message.chat.id, "⛔ Доступ запрещен!")
            return
            
        check_new_tickets(message.chat.id)
        
    except Exception as e:
        logger.error(f"Error in handle_tickets_command: {str(e)}", exc_info=True)

# Обработка ответа админа
@bot.callback_query_handler(func=lambda call: call.data.startswith("reply_"))
def reply_to_ticket(call):
    try:
        user_id = call.from_user.id
        ticket_id = call.data.split("_")[1]
        logger.info(f"Admin {user_id} started reply to ticket {ticket_id}")
        
        if user_id not in ADMIN_IDS:
            logger.warning(f"Unauthorized reply attempt by {user_id} to ticket {ticket_id}")
            return

        msg = bot.send_message(call.message.chat.id, "Введите ответ:")
        bot.register_next_step_handler(msg, process_admin_reply, ticket_id)
        logger.debug(f"Awaiting admin reply for ticket {ticket_id}")
        
    except Exception as e:
        logger.error(f"Error in reply_to_ticket: {str(e)}", exc_info=True)

def process_admin_reply(message, ticket_id):
    try:
        admin_id = message.from_user.id
        admin_reply = message.text
        logger.info(f"Processing admin reply for ticket {ticket_id} by {admin_id}")

        conn = sqlite3.connect('restaurant_bot.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE support_tickets SET admin_id = ?, admin_reply = ?, status = 'answered' WHERE id = ?",
            (admin_id, admin_reply, ticket_id)
        )
        conn.commit()
        cursor.execute("SELECT user_id FROM support_tickets WHERE id = ?", (ticket_id,))
        user_id = cursor.fetchone()[0]
        conn.close()

        logger.info(f"Reply to ticket {ticket_id} saved. User: {user_id}, Admin: {admin_id}")
        bot.send_message(message.chat.id, "✅ Ответ сохранен и отправлен пользователю!")
        
    except Exception as e:
        logger.error(f"Error processing admin reply for ticket {ticket_id}: {str(e)}", exc_info=True)
        bot.send_message(message.chat.id, "⚠️ Ошибка при сохранении ответа!")


    

@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    user_id = message.from_user.id
    user_log(user_id, f"Unknown command received: '{message.text}'", "warning")
    
    bot.reply_to(
        message,
        f"Извините, я пока не умею обрабатывать запрос \"{message.text}\"\n\n"
        "Попробуйте выбрать один из вариантов меню:",
        reply_markup=admin_start(message) # Ваша функция создания клавиатуры
    )


    
bot.infinity_polling()