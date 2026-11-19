"""Run the whole pipeline without GitHub Actions: python serve.py
Loops forever on any machine (PC, free cloud VM, Termux on Android, Docker).
Reads keys from a .env file (KEY=value per line) or normal environment variables.
scan every SCAN_EVERY seconds (default 120 = 2 min) -> clip+upload; harvest every 6h; status report every hour (printed + saved to out/status.md)."""
import collections, json, os, subprocess, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).parent
PY = sys.executable


def load_env():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


LOG = collections.deque(maxlen=400)
BUSY = threading.Lock()


def logline(text):
    for l in str(text).splitlines():
        if l.strip():
            LOG.append(time.strftime("%H:%M:%S ") + l[:300])
    print(text, flush=True)


def sh(*args, capture=False):
    r = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True)
    logline(f"$ {' '.join(a[:60] for a in args[:3])} -> exit {r.returncode}")
    logline((r.stderr or "")[-1500:])
    if not capture:
        logline((r.stdout or "")[-500:])
    return r


def env_report():
    names = ["YT_API_KEY", "YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN", "DISCORD_WEBHOOK",
             "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "TT_REFRESH_TOKEN", "ADMIN_KEY"]
    return "keys set: " + ", ".join(f"{n}={'yes' if os.environ.get(n) else 'NO'}" for n in names)


def tick_scan():
    r = sh("clipper.py", "scan", capture=True)
    out = r.stdout.strip().splitlines()
    if not out:
        logline("scan: no new permitted GTA 6 video this round")
        return
    try:
        job = json.loads(out[-1])
    except ValueError:
        return
    with BUSY:
        sh("clipper.py", "run", "--url", job["url"], "--channel", job.get("channel", ""), "--title", job.get("title", ""))


def tick_check():
    r = sh("clipper.py", "check", capture=True)
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "status.md").write_text(r.stdout)
    print(r.stdout[-1500:], flush=True)


def web():
    """Tiny status page so free web hosts (Render etc.) see an open port; ping it every 10 min to keep the host awake."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            import urllib.parse as up
            u = up.urlparse(self.path); q = dict(up.parse_qsl(u.query))
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
            cb = f"https://{host}/tiktok/callback"
            if u.path == "/logs":
                body = (env_report() + "\n\n" + "\n".join(LOG)).encode()
                self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
                self.wfile.write(body); return
            if u.path == "/clip":  # open on your phone: /clip?key=ADMIN_KEY&url=<youtube or twitch VOD link>
                ok = os.environ.get("ADMIN_KEY") and q.get("key") == os.environ.get("ADMIN_KEY") and q.get("url", "").startswith("http")
                if ok:
                    def go():
                        with BUSY:
                            sh("clipper.py", "run", "--url", q["url"], "--channel", q.get("channel", "manual"), "--title", q.get("title", ""))
                    threading.Thread(target=go, daemon=True).start()
                msg = "started - watch /logs and your Discord channel (a clip takes several minutes)" if ok else "refused: missing or wrong key or url"
                self.send_response(200 if ok else 403); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
                self.wfile.write(msg.encode()); return
            if u.path in ("/privacy", "/terms"):
                who = os.environ.get("OWNER_NAME", "the site owner")
                body = (f"{'Privacy Policy' if u.path == '/privacy' else 'Terms of Service'} - GTA6 Clipper\n\n"
                        f"GTA6 Clipper is a personal tool operated by {who}. It downloads short highlights from creators who "
                        "gave the operator permission, edits them, and posts them to the operator's own accounts. "
                        "It collects no data from visitors, sets no cookies and shares nothing with third parties. "
                        "Authorization tokens for the operator's own TikTok and YouTube accounts are stored only in the "
                        "operator's private server settings. Contact the operator through the linked accounts to request "
                        "removal of any clip.\n").encode()
                self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
                self.wfile.write(body); return
            if u.path == "/tiktok/login":  # one-time helper: gets your TikTok refresh token on a phone
                url = "https://www.tiktok.com/v2/auth/authorize/?" + up.urlencode({
                    "client_key": os.environ.get("TT_CLIENT_KEY", ""), "scope": "user.info.basic,video.publish,video.upload",
                    "response_type": "code", "redirect_uri": cb, "state": "gta6"})
                self.send_response(302); self.send_header("Location", url); self.end_headers(); return
            if u.path == "/tiktok/callback":
                import requests
                r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data={
                    "client_key": os.environ.get("TT_CLIENT_KEY", ""), "client_secret": os.environ.get("TT_CLIENT_SECRET", ""),
                    "code": q.get("code", ""), "grant_type": "authorization_code", "redirect_uri": cb}).json()
                msg = ("Copy this into the TT_REFRESH_TOKEN setting:\n\n" + r["refresh_token"]) if r.get("refresh_token") \
                    else "TikTok said: " + json.dumps({k: v for k, v in r.items() if k != "access_token"})
                self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
                self.wfile.write(msg.encode()); return
            f = ROOT / "out" / "status.md"
            body = (f.read_text() if f.exists() else "running").encode()
            self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a): pass
    threading.Thread(target=HTTPServer(("0.0.0.0", int(os.environ["PORT"])), H).serve_forever, daemon=True).start()


if __name__ == "__main__":
    load_env()
    logline("booted. " + env_report())
    if os.environ.get("PORT"):
        web()
    last = {"harvest": 0, "check": 0}
    while True:
        now = time.time()
        try:
            if now - last["harvest"] > 6 * 3600:
                threading.Thread(target=lambda: sh("harvest.py"), daemon=True).start(); last["harvest"] = now
            tick_scan()
            if now - last["check"] > 3600:
                tick_check(); last["check"] = now
        except Exception as e:
            print("loop error:", e, flush=True)
        time.sleep(int(os.environ.get("SCAN_EVERY", "120")))
