import os
import asyncio
import logging
from datetime import datetime
import openai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests
import json
from io import BytesIO
import speech_recognition as sr
from pydub import AudioSegment
import tempfile

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramBotWithAppsScript:
    def __init__(self):
        # Конфигурация
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.bitrix_webhook = os.getenv('BITRIX_WEBHOOK_URL')
        
        # URL вашего Google Apps Script веб-приложения
        self.google_script_url = os.getenv('GOOGLE_SCRIPT_URL')
        
        # Инициализация OpenAI
        openai.api_key = self.openai_api_key
        
        # Инициализация Telegram бота
        self.app = Application.builder().token(self.telegram_token).build()
        self.setup_handlers()

    def setup_handlers(self):
        """Настройка обработчиков команд и сообщений"""
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /start"""
        welcome_text = """
🤖 Добро пожаловать в бота для обработки идей!

Я могу:
• 🎤 Принимать голосовые сообщения
• 💬 Принимать текстовые сообщения  
• 🧠 Обрабатывать их через ChatGPT
• 📊 Сохранять в Google таблицу
• 📋 Создавать задачи в Bitrix24

Просто отправьте мне голосовое или текстовое сообщение!
        """
        await update.message.reply_text(welcome_text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /help"""
        help_text = """
📋 Как использовать бота:

1. 🎤 **Голосовые сообщения:**
   • Говорите четко и не спеша
   • Можно записывать до 5 минут
   • Бот автоматически распознает русскую речь

2. 💬 **Текстовые сообщения:**
   • Пишите любые идеи или задачи
   • Можно отправлять длинные сообщения
   • Бот структурирует вашу мысль

3. 📊 **Команды:**
   • /start - начать работу
   • /help - эта справка
   • /stats - статистика использования

💡 **Совет:** Чем подробнее опишете свою идею, тем лучше будет результат!
        """
        await update.message.reply_text(help_text)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение статистики из Google таблицы"""
        try:
            # Запрос статистики через Google Apps Script
            response = await asyncio.to_thread(
                requests.get,
                f"{self.google_script_url}?action=getStats&user={update.effective_user.username or update.effective_user.first_name}"
            )
            
            if response.status_code == 200:
                stats_data = response.json()
                stats_text = f"""
📊 **Ваша статистика:**

📨 Всего сообщений: {stats_data.get('total', 0)}
🎤 Голосовых: {stats_data.get('voice', 0)}
💬 Текстовых: {stats_data.get('text', 0)}
📅 Последнее сообщение: {stats_data.get('last_date', 'Нет данных')}

📋 **Категории:**
{stats_data.get('categories', 'Нет данных')}
                """
                await update.message.reply_text(stats_text)
            else:
                await update.message.reply_text("❌ Не удалось получить статистику")
                
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            await update.message.reply_text("❌ Ошибка при получении статистики")

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка голосовых сообщений"""
        try:
            processing_msg = await update.message.reply_text("🎤 Обрабатываю голосовое сообщение...")
            
            # Получаем файл
            voice_file = await context.bot.get_file(update.message.voice.file_id)
            
            # Скачиваем и конвертируем
            voice_bytes = BytesIO()
            await voice_file.download_to_memory(voice_bytes)
            voice_bytes.seek(0)
            
            # Обновляем статус
            await processing_msg.edit_text("🎧 Распознаю речь...")
            
            # Конвертируем в текст
            text = await self.voice_to_text(voice_bytes)
            
            if text:
                await processing_msg.edit_text(f"📝 Распознано: {text[:100]}{'...' if len(text) > 100 else ''}")
                
                # Обрабатываем через ChatGPT
                await processing_msg.edit_text("🤖 Обрабатываю через ChatGPT...")
                processed_text = await self.process_with_chatgpt(text)
                
                # Сохраняем в Google таблицу
                await processing_msg.edit_text("💾 Сохраняю в таблицу...")
                await self.save_to_google_sheet(
                    username=update.effective_user.username or update.effective_user.first_name,
                    user_id=update.effective_user.id,
                    message_type='voice',
                    original_text=text,
                    processed_text=processed_text
                )
                
                # Показываем результат
                result_text = f"""
✅ **Голосовое сообщение обработано!**

💭 **Обработанная мысль:**
{processed_text}

📊 Данные сохранены в Google таблицу
                """
                
                await processing_msg.edit_text(result_text)
            else:
                await processing_msg.edit_text("❌ Не удалось распознать голос. Попробуйте говорить четче.")
                
        except Exception as e:
            logger.error(f"Ошибка обработки голоса: {e}")
            await update.message.reply_text("❌ Произошла ошибка при обработке голосового сообщения.")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        try:
            text = update.message.text
            processing_msg = await update.message.reply_text("💭 Обрабатываю ваше сообщение...")
            
            # Обрабатываем через ChatGPT
            await processing_msg.edit_text("🤖 Обрабатываю через ChatGPT...")
            processed_text = await self.process_with_chatgpt(text)
            
            # Сохраняем в Google таблицу
            await processing_msg.edit_text("💾 Сохраняю в таблицу...")
            await self.save_to_google_sheet(
                username=update.effective_user.username or update.effective_user.first_name,
                user_id=update.effective_user.id,
                message_type='text',
                original_text=text,
                processed_text=processed_text
            )
            
            # Показываем результат
            result_text = f"""
✅ **Сообщение обработано!**

💭 **Обработанная мысль:**
{processed_text}

📊 Данные сохранены в Google таблицу
            """
            
            await processing_msg.edit_text(result_text)
            
        except Exception as e:
            logger.error(f"Ошибка обработки текста: {e}")
            await update.message.reply_text("❌ Произошла ошибка при обработке сообщения.")

    async def voice_to_text(self, voice_bytes):
        """Конвертация голоса в текст"""
        try:
            # Создаем временный файл
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as temp_ogg:
                temp_ogg.write(voice_bytes.read())
                temp_ogg_path = temp_ogg.name
            
            # Конвертируем в WAV
            audio = AudioSegment.from_ogg(temp_ogg_path)
            # Нормализуем аудио
            audio = audio.normalize()
            audio = audio.set_frame_rate(16000).set_channels(1)
            
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
                temp_wav_path = temp_wav.name
                audio.export(temp_wav_path, format="wav")
            
            # Распознаем речь
            r = sr.Recognizer()
            r.energy_threshold = 300
            r.pause_threshold = 0.8
            
            with sr.AudioFile(temp_wav_path) as source:
                r.adjust_for_ambient_noise(source, duration=0.5)
                audio_data = r.record(source)
                
                # Пробуем русский, потом английский
                try:
                    text = r.recognize_google(audio_data, language='ru-RU')
                except sr.UnknownValueError:
                    try:
                        text = r.recognize_google(audio_data, language='en-US')
                    except sr.UnknownValueError:
                        text = None
                
            # Удаляем временные файлы
            os.unlink(temp_ogg_path)
            os.unlink(temp_wav_path)
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка распознавания речи: {e}")
            return None

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

    async def save_to_google_sheet(self, username, user_id, message_type, original_text, processed_text):
        """Сохранение данных в Google таблицу через Apps Script"""
        try:
            # Определяем категорию автоматически
            category = self.determine_category(original_text)
            priority = self.determine_priority(original_text)
            responsible = self.get_responsible(category)
            
            # Данные для отправки
            data = {
                'action': 'saveMessage',
                'timestamp': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
                'username': username,
                'user_id': user_id,
                'message_type': message_type,
                'category': category,
                'priority': priority,
                'original_text': original_text,
                'processed_text': processed_text,
                'responsible': responsible
            }
            
            # Отправляем в Google Apps Script
            response = await asyncio.to_thread(
                requests.post,
                self.google_script_url,
                json=data,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                logger.info("Данные успешно сохранены в Google таблицу")
                
                # Если настроен Bitrix24, создаем задачу
                if self.bitrix_webhook:
                    await self.create_bitrix_task(processed_text, responsible, category, priority)
            else:
                logger.error(f"Ошибка сохранения в Google: {response.text}")
                
        except Exception as e:
            logger.error(f"Ошибка сохранения в Google таблицу: {e}")

    def determine_category(self, text):
        """Определение категории сообщения"""
        text_lower = text.lower()
        
        categories = {
            'разработка': ['код', 'баг', 'фича', 'api', 'база данных', 'разработка', 'программирование'],
            'маркетинг': ['реклама', 'сео', 'контент', 'соцсети', 'продвижение', 'маркетинг'],
            'продажи': ['клиент', 'сделка', 'продажи', 'менеджер', 'crm', 'лид'],
            'поддержка': ['поддержка', 'помощь', 'проблема', 'вопрос', 'техподдержка']
        }
        
        for category, keywords in categories.items():
            if any(keyword in text_lower for keyword in keywords):
                return category
        
        return 'общее'

    def determine_priority(self, text):
        """Определение приоритета"""
        text_lower = text.lower()
        
        high_priority = ['срочно', 'важно', 'критично', 'горит', 'asap', 'немедленно']
        low_priority = ['идея', 'предложение', 'когда-нибудь', 'не срочно']
        
        if any(word in text_lower for word in high_priority):
            return 'высокий'
        elif any(word in text_lower for word in low_priority):
            return 'низкий'
        
        return 'средний'

    def get_responsible(self, category):
        """Получение ответственного по категории"""
        responsible_map = {
            'разработка': 'Иван Петров',
            'маркетинг': 'Анна Сидорова',
            'продажи': 'Михаил Козлов',
            'поддержка': 'Елена Смирнова',
            'общее': 'Администратор'
        }
        
        return responsible_map.get(category, 'Не назначен')

    async def create_bitrix_task(self, description, responsible, category, priority):
        """Создание задачи в Bitrix24"""
        try:
            priority_map = {'низкий': '0', 'средний': '1', 'высокий': '2'}
            
            task_data = {
                "fields": {
                    "TITLE": f"[{category.upper()}] Новая идея из Telegram",
                    "DESCRIPTION": description,
                    "RESPONSIBLE_ID": 1,  # ID пользователя в Bitrix24
                    "PRIORITY": priority_map.get(priority, '1'),
                    "TAGS": [category, "telegram-bot", priority]
                }
            }
            
            response = await asyncio.to_thread(
                requests.post,
                f"{self.bitrix_webhook}/tasks.task.add",
                json=task_data
            )
            
            if response.status_code == 200:
                logger.info("Задача успешно создана в Bitrix24")
            else:
                logger.error(f"Ошибка создания задачи в Bitrix24: {response.text}")
                
        except Exception as e:
            logger.error(f"Ошибка создания задачи в Bitrix24: {e}")

    def run(self):
        """Запуск бота"""
        logger.info("Запуск Telegram бота с Google Apps Script...")
        self.app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    # Загружаем переменные окружения
    from dotenv import load_dotenv
    load_dotenv()
    
    bot = TelegramBotWithAppsScript()
    bot.run()
