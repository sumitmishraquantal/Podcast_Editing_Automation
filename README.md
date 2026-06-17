# Reel Studio — Automated Podcast Reel Pipeline

Turns raw podcast clips into finished vertical Instagram reels — fully automated,
from Google Drive ingest to delivered output. Fetches clips from Drive, merges,
transcribes, scores with mood-matched music + transition SFX, adds motion, burns
kinetic captions, runs objective QC, and archives the result back to Drive and
locally — with no manual steps once clips are uploaded.

Output spec: **1080×1920, 30 fps, −14 LUFS, true peak ≤ −1 dBTP, H.264/AAC MP4.**

---

## The automated flow

```
Google Drive inbox  →  fetch  →  merge → transcribe → sound → effects → captions → finalize  →  QC  →  archive
   (you upload clips)                    (6-stage pipeline)                              (gate)   (Drive + local)
```

One command runs the whole thing for every client:

```bash
python run_all.py
```

This is what the scheduled Routine (or a cron job) calls.

---

## How the pieces fit

| Script | Role |
|--------|------|
| `run_all.py` | Entry point. Finds every Drive client with clips waiting, runs `run_client.py` for each, prints a summary. |
| `run_client.py` | One client end-to-end: fetch → pipeline → QC → self-correct → archive (only if QC passes). |
| `rclone_sync.py` | Google Drive sync: `fetch` (download inbox), `archive` (move clips to done/, upload reel). |
| `pipeline.py` | The 6-stage video pipeline (merge, transcribe, sound, effects, captions, finalize). |
| `reel_captions.py` | Caption rendering + audio engine (imported by pipeline). |
| `merge_reel.py` | Clip conform + merge (called by the merge stage). |
| `qc_check.py` | Objective QC → writes `REVIEW.md`. |

### The 6 pipeline stages

| Stage | Does | Output |
|-------|------|--------|
| merge | Conforms clips to 1080×1920/30fps, loudness-matches, trims silence, concatenates | `01_merged.mp4`, `cuts.json` |
| transcribe | ElevenLabs Scribe → word-level timestamps | `words.json` |
| sound | Mood-matched music bed (ducked) + whoosh on each seam | `03_scored.m4a` |
| effects | Subtle Ken-Burns, zoom punch on up to 4 impact words, soft seam blur | `04_effects.mp4` |
| captions | Kinetic captions burned LAST (1–2 words, no overlap) | `05_captioned.mp4` |
| finalize | Delivery encode (CRF 19, faststart, final loudness pass) | `final.mp4` |

---

## Prerequisites

| Tool | Windows | macOS |
|------|---------|-------|
| Python 3.10+ | python.org | `brew install python` |
| ffmpeg (+ffprobe) | `winget install ffmpeg` | `brew install ffmpeg` |
| rclone | `winget install Rclone.Rclone` | `brew install rclone` |
| Git | git-scm.com | `brew install git` |

---

## Setup (one time)

```bash
git clone https://github.com/YOUR_ORG/reel-studio.git
cd reel-studio
pip install -r requirements.txt
```

Set the ElevenLabs key (transcribe + sound need it):

```powershell
# Windows
setx ELEVENLABS_API_KEY "your_key_here"
```
```bash
# macOS / Linux
export ELEVENLABS_API_KEY="your_key_here"
```

### Connect Google Drive (rclone)

One-time interactive auth. Run `rclone config` and create a remote **named exactly `gdrive`**:

```
n) new remote → name: gdrive → storage: drive → scope: 1 (full)
leave client_id/secret blank → auto config: y → log in via browser
configure as team drive: n (unless using a Shared Drive)
```

Verify it works:

```bash
rclone lsd gdrive:reel-projects
```

> **rclone discovery:** the scripts auto-find rclone even if it isn't on PATH
> (they check winget/scoop/choco/standard install locations). If rclone lives
> somewhere unusual, set `RCLONE_EXE` to its full path. This matters because
> scheduled runners (the Routine, cron) don't always inherit your PATH.

---

## Google Drive structure

```
reel-projects/                 ← the root the scripts watch
└── <CLIENT_NAME>/             ← one folder per client
    ├── clip1.mp4              ← INBOX: upload new clips here
    ├── clip2.mp4
    └── done/                  ← archive (scripts manage this — don't touch)
        ├── Videos/
        │   └── Video_<timestamp>/   ← raw clips, moved here after a successful run
        └── Processed_Video/
            └── Processed_<timestamp>.mp4   ← finished reel
```

**To add work:** upload clips into a client's top-level folder on Drive. That's it.
Drive is the single source of truth for inputs — never drop clips in the local
`raw/` folder, as it is wiped and re-mirrored from Drive on every run.

After a successful run, the raw clips **move** into `done/Videos/Video_<timestamp>/`
(nothing is deleted), and the reel lands in both `done/Processed_Video/` on Drive
and `delivered/<CLIENT>/` locally. The shared timestamp links each raw set to the
reel it produced.

---

## Usage

```bash
# Process every client with clips waiting (what the Routine runs):
python run_all.py

# Process one specific client:
python run_client.py <CLIENT>

# Lower-level, if needed:
python rclone_sync.py list                # show Drive clients
python rclone_sync.py fetch <CLIENT>       # download inbox -> local raw/
python pipeline.py projects/<CLIENT> --all # run the 6 stages locally
python qc_check.py projects/<CLIENT>       # objective QC -> REVIEW.md
python rclone_sync.py archive <CLIENT>     # archive (only after a good run)
```

---

## Quality control

`qc_check.py` writes `REVIEW.md` with a verdict and findings.

**Objective (pass/fail — block delivery if failed):** duration 12–90s, loudness
−16…−12 LUFS, true peak ≤ −0.5 dBTP, no black frames, no caption overlap,
caption tags well-formed, music bed audible.

**Flags (reported, do NOT block):** whoosh seam levels, and anything subjective —
music/SFX feel, transition look, caption taste. These are for a human to review.

### Delivery gate (strict)

`run_client.py` archives **only if QC passes** (`SHIPPABLE`). If objective checks
fail, it self-corrects (re-runs the relevant stage, max 2 attempts), and if still
failing, it does **not** deliver — the clips stay in the Drive inbox to retry on
the next run. A flawed reel never reaches the client.

> Always watch delivered reels for the subjective flags before publishing —
> QC catches measurable defects, not aesthetic ones.

---

## Scheduled / autonomous runs

Because everything is plain Python + ffmpeg + rclone, it runs unattended:

```bash
# cron: every night, process whatever is waiting on Drive
0 2 * * * cd /path/to/reel-studio && python run_all.py
```

External runtime dependencies: the ElevenLabs API key and rclone Drive auth.

> **Headless note:** scheduled runners don't inherit your interactive shell's
> PATH/env. The scripts auto-discover rclone, but ensure `ELEVENLABS_API_KEY` is
> set machine-wide (or in the job's environment) and that the Python used has
> `requests` installed.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `rclone is not installed or not on PATH` | Runner can't see rclone | Scripts auto-discover it; if not, set `RCLONE_EXE` to the full path |
| `No module named requests` | Wrong Python / venv not active | `pip install requests` for the Python the runner uses |
| transcribe/sound fail immediately | `ELEVENLABS_API_KEY` not set | Set it; reopen the terminal |
| `can't sync or move files on overlapping remotes` | (fixed) archive moved a dir into itself | Already handled via per-file moveto |
| Client skipped, "inbox empty" | All clips already archived to done/ | Upload new clips to the client's Drive folder |
| Final video has no motion | effects stage skipped | Use `--all` or `run_client.py`, not partial stages |

---

## What's intentionally out of scope

Intro cards, separate thumbnails, extra caption color variants — future add-ons,
not part of the current pipeline.