#!/usr/bin/env python3
"""Grows creators/registry.csv toward 50,000 unique creators (one row per creator NAME across all platforms).

Env (use either or both):
  YT_API_KEY                         YouTube Data API v3 key (free)
  TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET   free app at dev.twitch.tv
Each run adds whoever is currently trending or live; the list fills over days and weeks.
A creator's `permission` stays blank until you fill it in; the clipper only uses rows with a permission.
"""
import csv, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

REG = Path(__file__).parent / "creators" / "registry.csv"
FIELDS = ["key", "name", "platforms", "yt_channel_id", "twitch_login", "reach", "permission", "first_seen"]
REGIONS = ("US GB CA AU IN BR MX ES FR DE IT NL PL TR RU JP KR ID PH TH VN SA AE EG ZA NG KE AR CL CO PE VE "
           "SE NO DK FI PT GR RO UA CZ HU AT CH BE IE NZ SG MY HK TW PK BD LK IL MA DZ TN GH BG HR RS SK SI LT "
           "LV EE IS LU JO KW QA OM BH LB UY EC BO PY DO CR PA GT").split()
GTA_QUERIES = ["GTA 6", "GTA VI gameplay", "GTA 6 funny moments", "GTA 6 reaction", "GTA 6 stream",
               "GTA 6 roleplay", "GTA 6 online", "Grand Theft Auto VI"]
MIN_YT_SUBS, MIN_TWITCH_VIEWERS = 10_000, 25


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def load():
    if not REG.exists():
        return {}
    with REG.open(encoding="utf-8", newline="") as f:
        return {r["key"]: r for r in csv.DictReader(f)}


def save(reg):
    REG.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(reg.values(), key=lambda r: -int(float(r.get("reach") or 0)))
    with REG.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def add(reg, name, platform, reach, yt_id="", twitch=""):
    """One row per normalized name. Same name on another platform merges into the existing row."""
    k = norm(name)
    if not k:
        return False
    r = reg.get(k)
    if r is None:
        reg[k] = dict(key=k, name=name.strip(), platforms=platform, yt_channel_id=yt_id, twitch_login=twitch,
                      reach=int(reach), permission="", first_seen=time.strftime("%Y-%m-%d"))
        return True
    r["platforms"] = "|".join(sorted(set(r["platforms"].split("|")) | {platform}))
    r["yt_channel_id"] = r["yt_channel_id"] or yt_id
    r["twitch_login"] = r["twitch_login"] or twitch
    r["reach"] = max(int(float(r["reach"] or 0)), int(reach))
    return False


# ---------- YouTube ----------
def yt(path, **p):
    p["key"] = os.environ["YT_API_KEY"]
    url = f"https://www.googleapis.com/youtube/v3/{path}?{urllib.parse.urlencode(p)}"
    return json.load(urllib.request.urlopen(url, timeout=30))


def harvest_youtube(reg):
    ids = {}
    for region in REGIONS:                       # 1 quota unit per call
        for cat in ("20", None):                 # gaming chart + overall chart
            tok = None
            for _ in range(4):
                p = dict(part="snippet", chart="mostPopular", regionCode=region, maxResults=50)
                if cat:
                    p["videoCategoryId"] = cat
                if tok:
                    p["pageToken"] = tok
                try:
                    r = yt("videos", **p)
                except urllib.error.HTTPError:
                    break
                for it in r.get("items", []):
                    ids[it["snippet"]["channelId"]] = 1
                tok = r.get("nextPageToken")
                if not tok:
                    break
    for q in GTA_QUERIES:                        # 100 quota units per call
        try:
            r = yt("search", part="snippet", q=q, type="video", order="date", maxResults=50)
        except urllib.error.HTTPError:
            break
        for it in r.get("items", []):
            ids[it["snippet"]["channelId"]] = 1
    have = {r["yt_channel_id"] for r in reg.values() if r["yt_channel_id"]}
    todo = [c for c in ids if c not in have]
    new = 0
    for i in range(0, len(todo), 50):
        for ch in yt("channels", part="snippet,statistics", id=",".join(todo[i:i + 50])).get("items", []):
            subs = int(ch["statistics"].get("subscriberCount", 0))
            if subs >= MIN_YT_SUBS:
                new += add(reg, ch["snippet"]["title"], "youtube", subs, yt_id=ch["id"])
    log(f"youtube: {len(ids)} channels seen, {new} new")


# ---------- Twitch ----------
def harvest_twitch(reg):
    tok = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://id.twitch.tv/oauth2/token", method="POST", data=urllib.parse.urlencode({
            "client_id": os.environ["TWITCH_CLIENT_ID"], "client_secret": os.environ["TWITCH_CLIENT_SECRET"],
            "grant_type": "client_credentials"}).encode())))["access_token"]
    hdr = {"Client-Id": os.environ["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {tok}"}

    def tw(path, **p):
        url = f"https://api.twitch.tv/helix/{path}?{urllib.parse.urlencode(p)}"
        return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=30))

    new, seen = 0, 0
    gta = tw("games", name="Grand Theft Auto VI").get("data", [])
    feeds = [dict(first=100)] + ([dict(first=100, game_id=gta[0]["id"])] if gta else [])
    for base in feeds:
        after = None
        for _ in range(40):                      # up to 4,000 live streams per feed
            p = dict(base, **({"after": after} if after else {}))
            r = tw("streams", **p)
            for s in r.get("data", []):
                seen += 1
                if s["viewer_count"] >= MIN_TWITCH_VIEWERS:
                    new += add(reg, s["user_name"], "twitch", s["viewer_count"], twitch=s["user_login"])
            after = r.get("pagination", {}).get("cursor")
            if not after:
                break
    log(f"twitch: {seen} live streams seen, {new} new")


def load_seed(reg):
    f = REG.parent / "seed.txt"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                add(reg, line.strip(), "seed", 0)


def resolve_seeds(reg, limit=20):
    """Find the YouTube channel id of seed names (100 quota units each)."""
    n = 0
    for r in reg.values():
        if n >= limit:
            break
        if r["platforms"] == "seed" and not r["yt_channel_id"]:
            n += 1
            try:
                it = yt("search", part="snippet", q=r["name"], type="channel", maxResults=1).get("items", [])
            except urllib.error.HTTPError:
                break
            if it:
                r["yt_channel_id"] = it[0]["snippet"]["channelId"]
                r["platforms"] = "seed|youtube"
    log(f"seeds resolved this run: {n}")


def main():
    reg = load()
    before = len(reg)
    load_seed(reg)
    if os.environ.get("YT_API_KEY"):
        resolve_seeds(reg)
        harvest_youtube(reg)
    if os.environ.get("TWITCH_CLIENT_ID") and os.environ.get("TWITCH_CLIENT_SECRET"):
        harvest_twitch(reg)
    save(reg)
    log(f"registry: {len(reg)} unique creators (+{len(reg) - before})")


if __name__ == "__main__":
    main()
