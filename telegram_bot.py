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
        
        # Проверяем обязательные переменные окружения
        self._validate_env_variables()
        
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
    
    def _validate_env_variables(self):
        """Проверка обязательных переменных окружения"""
        required_vars = ["TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY"]
        missing_vars = []
        
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            raise ValueError(f"Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}")
        
        logger.info("✅ Все обязательные переменные окружения найдены")
    
    # ==============================
    # Handlers
    # ==============================
    def setup_handlers(self):
        """Настройка обработчиков команд и сообщений"""
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        logger.info("✅ Обработчики команд настроены")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        try:
            await update.message.reply_text(
                "👋 Привет! Я бот для обработки идей.\n"
                "Отправь мне текст или голосовое сообщение — я обработаю его через GPT 🤖"
            )
            logger.info(f"Команда /start от пользователя {update.effective_user.username}")
        except Exception as e:
            logger.error(f"Ошибка в start_command: {e}")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /help"""
        try:
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
            logger.info(f"Команда /help от пользователя {update.effective_user.username}")
        except Exception as e:
            logger.error(f"Ошибка в help_command: {e}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /stats"""
        if not self.google_script_url:
            await update.message.reply_text("❌ Статистика недоступна (не настроен Google Script)")
            return
            
        try:
            username = update.effective_user.username or "unknown"
            url = f"{self.google_script_url}?action=getStats&user={username}"
            
            response = await asyncio.to_thread(requests.get, url, timeout=10)
            
            if response.status_code == 200:
                try:
                    stats_data = response.json()
                    await update.message.reply_text(f"📊 Ваша статистика: {stats_data}")
                    logger.info(f"Статистика получена для {username}")
                except Exception as json_error:
                    await update.message.reply_text(f"📊 Статистика: {response.text}")
            else:
                await update.message.reply_text("❌ Не удалось получить статистику")
                logger.error(f"Ошибка получения статистики: {response.status_code}")
                
        except asyncio.TimeoutError:
            await update.message.reply_text("❌ Таймаут при получении статистики")
            logger.error("Таймаут при получении статистики")
        except Exception as e:
            logger.error(f"Ошибка stats_command: {e}")
            await update.message.reply_text("❌ Ошибка при получении статистики")

    # ==============================
    # Текстовые сообщения
    # ==============================
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        text = update.message.text
        username = update.effective_user.username or "unknown"
        user_id = update.effective_user.id
        
        logger.info(f"Получен текст от {username}: {text[:50]}...")
        
        processing_msg = await update.message.reply_text("🤖 Обрабатываю через GPT...")
        
        try:
            # Обработка через GPT
            processed_text = await self.process_with_chatgpt(text)
            
            # Сохранение данных
            await self.save_to_google_sheet(username, user_id, "text", text, processed_text)
            
            # Отправка результата
            await processing_msg.edit_text(f"✅ Обработано:\n\n{processed_text}")
            logger.info(f"Текст обработан для {username}")
            
        except Exception as e:
            logger.error(f"Ошибка handle_text: {e}")
            await processing_msg.edit_text("❌ Ошибка при обработке текста")

    # ==============================
    # Голосовые сообщения
    # ==============================
    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка голосовых сообщений"""
        username = update.effective_user.username or "unknown"
        user_id = update.effective_user.id
        
        logger.info(f"Получено голосовое от {username}")
        
        processing_msg = await update.message.reply_text("🎤 Обрабатываю голосовое...")
        
        try:
            # Скачивание файла
            voice_file = await context.bot.get_file(update.message.voice.file_id)
            voice_bytes = BytesIO()
            await voice_file.download_to_memory(voice_bytes)
            voice_bytes.seek(0)
            
            # Конвертация в текст (неблокирующая)
            text = await asyncio.to_thread(self.voice_to_text, voice_bytes)
            
            if not text:
                await processing_msg.edit_text("❌ Не удалось распознать голос")
                return
            
            await processing_msg.edit_text(f"📝 Распознано: {text[:100]}...")
            logger.info(f"Голос распознан для {username}: {text[:50]}...")
            
            # Обработка через GPT
            processed_text = await self.process_with_chatgpt(text)
            
            # Сохранение данных
            await self.save_to_google_sheet(username, user_id, "voice", text, processed_text)
            
            # Отправка результата
            await processing_msg.edit_text(f"✅ Обработано:\n\n{processed_text}")
            logger.info(f"Голосовое обработано для {username}")
            
        except Exception as e:
            logger.error(f"Ошибка handle_voice: {e}")
            await processing_msg.edit_text("❌ Ошибка при обработке голосового сообщения")

    # ==============================
    # GPT обработка
    # ==============================
    async def process_with_chatgpt(self, text: str) -> str:
        """Обработка текста через ChatGPT"""
        try:
            logger.info("Отправка запроса в OpenAI...")
            
            response = await asyncio.to_thread(
                self.openai_client.chat.completions.create,
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты помощник, который структурирует идеи и мысли пользователя. Делай ответ кратким, но информативным."},
                    {"role": "user", "content": text}
                ],
                max_tokens=600,
                temperature=0.7
            )
            
            result = response.choices[0].message.content.strip()
            logger.info("✅ Получен ответ от OpenAI")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка GPT: {e}")
            return f"❌ Ошибка обработки GPT. Исходный текст:\n\n{text}"

    # ==============================
    # Speech-to-text (синхронная функция)
    # ==============================
    def voice_to_text(self, voice_bytes):
        """Конвертация голоса в текст"""
        temp_ogg_path = None
        temp_wav_path = None
        
        try:
            # Сохраняем ogg файл
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
                temp_ogg.write(voice_bytes.read())
                temp_ogg_path = temp_ogg.name
            
            # Конвертируем в wav
            audio = AudioSegment.from_ogg(temp_ogg_path)
            audio = audio.set_frame_rate(16000).set_channels(1)
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                temp_wav_path = temp_wav.name
                audio.export(temp_wav_path, format="wav")
            
            # Распознаем речь
            recognizer = sr.Recognizer()
            with sr.AudioFile(temp_wav_path) as source:
                audio_data = recognizer.record(source)
                try:
                    text = recognizer.recognize_google(audio_data, language="ru-RU")
                    logger.info("✅ Голос успешно распознан")
                    return text
                except sr.UnknownValueError:
                    logger.warning("Не удалось распознать речь")
                    return None
                except sr.RequestError as e:
                    logger.error(f"Ошибка сервиса распознавания: {e}")
                    return None
            
        except Exception as e:
            logger.error(f"Ошибка voice_to_text: {e}")
            return None
        finally:
            # Очистка временных файлов
            if temp_ogg_path and os.path.exists(temp_ogg_path):
                os.unlink(temp_ogg_path)
            if temp_wav_path and os.path.exists(temp_wav_path):
                os.unlink(temp_wav_path)

    # ==============================
    # Google Sheets + Bitrix
    # ==============================
    async def save_to_google_sheet(self, username, user_id, message_type, original_text, processed_text):
        """Сохранение в Google Sheets"""
        if not self.google_script_url:
            logger.info("Google Script URL не настроен, пропускаем сохранение")
            return
        
        try:
            data = {
                "action": "saveMessage",
                "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                "username": username,
                "user_id": str(user_id),
                "message_type": message_type,
                "original_text": original_text,
                "processed_text": processed_text
            }
            
            response = await asyncio.to_thread(
                requests.post, 
                self.google_script_url, 
                json=data, 
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("✅ Данные сохранены в Google Sheets")
                # Создаем задачу в Bitrix, если настроен
                if self.bitrix_webhook:
                    await self.create_bitrix_task(processed_text, username)
            else:
                logger.error(f"Ошибка сохранения в Google Sheets: {response.status_code} - {response.text}")
                
        except asyncio.TimeoutError:
            logger.error("Таймаут при сохранении в Google Sheets")
        except Exception as e:
            logger.error(f"Ошибка save_to_google_sheet: {e}")

    async def create_bitrix_task(self, description, username):
        """Создание задачи в Bitrix24"""
        try:
            task_data = {
                "fields": {
                    "TITLE": f"Новая идея из Telegram от {username}",
                    "DESCRIPTION": description,
                    "RESPONSIBLE_ID": 1,
                    "PRIORITY": "1"
                }
            }
            
            response = await asyncio.to_thread(
                requests.post, 
                f"{self.bitrix_webhook}/tasks.task.add", 
                json=task_data, 
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("✅ Задача создана в Bitrix24")
            else:
                logger.error(f"Ошибка создания задачи в Bitrix: {response.status_code} - {response.text}")
                
        except asyncio.TimeoutError:
            logger.error("Таймаут при создании задачи в Bitrix")
        except Exception as e:
            logger.error(f"Ошибка create_bitrix_task: {e}")

    # ==============================
    # Запуск бота
    # ==============================
    def run(self):
        """Запуск бота"""
        try:
            logger.info("🚀 Запуск Telegram бота...")
            self.app.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES
            )
        except Exception as e:
            logger.error(f"Критическая ошибка при запуске бота: {e}")
            raise

# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    try:
        bot = TelegramBotWithAppsScript()
        bot.run()
    except ValueError as e:
        logger.error(f"Ошибка конфигурации: {e}")
        print(f"❌ Ошибка конфигурации: {e}")
        print("Убедитесь, что в .env файле указаны TELEGRAM_BOT_TOKEN и OPENAI_API_KEY")
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise
