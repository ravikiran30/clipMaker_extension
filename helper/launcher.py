"""
ClipMaker native-messaging launcher.

Chrome starts this when the extension asks for the helper and finds it down.
It speaks just enough of the native messaging protocol to answer one request,
starts server.py detached (so it outlives this process), waits for it to come
up, and replies.

Registered by install_ondemand.bat -- not meant to be run by hand.
"""

import os
import sys
import json
import struct
import subprocess
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HEALTH = "http://127.0.0.1:5005/health"


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    length = struct.unpack("<I", raw)[0]
    if not length:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def send_message(obj):
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def helper_up(timeout=2):
    try:
        with urllib.request.urlopen(HEALTH, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def pythonw():
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.exists() else exe)


def start_helper():
    if helper_up():
        return "already-running"

    flags = 0
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP -- survives Chrome closing
        # this launcher, and shows no console window.
        flags = 0x00000008 | 0x00000200

    subprocess.Popen(
        [pythonw(), str(BASE_DIR / "server.py")],
        cwd=str(BASE_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )

    # Cold start (importing Flask, probing ffmpeg) can take a while on Windows.
    for _ in range(60):
        if helper_up(2):
            return "started"
        time.sleep(0.5)
    return "timeout"


def main():
    try:
        read_message()  # content doesn't matter; the request itself is the signal
        result = start_helper()
        send_message({"ok": result in ("started", "already-running"), "result": result})
    except Exception as e:
        try:
            send_message({"ok": False, "result": f"{type(e).__name__}: {e}"})
        except Exception:
            pass


if __name__ == "__main__":
    main()
