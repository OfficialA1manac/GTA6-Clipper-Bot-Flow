# CONTEXT
- Goal: automated GTA 6 clip pipeline (TikTok + YT Shorts) for per-view campaign income.
- GTA 6 launches 2026-11-19 (PS5/Xbox).
- Design decision: allowlist-only sources (permission field required). No scraping of unpermissioned content.
- State: clipper.py render stage tested (1080x1920, 40s). Discovery/download/upload untested (workspace network allowlist).
- Open: user adds sources / Content Rewards campaign, YT secrets, API audit.
- Policy filter: BLOCKED regex in clipper.py skips leak/spoiler/ending/cutscene titles (Rockstar policy). Max ~3-6 posts/day.
- Nov 18: skip_title_words now config-driven (leaks only); 5 posts/day. User wants unpermissioned posting + takedown re-edit/repost: declined that part (evasion).
- Nov 18: all-GitHub architecture: scan.yml / clip.yml / overseer.yml. State in state/*.json (one writer each). Overseer pauses sources after 2 removals/30d. Takedown re-edit/repost loop NOT built (evasion). TikTok post via official API (private until audit).
- Nov 18: new repo GTA6-Clipper-Bot-Flow. harvest.py builds creators/registry.csv (dedupe by normalized name across platforms). scan = RSS rotation over permitted registry rows + 30-min YouTube search pass. Old repo gta6-clipper-bot: user must delete (no delete access).
