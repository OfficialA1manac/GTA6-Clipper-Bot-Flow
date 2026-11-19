# SETUP (phone-friendly, in this order)

Menu names can shift slightly; follow the idea if a label differs.

## 0. Fastest first result (no keys at all)
1. Repo -> Settings -> change visibility to **Public** (free unlimited Actions minutes).
2. Actions tab -> tap **"I understand my workflows, enable them"**.
3. Upload any .mp4 into the `inbox/` folder (Add file -> Upload files).
4. Actions -> **clip** -> Run workflow -> set `inbox` to `true` -> Run.
5. When it finishes, open the run -> **Artifacts -> clips**. Those are your finished 9:16 clips + captions.

## 1. Turn on the creator list + content search (YouTube Data API key)
1. console.cloud.google.com -> new project -> APIs & Services -> Library -> enable **YouTube Data API v3**.
2. APIs & Services -> Credentials -> Create credentials -> **API key**. Copy it.
3. Repo -> Settings -> Secrets and variables -> Actions -> New repository secret: `YT_API_KEY`.

## 2. Twitch (more creators)
1. dev.twitch.tv/console -> Register Your Application (OAuth redirect `http://localhost`, category Application Integration).
2. Copy Client ID, generate a Client Secret. Add secrets `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`.

## 3. Run the harvest, then add permitted creators
Actions -> **harvest** -> Run workflow. It fills `creators/registry.csv` (grows every 6h).
For each creator who agreed, put a note in the `permission` column (edit file in the GitHub app), or add them under `sources:` in `sources.yaml`.
The scanner only clips creators with a permission note.

## 4. YouTube uploads (OAuth)
1. Same Google Cloud project -> Credentials -> Create credentials -> **OAuth client ID** -> type **Web application**; add redirect URI `https://developers.google.com/oauthplayground`.
2. Add test user = your Google account (OAuth consent screen -> Audience -> Test users).
3. Open developers.google.com/oauthplayground -> gear icon -> tick **Use your own OAuth credentials** -> paste client ID/secret.
4. Step 1: select scopes `https://www.googleapis.com/auth/youtube.upload` and `https://www.googleapis.com/auth/youtube.readonly` -> Authorize -> pick the channel.
5. Step 2: Exchange authorization code for tokens -> copy the **refresh token**.
6. Secrets: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
Note: Google keeps uploads from unaudited projects private until its API audit passes.

## 5. TikTok uploads
1. developers.tiktok.com -> create an app -> add product **Content Posting API** (Direct Post), scope `video.publish`.
2. Authorize your own TikTok account as a target user to get a refresh token (TikTok's "Login Kit" authorization flow).
3. Secrets: `TT_CLIENT_KEY`, `TT_CLIENT_SECRET`, `TT_REFRESH_TOKEN`.
Note: posts are private until TikTok approves your app's audit. Clips still come out as downloads you can post by hand.

## 6. Texts (optional)
twilio.com -> get a number -> secrets `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM` (+1...), `TWILIO_TO` (your phone).
Every new clip texts the source link + caption.

## 7. Go
Actions -> **scan** -> Run workflow once. It then runs every 10 minutes by itself.
GitHub app -> watch this repo -> the "Pipeline status" issue notifies you of alerts.
