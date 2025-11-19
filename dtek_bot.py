from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import users_config
import asyncio
import os
import sys

# Путь к директории скрипта
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавляет chat_id пользователя в список, если его там ещё нет."""
    user_id = update.effective_message.id # Это ID чата, куда бот будет отправлять
    chat_id = update.effective_chat.id

    if chat_id in users_config.AUTHORIZED_USERS:
        await update.message.reply_text("Вы уже подписаны на оповещения!")
    else:
        users_config.AUTHORIZED_USERS.add(chat_id)
        # Сохраняем список пользователей в файл (упрощённо, можно улучшить)
        # Важно: для сохранения между запусками используйте JSON или базу данных
        with open("users_list.txt", "a") as f:
            f.write(str(chat_id) + "\n")
        await update.message.reply_text("Вы успешно подписались на оповещения отключения света!")

def load_users():
    """Загружает список пользователей из файла."""
    try:
        with open("users_list.txt", "r") as f:
            for line in f:
                user_id = int(line.strip())
                users_config.AUTHORIZED_USERS.add(user_id)
        print(f"INFO: Загружено {len(users_config.AUTHORIZED_USERS)} пользователей из файла.")
    except FileNotFoundError:
        print("INFO: Файл users_list.txt не найден. Список пользователей пуст.")
    except Exception as e:
        print(f"ОШИБКА при загрузке пользователей: {e}")

if __name__ == "__main__":
    # Загружаем список пользователей при запуске
    load_users()

    # Инициализируем бота
    app = ApplicationBuilder().token("8409750391:AAFlAmC1A5MOIzTwXIY7NUqzhiyFrHPWG3Q").build()
    app.add_handler(CommandHandler("start", start))

    print("Бот запущен. Ожидание команд /start...")
    app.run_polling()