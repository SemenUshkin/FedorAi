import os
import logging
import asyncio
from datetime import datetime
import openai
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests
from flask import Flask, request, jsonify
import threading
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask приложение
app = Flask(__name__)

# Глобальные переменные
telegram_app = None
bot = None

class WebhookBot:
    def __init__(self):
        # Конфигурация
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.google_script_url = os.getenv('GOOGLE_SCRIPT_URL')
        self.webhook_url = os.getenv('RENDER_EXTERNAL_URL', 'https://fedorai.onrender.com')
        
        # Инициализация OpenAI
        openai.api_key = self.openai_api_key
        
        # Инициализация бота
        self.bot = Bot(token=self.telegram_token)
        self.app = Application.builder().bot(self.bot).build()
        
        self.setup_handlers()

    def setup_handlers(self):
        """Настройка обработчиков"""
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        welcome_text = """
🤖 Добро пожаловать в бота для обработки идей!

Я могу:
• 💬 Принимать текстовые сообщения  
• 🧠 Обрабатывать их через ChatGPT
• 📊 Сохранять результаты

Просто отправьте мне текстовое сообщение!
        """
        await update.message.reply_text(welcome_text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /help"""
        help_text = """
📋 Как использовать бота:

1. Отправьте любую идею или задачу
2. Бот обработает её через ChatGPT  
3. Получите структурированный ответ

Команды:
• /start - начать работу
• /help - эта справка
        """
        await update.message.reply_text(help_text)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        try:
            text = update.message.text
            logger.info(f"Получено сообщение от {update.effective_user.username}: {text}")
            
            # Уведомление о начале обработки
            processing_msg = await update.message.reply_text("💭 Обрабатываю через ChatGPT...")
            
            # Обработка через ChatGPT
            processed_text = await self.process_with_chatgpt(text)
            
            # Сохранение в Google таблицу
            if self.google_script_url:
                await self.save_to_google_sheet(
                    username=update.effective_user.username or update.effective_user.first_name,
                    user_id=update.effective_user.id,
                    original_text=text,
                    processed_text=processed_text
                )
            
            # Отправка результата
            result_text = f"""
✅ **Сообщение обработано!**

💭 **Обработанная мысль:**
{processed_text}
            """
            
            await processing_msg.edit_text(result_text)
            logger.info(f"Сообщение обработано для {update.effective_user.username}")
            
        except Exception as e:
            logger.error(f"Ошибка обработки текста: {e}")
            await update.message.reply_text("❌ Произошла ошибка при обработке.")

    async def process_with_chatgpt(self, text):
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

    async def save_to_google_sheet(self, username, user_id, original_text, processed_text):
        """Сохранение в Google таблицу"""
        try:
            if not self.google_script_url:
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
                self.google_script_url,
                json=data,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Данные сохранены в Google таблицу")
            else:
                logger.error(f"Ошибка сохранения: {response.text}")
                
        except Exception as e:
            logger.error(f"Ошибка Google Sheets: {e}")

    async def set_webhook(self):
        """Установка webhook"""
        try:
            webhook_url = f"{self.webhook_url}/webhook/{self.telegram_token}"
            logger.info(f"Устанавливаем webhook: {webhook_url}")
            
            result = await self.bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message"]
            )
            
            if result:
                logger.info("✅ Webhook успешно установлен")
            else:
                logger.error("❌ Не удалось установить webhook")
                
        except Exception as e:
            logger.error(f"Ошибка установки webhook: {e}")

# Создание экземпляра бота
webhook_bot = WebhookBot()

@app.route(f'/webhook/{webhook_bot.telegram_token}', methods=['POST'])
def webhook():
    """Обработка webhook от Telegram"""
    try:
        json_data = request.get_json()
        
        if json_data:
            update = Update.de_json(json_data, webhook_bot.bot)
            
            # Создаем новый event loop для обработки
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Обрабатываем update
            loop.run_until_complete(webhook_bot.app.process_update(update))
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

async def setup_bot():
    """Инициализация бота"""
    try:
        logger.info("Инициализация Telegram бота...")
        
        # Инициализация Application
        await webhook_bot.app.initialize()
        
        # Установка webhook
        await webhook_bot.set_webhook()
        
        logger.info("🚀 Бот успешно инициализирован!")
        
    except Exception as e:
        logger.error(f"Ошибка инициализации: {e}")

def run_setup():
    """Запуск инициализации в отдельном потоке"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup_bot())
    loop.close()

if __name__ == '__main__':
    # Запуск инициализации
    setup_thread = threading.Thread(target=run_setup)
    setup_thread.start()
    setup_thread.join()
    
    # Запуск Flask сервера
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Запуск Flask сервера на порту {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
