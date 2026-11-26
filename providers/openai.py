from providers import base

KEY_ENV = 'OPENAI_API_KEY'
MODEL = 'gpt-5-mini'
URL = 'https://api.openai.com/v1/chat/completions'


def chat(url, prompt, key, model):
    """Chat completions call, shared by every OpenAI compatible provider."""
    data = base.post_json(url, {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                                'response_format': {'type': 'json_object'}},
                          {'Authorization': 'Bearer ' + key})
    try:
        return data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        raise base.unexpected(data)


def complete(prompt, key, model):
    return chat(URL, prompt, key, model)
