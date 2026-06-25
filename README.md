# Reel Studio — Automated Podcast Reel Pipeline

Turns raw podcast clips into finished vertical Instagram reels and posts them —
fully automated, from Google Drive ingest to a live Instagram post. The pipeline
fetches clips from Drive, merges them, transcribes, scores with mood-matched
music + transition SFX, adds motion, burns kinetic captions, runs objective QC,
generates a caption + hashtags, and delivers the reel for one-click email
approval. Approving posts the reel to Instagram and archives the source clips;
**Rerun** re-edits a fresh version.

**Output spec:** 1080×1920, 30 fps, −14 LUFS, true peak ≤ −0.5 dBTP, H.264/AAC MP4.

---

## The big picture — two halves

The system is split into two independent halves by design:

1. **The approval service** (`start_services.py`) — a small always-on web service
   (Flask + a cloudflared tunnel) that receives the Approve/Rerun button clicks
   from the email and acts on them. You start it once and leave it running.

2. **The pipeline** (`run_all.py`) — a batch job you run whenever there are new
   clips (manually, or on the hourly Routine). It edits every client's clips and
   emails you approval requests.

They are deliberately separate: a click can arrive minutes or hours after the
pipeline finishes, so the service must outlive any single pipeline run.

```
┌─ START ONCE, LEAVE RUNNING ──────────────────────────────────────────────┐
│  python start_services.py                                                 │
│    → Flask approval server (port 8000) + cloudflared tunnel               │
│    → auto-writes the public tunnel URL into .env (APPROVAL_BASE_URL)      │
└───────────────────────────────────────────────────────────────────────────┘

┌─ RUN WHEN THERE ARE NEW CLIPS (manual / hourly Routine) ─────────────────┐
│  python run_all.py                                                        │
│    → for each client with clips: fetch → edit → QC → caption → PREVIEW    │
│    → emails you an approval request per delivered reel                     │
└───────────────────────────────────────────────────────────────────────────┘
                                   │
                      email arrives with two buttons
                                   │
            ┌──────────────────────┴──────────────────────┐
       ✓ Approve                                      ↻ Rerun
            │                                              │
   finalize (move clips → done/)              re-edit via the pipeline
   then POST to Instagram                     (clips stay put), fresh email
```

---

## The end-to-end flow in detail

1. **You upload clips** to a client's inbox folder on Google Drive.
2. **`run_all.py` runs** (you, or the hourly Routine). For each client with clips:
   - **fetch** — mirror the Drive inbox into local `projects/<CLIENT>/raw/`
   - **pipeline** — the 6 stages produce `edit/final.mp4`
   - **QC** — objective checks; self-correct retries failing stages up to twice
   - **caption** — Groq writes a caption + tiered hashtags to `edit/caption.json`
   - **preview** — upload the reel to Drive for a watch link, write the share
     link into `caption.json`. **The raw clips stay in the inbox** (not archived
     yet — so a Rerun still has its source, and nothing is committed until you
     approve).
3. **An approval email is sent** per delivered reel: transcript, suggested
   caption + hashtags, a **Watch the reel** link, and **Approve** / **Rerun**
   buttons.
4. **You click a button:**
   - **Approve** → the service records the decision (shared state — a second
     person who clicks later sees "already approved by X"), moves the source
     clips to `done/Videos/`, then posts the reel to Instagram in the background.
   - **Rerun** → the service re-runs the pipeline immediately for that client
     (the clips are still in the inbox), overwrites the preview, and emails a
     fresh approval. Used when you want a different edit.

---

## How the pieces fit

| Script | Role |
|--------|------|
| `start_services.py` | **Launcher for the always-on half.** Starts the Flask approval server + the cloudflared tunnel, auto-captures the tunnel URL into `.env`. Ctrl+C stops both. |
| `approval_server.py` | Flask app. Routes: `/approve`, `/rerun`, `/status`, `/health`. Records decisions to `decisions.json` (shared state). On approve: finalize + post. On rerun: re-edit in the background. |
| `instagram_post.py` | Instagram Graph API posting: Cloudinary upload → REELS container → poll until FINISHED → publish. |
| `approval_mail.py` | Builds + sends the approval email (transcript, caption, hashtags, Watch button, Approve/Rerun buttons). |
| `run_all.py` | **Entry point for the batch half.** Finds every Drive client with clips, runs `run_client.py` for each, then emails approvals. Pre-flights the approval server. |
| `run_client.py` | One client end-to-end: fetch → pipeline → QC → self-correct → caption → preview (deliver for approval). |
| `rclone_sync.py` | Google Drive sync. `fetch` (download inbox), `preview` (upload reel + share link, clips stay), `finalize` (move clips to done/ on approval). `archive` = preview + finalize (legacy). |
| `pipeline.py` | The 6-stage video pipeline (merge, transcribe, sound, effects, captions, finalize). |
| `reel_captions.py` | Caption rendering + audio engine, curated caption presets (imported by pipeline as `rc`). |
| `caption_gen.py` | Groq caption + tiered hashtags from the transcript → `caption.json`. |
| `merge_reel.py` | Clip conform + merge (called by the merge stage). |
| `qc_check.py` | Objective QC → writes `REVIEW.md`. |

### The 6 pipeline stages

| Stage | What it does |
|-------|--------------|
| **merge** | Conforms and joins the raw clips into one 1080×1920 reel; records the seam cut points. |
| **transcribe** | ElevenLabs speech-to-text → `words.json` (word-level timing). |
| **sound** | Picks a mood from the transcript, generates mood-matched background music (ducked under the voice) + a transition swoosh on each seam, all via ElevenLabs. |
| **effects** | Subtle Ken-Burns drift, a few zoom punches on impact words, and a soft blur on each seam to **hide the clip joins**. |
| **captions** | Burns kinetic word-by-word captions using one of the curated presets (see below). |
| **finalize** | Loudness + true-peak limiting to spec, black-frame check, writes `final.mp4`. |

---

## Caption presets (research-backed)

Instead of randomizing every styling option (which produced inconsistent results),
the captions stage picks one of three curated, mobile-optimized presets per reel.
All use bold sans-serif fonts (best readability on mobile) with a highlighted
keyword color — the dominant high-retention style for short-form in 2026.

| Preset | Font | Highlight | Case | Words/card |
|--------|------|-----------|------|------------|
| `clean_edu` | Montserrat Bold | yellow | mixed | 1 (word-by-word) |
| `bold_punch` | Anton | orange | UPPER | 1 (word-by-word) |
| `editorial` | Oswald | yellow | mixed | 2 (short phrase) |

> **Font note:** the bundled `fonts/Montserrat.ttf` was the *Thin* weight (wrong
> for captions, and its internal name was "Montserrat Thin"). It has been replaced
> with `fonts/Montserrat-Bold.ttf` (a proper static Bold instance named
> "Montserrat"). Keep that file in `fonts/`; do not re-add the thin one.

---

## Transitions & SFX

- **Seams (clip joins):** a soft blur + a quiet transition swoosh (ElevenLabs)
  on each join. The goal is to make the merge **invisible** — it should not look
  like separate clips were stitched together.
- One swoosh sound is generated per reel and reused on all seams, for a consistent,
  professional feel.

---

## Prerequisites

| Tool | Windows | macOS |
|------|---------|-------|
| Python 3.10+ | python.org | `brew install python` |
| ffmpeg (+ffprobe) | `winget install ffmpeg` | `brew install ffmpeg` |
| rclone | `winget install Rclone.Rclone` | `brew install rclone` |
| cloudflared | `winget install Cloudflare.cloudflared` | `brew install cloudflared` |
| Git | git-scm.com | `brew install git` |

---

## Setup (one time)

```bash
git clone https://github.com/YOUR_ORG/reel-studio.git
cd reel-studio
pip install -r requirements.txt
```

### Environment variables (`.env` in the repo root)

```dotenv
# ── Editing / transcription / captions ──────────────────────────────
ELEVENLABS_API_KEY=your_elevenlabs_key       # transcribe + music + SFX
GROQ_API_KEY=your_groq_key                    # caption + hashtags
GROQ_MODEL=llama-3.3-70b-versatile

# ── Instagram posting (Graph API) ───────────────────────────────────
IG_ACCESS_TOKEN=your_long_lived_graph_token
IG_BUSINESS_ID=17841421996308337
GRAPH_API_VERSION=v22.0

# ── Cloudinary (public video host for Instagram) ────────────────────
CLOUDINARY_CLOUD_NAME=dpptaeeiu
CLOUDINARY_UPLOAD_PRESET=instagram_n8n_post

# ── Approval email (Gmail SMTP) ─────────────────────────────────────
OWNER_EMAILS=you@example.com,teammate@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=youraddress@gmail.com
SMTP_PASSWORD=your_gmail_app_password
EMAIL_TRANSPORT=auto                          # auto | smtp | file
SEND_APPROVAL_EMAIL=true

# ── Approval service ────────────────────────────────────────────────
APPROVAL_PORT=8000
# APPROVAL_BASE_URL is written automatically by start_services.py
# CLOUDFLARED_EXE=C:\Program Files (x86)\cloudflared\cloudflared.exe   # if not on PATH
# RCLONE_EXE=...   # if rclone isn't on PATH

# ── Optional tuning ─────────────────────────────────────────────────
# CAPTION_HASHTAG_MIN=12
# CAPTION_HASHTAG_MAX=15
```

> The scripts auto-discover `rclone` and `cloudflared` even if they aren't on
> PATH (they check winget/scoop/choco/standard locations). This matters because
> scheduled runners (the Routine, cron) don't always inherit your PATH. Set
> `RCLONE_EXE` / `CLOUDFLARED_EXE` if either lives somewhere unusual.

### Connect Google Drive (rclone)

One-time interactive auth. Run `rclone config` and create a remote **named
exactly `gdrive`**:

```
n) new remote → name: gdrive → storage: drive → scope: 1 (full)
leave client_id/secret blank → auto config: y → log in via browser
configure as team drive: n (unless using a Shared Drive)
```

Verify:

```bash
rclone lsd gdrive:reel-projects
```

---

## Google Drive structure

```
reel-projects/                 ← the root the scripts watch
└── <CLIENT_NAME>/             ← one folder per client (e.g. TEST)
    ├── clip1.mp4              ← INBOX: upload new clips here
    ├── clip2.mp4
    └── done/                  ← archive (scripts manage this — don't touch)
        ├── Videos/
        │   └── Video_<timestamp>/        ← raw clips, moved here ON APPROVAL
        ├── Processed_Video/
        │   └── Processed_<timestamp>.mp4 ← finished reel (uploaded at preview)
        └── Thumbnails/
            └── Thumbnail_<timestamp>.png ← thumbnail, moved here on approval
```

**To add work:** upload clips into a client's top-level folder on Drive. That's it.
Drive is the single source of truth for inputs — never drop clips in the local
`raw/` folder, as it is wiped and re-mirrored from Drive on every run.

**Important timing change:** the reel is uploaded to `done/Processed_Video/` at
**preview** (so the email has a watch link), but the **raw clips stay in the
inbox until you approve.** Only on **Approve** are the clips moved to
`done/Videos/Video_<timestamp>/` and the thumbnail to `done/Thumbnails/`. This
is what lets **Rerun** re-edit from the same clips without recovering anything.

---

## Usage

### 1. Start the approval service (once, leave it running)

```bash
python start_services.py
```

This starts the Flask server + cloudflared tunnel and writes the public URL into
`.env` automatically. Leave the terminal open. Confirm it's live by visiting the
printed `…/health` URL — it should show `ok`.

> The free cloudflared tunnel URL **changes every restart**; `start_services.py`
> rewrites `.env` each time, so always start the service **before** running the
> pipeline, and don't restart it while approval emails are still un-clicked.

### 2. Run the pipeline (when there are new clips)

```bash
# Process every client with clips waiting (what the hourly Routine runs):
python run_all.py

# Process one specific client:
python run_client.py TEST
```

`run_all.py` pre-flights the approval server (warns if it's unreachable, so you
don't email dead buttons), processes each client, then emails approvals.

### 3. Approve or Rerun from the email

- **Approve** posts the reel to Instagram and archives the clips.
- **Rerun** re-edits a fresh version and emails you again.

### Lower-level commands (if needed)

```bash
python rclone_sync.py fetch    TEST   # download inbox clips
python rclone_sync.py preview  TEST   # upload reel + share link (clips stay)
python rclone_sync.py finalize TEST   # move clips to done/ (normally on approval)
python pipeline.py projects/TEST --all --restart   # run all 6 stages
python qc_check.py projects/TEST                    # QC only → REVIEW.md
python caption_gen.py TEST                          # caption + hashtags only
python instagram_post.py TEST            # post newest delivered reel (live!)
python instagram_post.py TEST --dry      # everything except the final publish
python instagram_post.py TEST 2026-06-18_1616   # post a specific reel by timestamp
```

---

## Quality control

`qc_check.py` writes `projects/<CLIENT>/edit/REVIEW.md` with a verdict:

- **SHIPPABLE** — passes all objective checks, no human-eye flags.
- **SHIPPABLE (with human-eye flags)** — passes objective checks; some things a
  machine can't judge are flagged for your eyes/ears (e.g. SFX feel).
- **BLOCKED — objective fail** — an objective check failed; the reel is **not**
  delivered. Clips stay in the inbox to retry next run.

### Objective gates (must pass to deliver)

| Check | Threshold |
|-------|-----------|
| duration | 12–90 s |
| loudness | −17 … −11 LUFS |
| true peak | ≤ −0.5 dBTP |
| black frames | none |
| caption overlap | none |

> **True-peak handling:** the finalize stage applies loudnorm (`TP=-1.5`) plus a
> true-peak-aware limiter (`alimiter=limit=-1.0dB:asc=1`) so measured true peak
> stays comfortably under the −0.5 dBTP gate. (An earlier sample-peak-only
> limiter let inter-sample peaks slip over the gate; this is fixed.)

### Self-correction

If QC fails, `run_client.py` re-runs the relevant stage (up to twice) before
giving up. If it still fails, the reel is not delivered and the clips remain in
the inbox for the next run.

---

## Scheduled / autonomous runs

The pipeline half is meant to run on a schedule. Either works:

```bash
# cron (macOS/Linux): every hour, process whatever is waiting on Drive
0 * * * * cd /path/to/reel-studio && /usr/bin/python3 run_all.py >> logs/run.log 2>&1
```

Or the **Claude Desktop Routine** (Windows): point it at the repo folder and have
it run `python run_all.py` on an hourly schedule.

Remember: the **approval service must already be running** (`start_services.py`)
for the email buttons to work when a click eventually arrives. The Routine only
runs the pipeline half — it does not start the service.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Approval buttons say "inactive" | `APPROVAL_BASE_URL` missing from `.env` or the reel has no timestamp. Start `start_services.py` first, then run the pipeline so the email is built with the live URL. |
| Clicking Approve does nothing | The approval service isn't running, or the tunnel URL in the email is stale (service restarted). Keep the service up; don't restart it while emails are outstanding. |
| `cloudflared`/`rclone` "not recognized" | Not on PATH in that shell. Set `CLOUDFLARED_EXE` / `RCLONE_EXE` in `.env`, or run from a shell where they resolve. |
| Reel BLOCKED on true peak | Should be fixed by the finalize limiter; if a specific reel still fails, lower the limiter ceiling further. |
| Caption font looks thin/wrong | Ensure `fonts/Montserrat-Bold.ttf` is present and the thin `Montserrat.ttf` is removed. |
| Instagram post fails on auth | `IG_ACCESS_TOKEN` expired or missing the `instagram_content_publish` permission. |
| Caption is the fallback, not Groq | `GROQ_API_KEY` missing/invalid — check `source` in `caption.json`. |

---

## What's intentionally out of scope

- **No live "trending" hashtags.** Captions use a tiered broad + niche + specific
  hashtag mix (the actual reach strategy), but neither the script nor the model
  can verify what is trending on Instagram *right now* — there is no live trends
  feed wired in. `caption_gen.py` has a `_live_tags()` hook to add one later.
- **The Rerun button re-edits via the Python pipeline, not the Claude Routine.**
  A button click cannot trigger the Routine ahead of its schedule, so Rerun runs
  the pipeline directly for an immediate fresh edit.
- **The free cloudflared tunnel is for local/testing use.** For a permanent,
  stable URL (so the service survives restarts without re-emailing), move to a
  VPS with a named cloudflare tunnel.