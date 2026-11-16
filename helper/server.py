"""
ClipMaker local helper server.

Downloads only a requested section of a YouTube video with yt-dlp + ffmpeg
and hands the finished file back to the Chrome extension.

Listens on 127.0.0.1:5005 only. Personal use, no auth, no cloud.
Run:  python server.py
"""

import os
import time
import re
import sys
import json
import uuid
import shutil
import threading
import subprocess
import tempfile
from pathlib import Path

from flask import Flask, request, jsonify, send_file, abort

# Video titles routinely contain characters the Windows console (cp1252) cannot
# encode. Without this, printing a log line raises UnicodeEncodeError and kills
# the worker thread mid-job.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg):
    """Never let logging take down a job."""
    try:
        print(msg, flush=True)
    except Exception:
        try:
            print(str(msg).encode("ascii", "replace").decode("ascii"), flush=True)
        except Exception:
            pass

HOST = "127.0.0.1"
PORT = 5005

BASE_DIR = Path(__file__).resolve().parent
CLIPS_DIR = BASE_DIR / "clips"
CLIPS_DIR.mkdir(exist_ok=True)

# Started with pythonw.exe (no console window) there is nowhere to print to --
# sys.stdout is None and every print() would raise. Send the log to a file.
if sys.stdout is None or sys.stderr is None:
    try:
        _logfile = open(BASE_DIR / "helper.log", "a", encoding="utf-8",
                        errors="replace", buffering=1)
        sys.stdout = _logfile
        sys.stderr = _logfile
    except Exception:
        pass

# Hard cap on clip length (seconds). Raise if you ever need longer.
MAX_DURATION = 2 * 60 * 60

app = Flask(__name__)

# ---------------------------------------------------------------- CORS
# Only the extension talks to us, and only over 127.0.0.1. We allow any
# chrome-extension:// origin rather than hard-coding an extension id that
# changes every time the folder is re-loaded unpacked.


@app.after_request
def add_cors(resp):
    origin = request.headers.get("Origin", "")
    if origin.startswith("chrome-extension://") or origin.startswith("moz-extension://"):
        resp.headers["Access-Control-Allow-Origin"] = origin
    else:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.route("/<path:_any>", methods=["OPTIONS"])
@app.route("/", methods=["OPTIONS"])
def preflight(_any=None):
    return ("", 204)


# ---------------------------------------------------------------- helpers

YOUTUBE_RE = re.compile(
    r"^https?://"
    r"(?:(?:www\.|m\.|music\.)?youtube\.com/"
    r"(?:watch\?[^ ]*\bv=[A-Za-z0-9_-]{11}|shorts/[A-Za-z0-9_-]{11}|live/[A-Za-z0-9_-]{11}|embed/[A-Za-z0-9_-]{11})"
    r"|youtu\.be/[A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)

PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
# With --download-sections yt-dlp hands the job to ffmpeg, which reports
# "time=00:00:07.23" instead of a percentage. We turn that into one.
FFTIME_RE = re.compile(r"time=\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def ytdlp_cmd():
    """Prefer the importable module so we use the same Python env as this server."""
    try:
        import yt_dlp  # noqa: F401

        return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        exe = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
        if exe:
            return [exe]
    return None


# Extra places to look for ffmpeg when it isn't on PATH.
FFMPEG_FALLBACKS = [
    BASE_DIR / "bin",
    Path.home() / "ffmpeg" / "bin",
    Path("C:/ffmpeg/bin"),
    Path("/usr/local/bin"),
    Path("/opt/homebrew/bin"),
]


def ffmpeg_path():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for d in FFMPEG_FALLBACKS:
        for name in ("ffmpeg.exe", "ffmpeg"):
            p = d / name
            if p.exists():
                # Make it visible to yt-dlp's own child processes too.
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
                return str(p)
    return None


def parse_time(value):
    """Accept 90, 90.5, 1:30, 1:30.5, 01:02:03 -> float seconds. Raises ValueError."""
    if value is None:
        raise ValueError("missing time")
    s = str(value).strip()
    if not s:
        raise ValueError("missing time")
    # "1.30" means 1:30 to most people; "90.5" is still 90 and a half seconds.
    if ":" not in s and re.fullmatch(r"\d+\.\d{2}", s):
        s = s.replace(".", ":")
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(f"'{s}' is not a valid time")
    total = 0.0
    try:
        for i, p in enumerate(reversed(parts)):
            p = p.strip()
            if p == "":
                raise ValueError
            n = float(p)
            if n < 0:
                raise ValueError
            if i > 0 and n >= 60 and len(parts) > 1:
                raise ValueError
            total += n * (60 ** i)
    except ValueError:
        raise ValueError(f"'{s}' is not a valid time (use 90, 1:30 or 1:02:03)")
    return total


def fmt_hhmmss(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def fmt_tag(seconds):
    """Filename-safe time tag, e.g. 1h02m03s / 2m30s / 45s."""
    s = int(seconds)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    if h:
        return f"{h}h{m:02d}m{sec:02d}s"
    if m:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"


def sanitize(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] or "clip"


QUALITY_FORMATS = {
    "best": "bv*+ba/b",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]",
    "720": "bv*[height<=720]+ba/b[height<=720]",
    "480": "bv*[height<=480]+ba/b[height<=480]",
}

FRIENDLY_ERRORS = [
    ("ffmpeg", "ffmpeg not found or failed. Install ffmpeg and restart the helper."),
    ("Video unavailable", "Video unavailable (private, deleted or region-blocked)."),
    ("Sign in to confirm", "YouTube wants a sign-in for this video (age-restricted or bot check)."),
    ("age", "This video is age-restricted and can't be downloaded anonymously."),
    ("Private video", "That video is private."),
    ("members-only", "Members-only video."),
    ("HTTP Error 429", "YouTube is rate-limiting you. Wait a few minutes and retry."),
    ("Unsupported URL", "yt-dlp didn't recognise that URL."),
    ("Requested format is not available", "That quality isn't available for this video. Try Best."),
    ("urlopen error", "No network connection to YouTube."),
    ("nsig extraction failed", "yt-dlp is out of date. Run: yt-dlp -U"),
]


def friendly_error(stderr_text):
    for needle, msg in FRIENDLY_ERRORS:
        if needle.lower() in stderr_text.lower():
            return msg
    tail = [l.strip() for l in stderr_text.strip().splitlines() if l.strip()]
    tail = [l for l in tail if l.lower().startswith("error") or "error" in l.lower()]
    if tail:
        return tail[-1][:200]
    return "Download failed. See the helper console for details."


# ---------------------------------------------------------------- jobs

JOBS = {}
JOBS_LOCK = threading.Lock()


def set_job(job_id, **kw):
    with JOBS_LOCK:
        JOBS.setdefault(job_id, {}).update(kw)


def get_job(job_id):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        return dict(j) if j else None


def kill_tree(pid):
    """Kill yt-dlp *and* the ffmpeg it spawned. A plain terminate() leaves
    ffmpeg running and the clip half-written."""
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.kill(pid, 9)
    except Exception as e:
        log(f"kill_tree({pid}) failed: {e}")


def cleanup_partials(stem_prefix):
    for p in CLIPS_DIR.iterdir():
        if p.name.startswith(stem_prefix) and (
            p.suffix in (".part", ".ytdl", ".temp") or ".f" in p.stem
        ):
            try:
                p.unlink()
            except OSError:
                pass


def run_job(job_id, url, start, end, quality):
    """Wrapper so that *any* unexpected failure surfaces in the popup instead of
    leaving the job stuck on 'Downloading...' forever."""
    try:
        _run_job(job_id, url, start, end, quality)
    except Exception as e:
        log(f"[{job_id[:8]}] WORKER CRASHED: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        set_job(job_id, state="error", pct=0,
                message=f"Helper error: {type(e).__name__}. See the helper window.")


def _run_job(job_id, url, start, end, quality):
    set_job(job_id, state="downloading", pct=0, message="Starting yt-dlp...")

    base = ytdlp_cmd()
    if not base:
        set_job(job_id, state="error", message="yt-dlp is not installed. pip install -U yt-dlp")
        return

    clip_len = max(0.0, end - start)
    tag = f"{fmt_tag(start)}-{fmt_tag(end)}"
    # yt-dlp fills in the title; we keep it short and strip illegal characters.
    out_tpl = str(CLIPS_DIR / f"%(title).80B_{tag}.%(ext)s")

    printed = Path(tempfile.gettempdir()) / f"clipmaker_{job_id}.txt"

    cmd = base + [
        "--newline",
        "--no-playlist",
        "--no-part",
        "--windows-filenames",
        "--download-sections", f"*{start}-{end}",
        "--force-keyframes-at-cuts",
        "-o", out_tpl,
        "--print-to-file", "after_move:filepath", str(printed),
        "--no-simulate",
    ]

    if quality == "mp3":
        cmd += ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"]
    else:
        cmd += ["-f", QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"]),
                "--merge-output-format", "mp4"]

    ff = ffmpeg_path()
    if ff:
        cmd += ["--ffmpeg-location", ff]

    cmd.append(url)

    log(f"\n[{job_id[:8]}] $ " + " ".join(cmd))

    stderr_buf = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        set_job(job_id, state="error", message=f"Could not start yt-dlp: {e}")
        return

    set_job(job_id, pid=proc.pid)

    dest = [None]
    last_output = [time.time()]

    def watchdog():
        # yt-dlp/ffmpeg going completely silent for 10 minutes means it is wedged.
        while proc.poll() is None:
            if time.time() - last_output[0] > 600:
                log(f"[{job_id[:8]}] no output for 10 min, killing")
                try:
                    proc.kill()
                except Exception:
                    pass
                return
            time.sleep(15)

    threading.Thread(target=watchdog, daemon=True).start()

    for line in proc.stdout:
        last_output[0] = time.time()
        line = line.rstrip()
        if not line:
            continue
        log(f"[{job_id[:8]}] {line}")
        stderr_buf.append(line)
        if len(stderr_buf) > 200:
            del stderr_buf[:100]

        m = PROGRESS_RE.search(line)
        ft = None if m else FFTIME_RE.search(line)
        if m:
            set_job(job_id, state="downloading", pct=float(m.group(1)),
                    message=f"Downloading {m.group(1)}%")
        elif ft and clip_len > 0:
            done = int(ft.group(1)) * 3600 + int(ft.group(2)) * 60 + float(ft.group(3))
            pct = max(0.0, min(99.0, done / clip_len * 100))
            set_job(job_id, state="downloading", pct=pct,
                    message=f"Downloading {pct:.0f}%")
        elif "[Merger]" in line or "[ExtractAudio]" in line or "[VideoConvertor]" in line:
            set_job(job_id, state="processing", pct=99, message="Processing with ffmpeg...")
        elif "[download] Destination" in line:
            # Remember what is being written so a cancel can remove the stub.
            dest[0] = line.split("Destination:", 1)[-1].strip()
            set_job(job_id, state="downloading", message="Downloading...")

    code = proc.wait()
    text = "\n".join(stderr_buf)

    if (get_job(job_id) or {}).get("cancel_requested"):
        cleanup_partials("")
        # --no-part means the half-written clip sits under its final name.
        if dest[0]:
            try:
                p = Path(dest[0]).resolve()
                if CLIPS_DIR.resolve() in p.parents and p.exists():
                    p.unlink()
                    log(f"[{job_id[:8]}] removed partial {p.name}")
            except OSError as e:
                log(f"[{job_id[:8]}] could not remove partial: {e}")
        set_job(job_id, state="cancelled", pct=0, message="Cancelled")
        log(f"[{job_id[:8]}] cancelled by user")
        try:
            printed.unlink()
        except OSError:
            pass
        return

    if code != 0:
        cleanup_partials("")
        set_job(job_id, state="error", pct=0, message=friendly_error(text))
        try:
            printed.unlink()
        except OSError:
            pass
        return

    final = None
    try:
        if printed.exists():
            lines = [l.strip() for l in printed.read_text(encoding="utf-8").splitlines() if l.strip()]
            if lines:
                final = Path(lines[-1])
            printed.unlink()
    except OSError:
        pass

    if not final or not final.exists():
        # Fall back to the newest file in clips/
        files = sorted(
            [p for p in CLIPS_DIR.iterdir() if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        final = files[0] if files else None

    if not final or not final.exists():
        set_job(job_id, state="error", message="yt-dlp finished but no output file was found.")
        return

    size = final.stat().st_size
    set_job(
        job_id,
        state="done",
        pct=100,
        message="Done",
        filename=final.name,
        path=str(final),
        size=size,
    )
    log(f"[{job_id[:8]}] saved -> {final}  ({size/1048576:.1f} MB)")


# ---------------------------------------------------------------- routes


@app.get("/health")
def health():
    base = ytdlp_cmd()
    version = None
    if base:
        try:
            version = subprocess.run(
                base + ["--version"], capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip()
        except Exception:
            version = None
    ff = ffmpeg_path()
    return jsonify({
        "ok": bool(base) and bool(ff),
        "ytdlp": version,
        "ffmpeg": ff,
        "clips_dir": str(CLIPS_DIR),
    })


@app.post("/clip")
def clip():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    quality = (str(data.get("quality") or "best")).strip().lower()

    if not YOUTUBE_RE.match(url):
        return jsonify({"error": "That doesn't look like a YouTube video URL."}), 400

    try:
        start = parse_time(data.get("start"))
        end = parse_time(data.get("end"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if end <= start:
        return jsonify({"error": "End time must be after start time."}), 400
    if end - start > MAX_DURATION:
        return jsonify({"error": f"Clip is longer than the {MAX_DURATION//3600}h limit."}), 400
    if quality not in QUALITY_FORMATS and quality != "mp3":
        quality = "best"

    if not ytdlp_cmd():
        return jsonify({"error": "yt-dlp is not installed. pip install -U yt-dlp"}), 500
    if not ffmpeg_path():
        return jsonify({"error": "ffmpeg not found on PATH. Install it and restart the helper."}), 500

    job_id = uuid.uuid4().hex
    set_job(job_id, state="queued", pct=0, message="Queued",
            url=url, start=start, end=end, quality=quality,
            range=f"{fmt_hhmmss(start)} - {fmt_hhmmss(end)}")

    threading.Thread(target=run_job, args=(job_id, url, start, end, quality), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.post("/cancel/<job_id>")
def cancel(job_id):
    j = get_job(job_id)
    if not j:
        return jsonify({"error": "unknown job"}), 404
    if j.get("state") in ("done", "error", "cancelled"):
        return jsonify({"ok": True, "state": j.get("state")})
    set_job(job_id, cancel_requested=True, message="Cancelling...")
    kill_tree(j.get("pid"))
    return jsonify({"ok": True})


@app.get("/status/<job_id>")
def status(job_id):
    j = get_job(job_id)
    if not j:
        return jsonify({"error": "unknown job"}), 404
    return jsonify({
        "state": j.get("state"),
        "pct": round(j.get("pct", 0), 1),
        "message": j.get("message", ""),
        "filename": j.get("filename"),
        "path": j.get("path"),
        "size": j.get("size"),
        "range": j.get("range"),
    })


@app.get("/file/<job_id>")
def serve_file(job_id):
    j = get_job(job_id)
    if not j or j.get("state") != "done" or not j.get("path"):
        abort(404)
    p = Path(j["path"]).resolve()
    if CLIPS_DIR.resolve() not in p.parents or not p.exists():
        abort(403)
    return send_file(p, as_attachment=True, download_name=sanitize(p.name))


@app.get("/")
def index():
    return (
        "ClipMaker helper is running.<br>"
        f"Clips folder: {CLIPS_DIR}<br>"
        "Open the ClipMaker extension in Chrome."
    )


def already_running():
    """Windows lets a second process bind the same loopback port, which leaves
    two helpers answering at random. Refuse to start if one is already up."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


if __name__ == "__main__":
    if already_running():
        print(f"ClipMaker helper is already running on {HOST}:{PORT}. Nothing to do.")
        sys.exit(0)

    print("=" * 60)
    print(" ClipMaker helper")
    print(f" http://{HOST}:{PORT}")
    print(f" clips -> {CLIPS_DIR}")
    print(f" yt-dlp: {'yes' if ytdlp_cmd() else 'MISSING (pip install -U yt-dlp)'}")
    print(f" ffmpeg: {ffmpeg_path() or 'MISSING (see README)'}")
    print("=" * 60)
    print(" Keep this window open while you make clips. Ctrl+C to stop.\n")
    app.run(host=HOST, port=PORT, threaded=True, debug=False)
