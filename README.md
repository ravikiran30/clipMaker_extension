# ClipMaker

A personal Chrome extension (Manifest V3) + local Python helper that downloads **only a trimmed
section** of a YouTube video, using `yt-dlp` and `ffmpeg`. Everything runs on your own machine —
no accounts, no cloud, no tracking.

```
CLIPMAKER\
├── extension\        <- load this folder in chrome://extensions
│   ├── manifest.json
│   ├── popup.html / popup.css / popup.js
│   └── icons\
├── helper\
│   ├── server.py     <- local Flask server on 127.0.0.1:5005
│   ├── requirements.txt
│   └── clips\        <- finished clips land here
├── start_helper.bat  <- Windows one-click launcher
├── start_helper.sh   <- macOS / Linux launcher
└── README.md
```

---

## 1. Install the prerequisites

### Python packages

```
pip install -U flask yt-dlp
```

(`start_helper.bat` / `start_helper.sh` do this for you on first run.)

### ffmpeg — required

ffmpeg does the actual cutting and merging. The helper refuses to start a job without it.

| OS | Command |
|----|---------|
| **Windows** | `winget install Gyan.FFmpeg` &nbsp;(or `choco install ffmpeg`) |
| **macOS** | `brew install ffmpeg` |
| **Debian/Ubuntu** | `sudo apt install ffmpeg` |
| **Fedora** | `sudo dnf install ffmpeg` |

After installing on Windows, **close and reopen your terminal** so `ffmpeg` is on `PATH`.
Verify with `ffmpeg -version`.

If ffmpeg isn't on `PATH`, the helper also looks in these folders, in order — drop
`ffmpeg.exe` (and `ffprobe.exe`) into any one of them and it will be found:

```
CLIPMAKER\helper\bin\
C:\Users\<you>\ffmpeg\bin\
C:\ffmpeg\bin\
/usr/local/bin  ·  /opt/homebrew/bin
```

> **Tip:** `winget install Gyan.FFmpeg` sometimes fails at the final copy with
> *"Access is denied"* while still leaving the extracted build behind in
> `%LOCALAPPDATA%\Temp\WinGet\...`. If that happens, copy `ffmpeg.exe` and
> `ffprobe.exe` out of its `bin` folder into one of the paths above — the helper
> adds that folder to `PATH` for yt-dlp itself, so no system change is needed.

---

## 2. Run the helper

### Recommended: start it automatically, with no terminal

Double-click **`install_autostart.bat`** once. From then on the helper starts
silently every time you log in — no console window, nothing to remember.

It finds `pythonw.exe` (Python without a console), installs any missing
dependencies, writes `ClipMaker Helper.vbs` into your Startup folder, and
launches it immediately so you don't have to reboot.

Because there's no window, output goes to **`helper\helper.log`** instead.

To undo it: **`uninstall_autostart.bat`** — removes the startup entry and stops
the running helper.

### Or run it by hand

Double-click **`start_helper.bat`** (Windows) or run `./start_helper.sh` (macOS/Linux).

Or manually:

```
cd helper
python server.py
```

You should see:

```
============================================================
 ClipMaker helper
 http://127.0.0.1:5005
 clips -> ...\CLIPMAKER\helper\clips
 yt-dlp: yes
 ffmpeg: C:\...\ffmpeg.exe
============================================================
```

Keep that window open while you make clips. `Ctrl+C` stops it.

---

## 3. Load the extension

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `CLIPMAKER\extension` folder
5. Pin ClipMaker to the toolbar

---

## 4. Make a clip

1. Open a YouTube video, click the ClipMaker icon.
   The URL field is pre-filled from the current tab.
2. Enter **Start** and **End**. Accepted formats: `90`, `1:30`, `1:02:03` (decimals OK: `1:30.5`).
   Duration updates live.
3. Pick a quality (Best / 1080p / 720p / 480p / Audio only MP3).
4. Click **Download Clip**.

The dot next to the title shows helper status: green = ready, red = not running.

Status goes **Downloading NN% → Processing… → Done**. The finished file is saved in
`helper\clips\` *and* pushed to your browser's Downloads folder. The helper-side path is
shown under the status line.

You can close the popup while a clip is running — the job keeps going on the helper, and
reopening the popup reattaches to it.

File names look like: `Some_Video_Title_1m30s-2m45s.mp4`.

---

## 5. Keeping it working

YouTube changes things often. When downloads start failing:

```
yt-dlp -U
```

or, if yt-dlp was installed through pip (it was, if you used the launcher):

```
pip install -U yt-dlp
```

Then restart the helper.

---

## Troubleshooting

| Message | Fix |
|---|---|
| "Start the helper server first" | Run `start_helper.bat`. |
| "ffmpeg is missing" | Install ffmpeg (section 1), reopen the terminal, restart the helper. |
| "yt-dlp is out of date. Run: yt-dlp -U" | Update yt-dlp, restart the helper. |
| "Sign in to confirm…" / age-restricted | Anonymous download isn't possible for that video. |
| "YouTube is rate-limiting you" | Wait a few minutes. |
| Browser download blocked | The clip is still saved in `helper\clips\` — the path is shown in the popup. |
| "No supported JavaScript runtime could be found" (warning) | Harmless for most videos. If downloads start failing with signature/nsig errors, install Deno (`winget install DenoLand.Deno`) — yt-dlp uses it to solve YouTube's JS challenges. |

### Notes

- The helper binds to `127.0.0.1` only; nothing on your network can reach it.
- `/file/<id>` only ever serves files inside `helper\clips\`.
- Clip length is capped at 2 hours (`MAX_DURATION` in `server.py`).
- Cuts use `--force-keyframes-at-cuts`, so boundaries are frame-accurate but re-encode slightly
  around the cut points. That costs a few seconds of CPU and is why "Processing…" appears.
- Clips are never deleted automatically. Clean out `helper\clips\` yourself now and then.
