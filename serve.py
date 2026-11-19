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


if __name__ == "__main__":
    load_env()
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
