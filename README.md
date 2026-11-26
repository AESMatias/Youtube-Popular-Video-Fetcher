# RapidMov: popular YouTube videos by language

A static site built with [Astro](https://astro.build) that lists the most popular YouTube videos in several languages, each with a short summary. Live at <https://videos.rapidmov.online>.

## How it works

```
pipeline.py collect  ->  data/videos.db (SQLite, local)  ->  src/data/site.json  ->  astro build  ->  nginx
                                 |
                          archive/*.jsonl(.gz)  (committed: the data lives in git)
```

- `pipeline.py` reads YouTube's trending charts through the YouTube Data API, keeps each video's language and stores everything in SQLite.
- Summaries are written either by a coding agent following [`agent/AGENT.md`](agent/AGENT.md) (free, run by hand), or by an LLM API if you turn it on (see below).
- `export-site` writes `src/data/site.json`, the only file the site reads.
- `backup` writes the database to `archive/`, which is committed. Any machine can rebuild the database from git with `restore`.
- The server only builds and serves static files: nginx in Docker, a few MB of RAM.

Each video is stored once. When it trends again its numbers are updated and it is shown again, but its transcript and summary are never fetched or written twice.

## Requirements

- Python 3.9+ (standard library only, `youtube-transcript-api` is optional for transcripts)
- Node.js 22+ and npm
- A YouTube Data API key
- For the server: Linux with Docker and the compose plugin, `git`, `curl` and `flock`

Works on Linux, macOS and Windows (WSL for the shell scripts).

## Setup

```bash
git clone https://github.com/AESMatias/Youtube-Popular-Video-Fetcher.git
cd Youtube-Popular-Video-Fetcher
npm ci
pip install -r requirements.txt   # optional, for transcripts
echo "YOUTUBE_API_KEY=your-key" > .env
python3 pipeline.py restore       # builds data/videos.db from archive/
npm run dev
```

`config.json` holds the languages, the countries used for each one, how many videos per language (`top`, 30 by default) and how many countries are read per run (`regions_per_lang`, 3 by default, rotating through the list).

## Updating the data

```bash
python3 pipeline.py restore            # sync the local db with archive/
python3 pipeline.py collect            # --top 30 --regions-per-lang 3 --langs es,en
python3 pipeline.py agent-export       # agent/inbox.md: videos that still need a summary
# an agent reads agent/inbox.md and writes agent/outbox.json (see agent/AGENT.md)
python3 pipeline.py agent-import
python3 pipeline.py export-site
python3 pipeline.py backup
git add archive src/data/site.json && git commit -m "Update videos" && git push
```

`python3 pipeline.py update` runs all of it in one go. Without an LLM enabled it stops at the agent step and tells you how many videos are waiting.

Other commands: `stats` (counts and pending summaries), `prune` (drops transcripts and comments of summarized videos and compacts the db; it also runs on every import).

## Summaries with an LLM API (off by default)

The APIs cost money, so nothing calls them unless you ask for it. Supported providers, one module each in [`providers/`](providers):

| Provider | `--provider` | Key | Model override |
|---|---|---|---|
| OpenAI | `openai` | `OPENAI_API_KEY` | `OPENAI_MODEL` |
| Google Gemini | `gemini` | `GEMINI_API_KEY` | `GEMINI_MODEL` |
| Anthropic Claude | `claude` | `ANTHROPIC_API_KEY` | `CLAUDE_MODEL` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | `DEEPSEEK_MODEL` |
| xAI Grok | `grok` | `XAI_API_KEY` | `GROK_MODEL` |

```bash
python3 pipeline.py summarize --provider gemini --dry-run   # shows the prompt, no request
python3 pipeline.py summarize --provider gemini --limit 30
```

To make `update` use it automatically, set `"llm": {"enabled": true, "provider": "gemini"}` in `config.json`. Default models are cheap ones; check each provider's docs for current names.

## Storage and growth

Thumbnails are not stored: the site loads them from YouTube (`i.ytimg.com`), so they cost 0 bytes. What grows is the archive and the weekly `site.json`.

Measured on real data (615 videos):

| Item | Raw | Compressed |
|---|---|---|
| One video in the archive (metadata + summary) | ~1.9 KB | ~0.6 KB |
| One run (up to 30 videos x 8 languages = 240 new videos) | ~450 KB | ~150 KB |
| `site.json` (rewritten every run) | ~585 KB | ~196 KB |

Git stores every file compressed, so each run adds about **0.35 MB** to the repository history.

| Runs | 1 month | 3 months | 6 months | 1 year |
|---|---|---|---|---|
| Weekly | ~1.5 MB | ~4.5 MB | ~9 MB | ~18 MB |
| Twice a week | ~3 MB | ~9 MB | ~18 MB | ~36 MB |

GitHub recommends keeping repositories under 1 GB and blocks single files over 100 MB, so this fits for decades. These are upper bounds: videos that keep trending are not stored again.

Closed months are gzipped (`archive/2026-11.jsonl` becomes `2026-11.jsonl.gz` once the month is over), about 3x smaller. `restore` reads both formats, so nothing needs to be unpacked by hand. The current month stays as plain text because git diffs it well.

The local SQLite file stays small too: once a summary exists, the transcript and comments used to write it are dropped (about 35% smaller on real data).

## Deploying

The site is plain static files. On the server:

```bash
git clone https://github.com/AESMatias/Youtube-Popular-Video-Fetcher.git
cd Youtube-Popular-Video-Fetcher
./deploy.sh
```

`deploy.sh` pulls, runs `npm ci` only when the lockfile changed, builds into `dist.new/` and swaps it in only if the build passes, then starts nginx (`docker-compose.yml`, container `videos-web`) on `127.0.0.1:50000`. Point your reverse proxy or Cloudflare Tunnel at that address.

It exits early when there are no new commits, so it is cheap to run from cron:

```
0 * * * * /path/to/repo/deploy.sh >> /path/to/repo/deploy.log 2>&1
```

`./deploy.sh --force` rebuilds anyway, `BRANCH=name ./deploy.sh` deploys another branch.

The container runs read-only with a 32 MB memory limit and capped logs.

### Troubleshooting a 502

A 502 from Cloudflare means the tunnel is up but nothing answers on `127.0.0.1:50000`.

```bash
docker ps                           # is videos-web "Up (healthy)"?
docker logs videos-web
curl -I http://127.0.0.1:50000/
sudo systemctl status cloudflared
./deploy.sh --force
```

## Tests

```bash
npm test
```

Python standard library only. CI (`.github/workflows/ci.yml`) builds the site and runs the tests on Python 3.9 and 3.12.

## License

MIT, see [LICENSE](LICENSE). Not affiliated with YouTube or Google.
