from providers import base

KEY_ENV = 'GEMINI_API_KEY'
MODEL = 'gemini-2.5-flash'
URL = 'https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent'


def complete(prompt, key, model):
    data = base.post_json(URL % model, {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                                        'generationConfig': {'responseMimeType': 'application/json'}},
                          {'x-goog-api-key': key})
    try:
        return ''.join(p.get('text', '') for p in data['candidates'][0]['content']['parts'])
    except (KeyError, IndexError, TypeError, AttributeError):
        raise base.unexpected(data)
