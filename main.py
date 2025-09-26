import logging
from flask import Flask, request, jsonify
import requests
import time
import envparse
from threading import Thread, Event, Lock
from datetime import datetime, timedelta, timezone
import telebot
from queue import Queue
from hashlib import md5
import pytz

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    """Класс для хранения конфигурации"""
    def __init__(self):
        envparse.env.read_envfile()
        # Mattermost
        self.mattermost_server_url = envparse.env.str("MATTERMOST_SERVER_URL")
        self.channel_id = envparse.env.str("MATTERMOST_CHANNEL_ID")
        self.mattermost_bearer_token = envparse.env.str("MATTERMOST_BEARER_TOKEN")
        self.bot_user_id = envparse.env.str("MATTERMOST_BOT_USER_ID")
        
        # Telegram
        self.telegram_bot_token = envparse.env.str("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = envparse.env.str("TELEGRAM_CHAT_ID")
        self.manager_chat_id = envparse.env.str("MANAGER_CHAT_ID")
        
        # Временные зоны
        self.ekb_tz = pytz.timezone('Asia/Yekaterinburg')
        self.msk_tz = pytz.timezone('Europe/Moscow')
        
        # Настройки времени
        self.non_working_hours = {
            'ekb': {'start': 6, 'end': 10},  # 6-8 утра ЕКБ
            'msk': {'start': 6, 'end': 10}   # 8-10 утра МСК
        }
        
        # Внедренцы
        self.implementers = {
            'ekb': ['user1_id', 'user2_id'],
            'msk': ['user3_id', 'user4_id']
        }

class MessageProcessor:
    """Обработчик сообщений с расширенной функциональностью"""
    def __init__(self, config: Config):
        self.config = config
        self.telegram_bot = telebot.TeleBot(config.telegram_bot_token)
        self.message_queue = Queue(maxsize=100)
        self.processed_messages = set()
        self.pending_responses = {}
        self.lock = Lock()
        
        # Инициализация Telegram бота
        self._setup_telegram_handlers()
    
    def _setup_telegram_handlers(self):
        """Настройка обработчиков команд Telegram"""
        @self.telegram_bot.message_handler(func=lambda message: True)
        def handle_message(message):
            if message.reply_to_message and message.reply_to_message.message_id in self.pending_responses:
                original_msg = self.pending_responses[message.reply_to_message.message_id]
                self._send_to_mattermost(
                    original_msg['channel_id'],
                    f"Ответ от внедренца: {message.text}",
                    original_msg['post_id']
                )
                self.telegram_bot.send_message(
                    message.chat.id,
                    "Ваш ответ отправлен в Mattermost!",
                    reply_to_message_id=message.message_id
                )
    
    def _get_message_hash(self, message: str, channel_id: str, post_id: str) -> str:
        """Генерирует уникальный хеш для сообщения"""
        return md5(f"{message}-{channel_id}-{post_id}".encode()).hexdigest()
    
    def _is_non_working_time(self) -> bool:
        """Проверяет, находится ли текущее время в нерабочих часах"""
        now_ekb = datetime.now(self.config.ekb_tz)
        now_msk = datetime.now(self.config.msk_tz)
        
        ekb_hour = now_ekb.hour
        msk_hour = now_msk.hour
        
        ekb_time = self.config.non_working_hours['ekb']
        msk_time = self.config.non_working_hours['msk']
        
        return (ekb_time['start'] <= ekb_hour < ekb_time['end'] or 
                msk_time['start'] <= msk_hour < msk_time['end'])
    
    def _get_implementers(self) -> list:
        """Возвращает список внедренцев для текущего времени"""
        now_ekb = datetime.now(self.config.ekb_tz).hour
        now_msk = datetime.now(self.config.msk_tz).hour
        
        if self.config.non_working_hours['ekb']['start'] <= now_ekb < self.config.non_working_hours['ekb']['end']:
            return self.config.implementers['ekb']
        else:
            return self.config.implementers['msk']
    
    def process_message(self, message: str, channel_id: str, post_id: str, user_id: str):
        """Обрабатывает входящее сообщение"""
        message_hash = self._get_message_hash(message, channel_id, post_id)
        
        with self.lock:
            if message_hash in self.processed_messages:
                return
            self.processed_messages.add(message_hash)
        
        if self._is_non_working_time():
            self._send_to_mattermost(
                channel_id,
                "Спасибо за сообщение! Мы обработаем его в рабочее время (с 8 до 18).",
                post_id
            )
            return
        
        self.message_queue.put({
            'message': message,
            'channel_id': channel_id,
            'post_id': post_id,
            'user_id': user_id,
            'timestamp': time.time()
        })
    
    def _get_user_info(self, user_id: str) -> dict:
        """Получает информацию о пользователе из Mattermost"""
        headers = {
            'Authorization': f'Bearer {self.config.mattermost_bearer_token}',
            'Content-Type': 'application/json'
        }
        try:
            response = requests.get(
                f"{self.config.mattermost_server_url}/api/v4/users/{user_id}",
                headers=headers,
                timeout=5
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе: {str(e)}")
        
        return {'username': user_id}  # Возвращаем ID если не удалось получить информацию

    def _send_to_mattermost(self, channel_id: str, message: str, post_id: str = None):
        """Отправляет сообщение в Mattermost"""
        headers = {
            'Authorization': f'Bearer {self.config.mattermost_bearer_token}',
            'Content-Type': 'application/json'
        }
        payload = {
            "channel_id": channel_id,
            "message": message,
        }
        
        if post_id and len(post_id) == 26:
            payload["root_id"] = post_id
            
        try:
            response = requests.post(
                f"{self.config.mattermost_server_url}/api/v4/posts",
                headers=headers,
                json=payload,
                timeout=10
            )
            if response.status_code != 201:
                logger.error(f"Mattermost error: {response.text}")
        except Exception as e:
            logger.error(f"Mattermost send error: {str(e)}")
    
    def _format_mattermost_link(self, post_id: str) -> str:
        """Форматирует правильную ссылку на сообщение в Mattermost"""
        if not post_id or len(post_id) != 26:
            return "Ссылка недоступна"
        
        # Удаляем возможные пробелы или спецсимволы в post_id
        clean_post_id = post_id.strip()
        return f"{self.config.mattermost_server_url}/kontur/pl/{clean_post_id}"

    def _send_to_telegram(self, message_data: dict):
        """Отправляет уведомление в Telegram с корректными ссылками"""
        # Пропускаем сообщения от бота
        if message_data['user_id'] == self.config.bot_user_id:
            return

        # Получаем информацию об отправителе
        user_info = self._get_user_info(message_data['user_id'])
        display_name = self._get_display_name(user_info)
        
        # Форматируем ссылку
        mm_link = self._format_mattermost_link(message_data['post_id'])
        
        # Создаем текст сообщения
        message_text = (
            f"🚨 Новое сообщение во внерабочее время!\n\n"
            f"От: <b>{display_name}</b>\n"
            f"Сообщение: {message_data['message']}\n\n"
            f"<a href='{mm_link}'>Перейти к сообщению в Mattermost</a>"
        )

        try:
            # Создаем клавиатуру с кнопкой
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton(
                text="Ответить в Mattermost",
                url=mm_link
            ))
            
            # Отправляем сообщение
            sent_msg = self.telegram_bot.send_message(
                self.config.telegram_chat_id,
                message_text,
                parse_mode='HTML',
                reply_markup=markup,
                disable_web_page_preview=True
            )
            
            self.pending_responses[sent_msg.message_id] = message_data
            Thread(target=self._check_response, args=(message_data,)).start()
            
        except Exception as e:
            logger.error(f"Ошибка отправки в Telegram: {str(e)}")

    def _get_display_name(self, user_info: dict) -> str:
        """Форматирует отображаемое имя пользователя"""
        username = user_info.get('username', 'Неизвестный')
        first_name = user_info.get('first_name', '')
        last_name = user_info.get('last_name', '')
        
        if first_name or last_name:
            return f"{first_name} {last_name}".strip()
        return username
    
    def _check_response(self, message_data: dict):
        """Проверяет, был ли ответ на сообщение"""
        time.sleep(3600)  # Ждем 1 час
        
        with self.lock:
            if message_data['post_id'] not in [msg['post_id'] for msg in self.pending_responses.values()]:
                return
        
        # Если ответа не было, уведомляем руководителя
        self._notify_manager(message_data)
    
    def _notify_manager(self, message_data: dict):
        """Уведомляет руководителя об отсутствии ответа"""
        message = f"⚠️ Никто не ответил на сообщение от {message_data['user_id']}:\n\n{message_data['message']}"
        
        try:
            self.telegram_bot.send_message(
                self.config.manager_chat_id,
                message,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Manager notification error: {str(e)}")
    
    def start_processing(self, stop_event: Event):
        """Запускает обработку сообщений"""
        while not stop_event.is_set():
            try:
                message_data = self.message_queue.get(timeout=1)
                self._send_to_telegram(message_data)
                self.message_queue.task_done()
            except Exception as e:
                continue

class MattermostPoller:
    """Поллинг Mattermost на новые сообщения"""
    def __init__(self, config: Config, processor: MessageProcessor):
        self.config = config
        self.processor = processor
        self.last_post_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    
    def poll(self, stop_event: Event):
        """Основной цикл поллинга"""
        headers = {
            'Authorization': f'Bearer {self.config.mattermost_bearer_token}',
            'Content-Type': 'application/json'
        }
        
        while not stop_event.is_set():
            try:
                response = requests.get(
                    f"{self.config.mattermost_server_url}/api/v4/channels/{self.config.channel_id}/posts",
                    headers=headers,
                    params={'since': int(self.last_post_time.timestamp() * 1000)},
                    timeout=15
                )
                
                if response.status_code == 200:
                    self._process_messages(response.json())
                else:
                    logger.error(f"Mattermost poll error: {response.text}")
                
                time.sleep(5)
            except Exception as e:
                logger.error(f"Mattermost poll exception: {str(e)}")
                time.sleep(10)
    
    def _process_messages(self, messages: dict):
        """Обрабатывает полученные сообщения"""
        for post_id in messages.get('order', []):
            post = messages['posts'][post_id]
            
            if post['user_id'] == self.config.bot_user_id:
                continue
                
            self.processor.process_message(
                post['message'],
                self.config.channel_id,
                post_id,
                post['user_id']
            )
            
            # Обновляем время последнего сообщения
            create_at = post.get('create_at', 0) / 1000
            self.last_post_time = datetime.fromtimestamp(create_at, timezone.utc)

class WebhookServer:
    """Сервер для обработки вебхуков"""
    def __init__(self, config: Config, processor: MessageProcessor):
        self.app = Flask(__name__)
        self.config = config
        self.processor = processor
        self._setup_routes()
    
    def _setup_routes(self):
        @self.app.route('/mattermost_webhook', methods=['POST'])
        def webhook():
            data = request.json
            if data:
                post = data.get('post', {})
                if post and post.get('user_id') != self.config.bot_user_id:
                    self.processor.process_message(
                        post['message'],
                        data['channel_id'],
                        post['id'],
                        post['user_id']
                    )
            return jsonify({'status': 'ok'})
    
    def run(self, stop_event: Event):
        """Запускает сервер"""
        while not stop_event.is_set():
            try:
                self.app.run(port=5000, threaded=True)
            except Exception as e:
                logger.error(f"Webhook server error: {str(e)}")
                time.sleep(5)

def main():
    """Основная функция запуска"""
    stop_event = Event()
    
    try:
        config = Config()
        processor = MessageProcessor(config)
        
        # Запускаем обработчик сообщений
        Thread(target=processor.start_processing, args=(stop_event,), daemon=True).start()
        
        # Запускаем поллинг Mattermost
        poller = MattermostPoller(config, processor)
        Thread(target=poller.poll, args=(stop_event,), daemon=True).start()
        
        # Запускаем вебхук сервер
        webhook_server = WebhookServer(config, processor)
        Thread(target=webhook_server.run, args=(stop_event,), daemon=True).start()
        
        # Запускаем Telegram бота
        Thread(target=processor.telegram_bot.infinity_polling, daemon=True).start()
        
        # Основной цикл
        while not stop_event.is_set():
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        stop_event.set()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        stop_event.set()

if __name__ == '__main__':
    main()