import gzip
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline  # noqa: E402
import providers  # noqa: E402
from providers import base  # noqa: E402
from test_pipeline import LONG, FakeYouTube, video  # noqa: E402

GOOD = {'seo_title': 'A good title', 'seo_description': LONG}


class ProvidersTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.reply = None
        self._orig = base.post_json
        base.post_json = lambda url, body, headers: self.calls.append((url, body, headers)) or self.reply

    def tearDown(self):
        base.post_json = self._orig

    def test_openai_compatible(self):
        self.reply = {'choices': [{'message': {'content': '{"a": 1}'}}]}
        for name, url in (('openai', 'https://api.openai.com/v1/chat/completions'),
                          ('deepseek', 'https://api.deepseek.com/chat/completions'),
                          ('grok', 'https://api.x.ai/v1/chat/completions')):
            mod = providers.PROVIDERS[name]
            self.assertEqual(mod.complete('hi', 'k', mod.MODEL), '{"a": 1}')
            u, body, headers = self.calls[-1]
            self.assertEqual((u, body['model'], headers['Authorization']), (url, mod.MODEL, 'Bearer k'))
            self.assertEqual(body['messages'], [{'role': 'user', 'content': 'hi'}])
        self.reply = {'error': 'x'}
        with self.assertRaises(base.ProviderError):
            providers.PROVIDERS['openai'].complete('hi', 'k', 'm')

    def test_gemini(self):
        self.reply = {'candidates': [{'content': {'parts': [{'text': '{"a"'}, {'text': ': 1}'}]}}]}
        self.assertEqual(providers.gemini.complete('hi', 'k', 'gemini-2.5-flash'), '{"a": 1}')
        u, body, headers = self.calls[-1]
        self.assertEqual(u, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent')
        self.assertEqual(headers['x-goog-api-key'], 'k')
        self.assertEqual(body['contents'][0]['parts'][0]['text'], 'hi')

    def test_claude(self):
        self.reply = {'content': [{'type': 'thinking', 'thinking': ''}, {'type': 'text', 'text': '{"a": 1}'}],
                      'stop_reason': 'end_turn'}
        self.assertEqual(providers.claude.complete('hi', 'k', 'claude-haiku-5-5'), '{"a": 1}')
        u, body, headers = self.calls[-1]
        self.assertEqual(u, 'https://api.anthropic.com/v1/messages')
        self.assertEqual((headers['x-api-key'], headers['anthropic-version']), ('k', '2023-06-01'))
        self.assertEqual((body['model'], body['messages'][0]['content']), ('claude-haiku-5-5', 'hi'))
        self.reply = {'content': [], 'stop_reason': 'refusal'}
        with self.assertRaises(base.ProviderError):
            providers.claude.complete('hi', 'k', 'm')

    def test_model_env_override(self):
        os.environ['OPENAI_MODEL'] = 'other'
        try:
            self.assertEqual(providers.model_for('openai'), 'other')
        finally:
            del os.environ['OPENAI_MODEL']
        self.assertEqual(providers.model_for('claude'), 'claude-haiku-5-5')


class DbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ['YTP_DB'] = os.path.join(self.tmp, 'db', 'videos.db')
        self.conn = pipeline.connect()
        self.config = pipeline.load_config()
        self._orig = (pipeline.http_get, pipeline.fetch_transcript, pipeline.api_key)
        pipeline.fetch_transcript = lambda vid, lang: 'words ' * 50

    def tearDown(self):
        pipeline.http_get, pipeline.fetch_transcript, pipeline.api_key = self._orig
        providers.PROVIDERS.pop('fake', None)
        self.conn.close()
        shutil.rmtree(self.tmp)

    def collect(self, charts, langs):
        pipeline.http_get = FakeYouTube(charts)
        pipeline.collect(self.conn, self.config, 'k', 30, 3, langs)

    def q(self, conn, sql):
        return [tuple(r) for r in conn.execute(sql).fetchall()]


class SummarizeTest(DbTest):
    def fake_provider(self, replies):
        calls = []

        def complete(prompt, key, model):
            calls.append(prompt)
            r = replies[len(calls) - 1]
            if isinstance(r, Exception):
                raise r
            return r
        providers.PROVIDERS['fake'] = types.SimpleNamespace(KEY_ENV='FAKE_KEY', MODEL='fake-1', complete=complete)
        return calls

    def test_refuses_when_disabled_or_no_key(self):
        self.collect({'DE': [video('g1', 10, 'de')]}, ['de'])
        calls = self.fake_provider([json.dumps(GOOD)])
        self.assertFalse(self.config['llm']['enabled'])
        self.assertEqual(pipeline.main(['summarize']), 1)
        self.assertEqual(pipeline.run_summarize(self.conn, self.config, None, None, False, 100), 1)
        pipeline.api_key = lambda env='YOUTUBE_API_KEY': None
        self.assertEqual(pipeline.run_summarize(self.conn, self.config, 'fake', None, False, 100), 1)
        enabled = dict(self.config, llm={'enabled': True, 'provider': 'fake'})
        self.assertEqual(pipeline.run_summarize(self.conn, enabled, None, None, False, 100), 1)
        self.assertEqual(calls, [])
        self.assertEqual(self.q(self.conn, 'SELECT * FROM summaries'), [])

    def test_end_to_end_with_fake_provider(self):
        self.collect({'DE': [video('g%d' % i, 10 - i, 'de') for i in range(1, 5)]}, ['de'])
        calls = self.fake_provider(['```json\n%s\n```' % json.dumps(GOOD), 'not json',
                                    base.ProviderError('quota', fatal=True), json.dumps(GOOD)])
        pipeline.api_key = lambda env='YOUTUBE_API_KEY': 'secret' if env == 'FAKE_KEY' else None
        self.assertEqual(pipeline.run_summarize(self.conn, self.config, 'fake', None, True, 100), 0)
        self.assertEqual(calls, [])
        self.assertEqual(pipeline.run_summarize(self.conn, self.config, 'fake', None, False, 100), 0)
        self.assertEqual(len(calls), 3)  # stopped at the fatal error, g4 never sent
        self.assertIn('## g1 (de)', calls[0])
        self.assertIn('seo_description', calls[0])
        self.assertEqual(self.q(self.conn, 'SELECT video_id, seo_title, source FROM summaries'),
                         [('g1', 'A good title', 'fake')])
        self.assertEqual(self.q(self.conn, "SELECT text FROM transcripts WHERE video_id='g1'"), [(None,)])


class ArchiveTest(DbTest):
    def fill(self):
        self.collect({'JP': [video('j1', 100, 'ja'), video('j2', 50, 'ja')]}, ['ja'])
        self.collect({'KR': [video('k1', 7, 'ko')]}, ['ko'])
        # j1 and the first run belong to a closed month
        self.conn.execute("UPDATE videos SET first_seen='2025-03-02T00:00:00Z' WHERE video_id='j1'")
        self.conn.execute("UPDATE runs SET started_at='2025-03-02T00:00:00Z' WHERE id=1")
        self.conn.execute("INSERT INTO summaries VALUES ('j1', 'T', ?, 'agent', '2025-03-03T00:00:00Z')", (LONG,))
        self.conn.commit()
        self.folder = os.path.join(self.tmp, 'archive')
        pipeline.backup(self.conn, self.folder)

    def other_db(self):
        os.environ['YTP_DB'] = os.path.join(self.tmp, 'restored.db')
        conn = pipeline.connect()
        self.addCleanup(conn.close)
        return conn

    def test_round_trip(self):
        self.fill()
        conn = self.other_db()
        pipeline.restore(conn, self.folder)
        for table in ('videos', 'summaries', 'featured', 'runs'):
            sql = 'SELECT * FROM %s ORDER BY 1, 2, 3' % table
            self.assertEqual(self.q(conn, sql), self.q(self.conn, sql), table)
        self.assertEqual(self.q(conn, 'SELECT video_id, text FROM transcripts'), [('j1', None)])
        self.assertEqual(self.q(conn, 'SELECT video_id, json FROM comments'), [('j1', '[]')])
        self.assertEqual(len(pipeline.pending(conn)), 2)

    def test_closed_month_is_gzipped_and_stable(self):
        self.fill()
        names = sorted(os.listdir(self.folder))
        current = pipeline.datetime.datetime.utcnow().strftime('%Y-%m')
        self.assertEqual(names, ['2025-03.jsonl.gz', current + '.jsonl'])
        gz = os.path.join(self.folder, '2025-03.jsonl.gz')
        first = open(gz, 'rb').read()
        with gzip.open(gz, 'rt', encoding='utf-8') as f:
            types_ = [json.loads(line)['type'] for line in f]
        self.assertEqual(types_, ['video', 'run', 'featured', 'featured'])
        self.assertEqual(pipeline.backup(self.conn, self.folder), 0)
        os.remove(gz)
        pipeline.backup(self.conn, self.folder)
        self.assertEqual(open(gz, 'rb').read(), first)
        # a month that closes loses its plain file
        open(os.path.join(self.folder, '2025-03.jsonl'), 'w').close()
        pipeline.backup(self.conn, self.folder)
        self.assertEqual(sorted(os.listdir(self.folder)), names)

    def test_restore_is_idempotent(self):
        self.fill()
        conn = self.other_db()
        pipeline.restore(conn, self.folder)
        before = [self.q(conn, 'SELECT * FROM %s ORDER BY 1' % t) for t in ('videos', 'summaries', 'featured', 'runs')]
        pipeline.restore(conn, self.folder)
        pipeline.restore(self.conn, self.folder)
        after = [self.q(conn, 'SELECT * FROM %s ORDER BY 1' % t) for t in ('videos', 'summaries', 'featured', 'runs')]
        self.assertEqual(before, after)
        self.assertEqual(self.q(self.conn, 'SELECT COUNT(*) FROM featured'), [(3,)])


if __name__ == '__main__':
    unittest.main()
