import os
import logging
import asyncio
from datetime import datetime
import openai
import requests
from flask import Flask, request, jsonify
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

def send_telegram_message_sync(chat_id, text, reply_to_message_id=None):
    """Синхронная отправка сообщения через Telegram API"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        
        response = requests.post(url, json=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return result.get('result', {}).get('message_id')
        else:
            logger.error(f"Ошибка отправки сообщения: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка Telegram API: {e}")
        return None

def edit_telegram_message_sync(chat_id, message_id, text):
    """Синхронное редактирование сообщения через Telegram API"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=data, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"Ошибка редактирования сообщения: {response.text}")
            
    except Exception as e:
        logger.error(f"Ошибка редактирования: {e}")

def process_with_chatgpt_sync(text):
    """Синхронная обработка через ChatGPT"""
    try:
        logger.info("Отправка запроса в OpenAI...")
        
        response = openai.ChatCompletion.create(
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

def save_to_google_sheet_sync(username, user_id, original_text, processed_text):
    """Синхронное сохранение в Google таблицу"""
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
        
        response = requests.post(GOOGLE_SCRIPT_URL, json=data, timeout=10)
        
        if response.status_code == 200:
            logger.info("Данные сохранены в Google таблицу")
        else:
            logger.error(f"Ошибка сохранения: {response.text}")
            
    except Exception as e:
        logger.error(f"Ошибка Google Sheets: {e}")

def handle_message(update_data):
    """Обработка сообщения"""
    try:
        # Простой парсинг JSON без telegram библиотеки
        if not update_data.get('message'):
            return
            
        message = update_data['message']
        text = message.get('text')
        user = message.get('from', {})
        chat_id = message.get('chat', {}).get('id')
        
        if not text or not chat_id:
            return
            
        username = user.get('username') or user.get('first_name', 'Unknown')
        user_id = user.get('id')
        
        logger.info(f"Получено сообщение от {username}: {text}")
        
        # Команды
        if text == '/start':
            response_text = """🤖 *Добро пожаловать в бота для обработки идей!*

Я могу:
• 💬 Принимать текстовые сообщения  
• 🧠 Обрабатывать их через ChatGPT
• 📊 Сохранять результаты

Просто отправьте мне текстовое сообщение!"""
            
            send_telegram_message_sync(chat_id, response_text)
            return
            
        elif text == '/help':
            response_text = """📋 *Как использовать бота:*

1. Отправьте любую идею или задачу
2. Бот обработает её через ChatGPT  
3. Получите структурированный ответ

*Команды:*
• /start - начать работу
• /help - эта справка"""
            
            send_telegram_message_sync(chat_id, response_text)
            return
        
        # Обработка обычного сообщения
        if text and not text.startswith('/'):
            # Уведомление о начале обработки
            processing_msg_id = send_telegram_message_sync(
                chat_id, 
                "💭 Обрабатываю через ChatGPT..."
            )
            
            if not processing_msg_id:
                logger.error("Не удалось отправить сообщение о начале обработки")
                return
            
            # Обработка через ChatGPT
            processed_text = process_with_chatgpt_sync(text)
            
            # Сохранение в Google таблицу
            if GOOGLE_SCRIPT_URL:
                save_to_google_sheet_sync(
                    username=username,
                    user_id=user_id,
                    original_text=text,
                    processed_text=processed_text
                )
            
            # Отправка результата
            result_text = f"""✅ *Сообщение обработано!*

💭 *Обработанная мысль:*
{processed_text}"""
            
            edit_telegram_message_sync(chat_id, processing_msg_id, result_text)
            
            logger.info(f"Сообщение обработано для {username}")
            
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")

@app.route(f'/webhook/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    """Webhook endpoint"""
    try:
        json_data = request.get_json()
        
        if json_data:
            # Обрабатываем синхронно без event loop
            handle_message(json_data)
            
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

def setup_webhook():
    """Установка webhook"""
    try:
        webhook_url = f"{WEBHOOK_URL}/webhook/{TELEGRAM_TOKEN}"
        logger.info(f"Устанавливаем webhook: {webhook_url}")
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
        data = {
            "url": webhook_url,
            "allowed_updates": ["message"]
        }
        
        response = requests.post(url, json=data, timeout=30)
        
        if response.status_code == 200:
            logger.info("✅ Webhook успешно установлен")
        else:
            logger.error(f"❌ Не удалось установить webhook: {response.text}")
            
    except Exception as e:
        logger.error(f"Ошибка установки webhook: {e}")

if __name__ == '__main__':
    logger.info("Инициализация webhook бота...")
    
    # Установка webhook
    setup_webhook()
    
    # Запуск Flask сервера
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Запуск Flask сервера на порту {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
