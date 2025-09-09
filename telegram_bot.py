import os
import asyncio
import logging
from datetime import datetime
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests
from io import BytesIO
import speech_recognition as sr
from pydub import AudioSegment
import tempfile
from dotenv import load_dotenv

# ==============================
# Логирование
# ==============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================
# Основной класс бота
# ==============================
class TelegramBotWithAppsScript:
    def __init__(self):
        # Загружаем env
        load_dotenv()

        # Конфигурация
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.bitrix_webhook = os.getenv("BITRIX_WEBHOOK_URL")
        self.google_script_url = os.getenv("GOOGLE_SCRIPT_URL")

        # Инициализация OpenAI
        self.openai_client = OpenAI(api_key=self.openai_api_key)

        # Инициализация Telegram
        self.app = Application.builder().token(self.telegram_token).build()
        self.setup_handlers()

    # ==============================
    # Handlers
    # ==============================
    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "👋 Привет! Я бот для обработки идей.\n"
            "Отправь мне текст или голосовое сообщение — я обработаю его через GPT 🤖"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📋 Я умею:\n"
            "• Обрабатывать текст через ChatGPT\n"
            "• Распознавать голосовые и структурировать мысль\n"
            "• Сохранять данные в Google таблицу\n"
            "• Создавать задачи в Bitrix24\n\n"
            "Команды:\n"
            "• /start — запуск\n"
            "• /help — справка\n"
            "• /stats — твоя статистика"
        )

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            response = requests.get(
                f"{self.google_script_url}?action=getStats&user={update.effective_user.username}"
            )
            if response.status_code == 200:
                stats_data = response.json()
                await update.message.reply_text(f"📊 Ваша статистика: {stats_data}")
            else:
                await update.message.reply_text("❌ Не удалось получить статистику")
        except Exception as e:
            logger.error(f"Ошибка stats: {e}")
            await update.message.reply_text("❌ Ошибка при получении статистики")

    # ==============================
    # Текстовые сообщения
    # ==============================
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        processing_msg = await update.message.reply_text("🤖 Обрабатываю через GPT...")
        processed_text = await self.process_with_chatgpt(text)

        # Сохраняем
        await self.save_to_google_sheet(
            update.effective_user.username,
            update.effective_user.id,
            "text",
            text,
            processed_text
        )

        await processing_msg.edit_text(f"✅ Обработано:\n\n{processed_text}")

    # ==============================
    # Голосовые сообщения
    # ==============================
    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        processing_msg = await update.message.reply_text("🎤 Обрабатываю голосовое...")
        try:
            voice_file = await context.bot.get_file(update.message.voice.file_id)
            voice_bytes = BytesIO()
            await voice_file.download_to_memory(voice_bytes)
            voice_bytes.seek(0)

            # Конвертация в текст
            text = await self.voice_to_text(voice_bytes)
            if not text:
                await processing_msg.edit_text("❌ Не удалось распознать голос.")
                return

            await processing_msg.edit_text(f"📝 Распознано: {text[:100]}...")

            processed_text = await self.process_with_chatgpt(text)

            await self.save_to_google_sheet(
                update.effective_user.username,
                update.effective_user.id,
                "voice",
                text,
                processed_text
            )

            await processing_msg.edit_text(f"✅ Обработано:\n\n{processed_text}")

        except Exception as e:
            logger.error(f"Ошибка voice: {e}")
            await processing_msg.edit_text("❌ Ошибка при обработке голосового")

    # ==============================
    # GPT обработка
    # ==============================
    async def process_with_chatgpt(self, text: str) -> str:
        try:
            response = await asyncio.to_thread(
                self.openai_client.chat.completions.create,
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты помощник, структурируешь идеи."},
                    {"role": "user", "content": text}
                ],
                max_tokens=600,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Ошибка GPT: {e}")
            return f"❌ Ошибка GPT. Исходный текст: {text}"

    # ==============================
    # Speech-to-text
    # ==============================
    async def voice_to_text(self, voice_bytes):
        try:
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
                temp_ogg.write(voice_bytes.read())
                temp_ogg_path = temp_ogg.name

            audio = AudioSegment.from_ogg(temp_ogg_path)
            audio = audio.set_frame_rate(16000).set_channels(1)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                temp_wav_path = temp_wav.name
                audio.export(temp_wav_path, format="wav")

            recognizer = sr.Recognizer()
            with sr.AudioFile(temp_wav_path) as source:
                audio_data = recognizer.record(source)
                try:
                    text = recognizer.recognize_google(audio_data, language="ru-RU")
                except sr.UnknownValueError:
                    text = None

            os.unlink(temp_ogg_path)
            os.unlink(temp_wav_path)
            return text
        except Exception as e:
            logger.error(f"Ошибка STT: {e}")
            return None

    # ==============================
    # Google Sheets + Bitrix
    # ==============================
    async def save_to_google_sheet(self, username, user_id, message_type, original_text, processed_text):
        if not self.google_script_url:
            return
        try:
            data = {
                "action": "saveMessage",
                "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                "username": username,
                "user_id": user_id,
                "message_type": message_type,
                "original_text": original_text,
                "processed_text": processed_text
            }
            response = requests.post(self.google_script_url, json=data)
            if response.status_code == 200:
                logger.info("✅ Данные сохранены в Google Sheets")
                if self.bitrix_webhook:
                    await self.create_bitrix_task(processed_text)
            else:
                logger.error(f"Ошибка сохранения: {response.text}")
        except Exception as e:
            logger.error(f"Ошибка Google Sheets: {e}")

    async def create_bitrix_task(self, description):
        try:
            task_data = {
                "fields": {
                    "TITLE": "Новая идея из Telegram",
                    "DESCRIPTION": description,
                    "RESPONSIBLE_ID": 1,
                    "PRIORITY": "1"
                }
            }
            response = requests.post(f"{self.bitrix_webhook}/tasks.task.add", json=task_data)
            if response.status_code == 200:
                logger.info("✅ Задача создана в Bitrix24")
            else:
                logger.error(f"Ошибка Bitrix: {response.text}")
        except Exception as e:
            logger.error(f"Ошибка Bitrix: {e}")

    # ==============================
    # Run
    # ==============================
    def run(self):
        logger.info("🚀 Бот запущен")
        self.app.run_polling(drop_pending_updates=True)

# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    bot = TelegramBotWithAppsScript()
    bot.run()
