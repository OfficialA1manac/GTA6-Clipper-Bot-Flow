# GTA6-Clipper-Bot-Flow (all-GitHub, free, 24/7)
Public repo = unlimited free Actions minutes. Secrets stay private.

| Workflow | When | Job |
|---|---|---|
| harvest.yml | every 6h | grows `creators/registry.csv` toward 50,000 unique creators (YouTube trending + GTA searches, Twitch live streams). One row per creator NAME across all platforms. |
| scan.yml | every 10 min | crawler (no API key): searches YouTube for the newest GTA 6 videos, checks permitted creators' feeds and Twitch VODs; every video found is logged to `state/leads.json` (shown in the Pipeline status issue); only permitted creators' videos are sent to the worker, one at a time |
| clip.yml | on dispatch | download -> loudest moments -> 9:16 -> post YouTube + TikTok (up to 15/day: 6 YouTube, 15 TikTok) |
| overseer.yml | hourly | checks posted videos still live, pauses sources after 2 removals/30d, updates the "Pipeline status" issue with links clipped in the last 24h |

## Setup
Secrets (Settings -> Secrets and variables -> Actions):
YT_API_KEY, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (scopes youtube.upload + youtube.readonly),
TT_CLIENT_KEY, TT_CLIENT_SECRET, TT_REFRESH_TOKEN (scope video.publish), TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET,
Texts (optional, Twilio): TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, TWILIO_TO. Each new clip sends you its source link by SMS.
Then Actions -> enable workflows -> run `harvest`, then `scan`.

## The creator list
`creators/registry.csv` fills over days/weeks (each run adds whoever is trending or live). Fill the `permission` column for creators who agreed; the clipper only uses rows with a permission note.
Platforms keep unaudited API apps private until their audit passes.

## Retention edit (fx.py)
Every clip gets: opening hook text + "WAIT FOR THE END", zoom punch-ins on the loudest moments, synthesized sound effects (boom, honk, ding, womp, pop, whoosh; generated locally, no copyright), red reaction text, word-by-word captions (faster-whisper, profanity masked), and a progress bar that fills across the clip.

## Run without GitHub Actions (serve.py)
`python serve.py` runs everything in one loop (scan every 10 min, clip, upload, harvest every 6h, hourly status in `out/status.md`). Put your keys in a `.env` file next to it (`YT_API_KEY=...`, one per line, same names as the GitHub secrets).
- Any free always-on machine works: Oracle Cloud Always Free VM, an old PC, or Termux on Android (`pkg install python ffmpeg git`, then `pip install -r requirements.txt`).
- Docker: `docker build -t gta6 . && docker run -d --restart always --env-file .env -v $PWD/state:/app/state -v $PWD/out:/app/out gta6`
- Text alerts via Twilio work the same; without Twilio read `out/status.md`.

## Phone alerts
Set `DISCORD_WEBHOOK` (Discord server > channel settings > Integrations > Webhooks > New > Copy URL). Each new clip arrives in Discord with the finished video attached (if under 24 MB), the source link and a caption to paste. Twilio SMS is optional. `serve.py` scans every 2 minutes by default (`SCAN_EVERY=120`); GitHub Actions cron cannot go below 5 minutes.
