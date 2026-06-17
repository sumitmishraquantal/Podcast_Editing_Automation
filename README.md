# Reel Studio — Automated Podcast Reel Pipeline

Turns raw podcast clips into a finished, vertical Instagram reel: merges clips,
transcribes speech, scores it with mood-matched background music and transition
SFX, adds subtle motion, burns kinetic captions, and delivers a spec-compliant
`final.mp4` — with an objective QC pass at the end.

Output spec: **1080×1920, 30 fps, −14 LUFS, true peak ≤ −1 dBTP, H.264/AAC MP4.**

---

## How it works

The pipeline runs in six ordered stages. Each stage reads the previous stage's
output, so order matters.

| # | Stage | What it does | Output |
|---|-------|--------------|--------|
| 1 | `merge` | Conforms every raw clip to 1080×1920/30fps, loudness-matches each to −14 LUFS, trims edge silence, concatenates into one reel | `01_merged.mp4`, `cuts.json` |
| 2 | `transcribe` | ElevenLabs Scribe → word-level timestamps (caption + zoom source) | `words.json` |
| 3 | `sound` | Detects mood from transcript, generates a ducked music bed + a whoosh on each seam, normalizes to −14 LUFS | `03_scored.m4a` |
| 4 | `effects` | Subtle Ken-Burns push, zoom punch on up to 4 impact words, soft blur on each seam | `04_effects.mp4` |
| 5 | `captions` | Burns kinetic captions LAST (1–2 words at a time, never overlapping) onto the effects video | `05_captioned.mp4` |
| 6 | `finalize` | Delivery encode: CRF 19, faststart, final loudness pass | `final.mp4` |

A separate `qc_check.py` then measures the result and writes `REVIEW.md`.

---

## Prerequisites

Install these on any machine before first use:

| Tool | Windows | macOS |
|------|---------|-------|
| **Python 3.10+** | [python.org](https://python.org) | `brew install python` |
| **ffmpeg** (with ffprobe) | `winget install ffmpeg` | `brew install ffmpeg` |
| **Git** | [git-scm.com](https://git-scm.com) | `brew install git` |

Verify they're on your PATH:

```bash
python --version
ffmpeg -version
ffprobe -version
```

---

## Setup (one time)

```bash
# 1. Clone
git clone https://github.com/YOUR_ORG/reel-studio.git
cd reel-studio

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Set your ElevenLabs API key (needed for transcribe + sound stages)
```

**Windows (PowerShell):**
```powershell
setx ELEVENLABS_API_KEY "your_key_here"
# close and reopen the terminal, then confirm:
echo $env:ELEVENLABS_API_KEY
```

**macOS / Linux:**
```bash
export ELEVENLABS_API_KEY="your_key_here"
# add the line above to ~/.zshrc or ~/.bashrc to persist it
```

Get the key from your ElevenLabs account → Profile → API Keys.

---

## Project structure

Each reel is one "project" folder. Clips always go in a subfolder named exactly
`raw`. The pipeline writes everything else into `edit/`.

```
reel-studio/
├── pipeline.py            # orchestrator
├── reel_captions.py       # captions + audio engine
├── merge_reel.py          # clip conform + merge
├── qc_check.py            # objective QC → REVIEW.md
├── fonts/                 # caption fonts (8 .ttf)
├── requirements.txt
├── README.md
└── projects/              # ← git-ignored; your footage lives here
    └── <PROJECT_NAME>/
        ├── raw/           # ← put .mp4 / .mov clips here (never modified)
        └── edit/          # ← all pipeline output (safe to delete & regenerate)
            └── final.mp4
```

> **Note:** `projects/` is git-ignored — raw footage and renders never get
> committed. Only the code, fonts, and docs are tracked.

---

## Usage

Add a project, then run all six stages in one pass:

```bash
# create a project and add clips
mkdir -p projects/MY_REEL/raw
# copy your .mp4 / .mov files into projects/MY_REEL/raw/

# run the whole pipeline
python pipeline.py projects/MY_REEL --all

# objective QC
python qc_check.py projects/MY_REEL
```

Result: `projects/MY_REEL/edit/final.mp4` plus `REVIEW.md`.

### Running one stage at a time

Useful for debugging or re-running just one step:

```bash
python pipeline.py projects/MY_REEL --stage merge
python pipeline.py projects/MY_REEL --stage transcribe
python pipeline.py projects/MY_REEL --stage sound
python pipeline.py projects/MY_REEL --stage effects
python pipeline.py projects/MY_REEL --stage captions
python pipeline.py projects/MY_REEL --stage finalize
```

> Stages depend on earlier outputs. If you re-run `effects`, also re-run
> `captions` and `finalize` afterward, since they build on top of it.

`--restart` wipes the saved stage state and starts the project clean.

---

## Quality control & what gets auto-checked

`qc_check.py` writes `REVIEW.md` with a verdict (`SHIPPABLE` / `BLOCKED`) and two
kinds of findings.

**Objective (measured, pass/fail):**
- Duration 12–90 s
- Loudness within −16…−12 LUFS
- True peak ≤ −0.5 dBTP
- No black frames
- No overlapping captions
- Caption tags well-formed
- Music bed audible

**Subjective (flagged for a human — the tool cannot see or hear video):**
- Whether music/SFX fit the mood
- Whether transitions and motion look good
- Whether the right words are emphasised
- Overall caption taste

> Always watch `final.mp4` yourself before publishing. QC catches measurable
> defects, not aesthetic ones.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No clips in ...\raw` | Wrong path, or clips not in a `raw` subfolder | Pass the full project path; ensure clips are in `projects/<NAME>/raw/` |
| transcribe/sound fails immediately | `ELEVENLABS_API_KEY` not set in this terminal | Set it, then **open a new terminal** |
| Final video has no motion | `effects` stage was skipped | Run `effects` before `captions` |
| Captions look like a plain default font | Font internal name mismatch / fonts not found | Confirm the `fonts/` folder is present; pass `--fontsdir` if needed |
| ffmpeg/ffprobe "not recognized" | Not on PATH | Reinstall ffmpeg and reopen the terminal |

---

## What's intentionally out of scope

Intro cards, separate thumbnails, and extra caption color variants are **not**
part of the current pipeline. They're future add-ons.

---

## Deploying for automated / scheduled runs

Because the pipeline is plain Python + ffmpeg, it can run unattended (e.g. a cron
job on a VPS) with no interactive tooling:

```bash
# nightly: process any project that has clips
0 2 * * * cd /path/to/reel-studio && python pipeline.py projects/CLIENT --all && python qc_check.py projects/CLIENT
```

The only external runtime dependency is the ElevenLabs API key.