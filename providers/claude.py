from providers import base

KEY_ENV = 'ANTHROPIC_API_KEY'
MODEL = 'claude-haiku-5-5'
URL = 'https://api.anthropic.com/v1/messages'


def complete(prompt, key, model):
    # stdlib only, so raw HTTP instead of the anthropic SDK
    data = base.post_json(URL, {'model': model, 'max_tokens': 8000,
                                'messages': [{'role': 'user', 'content': prompt}]},
                          {'x-api-key': key, 'anthropic-version': '2023-06-01'})
    if not isinstance(data, dict) or not isinstance(data.get('content'), list):
        raise base.unexpected(data)
    if data.get('stop_reason') == 'refusal':
        raise base.ProviderError('model refused this video')
    # newer models can return thinking blocks before the text
    text = ''.join(b.get('text', '') for b in data['content'] if isinstance(b, dict) and b.get('type') == 'text')
    if not text:
        raise base.unexpected(data)
    return text
