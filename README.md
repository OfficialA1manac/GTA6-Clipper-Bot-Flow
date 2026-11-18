# GTA6-Clipper-Bot-Flow (all-GitHub, free, 24/7)
Public repo = unlimited free Actions minutes. Secrets stay private.

| Workflow | When | Job |
|---|---|---|
| harvest.yml | every 6h | grows `creators/registry.csv` toward 50,000 unique creators (YouTube trending + GTA searches, Twitch live streams). One row per creator NAME across all platforms. |
| scan.yml | every 10 min | content search flow: RSS-polls a rotating batch of permitted creators + (every 30 min) searches "GTA 6" newest on YouTube, keeps only permitted channels; dispatches ONE video to the worker |
| clip.yml | on dispatch | download -> loudest moments -> 9:16 -> post YouTube + TikTok (max 5/day) |
| overseer.yml | hourly | checks posted videos still live, pauses sources after 2 removals/30d, updates the "Pipeline status" issue with links clipped in the last 24h |

## Setup
Secrets (Settings -> Secrets and variables -> Actions):
YT_API_KEY, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (scopes youtube.upload + youtube.readonly),
TT_CLIENT_KEY, TT_CLIENT_SECRET, TT_REFRESH_TOKEN (scope video.publish), TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET.
Then Actions -> enable workflows -> run `harvest`, then `scan`.

## The creator list
`creators/registry.csv` fills over days/weeks (each run adds whoever is trending or live). Fill the `permission` column for creators who agreed; the clipper only uses rows with a permission note.
Platforms keep unaudited API apps private until their audit passes.
