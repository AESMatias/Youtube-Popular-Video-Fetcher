# Weekly update

You are refreshing the site data and writing the video summaries. Run everything from the repo root.

1. `python3 pipeline.py collect`
   Needs `YOUTUBE_API_KEY` in the environment or in `.env`. A quota warning is fine: what was collected is saved.
2. `python3 pipeline.py agent-export --limit 30`
   Writes `agent/inbox.md` with the featured videos that have no summary yet. If it says nothing is pending, skip to step 5.
   Keep the token budget in mind: `--limit` caps how many videos you get, `--max-chars` caps each transcript. Start small and run steps 2 to 4 again if you have budget left.
3. Read `agent/inbox.md` and write `agent/outbox.json`:

   ```json
   {
     "VIDEO_ID": {"seo_title": "...", "seo_description": "..."}
   }
   ```

   For each video:
   - Write in the video's language (the code next to the id: en, es, pt, fr, de, hi, ja, ko).
   - `seo_title`: 70 characters or less, clear and specific, no clickbait.
   - `seo_description`: 2 or 3 short paragraphs separated by `\n\n`, about 120 to 200 words (at least 300 characters).
     Say what the video is about and why people are watching it. Use the transcript and comments as context.
   - Use your own words. Do not copy the description, song lyrics or links. No intro like "Here is the summary".
   - If you don't have enough information for a video, leave it out. It will show up again next week.
4. `python3 pipeline.py agent-import`
   Check the rejected list, fix those entries in a new `agent/outbox.json` and import again if needed.
5. `python3 pipeline.py export-site`
6. `npm run build` and make sure it passes.
7. Commit `src/data/site.json` and push.

`python3 pipeline.py stats` shows table counts, pending summaries and the last run.
