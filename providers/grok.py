from providers import openai

KEY_ENV = 'XAI_API_KEY'
MODEL = 'grok-3-mini'
URL = 'https://api.x.ai/v1/chat/completions'


def complete(prompt, key, model):
    return openai.chat(URL, prompt, key, model)
