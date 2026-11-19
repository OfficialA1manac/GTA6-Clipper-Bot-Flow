"""Run the whole pipeline without GitHub Actions: python serve.py
Loops forever on any machine (PC, free cloud VM, Termux on Android, Docker).
Reads keys from a .env file (KEY=value per line) or normal environment variables.
scan every SCAN_EVERY seconds (default 120 = 2 min) -> clip+upload; harvest every 6h; status report every hour (printed + saved to out/status.md)."""
import json, os, subprocess, sys, time
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


def sh(*args, capture=False):
    return subprocess.run([PY, *args], cwd=ROOT, capture_output=capture, text=True)


def tick_scan():
    r = sh("clipper.py", "scan", capture=True)
    sys.stderr.write(r.stderr[-2000:])
    out = r.stdout.strip().splitlines()
    if not out:
        return
    try:
        job = json.loads(out[-1])
    except ValueError:
        return
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
    if os.environ.get("PORT"):
        web()
    last = {"harvest": 0, "check": 0}
    while True:
        now = time.time()
        try:
            if now - last["harvest"] > 6 * 3600:
                sh("harvest.py"); last["harvest"] = now
            tick_scan()
            if now - last["check"] > 3600:
                tick_check(); last["check"] = now
        except Exception as e:
            print("loop error:", e, flush=True)
        time.sleep(int(os.environ.get("SCAN_EVERY", "120")))
