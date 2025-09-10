import os
import logging
import asyncio
from datetime import datetime
import openai
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests
from flask import Flask, request
import threading
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebhookTelegramBot:
    def __init__(self):
        # Конфигурация
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.google_script_url = os.getenv('GOOGLE_SCRIPT_URL')
        self.bitrix_webhook = os.getenv('BITRIX_WEBHOOK_URL')
        
        # URL вашего Render сервиса (будет автоматически определен)
        self.webhook_url = os.getenv('RENDER_EXTERNAL_URL', 'https://your-service.onrender.com')
        
        # Инициализация OpenAI
        openai.api_key = self.openai_api_key
        
        # Инициализация бота
        self.bot = Bot(token=self.telegram_token)
        self.app = Application.builder().bot(self.bot).build()
        
        # Flask приложение для webhook
        self.flask_app = Flask(__name__)
        
        self.setup_handlers()
        self.setup_webhook_route()

    def setup_handlers(self):
        """Настройка обработчиков команд и сообщений"""
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

    def setup_webhook_route(self):
        """Настройка маршрута для webhook"""
        @self.flask_app.route(f'/webhook/{self.telegram_token}', methods=['POST'])
        async def webhook():
            try:
                json_data = request.get_json()
                update = Update.de_json(json_data, self.bot)
                
                # Обработка update через Application
                await self.app.process_update(update)
                
                return 'OK', 200
            except Exception as e:
                logger.error(f"Ошибка обработки webhook: {e}")
                return 'Error', 500

        @self.flask_app.route('/health', methods=['GET'])
        def health_check():
            return {'status': 'healthy', 'bot': 'running'}, 200

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /start"""
        welcome_text = """
🤖 Добро пожаловать в бота для обработки идей!

Я могу:
• 💬 Принимать текстовые сообщения  
• 🧠 Обрабатывать их через ChatGPT
• 📊 Сохранять в Google таблицу

Просто отправьте мне текстовое сообщение!
        """
        await update.message.reply_text(welcome_text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /help"""
        help_text = """
📋 Как использовать бота:

1. 💬 **Текстовые сообщения:**
   • Пишите любые идеи или задачи
   • Бот структурирует вашу мысль через ChatGPT

2. 📊 **Команды:**
   • /start - начать работу
   • /help - эта справка

💡 **Совет:** Чем подробнее опишете свою идею, тем лучше будет результат!
        """
        await update.message.reply_text(help_text)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        try:
            text = update.message.text
            
            # Отправляем сообщение о начале обработки
            processing_msg = await update.message.reply_text("💭 Обрабатываю ваше сообщение через ChatGPT...")
            
            # Обрабатываем через ChatGPT
            processed_text = await self.process_with_chatgpt(text)
            
            # Сохраняем в Google таблицу (если настроено)
            if self.google_script_url:
                await self.save_to_google_sheet(
                    username=update.effective_user.username or update.effective_user.first_name,
                    user_id=update.effective_user.id,
                    original_text=text,
                    processed_text=processed_text
                )
            
            # Отправляем результат
            result_text = f"""
✅ **Сообщение обработано!**

💭 **Обработанная мысль:**
{processed_text}
            """
            
            await processing_msg.edit_text(result_text)
            
        except Exception as e:
            logger.error(f"Ошибка обработки текста: {e}")
            await update.message.reply_text("❌ Произошла ошибка при обработке сообщения.")

    async def process_with_chatgpt(self, text):
        """Обработка текста через ChatGPT API"""
        try:
            response = await asyncio.to_thread(
                openai.ChatCompletion.create,
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system", 
                        "content": """Ты эксперт-помощник по обработке рабочих идей и мыслей.
                        
Твоя задача:
1. Структурировать и улучшить мысль пользователя
2. Сделать её более понятной и конкретной
3. Добавить практические шаги для реализации
4. Определить приоритет (высокий/средний/низкий)
5. Предложить следующие действия

Отвечай на русском языке структурированно. Будь конкретным и практичным.
Формат ответа:
🎯 Суть идеи: [краткое описание]
📋 План действий: [конкретные шаги]
⚡ Приоритет: [высокий/средний/низкий]
📊 Метрики успеха: [как измерить результат]"""
                    },
                    {"role": "user", "content": text}
                ],
                max_tokens=600,
                temperature=0.7
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Ошибка ChatGPT API: {e}")
            return f"Не удалось обработать через ChatGPT. Исходный текст: {text}"

    async def save_to_google_sheet(self, username, user_id, original_text, processed_text):
        """Сохранение данных в Google таблицу через Apps Script"""
        try:
            if not self.google_script_url:
                return
                
            data = {
                'action': 'saveMessage',
                'timestamp': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
                'username': username,
                'user_id': user_id,
                'message_type': 'text',
                'category': 'общее',
                'priority': 'средний',
                'original_text': original_text,
                'processed_text': processed_text,
                'responsible': 'Не назначен'
            }
            
            # Отправляем в Google Apps Script
            response = await asyncio.to_thread(
                requests.post,
                self.google_script_url,
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Данные успешно сохранены в Google таблицу")
            else:
                logger.error(f"Ошибка сохранения в Google: {response.text}")
                
        except Exception as e:
            logger.error(f"Ошибка сохранения в Google таблицу: {e}")

    async def set_webhook(self):
        """Установка webhook"""
        try:
            webhook_url = f"{self.webhook_url}/webhook/{self.telegram_token}"
            
            success = await self.bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message", "callback_query"]
            )
            
            if success:
                logger.info(f"✅ Webhook установлен: {webhook_url}")
            else:
                logger.error("❌ Не удалось установить webhook")
                
        except Exception as e:
            logger.error(f"Ошибка установки webhook: {e}")

    def run_flask(self):
        """Запуск Flask приложения"""
        port = int(os.environ.get("PORT", 5000))
        self.flask_app.run(host="0.0.0.0", port=port, debug=False)

    async def startup(self):
        """Инициализация бота"""
        try:
            # Инициализация Application
            await self.app.initialize()
            
            # Установка webhook
            await self.set_webhook()
            
            logger.info("🚀 Webhook бот успешно запущен!")
            
        except Exception as e:
            logger.error(f"Ошибка запуска: {e}")

def main():
    bot = WebhookTelegramBot()
    
    # Запуск инициализации в отдельном потоке
    def run_startup():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot.startup())
    
    startup_thread = threading.Thread(target=run_startup)
    startup_thread.start()
    startup_thread.join()
    
    # Запуск Flask сервера
    logger.info("Запуск Flask сервера...")
    bot.run_flask()

if __name__ == "__main__":
    main()
