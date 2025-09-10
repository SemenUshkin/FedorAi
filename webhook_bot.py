import os
import logging
import asyncio
from datetime import datetime
import openai
import requests
from flask import Flask, request, jsonify
from telegram import Bot, Update
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask приложение
app = Flask(__name__)

# Конфигурация
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GOOGLE_SCRIPT_URL = os.getenv('GOOGLE_SCRIPT_URL')
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL', 'https://fedorai.onrender.com')

# Инициализация
openai.api_key = OPENAI_API_KEY
bot = Bot(token=TELEGRAM_TOKEN)

async def process_with_chatgpt(text):
    """Обработка через ChatGPT"""
    try:
        logger.info("Отправка запроса в OpenAI...")
        
        response = await asyncio.to_thread(
            openai.ChatCompletion.create,
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": """Ты эксперт по обработке идей и мыслей.

Твоя задача:
1. Структурировать мысль пользователя
2. Добавить практические шаги
3. Определить приоритет
4. Предложить следующие действия

Отвечай на русском языке. Формат:
🎯 Суть идеи: [описание]
📋 План действий: [шаги]
⚡ Приоритет: [высокий/средний/низкий]
📊 Метрики: [как измерить успех]"""
                },
                {"role": "user", "content": text}
            ],
            max_tokens=600,
            temperature=0.7
        )
        
        result = response.choices[0].message.content.strip()
        logger.info("Ответ от OpenAI получен")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка OpenAI: {e}")
        return f"Ошибка обработки через ChatGPT: {e}\n\nИсходный текст: {text}"

async def save_to_google_sheet(username, user_id, original_text, processed_text):
    """Сохранение в Google таблицу"""
    try:
        if not GOOGLE_SCRIPT_URL:
            logger.info("Google Script URL не настроен")
            return
            
        data = {
            'action': 'saveMessage',
            'timestamp': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
            'username': username,
            'user_id': user_id,
            'original_text': original_text,
            'processed_text': processed_text
        }
        
        response = await asyncio.to_thread(
            requests.post,
            GOOGLE_SCRIPT_URL,
            json=data,
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info("Данные сохранены в Google таблицу")
        else:
            logger.error(f"Ошибка сохранения: {response.text}")
            
    except Exception as e:
        logger.error(f"Ошибка Google Sheets: {e}")

async def handle_message(update_data):
    """Обработка сообщения"""
    try:
        update = Update.de_json(update_data, bot)
        
        if not update.message:
            return
            
        message = update.message
        text = message.text
        user = message.from_user
        
        logger.info(f"Получено сообщение от {user.username}: {text}")
        
        # Команды
        if text == '/start':
            response_text = """
🤖 Добро пожаловать в бота для обработки идей!

Я могу:
• 💬 Принимать текстовые сообщения  
• 🧠 Обрабатывать их через ChatGPT
• 📊 Сохранять результаты

Просто отправьте мне текстовое сообщение!
            """
            await bot.send_message(chat_id=message.chat_id, text=response_text)
            return
            
        elif text == '/help':
            response_text = """
📋 Как использовать бота:

1. Отправьте любую идею или задачу
2. Бот обработает её через ChatGPT  
3. Получите структурированный ответ

Команды:
• /start - начать работу
• /help - эта справка
            """
            await bot.send_message(chat_id=message.chat_id, text=response_text)
            return
        
        # Обработка обычного сообщения
        if text and not text.startswith('/'):
            # Уведомление о начале обработки
            processing_msg = await bot.send_message(
                chat_id=message.chat_id, 
                text="💭 Обрабатываю через ChatGPT..."
            )
            
            # Обработка через ChatGPT
            processed_text = await process_with_chatgpt(text)
            
            # Сохранение в Google таблицу
            if GOOGLE_SCRIPT_URL:
                await save_to_google_sheet(
                    username=user.username or user.first_name,
                    user_id=user.id,
                    original_text=text,
                    processed_text=processed_text
                )
            
            # Отправка результата
            result_text = f"""
✅ **Сообщение обработано!**

💭 **Обработанная мысль:**
{processed_text}
            """
            
            await bot.edit_message_text(
                chat_id=message.chat_id,
                message_id=processing_msg.message_id,
                text=result_text
            )
            
            logger.info(f"Сообщение обработано для {user.username}")
            
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")

@app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    """Webhook endpoint"""
    try:
        json_data = request.get_json()
        
        if json_data:
            # Создаем event loop для async функций
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(handle_message(json_data))
            loop.close()
            
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f"Ошибка webhook: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'bot': 'running',
        'webhook': 'active'
    }), 200

@app.route('/', methods=['GET'])
def index():
    """Главная страница"""
    return jsonify({
        'message': 'Telegram Bot is running',
        'status': 'active'
    }), 200

async def setup_webhook():
    """Установка webhook"""
    try:
        webhook_url = f"{WEBHOOK_URL}/webhook/{TELEGRAM_TOKEN}"
        logger.info(f"Устанавливаем webhook: {webhook_url}")
        
        result = await bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message"]
        )
        
        if result:
            logger.info("✅ Webhook успешно установлен")
        else:
            logger.error("❌ Не удалось установить webhook")
            
    except Exception as e:
        logger.error(f"Ошибка установки webhook: {e}")

def run_webhook_setup():
    """Запуск установки webhook"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup_webhook())
    loop.close()

if __name__ == '__main__':
    logger.info("Инициализация webhook бота...")
    
    # Установка webhook
    run_webhook_setup()
    
    # Запуск Flask сервера
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Запуск Flask сервера на порту {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
