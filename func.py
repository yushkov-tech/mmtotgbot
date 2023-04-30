def catcherrors(e, chat):
    if e.result.status_code == 400:
        if 'chat not found' in e.description:
            print("Bad Request: chat not found", chat)
        elif 'not enough rights' in e.description:
            print("Bad Request: not enough rights to send text messages to the chat", chat)
        else:
            raise e
    elif e.result.status_code == 403:
        if 'bot was blocked by the user' in e.description:
            print("Forbidden: bot was blocked by the chat", chat)
        elif 'bot was kicked from the group chat' in e.description:
            print("Forbidden: bot was kicked from the chat", chat)
        else:
            raise e
    else:
        raise e


mentiontext = '''{}, тебя отметили в треде {} на канале {}.
Текст: {}'''
newthreadunique = '''Создан тред {} ({}) на канале {}
obj={}'''

newthread = '''Создан тред {} ({}) на канале {}
obj={}'''

create_mention_mapping ='CREATE TABLE IF NOT EXISTS mention_mapping (id INT PRIMARY KEY, trigger_word TEXT, tgusername TEXT, tgid TEXT)'
create_mask_regions = 'CREATE TABLE IF NOT EXISTS mask_regions (id INTEGER PRIMARY KEY AUTOINCREMENT, mask TEXT, region TEXT)'
