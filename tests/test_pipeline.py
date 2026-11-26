import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline  # noqa: E402

LONG = 'This video shows a lot of interesting things. ' * 10


def video(vid, views, audio=None):
    sn = {'title': 'Title ' + vid, 'channelTitle': 'Chan', 'publishedAt': '2026-11-01T00:00:00Z',
          'description': 'desc ' + vid, 'thumbnails': {'medium': {'url': 'https://i.ytimg.com/vi/%s/mq.jpg' % vid}}}
    if audio:
        sn['defaultAudioLanguage'] = audio
    return {'id': vid, 'snippet': sn, 'statistics': {'viewCount': str(views), 'likeCount': '5'},
            'contentDetails': {'duration': 'PT3M'}}


class FakeYouTube(object):
    def __init__(self, charts):
        self.charts = charts
        self.calls = []
        self.quota_after = None

    def __call__(self, url):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        endpoint = u.path.rsplit('/', 1)[-1]
        self.calls.append((endpoint, q.get('regionCode') or q.get('videoId')))
        if self.quota_after is not None and len(self.calls) > self.quota_after:
            raise pipeline.ApiError(403, 'quotaExceeded')
        if endpoint == 'videos':
            return {'items': self.charts.get(q['regionCode'], [])}
        if q['videoId'] == 'nocomments':
            raise pipeline.ApiError(403, 'commentsDisabled')
        return {'items': [{'snippet': {'topLevelComment': {'snippet': {'textDisplay': 'great ' + q['videoId']}}}}]}

    def regions(self):
        return [x for e, x in self.calls if e == 'videos']


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ['YTP_DB'] = os.path.join(self.tmp, 'db', 'videos.db')
        self.conn = pipeline.connect()
        self.config = pipeline.load_config()
        self.transcripts = []
        self._orig = (pipeline.http_get, pipeline.fetch_transcript)
        pipeline.fetch_transcript = lambda vid, lang: self.transcripts.append(vid) or 'words ' * 3000

    def tearDown(self):
        pipeline.http_get, pipeline.fetch_transcript = self._orig
        self.conn.close()
        shutil.rmtree(self.tmp)

    def run_collect(self, charts, langs, top=30, per_lang=3, fake=None):
        fake = fake or FakeYouTube(charts)
        pipeline.http_get = fake
        pipeline.collect(self.conn, self.config, 'k', top, per_lang, langs)
        return fake

    def q(self, sql, *args):
        return self.conn.execute(sql, args).fetchall()

    def test_language_filter_and_ambiguous_region(self):
        charts = {'US': [video('a', 10, 'en-US'), video('b', 20, 'es'), video('c', 5)],
                  'IN': [video('d', 99), video('e', 50, 'en')],
                  'GB': [], 'CA': []}
        self.run_collect(charts, ['en'], per_lang=16)
        ids = [r[0] for r in self.q("SELECT video_id FROM featured WHERE lang='en' ORDER BY rank")]
        # c has no language but US is English only; d has none and IN is en+hi, so it is dropped
        self.assertEqual(ids, ['e', 'a', 'c'])

    def test_second_collect_dedupes(self):
        charts = {'JP': [video('j1', 100, 'ja'), video('j2', 50, 'ja')]}
        self.run_collect(charts, ['ja'])
        charts['JP'][0]['statistics']['viewCount'] = '500'
        fake = self.run_collect(charts, ['ja'])
        row = self.q("SELECT * FROM videos WHERE video_id='j1'")
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]['times_featured'], 2)
        self.assertEqual(row[0]['view_count'], 500)
        self.assertEqual(self.transcripts.count('j1'), 1)
        self.assertNotIn('commentThreads', [e for e, _ in fake.calls])
        self.assertEqual(len(self.q("SELECT * FROM transcripts WHERE video_id='j1'")[0]['text']), 8000)
        self.assertEqual(len(self.q('SELECT * FROM featured')), 4)

    def test_region_rotation(self):
        regions = self.config['languages']['es']['regions']
        a = self.run_collect({}, ['es'], per_lang=3)
        b = self.run_collect({}, ['es'], per_lang=3)
        self.assertEqual(a.regions(), regions[:3])
        self.assertEqual(b.regions(), regions[3:6])

    def test_quota_stop_keeps_data(self):
        charts = {'BR': [video('p1', 10, 'pt-BR'), video('p2', 9, 'pt')], 'PT': [], 'KR': [video('k1', 5, 'ko')]}
        fake = FakeYouTube(charts)
        fake.quota_after = 3  # BR, PT, comments for p1, then quota
        self.run_collect(charts, ['pt', 'ko'], fake=fake)
        self.assertEqual(len(self.q("SELECT * FROM featured WHERE lang='pt'")), 2)
        self.assertEqual(len(self.q('SELECT * FROM comments')), 1)
        self.assertEqual(self.q("SELECT * FROM featured WHERE lang='ko'"), [])
        self.assertIsNotNone(self.q('SELECT finished_at FROM runs')[0][0])

    def test_blocked_transcript_is_retried(self):
        charts = {'JP': [video('j1', 100, 'ja')]}
        pipeline.fetch_transcript = lambda vid, lang: pipeline.RETRY
        self.run_collect(charts, ['ja'])
        self.assertEqual(self.q('SELECT * FROM transcripts'), [])
        pipeline.fetch_transcript = lambda vid, lang: 'hello'
        self.run_collect(charts, ['ja'])
        self.assertEqual(self.q('SELECT text FROM transcripts')[0][0], 'hello')

    def test_comments_disabled_is_skipped(self):
        self.run_collect({'KR': [video('nocomments', 5, 'ko')]}, ['ko'])
        self.assertEqual(self.q('SELECT json FROM comments')[0][0], '[]')

    def test_agent_round_trip(self):
        self.run_collect({'DE': [video('g1', 10, 'de'), video('g2', 9, 'de'), video('g3', 8, 'de')]}, ['de'])
        inbox = os.path.join(self.tmp, 'agent', 'inbox.md')
        self.assertEqual(pipeline.agent_export(self.conn, inbox, 60, 100), 3)
        text = open(inbox, encoding='utf-8').read()
        self.assertIn('## g1 (de)', text)
        self.assertIn('- great g1', text)
        self.assertLess(len(text), 3000)

        outbox = os.path.join(self.tmp, 'agent', 'outbox.json')
        with open(outbox, 'w') as f:
            json.dump({'g1': {'seo_title': ' Good ', 'seo_description': LONG + 'x' * 2000},
                       'g2': {'seo_title': 'Short', 'seo_description': 'too short'},
                       'g3': {'seo_title': '', 'seo_description': LONG},
                       'zzz': {'seo_title': 'Unknown', 'seo_description': LONG}}, f)
        self.assertEqual(pipeline.agent_import(self.conn, outbox), (1, 3))
        self.assertFalse(os.path.exists(outbox))
        self.assertEqual(len([n for n in os.listdir(os.path.dirname(outbox)) if n.endswith('.done.json')]), 1)
        s = self.q('SELECT * FROM summaries')[0]
        self.assertEqual((s['video_id'], s['seo_title'], s['source']), ('g1', 'Good', 'agent'))
        self.assertLessEqual(len(s['seo_description']), 1500)
        # summarized video: text dropped but rows kept, the others untouched
        t = {r['video_id']: r['text'] for r in self.q('SELECT * FROM transcripts')}
        self.assertEqual((t['g1'], bool(t['g2'])), (None, True))
        self.assertEqual(self.q("SELECT json FROM comments WHERE video_id='g1'")[0][0], '[]')
        self.assertEqual(pipeline.agent_export(self.conn, inbox, 60, 100), 2)
        self.assertEqual(pipeline.agent_export(self.conn, inbox, 1, 100), 1)

    def test_export_site_shape(self):
        self.run_collect({'JP': [video('j1', 100, 'ja'), video('j2', 50, 'ja')]}, ['ja'])
        self.run_collect({'KR': [video('k1', 7, 'ko')]}, ['ko'])
        self.run_collect({'JP': [video('j3', 70, 'ja')]}, ['ja'])
        self.conn.execute("INSERT INTO summaries VALUES ('k1', 'T', 'D', 'agent', 'now')")
        out = os.path.join(self.tmp, 'src', 'data', 'site.json')
        pipeline.export_site(self.conn, self.config, out)
        data = json.load(open(out, encoding='utf-8'))
        self.assertRegex(data['updated_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        self.assertEqual(data['languages'], [{'code': 'ja', 'name': '日本語', 'count': 1},
                                             {'code': 'ko', 'name': '한국어', 'count': 1}])
        self.assertEqual([v['video_id'] for v in data['videos']], ['j3', 'k1'])
        v = data['videos'][1]
        self.assertEqual(v['view_count'], 7)
        self.assertEqual(v['youtube_url'], 'https://www.youtube.com/watch?v=k1')
        self.assertEqual((v['seo_title'], v['seo_description'], v['rank']), ('T', 'D', 1))
        self.assertIsNone(data['videos'][0]['seo_title'])
        for key in ('lang', 'channel_title', 'published_at', 'like_count', 'comment_count', 'duration',
                    'thumbnail_url', 'description', 'times_featured', 'first_seen'):
            self.assertIn(key, v)

    def test_import_legacy(self):
        old = os.path.join(self.tmp, 'old')
        os.makedirs(os.path.join(old, 'sumarios_seo'))
        items = [{'video_id': 'l1', 'title': 'One', 'view_count': '30', 'region_code': 'ES', 'transcript': 'hola',
                  'comments': ['c1', 'c2']},
                 {'video_id': 'l1', 'title': 'Dup', 'view_count': '1', 'region_code': 'US'},
                 {'video_id': 'l2', 'title': 'Two', 'view_count': '20', 'region_code': 'IT'},
                 {'video_id': 'l3', 'title': 'Three', 'view_count': '10', 'region_code': 'DE'}]
        json.dump(items, open(os.path.join(old, 'videos_metadata.json'), 'w'))
        json.dump({'seo_title': 'S1', 'seo_description': 'D1'}, open(os.path.join(old, 'sumarios_seo', 'l1.json'), 'w'))
        json.dump({'seo_title': 'S3', 'seo_description': 'D3', 'fallback': True},
                  open(os.path.join(old, 'sumarios_seo', 'l3.json'), 'w'))
        self.assertEqual(pipeline.import_legacy(self.conn, self.config, old, 30), 3)
        langs = dict(self.q('SELECT video_id, lang FROM videos'))
        self.assertEqual(langs, {'l1': 'es', 'l2': 'en', 'l3': 'de'})
        self.assertEqual([tuple(r) for r in self.q('SELECT video_id, source FROM summaries')], [('l1', 'legacy')])
        self.assertEqual(len(self.q('SELECT * FROM featured')), 3)
        self.assertEqual(self.q("SELECT text FROM transcripts")[0][0], 'hola')

    def test_collect_without_key_fails(self):
        old = os.environ.pop('YOUTUBE_API_KEY', None)
        orig = pipeline.api_key
        pipeline.api_key = lambda: None
        try:
            self.assertEqual(pipeline.main(['collect']), 1)
        finally:
            pipeline.api_key = orig
            if old:
                os.environ['YOUTUBE_API_KEY'] = old


if __name__ == '__main__':
    unittest.main()
