#!/usr/bin/env python3
"""Collect popular YouTube videos into SQLite and export the site data.

Run `python3 pipeline.py -h` for commands. See agent/AGENT.md for the weekly routine.
"""
import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, 'config.json')
API_BASE = 'https://www.googleapis.com/youtube/v3/'
QUOTA_REASONS = ('quotaExceeded', 'dailyLimitExceeded')
STORED_TRANSCRIPT_CHARS = 8000

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY, lang TEXT, title TEXT, channel_title TEXT, published_at TEXT,
    description TEXT, duration TEXT, thumbnail_url TEXT, view_count INTEGER, like_count INTEGER,
    comment_count INTEGER, first_seen TEXT, last_seen TEXT, times_featured INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS transcripts (video_id TEXT PRIMARY KEY, text TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS comments (video_id TEXT PRIMARY KEY, json TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS summaries (
    video_id TEXT PRIMARY KEY, seo_title TEXT, seo_description TEXT, source TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, params TEXT);
CREATE TABLE IF NOT EXISTS featured (
    run_id INTEGER, lang TEXT, rank INTEGER, video_id TEXT, PRIMARY KEY (run_id, lang, video_id));
CREATE TABLE IF NOT EXISTS region_usage (region TEXT PRIMARY KEY, last_used TEXT);
"""

# Latest featured row set per language, used by agent-export, export-site and stats.
LATEST_FEATURED = """
SELECT f.lang, f.rank, f.video_id FROM featured f
JOIN (SELECT lang, MAX(run_id) AS run_id FROM featured GROUP BY lang) m
  ON m.lang = f.lang AND m.run_id = f.run_id
"""


class ApiError(Exception):
    def __init__(self, status, reason):
        Exception.__init__(self, '%s %s' % (status, reason))
        self.status = status
        self.reason = reason

    @property
    def quota(self):
        return self.reason in QUOTA_REASONS


def now(precise=False):
    fmt = '%Y-%m-%dT%H:%M:%S.%fZ' if precise else '%Y-%m-%dT%H:%M:%SZ'
    return datetime.datetime.utcnow().strftime(fmt)


def warn(msg):
    print('warning: ' + msg, file=sys.stderr)


def load_config():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)


def connect():
    path = os.environ.get('YTP_DB') or os.path.join(ROOT, 'data', 'videos.db')
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def api_key():
    key = os.environ.get('YOUTUBE_API_KEY')
    env_path = os.path.join(ROOT, '.env')
    if not key and os.path.exists(env_path):
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                name, sep, value = line.strip().partition('=')
                if sep and name.strip() == 'YOUTUBE_API_KEY':
                    key = value.strip().strip('"\'')
    return key


def http_get(url):
    """Return parsed JSON or raise ApiError. Tests replace this function."""
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        reason = e.reason
        try:
            reason = json.loads(e.read().decode('utf-8'))['error']['errors'][0]['reason']
        except Exception:
            pass
        raise ApiError(e.code, reason)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ApiError(0, str(e))


def api(endpoint, key, **params):
    params['key'] = key
    return http_get(API_BASE + endpoint + '?' + urllib.parse.urlencode(params))


RETRY = object()


def fetch_transcript(video_id, lang):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        if not getattr(fetch_transcript, 'warned', False):
            warn('youtube-transcript-api not installed, skipping transcripts (pip3 install -r requirements.txt)')
            fetch_transcript.warned = True
        return None
    try:
        import requests

        class TimeoutSession(requests.Session):
            # the library sets no timeout, so a stalled connection would hang the run
            def request(self, *args, **kwargs):
                kwargs.setdefault('timeout', 20)
                return requests.Session.request(self, *args, **kwargs)

        langs = [lang] if lang == 'en' else [lang, 'en']
        transcript = YouTubeTranscriptApi(http_client=TimeoutSession()).fetch(video_id, languages=langs)
        return ' '.join(s.text for s in transcript)
    except Exception as e:
        name = type(e).__name__
        print('  no transcript for %s: %s' % (video_id, name))
        # disabled or missing is final; a block or network error should be retried next run
        return None if name in ('TranscriptsDisabled', 'NoTranscriptFound', 'VideoUnavailable') else RETRY


def fetch_comments(video_id, key, n):
    data = api('commentThreads', key, part='snippet', videoId=video_id, maxResults=max(1, min(n, 100)),
               order='relevance', textFormat='plainText')
    return [i['snippet']['topLevelComment']['snippet']['textDisplay'] for i in data.get('items', [])][:n]


def region_langs(config):
    out = {}
    for code, lang in config['languages'].items():
        for region in lang['regions']:
            out.setdefault(region, []).append(code)
    return out


def matches_lang(item, lang, region, regions_map):
    sn = item.get('snippet', {})
    audio = sn.get('defaultAudioLanguage') or sn.get('defaultLanguage')
    if audio:
        return audio.lower().startswith(lang)
    # no language info: only trust regions that belong to a single language
    return len(regions_map.get(region, [])) == 1


def pick_regions(conn, regions, n):
    used = dict(conn.execute('SELECT region, last_used FROM region_usage').fetchall())
    order = sorted(range(len(regions)), key=lambda i: (used.get(regions[i]) or '', i))
    return [regions[i] for i in order[:n]]


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def thumbnail(video_id, thumbs):
    for size in ('medium', 'high', 'default'):
        if (thumbs or {}).get(size, {}).get('url'):
            return thumbs[size]['url']
    return 'https://i.ytimg.com/vi/%s/mqdefault.jpg' % video_id


def upsert_video(conn, v, seen_at):
    conn.execute("""
        INSERT INTO videos (video_id, lang, title, channel_title, published_at, description, duration,
            thumbnail_url, view_count, like_count, comment_count, first_seen, last_seen, times_featured)
        VALUES (:video_id, :lang, :title, :channel_title, :published_at, :description, :duration,
            :thumbnail_url, :view_count, :like_count, :comment_count, :seen, :seen, 1)
        ON CONFLICT(video_id) DO UPDATE SET title = excluded.title, description = excluded.description,
            thumbnail_url = excluded.thumbnail_url, view_count = excluded.view_count,
            like_count = excluded.like_count, comment_count = excluded.comment_count,
            last_seen = excluded.last_seen, times_featured = times_featured + 1
    """, dict(v, seen=seen_at))


def video_row(item, lang):
    sn, st = item.get('snippet', {}), item.get('statistics', {})
    return {
        'video_id': item['id'], 'lang': lang, 'title': sn.get('title'),
        'channel_title': sn.get('channelTitle'), 'published_at': sn.get('publishedAt'),
        'description': sn.get('description'), 'duration': item.get('contentDetails', {}).get('duration'),
        'thumbnail_url': thumbnail(item['id'], sn.get('thumbnails')),
        'view_count': to_int(st.get('viewCount')), 'like_count': to_int(st.get('likeCount')),
        'comment_count': to_int(st.get('commentCount')),
    }


def fetch_extras(conn, video_ids, lang, key, n_comments, transcripts):
    """Fetch transcript and comments for videos that don't have them yet. Returns True on quota stop."""
    for vid in video_ids:
        try:
            if transcripts and not conn.execute('SELECT 1 FROM transcripts WHERE video_id=?', (vid,)).fetchone():
                text = fetch_transcript(vid, lang)
                if text is not RETRY:
                    conn.execute('INSERT INTO transcripts VALUES (?, ?, ?)',
                                 (vid, text[:STORED_TRANSCRIPT_CHARS] if text else None, now()))
            if not conn.execute('SELECT 1 FROM comments WHERE video_id=?', (vid,)).fetchone():
                try:
                    comments = fetch_comments(vid, key, n_comments)
                except ApiError as e:
                    if e.quota:
                        raise
                    if e.reason != 'commentsDisabled':
                        warn('comments for %s: %s' % (vid, e))
                        continue
                    comments = []
                conn.execute('INSERT INTO comments VALUES (?, ?, ?)',
                             (vid, json.dumps(comments, ensure_ascii=False), now()))
        except ApiError as e:
            if e.quota:
                return True
            warn('%s: %s' % (vid, e))
        except Exception as e:
            warn('%s: %s' % (vid, e))
        finally:
            conn.commit()
    return False


def collect(conn, config, key, top, regions_per_lang, langs, transcripts=True):
    regions_map = region_langs(config)
    n_comments = config['defaults']['comments']
    params = {'top': top, 'regions_per_lang': regions_per_lang, 'langs': langs, 'transcripts': transcripts}
    run_id = conn.execute('INSERT INTO runs (started_at, params) VALUES (?, ?)',
                          (now(), json.dumps(params))).lastrowid
    conn.commit()
    stopped = False
    for lang in langs:
        candidates = {}
        regions = pick_regions(conn, config['languages'][lang]['regions'], regions_per_lang)
        for region in regions:
            try:
                items = api('videos', key, part='snippet,statistics,contentDetails', chart='mostPopular',
                            regionCode=region, maxResults=50).get('items', [])
            except ApiError as e:
                if e.quota:
                    stopped = True
                    break
                warn('%s/%s: %s' % (lang, region, e))
                continue
            for item in items:
                if matches_lang(item, lang, region, regions_map):
                    candidates.setdefault(item['id'], item)
            conn.execute('INSERT OR REPLACE INTO region_usage VALUES (?, ?)', (region, now(precise=True)))
            conn.commit()

        ranked = sorted(candidates.values(), key=lambda i: to_int(i.get('statistics', {}).get('viewCount')) or 0,
                        reverse=True)[:top]
        seen_at = now()
        for rank, item in enumerate(ranked, 1):
            upsert_video(conn, video_row(item, lang), seen_at)
            conn.execute('INSERT OR IGNORE INTO featured VALUES (?, ?, ?, ?)', (run_id, lang, rank, item['id']))
        conn.commit()
        print('%s: %d featured from %s' % (lang, len(ranked), ','.join(regions)))
        if not stopped and ranked:
            stopped = fetch_extras(conn, [i['id'] for i in ranked], lang, key, n_comments, transcripts)
        if stopped:
            warn('YouTube API quota exceeded, stopping early. Everything collected so far is saved.')
            break
    conn.execute('UPDATE runs SET finished_at=? WHERE id=?', (now(), run_id))
    conn.commit()
    return run_id


def squash(text, limit):
    text = re.sub(r'\s+', ' ', text or '').strip()
    return text if len(text) <= limit else text[:limit].rsplit(' ', 1)[0] + '...'


def pending(conn, limit=-1):
    return conn.execute("""
        SELECT v.*, t.text AS transcript, c.json AS comments FROM (%s) lf
        JOIN videos v ON v.video_id = lf.video_id
        LEFT JOIN summaries s ON s.video_id = v.video_id
        LEFT JOIN transcripts t ON t.video_id = v.video_id
        LEFT JOIN comments c ON c.video_id = v.video_id
        WHERE s.video_id IS NULL ORDER BY lf.lang, lf.rank LIMIT ?
    """ % LATEST_FEATURED, (limit,)).fetchall()


def agent_export(conn, out, limit, max_chars):
    rows = pending(conn, limit)
    if not rows:
        print('Nothing pending: every featured video has a summary.')
        return 0
    lines = ['# %d videos to summarize' % len(rows),
             'Write agent/outbox.json as {"<video_id>": {"seo_title": "...", "seo_description": "..."}}. '
             'Rules are in agent/AGENT.md.', '']
    for r in rows:
        lines += ['## %s (%s)' % (r['video_id'], r['lang']),
                  'Title: ' + squash(r['title'], 200),
                  'Channel: ' + squash(r['channel_title'], 100),
                  'Description: ' + squash(r['description'], 400)]
        if r['transcript']:
            lines.append('Transcript: ' + squash(r['transcript'], max_chars))
        comments = json.loads(r['comments'] or '[]')[:10]
        if comments:
            lines.append('Comments:')
            lines += ['- ' + squash(c, 150) for c in comments]
        lines.append('')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('Exported %d videos to %s' % (len(rows), out))
    return len(rows)


def validate_summary(entry):
    if not isinstance(entry, dict):
        return None, 'not an object'
    title, desc = entry.get('seo_title'), entry.get('seo_description')
    if not isinstance(title, str) or not isinstance(desc, str) or not title.strip() or not desc.strip():
        return None, 'seo_title and seo_description must be non-empty strings'
    title, desc = title.strip(), desc.strip()
    if len(title) > 100:
        return None, 'seo_title longer than 100 chars'
    if len(desc) < 300:
        return None, 'seo_description shorter than 300 chars'
    if len(desc) > 1500:
        desc = desc[:1500].rsplit(' ', 1)[0]
    return (title, desc), None


def agent_import(conn, path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print('error: could not read %s: %s' % (path, e), file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print('error: %s must be a JSON object keyed by video_id' % path, file=sys.stderr)
        return None
    accepted, rejected = 0, []
    for vid, entry in data.items():
        if not conn.execute('SELECT 1 FROM videos WHERE video_id=?', (vid,)).fetchone():
            rejected.append((vid, 'unknown video_id'))
            continue
        value, err = validate_summary(entry)
        if err:
            rejected.append((vid, err))
            continue
        conn.execute('INSERT OR REPLACE INTO summaries VALUES (?, ?, ?, ?, ?)',
                     (vid, value[0], value[1], 'agent', now()))
        accepted += 1
    conn.commit()
    prune(conn)
    for vid, err in rejected:
        print('rejected %s: %s' % (vid, err))
    done = re.sub(r'\.json$', '', path) + '.%s.done.json' % datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')
    os.rename(path, done)
    print('Accepted %d, rejected %d. Moved %s to %s' % (accepted, len(rejected), path, done))
    return accepted, len(rejected)


def prune(conn):
    # Transcripts and comments are only needed to write the summary. Keep the rows so they
    # are never fetched again, drop the text so the db doesn't grow every week.
    n = conn.execute('UPDATE transcripts SET text=NULL WHERE text IS NOT NULL '
                     'AND video_id IN (SELECT video_id FROM summaries)').rowcount
    n += conn.execute("UPDATE comments SET json='[]' WHERE json != '[]' "
                      'AND video_id IN (SELECT video_id FROM summaries)').rowcount
    conn.commit()
    return n


def export_site(conn, config, out):
    last = conn.execute('SELECT MAX(finished_at) FROM runs').fetchone()[0]
    rows = conn.execute("""
        SELECT lf.lang, lf.rank, v.*, s.seo_title, s.seo_description FROM (%s) lf
        JOIN videos v ON v.video_id = lf.video_id
        LEFT JOIN summaries s ON s.video_id = v.video_id
        ORDER BY lf.lang, lf.rank
    """ % LATEST_FEATURED).fetchall()
    videos, counts = [], {}
    for r in rows:
        counts[r['lang']] = counts.get(r['lang'], 0) + 1
        videos.append({
            'video_id': r['video_id'], 'lang': r['lang'], 'rank': r['rank'], 'title': r['title'],
            'channel_title': r['channel_title'], 'published_at': r['published_at'],
            'view_count': r['view_count'] or 0, 'like_count': r['like_count'],
            'comment_count': r['comment_count'], 'duration': r['duration'],
            'thumbnail_url': r['thumbnail_url'],
            'youtube_url': 'https://www.youtube.com/watch?v=' + r['video_id'],
            'description': (r['description'] or '')[:5000],
            'seo_title': r['seo_title'], 'seo_description': r['seo_description'],
            'times_featured': r['times_featured'], 'first_seen': r['first_seen'],
        })
    languages = [{'code': code, 'name': lang['name'], 'count': counts[code]}
                 for code, lang in config['languages'].items() if code in counts]
    data = {'updated_at': last, 'languages': languages, 'videos': videos}
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    print('Wrote %d videos in %d languages to %s' % (len(videos), len(languages), out))
    return data


def legacy_lang(d, config, regions_map):
    for field in ('lang', 'language', 'default_audio_language', 'defaultAudioLanguage', 'default_language'):
        value = (d.get(field) or '')[:2].lower()
        if value in config['languages']:
            return value
    langs = regions_map.get(d.get('region_code') or d.get('region') or '')
    return langs[0] if langs else 'en'


def import_legacy(conn, config, folder, top):
    # shortcut: loads the whole old JSON at once, fine for a one-time import
    with open(os.path.join(folder, 'videos_metadata.json'), encoding='utf-8') as f:
        old = json.load(f)
    regions_map = region_langs(config)
    n_comments = config['defaults']['comments']
    run_id = conn.execute('INSERT INTO runs (started_at, params) VALUES (?, ?)',
                          (now(), json.dumps({'legacy': folder}))).lastrowid
    by_lang, seen, summaries = {}, set(), 0
    for d in old if isinstance(old, list) else []:
        vid = isinstance(d, dict) and d.get('video_id')
        if not vid or vid in seen:
            continue
        seen.add(vid)
        lang = legacy_lang(d, config, regions_map)
        conn.execute("""
            INSERT OR IGNORE INTO videos (video_id, lang, title, channel_title, published_at, description,
                duration, thumbnail_url, view_count, like_count, comment_count, first_seen, last_seen,
                times_featured) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (vid, lang, d.get('title'), d.get('channel_title'), d.get('published_at'), d.get('description'),
              d.get('duration'), thumbnail(vid, d.get('thumbnails')), to_int(d.get('view_count')),
              to_int(d.get('like_count')), to_int(d.get('comment_count')), now(), now()))
        if d.get('transcript'):
            conn.execute('INSERT OR IGNORE INTO transcripts VALUES (?, ?, ?)',
                         (vid, d['transcript'][:STORED_TRANSCRIPT_CHARS], now()))
        if d.get('comments'):
            conn.execute('INSERT OR IGNORE INTO comments VALUES (?, ?, ?)',
                         (vid, json.dumps(d['comments'][:n_comments], ensure_ascii=False), now()))
        try:
            with open(os.path.join(folder, 'sumarios_seo', vid + '.json'), encoding='utf-8') as f:
                s = json.load(f)
            if s.get('seo_description') and not s.get('fallback'):
                cur = conn.execute('INSERT OR IGNORE INTO summaries VALUES (?, ?, ?, ?, ?)',
                                   (vid, s.get('seo_title') or d.get('title'), s['seo_description'], 'legacy', now()))
                summaries += cur.rowcount
        except (OSError, ValueError, AttributeError):
            pass
        by_lang.setdefault(lang, []).append((to_int(d.get('view_count')) or 0, vid))
    for lang, items in by_lang.items():
        for rank, (_, vid) in enumerate(sorted(items, reverse=True)[:top], 1):
            conn.execute('INSERT INTO featured VALUES (?, ?, ?, ?)', (run_id, lang, rank, vid))
            conn.execute('UPDATE videos SET times_featured = times_featured + 1 WHERE video_id=?', (vid,))
    conn.execute('UPDATE runs SET finished_at=? WHERE id=?', (now(), run_id))
    conn.commit()
    print('Imported %d videos and %d summaries from %s' % (len(seen), summaries, folder))
    return len(seen)


def stats(conn):
    for table in ('videos', 'transcripts', 'comments', 'summaries', 'runs', 'featured', 'region_usage'):
        print('%-13s %d' % (table, conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]))
    print('%-13s %d' % ('pending', len(pending(conn))))
    run = conn.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 1').fetchone()
    if run:
        print('last run     #%d started %s finished %s %s' % (run['id'], run['started_at'],
                                                             run['finished_at'] or '(unfinished)', run['params']))


def main(argv=None):
    config = load_config()
    d = config['defaults']
    p = argparse.ArgumentParser(description='YouTube popular videos pipeline')
    sub = p.add_subparsers(dest='cmd')
    c = sub.add_parser('collect', help='fetch popular videos from the YouTube API')
    c.add_argument('--top', type=int, default=d['top'])
    c.add_argument('--regions-per-lang', type=int, default=d['regions_per_lang'])
    c.add_argument('--langs', default=','.join(config['languages']))
    c.add_argument('--no-transcripts', action='store_true')
    e = sub.add_parser('agent-export', help='write agent/inbox.md with videos missing a summary')
    e.add_argument('--limit', type=int, default=60)
    e.add_argument('--max-chars', type=int, default=d['transcript_chars'])
    e.add_argument('--out', default=os.path.join(ROOT, 'agent', 'inbox.md'))
    i = sub.add_parser('agent-import', help='load summaries from agent/outbox.json')
    i.add_argument('path', nargs='?', default=os.path.join(ROOT, 'agent', 'outbox.json'))
    s = sub.add_parser('export-site', help='write the JSON the site reads')
    s.add_argument('--out', default=os.path.join(ROOT, 'src', 'data', 'site.json'))
    l = sub.add_parser('import-legacy', help='import the old videos_metadata.json and sumarios_seo/')
    l.add_argument('dir')
    l.add_argument('--top', type=int, default=d['top'])
    sub.add_parser('stats', help='show database counts')
    sub.add_parser('prune', help='drop transcripts and comments of summarized videos, then compact the db')
    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 1

    if args.cmd == 'collect':
        key = api_key()
        if not key:
            print('error: YOUTUBE_API_KEY is not set. Export it or put YOUTUBE_API_KEY=... in .env',
                  file=sys.stderr)
            return 1
        langs = [x.strip() for x in args.langs.split(',') if x.strip()]
        unknown = [x for x in langs if x not in config['languages']]
        if unknown:
            print('error: unknown languages: %s' % ','.join(unknown), file=sys.stderr)
            return 1
        collect(connect(), config, key, args.top, args.regions_per_lang, langs, not args.no_transcripts)
    elif args.cmd == 'agent-export':
        agent_export(connect(), args.out, args.limit, args.max_chars)
    elif args.cmd == 'agent-import':
        if agent_import(connect(), args.path) is None:
            return 1
    elif args.cmd == 'export-site':
        export_site(connect(), config, args.out)
    elif args.cmd == 'import-legacy':
        import_legacy(connect(), config, args.dir, args.top)
    elif args.cmd == 'stats':
        stats(connect())
    elif args.cmd == 'prune':
        conn = connect()
        print('Cleared %d rows' % prune(conn))
        conn.execute('VACUUM')
    return 0


if __name__ == '__main__':
    sys.exit(main())
