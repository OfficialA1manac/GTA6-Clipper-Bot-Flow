"""Retention edit for clips: punch-in zooms, synthesized sound effects, reaction text, word captions, progress bar.
All sound effects are generated here with ffmpeg (no downloaded audio, so no copyright issues)."""
import random, re, subprocess, tempfile
from pathlib import Path

SFX_DIR = Path(tempfile.gettempdir()) / "gta6_sfx"
SFX = {  # name -> lavfi source
    "boom": "aevalsrc='0.9*sin(2*PI*(70-45*t)*t)*exp(-4*t)':d=0.9",
    "ding": "aevalsrc='0.5*sin(2*PI*1568*t)*exp(-6*t)+0.3*sin(2*PI*2093*t)*exp(-8*t)':d=0.7",
    "honk": "aevalsrc='0.5*(sin(2*PI*392*t)+0.5*sin(2*PI*784*t)+0.25*sin(2*PI*1176*t))*exp(-3*t)':d=0.6",
    "womp": "aevalsrc='0.6*sin(2*PI*(330-140*t)*t)*exp(-1.5*t)':d=1.0",
    "whoosh": "anoisesrc=d=0.6:c=pink:a=0.6,highpass=f=700,afade=t=in:d=0.3,afade=t=out:st=0.3:d=0.3",
    "pop": "aevalsrc='0.7*sin(2*PI*(900-700*t)*t)*exp(-25*t)':d=0.25",
}
REACT = ["NO WAY", "BRO WHAT", "WAIT WHAT", "LOOK AT THIS", "INSANE", "HOLD UP", "CRAZY", "BRO", "NOT AGAIN", "WATCH THIS"]
BAD = re.compile(r"(?i)\b(fuck\w*|shit\w*|bitch\w*|nigg\w*|fag\w*|retard\w*)\b")


def sfx(name):
    SFX_DIR.mkdir(exist_ok=True)
    f = SFX_DIR / f"{name}.wav"
    if not f.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", SFX[name], "-ar", "44100", "-ac", "2", str(f)], check=True)
    return f


def peaks(e, start, length, n=4, gap=6):
    """Loudest moments inside the clip, in clip-relative seconds."""
    import numpy as np
    seg = np.array(e[int(start) + 2: int(start) + int(length) - 2], dtype=float)
    out = []
    for _ in range(n):
        if len(seg) == 0 or seg.max() <= 0:
            break
        i = int(seg.argmax())
        out.append(i + 2)
        seg[max(0, i - gap): i + gap] = -1
    return sorted(out)


def words(src, start, length):
    """Word timings via faster-whisper if installed; [] otherwise."""
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return []
    try:
        wav = Path(tempfile.gettempdir()) / "clip_audio.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(length), "-i", str(src),
                        "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
        segs, _ = WhisperModel("tiny", device="cpu", compute_type="int8").transcribe(str(wav), word_timestamps=True, vad_filter=True)
        return [(w.start, w.end, BAD.sub("***", w.word.strip())) for s in segs for w in (s.words or []) if w.word.strip()]
    except Exception:
        return []


def chunks(ws, size=3, cap=28):
    out = []
    for i in range(0, len(ws), size):
        g = ws[i:i + size]
        out.append((g[0][0], g[-1][1] + 0.15, " ".join(x[2] for x in g).upper()))
    return out[:cap]


def render(src, start, length, dest, hook, e, font, seed=0):
    rnd = random.Random(seed or hash(str(dest)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    pk = peaks(e, start, length) if e is not None else []
    # zoom pulse expression: 0..1 spike around each peak
    pulse = "+".join(f"max(0,1-abs(t-{p})/0.4)" for p in pk) or "0"
    fc = ["[0:v]split=2[a][b]",
          "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg]",
          f"[b]scale=w='trunc(1080*(1+0.16*min(1,{pulse}))/2)*2':h=-2:eval=frame[fg]",
          "[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2:eval=frame[v0]",
          f"color=c=0xFFD400:s=1080x18:d={length}[bar]",
          f"[v0][bar]overlay=x='-w+w*t/{length}':y=H-h:eval=frame[v1]"]
    last, n = "v1", 0
    tmp = dest.parent
    def text(txt, y, size, color, t0, t1, box=False):
        nonlocal last, n
        tf = tmp / f"{dest.stem}_t{n}.txt"; tf.write_text(txt)
        extra = ":box=1:boxcolor=black@0.55:boxborderw=18" if box else ""
        fc.append(f"[{last}]drawtext=fontfile={font}:textfile={tf}:fontcolor={color}:fontsize={size}:borderw=6:"
                  f"bordercolor=black:x=(w-text_w)/2:y={y}:line_spacing=10{extra}:enable='between(t,{t0:.2f},{t1:.2f})'[t{n}]")
        last = f"t{n}"; n += 1
    if hook:
        text("\n".join(__import__("textwrap").wrap(hook.upper(), 20)[:3]), 220, 72, "0xFFD400", 0, 3.5)
        text("WAIT FOR THE END", 120, 46, "white", 0, 3.5, box=True)
    for p in pk:
        text(rnd.choice(REACT) + "!!", 1250, 84, "0xFF3B30", max(0, p - 0.2), p + 1.3)
    for a, b, txt in chunks(words(src, start, length)):
        text(txt, 1480, 62, "white", a, b)
    # audio: original + synthesized effects
    names = ["boom", "honk", "ding", "womp", "pop"]
    cues = [(0.0, "whoosh")] + [(max(0, p - 0.05), names[i % len(names)]) for i, p in enumerate(pk)]
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(length), "-i", str(src)]
    for _, nm in cues:
        cmd += ["-i", str(sfx(nm))]
    af = ["[0:a]volume=1.0[m]"]
    mix = ["[m]"]
    for i, (t, _) in enumerate(cues, 1):
        af.append(f"[{i}:a]adelay={int(t*1000)}|{int(t*1000)},volume=0.8[s{i}]"); mix.append(f"[s{i}]")
    af.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:dropout_transition=0,alimiter=limit=0.95[aout]")
    cmd += ["-filter_complex", ";".join(fc + af), "-map", f"[{last}]", "-map", "[aout]", "-t", str(length), "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dest)]
    try:
        subprocess.run(cmd, check=True)
    finally:
        for t in dest.parent.glob(f"{dest.stem}_t*.txt"):
            t.unlink()
    return dest
