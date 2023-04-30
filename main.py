from flask import Flask, request, jsonify
import telebot
import re
import envparse
from telebot import TeleBot
import requests
import sqlite3
import func

production = True
unique_thread_names = False
envparse.env.read_envfile()
telegram_token_prod: str = envparse.env.str("telegram_token_prod")
telegram_token_dev: str = envparse.env.str("telegram_token_dev")
mattermost_bearer_token: str = envparse.env.str("mattermost_bearer_token")
mattermost_server_url: str = envparse.env.str("mattermost_server_url")
prod_tg_chat: str = envparse.env.str("prod_tg_chat")
test_tg_chat: str = envparse.env.str("test_tg_chat")
mattermost_team_id: str = envparse.env.str("mattermost_team_id")
if production:
    bot = TeleBot(telegram_token_prod, threaded=False)
    print('prod')
else:
    bot = TeleBot(telegram_token_dev, threaded=False)
    print('dev')

app = Flask(__name__)

conn = sqlite3.connect('mentions.db')
c = conn.cursor()

c.execute(func.create_mention_mapping)
conn.commit()
c.execute(func.create_mask_regions)
conn.commit()
c.close()

headers = {
    'Authorization': 'Bearer {}'.format(mattermost_bearer_token),
    'X-Requested-With': 'XMLHttpRequest'
}
get_root_id = ''
get_root_name = ''
get_channel_id = ''
got_channel_name_to_reply = ''


def get_channel_name(channel_id):
    api_url = '{}/api/v4/channels/{}'.format(mattermost_server_url, channel_id)
    response = requests.get(api_url, headers=headers)
    if response.status_code == 200:
        return response.json().get('display_name', '')
    return ''


def get_data_from_mattermost_post(data):
    post_id_url = '{}/api/v4/posts/{}'.format(mattermost_server_url, data['post_id'])
    get_channel_id = data['channel_id']
    r_post_id = requests.get(post_id_url, headers=headers)
    get_post_id = r_post_id.json()
    get_post_r_id = get_post_id['id']
    get_root_id = get_post_id['root_id']
    root_id_url = '{}/api/v4/posts/{}'.format(mattermost_server_url, get_root_id)
    r_root_id = requests.get(root_id_url, headers=headers)
    get_root_id = r_root_id.json()
    get_root_name = get_root_id['message']
    channel_name = get_channel_name(data['channel_id'])

    return get_root_name, channel_name, get_post_r_id


@app.route('/callback', methods=['POST'])
def callback_handler():
    data = request.get_json()
    if 'trigger_word' in data:
        #   вебхук на тег юзернейма в mattermost
        if str(data['text']).startswith('@'):
            get_root_name, channel_name, get_post_r_id = get_data_from_mattermost_post(data)
            conn = sqlite3.connect('mentions.db')
            c = conn.cursor()
            c.execute("SELECT * FROM mention_mapping")
            rows = c.fetchall()
            for row in rows:
                trigger_word = row[1]
                tg_username = row[2]
                if trigger_word in data.get('text', ''):
                    message = func.mentiontext.format(tg_username, get_root_name, channel_name, data['text'])
                    send_telegram_message(message)
            c.close()
        else:
            get_root_name, channel_name, get_post_r_id = get_data_from_mattermost_post(data)
            get_message = data['text']
            channel_name = get_channel_name(data['channel_id'])
            pattern = r'\d{2}-\d{3,5}'
            if re.search(pattern, get_message):
                conn = sqlite3.connect('mentions.db')
                c = conn.cursor()
                c.execute("SELECT * FROM mask_regions")
                rows = c.fetchall()
                for row in rows:
                    region_mask = row[1]
                    region_name = row[2]
                    if not unique_thread_names:
                        if region_mask in data.get('text', ''):
                            message = func.newthread.format(get_message, region_name, channel_name, get_post_r_id)
                            send_telegram_message(message)
                    else:
                        if region_mask in data.get('text', ''):
                            message = func.newthreadunique.format(get_message, region_name, channel_name, get_post_r_id)
                            send_telegram_message(message)
                    c.close()
        return ''


def send_telegram_message(message):
    print(message)
    if production:
        try:
            bot.send_message(chat_id=prod_tg_chat, text=message)
        except telebot.apihelper.ApiTelegramException as e:
            func.catcherrors(e, prod_tg_chat)
    else:
        try:
            bot.send_message(chat_id=test_tg_chat, text=message)
        except telebot.apihelper.ApiTelegramException as e:
            func.catcherrors(e, test_tg_chat)


def post_to_mattermost(channel_id, thread_id, message):
    post_url = '{}/api/v4/posts'.format(mattermost_server_url)
    data = {
        'channel_id': channel_id,
        'message': message,
        'root_id': thread_id
    }
    response = requests.post(post_url, headers=headers, json=data)
    return response.ok


def get_channel_id_by_name(channel_name):
    url = '{}/api/v4/teams/{}/channels'.format(mattermost_server_url, mattermost_team_id)
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    channels = response.json()
    for channel in channels:
        if channel['display_name'] == channel_name:
            return channel['id']
    return None


def get_thread_id(thread_name, channel_id):
    pattern = r"\d{2}-\d{3,5}"
    get_thread_name = re.search(pattern, thread_name)
    get_thread_id_url = "{}/api/v4/channels/{}/posts".format(mattermost_server_url, channel_id)
    response = requests.get(get_thread_id_url, headers=headers)
    response.raise_for_status()
    get_thread_name = get_thread_name.group()  # 66-123
    posts = response.json()
    for post_id, post_data in sorted(posts["posts"].items(), reverse=True):
        # access post properties
        if post_data["message"] == get_thread_name:
            return post_data["id"]


def get_updates():
    apiurl = 'https://api.telegram.org/bot{}/getUpdates'.format(telegram_token_prod)
    r = requests.get(apiurl)
    return r.json()


# Handler for incoming updates
@app.route('/', methods=['POST'])
def handle_update():
    if request.method == 'POST':
        r = request.get_json()
        if 'message' in r and 'text' in r['message']:
            message_api = r['message']['text']
            if 'reply_to_message' in r['message']:
                if r['message']['reply_to_message']:
                    reply_text = r['message']['reply_to_message']['text']
                    message_to_reply = ''
                    # Check if the message is a reply to a Telegram bot message
                    print('replied!')
                    if message_api.startswith('/@'):
                        thread_name = reply_text
                        conn = sqlite3.connect('mentions.db')
                        c = conn.cursor()
                        c.execute("SELECT * FROM mention_mapping")
                        rows = c.fetchall()
                        mention_message = message_api.replace('/', '')
                        print(mention_message)
                        for row in rows:
                            trigger_word = row[1]
                            tg_username = row[2]
                            print(trigger_word, tg_username)
                            if tg_username == mention_message:
                                message_to_reply = trigger_word
                        c.close()
                        get_channel_name = re.search(r'на канале (\w+)', thread_name)
                        if get_channel_name:
                            got_channel_name_to_reply = get_channel_name.group(1)
                            channel_id_to_reply = get_channel_id_by_name(got_channel_name_to_reply)  # channel_id
                            #   obj=post_id - Создан тред...obj=... , чтобы отвечать на конкретный тред, если их имена дублируются
                            if not unique_thread_names:
                                pattern = r'obj=(\w+)'
                                print(thread_name)
                                match = re.search(pattern, thread_name)
                                print(match)
                                if match:
                                    get_thread_id_by_pattern = match.group(1)
                                    post_to_mattermost(channel_id_to_reply, get_thread_id_by_pattern, message_to_reply)
                                    print(get_thread_id_by_pattern)
                                    #   если имена уникальны
                                else:
                                    thread_id_to_reply = get_thread_id(thread_name, channel_id_to_reply)  # thread_id
                                    post_to_mattermost(channel_id_to_reply, thread_id_to_reply, message_to_reply)
                        else:
                            print('Not posted!')
                    else:
                        print('No reply!')
        return jsonify(r)


if __name__ == '__main__':
    app.run()
