"""Shared HTTP helper for the LLM providers. Tests replace post_json."""
import json
import urllib.error
import urllib.request

TIMEOUT = 120


class ProviderError(Exception):
    def __init__(self, msg, fatal=False):
        Exception.__init__(self, msg)
        # fatal means auth, billing or quota: stop the whole run instead of skipping one video
        self.fatal = fatal


def post_json(url, body, headers):
    headers = dict(headers, **{'Content-Type': 'application/json'})
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:300]
        raise ProviderError('HTTP %d: %s' % (e.code, detail), fatal=e.code in (401, 402, 403, 429))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ProviderError(str(e))


def unexpected(data):
    return ProviderError('unexpected response: ' + json.dumps(data)[:300])
