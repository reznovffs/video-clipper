# 🎬 AI Video Clipper

A fully local desktop app: upload a long video (podcast, interview, stream, course...)
and it automatically transcribes it, finds the most interesting moments, and exports
short subtitled clips (15s / 30s / 60s) as MP4. No SaaS, no accounts, no payments —
everything runs on your machine.

## 1. Project structure

```
video_clipper/
├── app.py                     # Gradio UI + orchestration (run this)
├── requirements.txt
├── README.md
├── modules/
│   ├── __init__.py
│   ├── transcriber.py         # Whisper transcription (word-level timestamps)
│   ├── highlight_detector.py  # Heuristic scoring to find "interesting" moments
│   ├── subtitles.py           # Builds styled .ass subtitle files per clip
│   ├── clipper.py             # ffmpeg cut + burn-in subtitles
│   └── utils.py                # Shared helpers (color conversion, paths, timestamps)
├── output/                    # Generated clips land here
└── temp/                      # Scratch subtitle files
```

## 2. Installation (Windows)

### Step 1 — Install Python
Install Python 3.10 or 3.11 from https://www.python.org/downloads/.
During install, check **"Add python.exe to PATH"**.

### Step 2 — Install FFmpeg
Whisper and the clipper both need the `ffmpeg` binary (not just the Python package).

1. Download a Windows build from https://www.gyan.dev/ffmpeg/builds/ (get the "release essentials" zip).
2. Extract it, e.g. to `C:\ffmpeg`.
3. Add `C:\ffmpeg\bin` to your Windows PATH:
   - Search "Environment Variables" in the Start menu → Edit the system environment variables → Environment Variables
   - Under "System variables", select `Path` → Edit → New → paste `C:\ffmpeg\bin`
4. Open a **new** terminal and confirm it works:
   ```
   ffmpeg -version
   ```

### Step 3 — Get the project files
Put the `video_clipper` folder anywhere, e.g. `C:\Users\<you>\video_clipper`.

### Step 4 — Create a virtual environment and install dependencies
Open a terminal (PowerShell or cmd) in the `video_clipper` folder:

```bash
cd C:\Users\<you>\video_clipper
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> Note: `openai-whisper` pulls in PyTorch. If you have an NVIDIA GPU and want faster
> transcription, install the CUDA build of torch first from https://pytorch.org/get-started/locally/,
> then run `pip install -r requirements.txt` (it will skip re-installing torch).
> A CPU-only setup works fine, just slower — "base" model on a 30-min video is typically a
> few minutes on CPU.

## 3. Running the app

With the virtual environment active:

```bash
python app.py
```

This starts a local Gradio server and prints a URL like `http://127.0.0.1:7860`.
Open that in your browser — it's a local page, nothing is uploaded anywhere.

**Usage:**

The app is organized into four tabs so it's not one overwhelming page:

**Tab 1 — Upload & Highlights**
1. Upload your video.
2. Pick a Whisper model size, clip lengths, and how many candidates to surface per length.
3. Click **Find Highlights**. You'll get a checklist like
   `[30s | score 8.4] 4:12–4:42 — "honestly this is the biggest mistake..."` for each
   candidate, best-scoring first.
4. **Already watched the video and know exactly what you want?** Open "Already know a
   part you want? Add it manually", enter time ranges like `8:30-9:48` (one per line,
   `m:ss` or `h:mm:ss`), and click **Add Manual Clip(s)**. These merge into the same
   checklist — this requires "Find Highlights" to have run first, since that's what
   transcribes the video (needed for subtitles on your manual range too).
5. Check the clips you actually want.

**Tab 2 — Subtitle Style**
Pick a font, size, colors, position, bold, and how many words per caption burst
(low = punchy TikTok-style captions, high = full sentences), plus the vertical 9:16
crop toggle. **A live preview updates automatically** on the right as you change
settings — it burns a sample caption onto an actual frame from your video using the
exact same rendering path as the real export, so what you see is what you'll get.
No more guessing and re-rendering full clips just to check if a color works.

**Tab 3 — Background Music (optional)**
Upload a track, set its volume, click **Preview Music Mix** to hear a 6-second sample
of your video's real audio mixed with the music at that volume — before committing to
rendering full clips. The original dialogue always stays at full volume; only the music
volume is adjustable.

**Tab 4 — Export**
Toggle fast render mode if you want quicker (larger) exports, then **Generate Selected
Clips**. Only the ones you checked in Tab 1 get rendered. Finished clips appear in the
file list and are saved to the `output/` folder.

This flow exists because no local heuristic can reliably predict what "goes viral" —
that depends on the platform algorithm, your audience, timing, and thumbnail/caption
choices, none of which the video itself can tell you. The scoring surfaces *candidates*
worth a look; you make the final call — including overriding it with your own timestamps,
and previewing your styling choices before spending render time on them.

### Installing extra caption fonts (optional)

The font dropdown includes fonts marked "(built-in)" - these ship with Windows and
just work. The others ("(install first)") are free Google Fonts widely used for
TikTok/Shorts-style captions:

- Montserrat: https://fonts.google.com/specimen/Montserrat
- Poppins: https://fonts.google.com/specimen/Poppins
- Bebas Neue: https://fonts.google.com/specimen/Bebas+Neue
- Anton: https://fonts.google.com/specimen/Anton
- Oswald: https://fonts.google.com/specimen/Oswald

To install: download the family's zip from the link, extract it, select all the
`.ttf` files, right-click → **Install for all users** (or just **Install**). Restart
the app afterward. If you pick a font that isn't actually installed, ffmpeg's
subtitle renderer silently substitutes a default font instead of erroring — so if
your preview doesn't look like the font you picked, that's the most likely reason.

## 4. Can I edit the subtitles / colors / styling?

Yes — fully, in two ways:

**From the UI (no code):**
- Font family (dropdown)
- Font size (slider)
- Text color and outline color (color pickers)
- Position: bottom / center / top
- Bold on/off
- "Words per subtitle burst" — lower = short punchy TikTok-style captions, higher = fuller sentence lines

**By editing code, for more control** (`modules/subtitles.py`, `SubtitleStyle` dataclass):
- `outline_width` — stroke thickness
- `margin_v` — distance from the top/bottom edge
- Add a `BackColour` / semi-transparent box behind text
- Add word-by-word karaoke-style highlighting (ASS supports `\k` karaoke tags — you'd
  emit per-word `{\k<duration>}word` tags inside each Dialogue line instead of one
  block of text)
- Multiple named `Style:` lines if you want different styles for different clips

Subtitles are generated as `.ass` (Advanced SubStation Alpha) files rather than plain
`.srt`, specifically because `.ass` supports full styling — `.srt` has no color/font/
position support, which is why this project uses `.ass` under the hood even though the
final output is a normal burned-in MP4.

## 5. How highlight detection works

There's no free local model that reliably judges "what's interesting" in arbitrary
speech, so `highlight_detector.py` uses a transparent, anchor-based heuristic:

1. **Find anchors** — sentences that contain a real hook: a substantive question
   (e.g. *"do you think it's possible for humans to use 100% of their brain?"* —
   at least 4 words, not filler like "right?" or "you know?"), strong hook/emphasis
   language ("crazy", "secret", "the biggest mistake"...), or an exclamation.
2. **Build candidates from anchors only** — one candidate clip per anchor per target
   duration, with a bit of lead-in before the hook for context. Stretches of the video
   with no anchor don't produce any candidates at all.
3. **Threshold, don't just rank** — candidates below a minimum engagement density are
   dropped entirely rather than kept as a low-ranked option, so plain back-and-forth
   small talk won't surface as a clip. (There's a fallback to the least-boring options
   only if a duration has literally zero candidates clearing the bar, so the app
   doesn't come back completely empty on a quiet video.)

In practice: a stretch of "how's your week going, mine's fine, cool cool" won't get
clipped, but the moment a real question or emphatic claim shows up, that becomes a
candidate you can pick from in the highlight list. It's not literal virality
prediction (see the note in the Usage section above) — it's "don't waste my time
clipping boring stretches," which is what it's tuned for.

Tune `HOOK_WORDS` and `QUESTION_MIN_WORDS`/`FILLER_QUESTION_TAILS` in
`modules/highlight_detector.py` to bias it toward your content, and
`min_score_density` in `find_highlights()` to make it stricter (fewer, better
candidates) or looser (more candidates, lower bar).

## 6. Speeding up long videos

An hour-long video is a lot of audio to transcribe, so a few things were added
specifically to cut down wait time:

- **faster-whisper instead of openai-whisper** — same accuracy, 4–10x faster on CPU
  (uses int8-quantized CTranslate2 models), and automatically uses your GPU if you
  have `torch`+CUDA installed. This is the single biggest speed lever.
- **VAD (voice activity detection) filtering** — silent stretches (pauses, dead air)
  are skipped instead of transcribed, which matters a lot for podcasts/streams.
- **Transcript caching** — the transcript is cached to `temp/transcript_cache/` keyed
  by file + model size. If you re-run the app on the *same* video (e.g. just to try
  different subtitle colors or clip lengths), it reuses the cached transcript instead
  of re-transcribing — this step alone usually takes 90%+ of the total time, so re-runs
  become nearly instant. Uncheck "Reuse transcript" in the UI to force a fresh one.
- **"Fast render mode"** checkbox — switches ffmpeg's encode preset from `veryfast` to
  `ultrafast` for the clip export step. Slightly larger file sizes, noticeably faster.

Practical tips for an hour-long video:
- Use the `tiny` or `base` Whisper model for a first pass — `small`/`medium` are more
  accurate but take meaningfully longer, especially on CPU.
- If you have an NVIDIA GPU, install CUDA-enabled `torch` (see Step 4) — faster-whisper
  will automatically use it and be dramatically faster than CPU.
- If you're just iterating on subtitle styling/colors, leave "Reuse transcript" checked
  so you only pay the transcription cost once per video.

## 7. Troubleshooting

- **`ffmpeg: command not found` / clips fail to render** → ffmpeg isn't on PATH, see Step 2.
- **Very slow transcription** → use a smaller Whisper model (`tiny` or `base`), or install
  a CUDA-enabled torch build if you have an NVIDIA GPU.
- **Subtitles show as boxes/garbled text** → the font you picked isn't installed on
  Windows; pick a standard one (Arial, Verdana) or install the font first.
- **First run is slow** → Whisper downloads the model weights once and caches them
  (in `%USERPROFILE%\.cache\whisper`); subsequent runs are much faster to start.
