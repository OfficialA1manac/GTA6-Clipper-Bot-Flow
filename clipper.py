#!/usr/bin/env python3
"""GTA 6 clipper. Three roles, one file:
  scan    (every 10 min)  find ONE new GTA 6 video from your sources -> prints job JSON
  run     (worker)        download -> loudest moments -> 9:16 -> post YouTube + TikTok
  check   (overseer)      verify posted videos still live; pause sources with repeated removals; print report
  render  (local test)
"""
import argparse, csv, html, json, os, re, shutil, subprocess, sys, textwrap, time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import urllib.request, xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
OUT = ROOT / "out"
INBOX = ROOT / "inbox"
SD = Path(os.environ.get("CLIPPER_STATE", ROOT / "state"))
KEYWORDS = re.compile(r"gta\s*(6|vi)\b|grand theft auto\s*(6|vi)\b|leonida", re.I)
ATOM, YTNS = "{http://www.w3.org/2005/Atom}", "{http://www.youtube.com/xml/schemas/2015}"
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"]
DAY = 86400


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def sload(name, default):
    p = SD / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else default


def ssave(name, data):
    SD.mkdir(parents=True, exist_ok=True)
    (SD / f"{name}.json").write_text(json.dumps(data, indent=1))


def paused_channels():
    now = time.time()
    return {c for c, until in sload("health", {}).get("paused", {}).items() if until > now}


# ---------- scan ----------
def blocked_re(s):
    words = s.get("skip_title_words") or []
    return re.compile("|".join(re.escape(w) for w in words), re.I) if words else None


def registry_sources():
    p = ROOT / "creators" / "registry.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as f:
        return [{"name": r["name"], "channel_id": r["yt_channel_id"], "permission": r["permission"]}
                for r in csv.DictReader(f) if (r.get("permission") or "").strip() and r.get("yt_channel_id")]


def permitted_sources(cfg):
    out, ids = [], set()
    for src in (cfg.get("sources") or []) + registry_sources():
        if not str(src.get("permission", "")).strip():
            log(f"SKIP {src.get('name')}: no 'permission' recorded"); continue
        if src["channel_id"] in ids:
            continue
        ids.add(src["channel_id"]); out.append(src)
    return out


def _feed(src):
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={src['channel_id']}"
    try:
        return src, urllib.request.urlopen(url, timeout=20).read()
    except Exception as e:
        log(f"feed fail {src['name']}: {e}")
        return src, None


def discover(cfg, seen, paused, cursor=0, batch=300):
    """RSS-poll a rotating batch of permitted sources (uses no API quota). Returns (jobs, next_cursor)."""
    s, jobs = cfg["settings"], []
    cutoff = time.time() - s["max_age_hours"] * 3600
    blocked = blocked_re(s)
    srcs = [x for x in permitted_sources(cfg) if x["name"] not in paused]
    if not srcs:
        return jobs, 0
    start = cursor % len(srcs)
    chunk = (srcs[start:] + srcs[:start])[:batch]
    with ThreadPoolExecutor(16) as ex:
        results = list(ex.map(_feed, chunk))
    for src, xml in results:
        if not xml:
            continue
        for e in ET.fromstring(xml).iter(ATOM + "entry"):
            vid = e.findtext(YTNS + "videoId")
            title = e.findtext(ATOM + "title") or ""
            pub = time.mktime(time.strptime(e.findtext(ATOM + "published")[:19], "%Y-%m-%dT%H:%M:%S"))
            if vid in seen or pub < cutoff or not KEYWORDS.search(title):
                continue
            if blocked and blocked.search(title):
                log(f"SKIP (skip_title_words): {title}"); continue
            jobs.append(dict(id=vid, title=title, channel=src["name"], pub=pub,
                             url=f"https://www.youtube.com/watch?v={vid}", path=None))
    return jobs, (start + len(chunk)) % len(srcs)


def search_jobs(cfg, srcs, seen, paused):
    """Content search flow: newest 'GTA 6' videos across YouTube, kept only if the channel is permitted.
    Every 30 min (100 quota units per call)."""
    key = os.environ.get("YT_API_KEY")
    if not key or int(time.time() // 600) % 3:
        return []
    byid = {x["channel_id"]: x for x in srcs if x["name"] not in paused}
    if not byid:
        return []
    blocked = blocked_re(cfg["settings"])
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3 * 3600))
    q = urllib.parse.urlencode(dict(part="snippet", q="GTA 6", type="video", order="date", maxResults=50,
                                    publishedAfter=since, key=key))
    try:
        data = json.load(urllib.request.urlopen(f"https://www.googleapis.com/youtube/v3/search?{q}", timeout=30))
    except Exception as e:
        log(f"search fail: {e}"); return []
    jobs = []
    for it in data.get("items", []):
        cid, vid = it["snippet"]["channelId"], it["id"].get("videoId")
        title = html.unescape(it["snippet"]["title"])
        if not vid or cid not in byid or vid in seen or not KEYWORDS.search(title):
            continue
        if blocked and blocked.search(title):
            continue
        jobs.append(dict(id=vid, title=title, channel=byid[cid]["name"], pub=time.time(),
                         url=f"https://www.youtube.com/watch?v={vid}", path=None))
    return jobs


def scan(cfg):
    st = sload("seen", {"seen": [], "cursor": 0})
    seen, paused = set(st["seen"]), paused_channels()
    jobs, st["cursor"] = discover(cfg, seen, paused, st.get("cursor", 0))
    jobs += search_jobs(cfg, permitted_sources(cfg), seen, paused)
    uniq = {j["id"]: j for j in jobs}
    jobs = sorted(uniq.values(), key=lambda j: -j["pub"])
    if jobs:
        j = jobs[0]  # one per scan; worker queue holds one at a time
        st["seen"] = (st["seen"] + [j["id"]])[-3000:]
        print(json.dumps({"url": j["url"], "channel": j["channel"], "title": j["title"]}))
    ssave("seen", st)


def inbox_jobs():
    INBOX.mkdir(exist_ok=True)
    return [dict(id=f"inbox-{p.stem}", title=p.stem.replace("_", " "), channel="inbox", pub=time.time(),
                 url="", path=p) for p in sorted(INBOX.glob("*.mp4"))]


def url_job(url, channel, title):
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url)
    if not m:
        raise SystemExit(f"bad YouTube url: {url}")
    return dict(id=m.group(1), title=title or "GTA 6", channel=channel or "manual", pub=time.time(),
                url=f"https://www.youtube.com/watch?v={m.group(1)}", path=None)


def download(job, max_min):
    dest = OUT / "raw" / f"{job['id']}.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["yt-dlp", "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4",
           "--match-filter", f"duration < {max_min * 60}", "--no-playlist", "-o", str(dest), job["url"]]
    subprocess.run(cmd, check=True)
    if not dest.exists():
        raise RuntimeError("download filtered out (too long) or failed")
    return dest


# ---------- highlights + render ----------
def energy(path):
    import numpy as np
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000",
                        "-f", "s16le", "-"], capture_output=True, check=True)
    a = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32)
    n = len(a) // 8000
    return np.sqrt((a[: n * 8000].reshape(n, 8000) ** 2).mean(axis=1))


def pick(e, count, length):
    import numpy as np
    if len(e) <= length:
        return [0]
    score = np.convolve(e, np.ones(length) / length, mode="valid") / (np.median(e) + 1e-6)
    out = []
    for _ in range(count):
        i = int(score.argmax())
        if score[i] <= 0:
            break
        out.append(max(0, i - 3))
        score[max(0, i - length): i + length] = -1
    return sorted(out)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def render(src, start, length, dest, hook=""):
    dest.parent.mkdir(parents=True, exist_ok=True)
    start = max(0, min(start, duration(src) - length))
    fc = ("[0:v]split=2[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "boxblur=25:5[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    font = next((f for f in FONTS if Path(f).exists()), None)
    if hook and font:
        tf = dest.with_suffix(".txt")
        tf.write_text("\n".join(textwrap.wrap(hook, 24)[:3]))
        fc += (f",drawtext=fontfile={font}:textfile={tf}:fontcolor=white:fontsize=64:borderw=5:"
               "bordercolor=black:x=(w-text_w)/2:y=200:line_spacing=12")
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(length), "-i", str(src),
           "-filter_complex", fc, "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest)]
    subprocess.run(cmd, check=True)
    return dest


# ---------- posting ----------
def yt_client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        scopes=["https://www.googleapis.com/auth/youtube.upload",
                                "https://www.googleapis.com/auth/youtube.readonly"])
    return build("youtube", "v3", credentials=creds)


def post_youtube(file, title, desc):
    from googleapiclient.http import MediaFileUpload
    body = {"snippet": {"title": title[:100], "description": desc, "categoryId": "20",
                        "tags": ["GTA6", "GTAVI", "Shorts"]},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
    r = yt_client().videos().insert(part="snippet,status", body=body,
                                    media_body=MediaFileUpload(str(file), resumable=True)).execute()
    return r["id"]


def post_tiktok(file, caption):
    """TikTok Content Posting API (direct post). Posts are private until your TikTok app passes audit."""
    import requests
    tok = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data={
        "client_key": os.environ["TT_CLIENT_KEY"], "client_secret": os.environ["TT_CLIENT_SECRET"],
        "grant_type": "refresh_token", "refresh_token": os.environ["TT_REFRESH_TOKEN"]}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}", "Content-Type": "application/json; charset=UTF-8"}
    info = requests.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
                         headers=h, timeout=30).json()["data"]
    opts = info.get("privacy_level_options", ["SELF_ONLY"])
    priv = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in opts else opts[0]
    size = file.stat().st_size
    init = requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/", headers=h, timeout=30, json={
        "post_info": {"title": caption[:2200], "privacy_level": priv, "disable_duet": False,
                      "disable_comment": False, "disable_stitch": False},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size,
                        "total_chunk_count": 1}}).json()["data"]
    requests.put(init["upload_url"], timeout=300, data=file.read_bytes(), headers={
        "Content-Type": "video/mp4", "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}"}).raise_for_status()
    return init["publish_id"]


def queue_tiktok(file, caption):
    q = OUT / "queue"
    q.mkdir(parents=True, exist_ok=True)
    shutil.copy(file, q / file.name)
    (q / (file.stem + ".caption.txt")).write_text(caption)


# ---------- worker ----------
def run(cfg, url, channel, title, inbox):
    s = cfg["settings"]
    posted = sload("posted", {"posted": []})
    if inbox:
        jobs = inbox_jobs()
    else:
        j = url_job(url, channel, title)
        words = s.get("skip_title_words") or []
        if words and re.search("|".join(map(re.escape, words)), j["title"], re.I):
            log("skipped: skip_title_words"); return
        if j["channel"] in paused_channels():
            log(f"skipped: {j['channel']} is paused"); return
        jobs = [j]
    for j in jobs:
        try:
            src = j["path"] or download(j, s["max_source_minutes"])
            for k, start in enumerate(pick(energy(src), s["clips_per_video"], s["clip_seconds"])):
                today = sum(1 for p in posted["posted"] if time.time() - p["t"] < DAY)
                hook = re.sub(r"(?i)\bgta\s*(6|vi)\b|[|\-–—:]", " ", j["title"]).strip()[:70]
                f = render(src, start, s["clip_seconds"], OUT / "clips" / f"{j['id']}_{k}.mp4", hook)
                queue_tiktok(f, f"{hook} #gta6 #gtavi #fyp")
                if today >= s["max_posts_per_day"]:
                    log("daily cap reached; clip queued only"); continue
                title_ = f"{hook} #GTA6 #Shorts"
                desc = (f"Clip from {j['channel']} (used with permission): {j['url']}\n\n"
                        "#GTA6 #GTAVI #Shorts").strip()
                entry = {"t": time.time(), "src": j["id"], "channel": j["channel"], "file": f.name}
                if s.get("upload_youtube") and os.environ.get("YT_REFRESH_TOKEN"):
                    entry["yt_id"] = post_youtube(f, title_, desc); log("YT", entry["yt_id"])
                if os.environ.get("TT_REFRESH_TOKEN"):
                    try:
                        entry["tt_id"] = post_tiktok(f, f"{hook} #gta6 #gtavi #fyp"); log("TT", entry["tt_id"])
                    except Exception as e:
                        log(f"TikTok post failed: {e}")
                if "yt_id" in entry or "tt_id" in entry:
                    posted["posted"] = (posted["posted"] + [entry])[-1000:]
                    ssave("posted", posted)
        except Exception as e:
            log(f"FAIL {j['id']}: {e}"); raise


# ---------- overseer ----------
def yt_status(ids):
    out, yt = {}, yt_client()
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="status", id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            out[it["id"]] = it["status"]
    return out


def check():
    now = time.time()
    posted = sload("posted", {"posted": []})["posted"]
    h = sload("health", {})
    h.setdefault("removed", {}); h.setdefault("strikes", {}); h.setdefault("paused", {})
    h["paused"] = {c: u for c, u in h["paused"].items() if u > now}
    alerts = []
    recent = [p for p in posted if p.get("yt_id") and now - p["t"] < 30 * DAY]
    if recent and os.environ.get("YT_REFRESH_TOKEN"):
        found = yt_status([p["yt_id"] for p in recent])
        for p in recent:
            if p["yt_id"] in h["removed"]:
                continue
            st = found.get(p["yt_id"])
            bad = st is None or st.get("uploadStatus") in ("rejected", "failed", "deleted") \
                or st.get("rejectionReason")
            if bad:
                why = (st or {}).get("rejectionReason") or (st or {}).get("uploadStatus") or "missing/removed"
                h["removed"][p["yt_id"]] = {"t": now, "channel": p["channel"], "src": p["src"], "why": why}
                h["strikes"].setdefault(p["channel"], []).append(now)
                alerts.append(f"Removed: youtu.be/{p['yt_id']} ({p['channel']}, {why})")
    for ch in list(h["strikes"]):
        h["strikes"][ch] = [t for t in h["strikes"][ch] if now - t < 30 * DAY]
        if len(h["strikes"][ch]) >= 2 and ch not in h["paused"]:
            h["paused"][ch] = now + 7 * DAY
            alerts.append(f"PAUSED source '{ch}' for 7 days: 2+ removals in 30 days. Review its permission and content.")
    ssave("health", h)
    day = sum(1 for p in posted if now - p["t"] < DAY)
    month_removed = sum(1 for v in h["removed"].values() if now - v["t"] < 30 * DAY)
    print("ALERT" if alerts else "OK", "- GTA6 clipper status")
    print(f"\n- Posted last 24h: {day} (cap {yaml.safe_load((ROOT / 'sources.yaml').read_text())['settings']['max_posts_per_day']})")
    print(f"- Posted last 30d: {sum(1 for p in posted if now - p['t'] < 30 * DAY)}")
    print(f"- Removed last 30d: {month_removed}")
    print(f"- Paused sources: {', '.join(h['paused']) or 'none'}")
    for a in alerts:
        print(f"\n> {a}")
    srcs = {}
    for p in posted:
        if now - p["t"] < DAY and p.get("src") and not p["src"].startswith("inbox-"):
            srcs[p["src"]] = p["channel"]
    print("\n**Clipped from (last 24h)**")
    for sid, ch in srcs.items():
        print(f"- {ch}: https://www.youtube.com/watch?v={sid}")
    if not srcs:
        print("- none")


# ---------- cli ----------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan"); sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--url", default=""); r.add_argument("--channel", default="")
    r.add_argument("--title", default=""); r.add_argument("--inbox", action="store_true")
    t = sub.add_parser("render"); t.add_argument("file"); t.add_argument("--title", default="")
    t.add_argument("--start", type=float)
    a = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "sources.yaml").read_text())
    if a.cmd == "scan":
        scan(cfg)
    elif a.cmd == "check":
        check()
    elif a.cmd == "run":
        if not (a.url or a.inbox):
            raise SystemExit("run needs --url or --inbox")
        run(cfg, a.url, a.channel, a.title, a.inbox)
    else:
        src = Path(a.file)
        st_ = a.start if a.start is not None else pick(energy(src), 1, 40)[0]
        log("start", st_, "->", render(src, st_, 40, OUT / "clips" / "test.mp4", a.title))
