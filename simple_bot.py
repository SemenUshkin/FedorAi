import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimpleBot:
    def __init__(self):
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        print(f"Token length: {len(self.telegram_token) if self.telegram_token else 'None'}")
        print(f"Token starts with: {self.telegram_token[:10] if self.telegram_token else 'None'}")
        
        self.app = Application.builder().token(self.telegram_token).build()
        self.setup_handlers()

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(MessageHandler(filters.TEXT, self.handle_text))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Бот работает! Отправьте любое сообщение.")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(f"Получил сообщение: {update.message.text}")

    def run(self):
        logger.info("Запуск простого бота...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = SimpleBot()
    bot.run()
