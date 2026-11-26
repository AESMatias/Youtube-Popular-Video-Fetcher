from providers import openai

KEY_ENV = 'DEEPSEEK_API_KEY'
MODEL = 'deepseek-chat'
URL = 'https://api.deepseek.com/chat/completions'


def complete(prompt, key, model):
    return openai.chat(URL, prompt, key, model)
