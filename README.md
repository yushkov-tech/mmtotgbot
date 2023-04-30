# mmtotgbot
Mattermost mentions to Telegram bot
Sends info about new threads in any channels of team from Mattermost to Telegram group chat.\
If somebody replies with /@username to this message it sends mention to Mattermost using association database of users - for cases such:\
@username in Telegram but @nameuser in Mattermost\
If somebody mentions you in Mattermost, Telegram bot sends mention to Telegram group chat with association of users.

Gets POST messages from Mattermost and Telegram Bot Updates (instead of classic polling because of using flask)

Stack: flask, sqlite, PyTelegramBotAPI aka Telebot
