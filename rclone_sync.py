# #!/usr/bin/env python3
# """
# rclone_sync.py - Google Drive <-> local sync for the reel pipeline (Phase 1)

# Two operations, both standalone and testable on their own:

#   fetch <CLIENT>
#       - wipes the local projects/<CLIENT>/raw/ folder
#       - downloads the current top-level clips from
#         gdrive:reel-projects/<CLIENT>/  (the "inbox", excluding done/)
#         into projects/<CLIENT>/raw/
#       - Drive is the single source of truth for inputs.

#   archive <CLIENT>
#       - run this ONLY after a successful + QC-passing pipeline run
#       - moves the inbox clips on Drive into
#         gdrive:reel-projects/<CLIENT>/done/Videos/Video_<timestamp>/
#       - uploads the finished reel (projects/<CLIENT>/edit/final.mp4) to
#         gdrive:reel-projects/<CLIENT>/done/Processed_Video/Processed_<timestamp>.mp4
#       - also copies it locally to delivered/<CLIENT>/Processed_<timestamp>.mp4
#       - the <timestamp> ties the raw set to the reel it produced.

# Nothing is ever deleted on Drive: inbox clips are MOVED into the archive.

# Usage:
#     python rclone_sync.py fetch   <CLIENT>
#     python rclone_sync.py archive <CLIENT>
#     python rclone_sync.py list                 # list client folders on Drive

# Config via env vars (sensible defaults):
#     RCLONE_REMOTE   default "gdrive"
#     RCLONE_ROOT     default "reel-projects"
# """
# import argparse
# import os
# import shutil
# import subprocess
# import sys
# from datetime import datetime
# from pathlib import Path

# # ── config ────────────────────────────────────────────────────────────────────
# REMOTE = os.environ.get("RCLONE_REMOTE", "gdrive")
# ROOT   = os.environ.get("RCLONE_ROOT", "reel-projects")
# HERE   = Path(__file__).resolve().parent
# PROJECTS_DIR  = HERE / "projects"
# DELIVERED_DIR = HERE / "delivered"
# VIDEO_EXTS    = (".mp4", ".mov", ".MP4", ".MOV")

# def _resolve_rclone():
#     """Find the rclone executable portably (works on Windows, Mac, Linux, venv).

#     Order: RCLONE_EXE env override -> shutil.which on PATH -> 'rclone' as last resort.
#     shutil.which() handles the Windows .exe extension and searches PATH the same
#     way the shell does, which a bare subprocess(['rclone',...]) does not.
#     """
#     override = os.environ.get("RCLONE_EXE")
#     if override and Path(override).exists():
#         return override
#     found = shutil.which("rclone")
#     if found:
#         return found
#     return "rclone"  # last resort; will surface a clear error if truly missing

# RCLONE = _resolve_rclone()

# def drive_path(*parts):
#     """Build a remote path like gdrive:reel-projects/CLIENT/done"""
#     tail = "/".join(str(p).strip("/") for p in parts if p is not None and str(p) != "")
#     return f"{REMOTE}:{ROOT}" + (f"/{tail}" if tail else "")

# def run(cmd, capture=True):
#     """Run an rclone command. cmd[0] is replaced with the resolved rclone path."""
#     if cmd and cmd[0] == "rclone":
#         cmd = [RCLONE] + cmd[1:]
#     print(f"  $ {' '.join(cmd)}")
#     r = subprocess.run(cmd, capture_output=capture, text=True)
#     if r.returncode != 0:
#         sys.stderr.write((r.stderr or "")[-1500:] + "\n")
#         raise RuntimeError(f"rclone command failed (exit {r.returncode}): {' '.join(cmd)}")
#     return r

# def check_rclone():
#     try:
#         subprocess.run([RCLONE, "version"], capture_output=True, text=True, check=True)
#     except (FileNotFoundError, subprocess.CalledProcessError):
#         sys.exit("ERROR: rclone is not installed or not on PATH.\n"
#                  "  Install it (winget install Rclone.Rclone) and reopen the terminal,\n"
#                  "  or set RCLONE_EXE to the full path of rclone.exe.")

# def timestamp():
#     return datetime.now().strftime("%Y-%m-%d_%H%M")

# # ── operations ──────────────────────────────────────────────────────────────────
# def list_clients():
#     """Print the client folders under the Drive root."""
#     check_rclone()
#     print(f"Client folders under {drive_path()}:")
#     r = run(["rclone", "lsf", drive_path(), "--dirs-only"])
#     names = [ln.strip().rstrip("/") for ln in r.stdout.splitlines() if ln.strip()]
#     for n in names:
#         print(f"  - {n}")
#     if not names:
#         print("  (none)")
#     return names

# def inbox_clips(client):
#     """Return list of top-level clip filenames in the Drive inbox (excludes done/)."""
#     r = run(["rclone", "lsf", drive_path(client),
#              "--files-only", "--max-depth", "1"])
#     return [ln.strip() for ln in r.stdout.splitlines()
#             if ln.strip().endswith(VIDEO_EXTS)]

# def fetch(client):
#     """Wipe local raw/, then download the Drive inbox clips into it."""
#     check_rclone()
#     raw = PROJECTS_DIR / client / "raw"

#     clips = inbox_clips(client)
#     if not clips:
#         print(f"  fetch: no clips in inbox for '{client}' — nothing to do.")
#         return []

#     # Wipe local raw/ so it is a fresh mirror of the Drive inbox (Meaning A)
#     if raw.exists():
#         shutil.rmtree(raw)
#     raw.mkdir(parents=True, exist_ok=True)

#     # Copy ONLY top-level clips (max-depth 1 excludes done/)
#     print(f"  fetch: downloading {len(clips)} clip(s) for '{client}' -> {raw}")
#     run(["rclone", "copy", drive_path(client), str(raw),
#          "--max-depth", "1",
#          "--include", "*.mp4", "--include", "*.mov",
#          "--include", "*.MP4", "--include", "*.MOV"])

#     got = sorted(p.name for p in raw.iterdir() if p.suffix in VIDEO_EXTS)
#     print(f"  fetch: raw/ now has {len(got)} clip(s): {got}")
#     return got

# def archive(client):
#     """After a successful run: archive raw clips + finished reel, versioned by timestamp."""
#     check_rclone()
#     ts    = timestamp()
#     edit  = PROJECTS_DIR / client / "edit"
#     final = edit / "final.mp4"

#     if not final.exists():
#         sys.exit(f"ERROR: {final} not found. Archive only runs AFTER a successful pipeline run.")

#     clips = inbox_clips(client)

#     # 1. Move inbox clips -> done/Videos/Video_<ts>/   (MOVE, not delete)
#     #    We use per-file `moveto` (one named source -> one named dest) instead of a
#     #    directory `move`. A directory move fails here because the destination
#     #    (done/Videos/...) is nested INSIDE the source (TEST/), which rclone blocks
#     #    as "overlapping remotes". Per-file moveto sidesteps that check entirely.
#     if clips:
#         dest_dir = drive_path(client, "done", "Videos", f"Video_{ts}")
#         print(f"  archive: moving {len(clips)} raw clip(s) -> {dest_dir}")
#         for fname in clips:
#             src = drive_path(client) + f"/{fname}"
#             dst = f"{dest_dir}/{fname}"
#             run(["rclone", "moveto", src, dst])
#     else:
#         print("  archive: no inbox clips to move (already archived?).")

#     # 2. Upload finished reel -> done/Processed_Video/Processed_<ts>.mp4
#     proc_name = f"Processed_{ts}.mp4"
#     proc_dest = drive_path(client, "done", "Processed_Video")
#     print(f"  archive: uploading reel -> {proc_dest}/{proc_name}")
#     print("  archive: (large uploads can take several minutes on slow connections)")
#     # rclone copyto renames in one step; -P streams live progress so a slow
#     # upload looks healthy instead of hung. --stats forces periodic updates.
#     run(["rclone", "copyto", str(final), f"{proc_dest}/{proc_name}",
#          "-P", "--stats", "5s"], capture=False)

#     # 3. Local copy -> delivered/<client>/Processed_<ts>.mp4
#     local_dir = DELIVERED_DIR / client
#     local_dir.mkdir(parents=True, exist_ok=True)
#     local_out = local_dir / proc_name
#     shutil.copy2(final, local_out)
#     print(f"  archive: local copy -> {local_out}")

#     print(f"  archive: done. Timestamp {ts} links the raw set to the reel.")
#     return ts

# # ── cli ───────────────────────────────────────────────────────────────────────
# def main():
#     ap = argparse.ArgumentParser(description="Google Drive sync for the reel pipeline")
#     ap.add_argument("op", choices=["fetch", "archive", "list"])
#     ap.add_argument("client", nargs="?", help="client/project folder name on Drive")
#     a = ap.parse_args()

#     if a.op == "list":
#         list_clients(); return
#     if not a.client:
#         sys.exit(f"ERROR: '{a.op}' needs a client name. e.g. python rclone_sync.py {a.op} TEST_CLIENT")

#     if a.op == "fetch":
#         fetch(a.client)
#     elif a.op == "archive":
#         archive(a.client)

# if __name__ == "__main__":
#     main()





#!/usr/bin/env python3
"""
rclone_sync.py - Google Drive <-> local sync for the reel pipeline (Phase 1)

Two operations, both standalone and testable on their own:

  fetch <CLIENT>
      - wipes the local projects/<CLIENT>/raw/ folder
      - downloads the current top-level clips from
        gdrive:reel-projects/<CLIENT>/  (the "inbox", excluding done/)
        into projects/<CLIENT>/raw/
      - Drive is the single source of truth for inputs.

  archive <CLIENT>
      - run this ONLY after a successful + QC-passing pipeline run
      - moves the inbox clips on Drive into
        gdrive:reel-projects/<CLIENT>/done/Videos/Video_<timestamp>/
      - uploads the finished reel (projects/<CLIENT>/edit/final.mp4) to
        gdrive:reel-projects/<CLIENT>/done/Processed_Video/Processed_<timestamp>.mp4
      - also copies it locally to delivered/<CLIENT>/Processed_<timestamp>.mp4
      - the <timestamp> ties the raw set to the reel it produced.

Nothing is ever deleted on Drive: inbox clips are MOVED into the archive.

Usage:
    python rclone_sync.py fetch   <CLIENT>
    python rclone_sync.py archive <CLIENT>
    python rclone_sync.py list                 # list client folders on Drive

Config via env vars (sensible defaults):
    RCLONE_REMOTE   default "gdrive"
    RCLONE_ROOT     default "reel-projects"
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── config ────────────────────────────────────────────────────────────────────
REMOTE = os.environ.get("RCLONE_REMOTE", "gdrive")
ROOT   = os.environ.get("RCLONE_ROOT", "reel-projects")
HERE   = Path(__file__).resolve().parent
PROJECTS_DIR  = HERE / "projects"
DELIVERED_DIR = HERE / "delivered"
VIDEO_EXTS    = (".mp4", ".mov", ".MP4", ".MOV")
THUMB_EXTS    = (".png", ".PNG")

def _resolve_rclone():
    """Find the rclone executable portably (works on Windows, Mac, Linux, venv).

    Order:
      1. RCLONE_EXE env override (if set and exists)
      2. shutil.which on PATH
      3. known install locations (winget on Windows) via glob
      4. 'rclone' as last resort (surfaces a clear error if truly missing)

    Step 3 matters because automated runners (the Routine, cron, services) often
    do NOT inherit the user's PATH or env vars, so rclone can be installed yet
    invisible. Globbing the winget package dir finds it regardless of version.
    """
    override = os.environ.get("RCLONE_EXE")
    if override and Path(override).exists():
        return override
    found = shutil.which("rclone")
    if found:
        return found
    # Known install locations (version-agnostic glob)
    import glob
    home = Path.home()
    patterns = [
        str(home / "AppData/Local/Microsoft/WinGet/Packages/Rclone.Rclone_*/rclone-*/rclone.exe"),
        str(home / "scoop/apps/rclone/current/rclone.exe"),
        r"C:\ProgramData\chocolatey\bin\rclone.exe",
        r"C:\rclone\rclone.exe",
        "/usr/bin/rclone", "/usr/local/bin/rclone", "/opt/homebrew/bin/rclone",
    ]
    for pat in patterns:
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    return "rclone"  # last resort

RCLONE = _resolve_rclone()

def drive_path(*parts):
    """Build a remote path like gdrive:reel-projects/CLIENT/done"""
    tail = "/".join(str(p).strip("/") for p in parts if p is not None and str(p) != "")
    return f"{REMOTE}:{ROOT}" + (f"/{tail}" if tail else "")

def run(cmd, capture=True):
    """Run an rclone command. cmd[0] is replaced with the resolved rclone path."""
    if cmd and cmd[0] == "rclone":
        cmd = [RCLONE] + cmd[1:]
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if r.returncode != 0:
        sys.stderr.write((r.stderr or "")[-1500:] + "\n")
        raise RuntimeError(f"rclone command failed (exit {r.returncode}): {' '.join(cmd)}")
    return r

def check_rclone():
    try:
        subprocess.run([RCLONE, "version"], capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.exit("ERROR: rclone is not installed or not on PATH.\n"
                 "  Install it (winget install Rclone.Rclone) and reopen the terminal,\n"
                 "  or set RCLONE_EXE to the full path of rclone.exe.")

def timestamp():
    return datetime.now().strftime("%Y-%m-%d_%H%M")

# ── operations ──────────────────────────────────────────────────────────────────
def list_clients():
    """Print the client folders under the Drive root."""
    check_rclone()
    print(f"Client folders under {drive_path()}:")
    r = run(["rclone", "lsf", drive_path(), "--dirs-only"])
    names = [ln.strip().rstrip("/") for ln in r.stdout.splitlines() if ln.strip()]
    for n in names:
        print(f"  - {n}")
    if not names:
        print("  (none)")
    return names

def inbox_clips(client):
    """Return list of top-level clip filenames in the Drive inbox (excludes done/)."""
    r = run(["rclone", "lsf", drive_path(client),
             "--files-only", "--max-depth", "1"])
    return [ln.strip() for ln in r.stdout.splitlines()
            if ln.strip().endswith(VIDEO_EXTS)]

def inbox_thumbnails(client):
    """Return top-level .png filenames in the Drive inbox (excludes done/)."""
    r = run(["rclone", "lsf", drive_path(client),
             "--files-only", "--max-depth", "1"])
    return sorted(ln.strip() for ln in r.stdout.splitlines()
                  if ln.strip().endswith(THUMB_EXTS))

def fetch(client):
    """Wipe local raw/, then download the Drive inbox clips into it."""
    check_rclone()
    raw = PROJECTS_DIR / client / "raw"

    clips = inbox_clips(client)
    if not clips:
        print(f"  fetch: no clips in inbox for '{client}' — nothing to do.")
        return []

    # Wipe local raw/ so it is a fresh mirror of the Drive inbox (Meaning A)
    if raw.exists():
        shutil.rmtree(raw)
    raw.mkdir(parents=True, exist_ok=True)

    thumbs = inbox_thumbnails(client)

    # Copy ONLY top-level clips + thumbnails (max-depth 1 excludes done/)
    print(f"  fetch: downloading {len(clips)} clip(s) for '{client}' -> {raw}")
    run(["rclone", "copy", drive_path(client), str(raw),
         "--max-depth", "1",
         "--include", "*.mp4", "--include", "*.mov",
         "--include", "*.MP4", "--include", "*.MOV",
         "--include", "*.png", "--include", "*.PNG"])

    got = sorted(p.name for p in raw.iterdir() if p.suffix in VIDEO_EXTS)
    print(f"  fetch: raw/ now has {len(got)} clip(s): {got}")
    if thumbs:
        print(f"  fetch: thumbnail(s) in inbox: {thumbs}")
    return got

def archive(client):
    """After a successful run: archive raw clips + finished reel, versioned by timestamp."""
    check_rclone()
    ts    = timestamp()
    edit  = PROJECTS_DIR / client / "edit"
    final = edit / "final.mp4"

    if not final.exists():
        sys.exit(f"ERROR: {final} not found. Archive only runs AFTER a successful pipeline run.")

    clips = inbox_clips(client)
    thumbs = inbox_thumbnails(client)
    thumb_name = f"Thumbnail_{ts}.png" if thumbs else ""

    # 1. Move inbox clips -> done/Videos/Video_<ts>/   (MOVE, not delete)
    #    We use per-file `moveto` (one named source -> one named dest) instead of a
    #    directory `move`. A directory move fails here because the destination
    #    (done/Videos/...) is nested INSIDE the source (TEST/), which rclone blocks
    #    as "overlapping remotes". Per-file moveto sidesteps that check entirely.
    if clips:
        dest_dir = drive_path(client, "done", "Videos", f"Video_{ts}")
        print(f"  archive: moving {len(clips)} raw clip(s) -> {dest_dir}")
        for fname in clips:
            src = drive_path(client) + f"/{fname}"
            dst = f"{dest_dir}/{fname}"
            run(["rclone", "moveto", src, dst])
    else:
        print("  archive: no inbox clips to move (already archived?).")

    # 1b. Move inbox thumbnail(s) -> done/Thumbnails/Thumbnail_<ts>.png
    #     If multiple PNGs exist, use the first alphabetically and warn.
    local_thumb = None
    if thumbs:
        if len(thumbs) > 1:
            print(f"  archive: multiple thumbnails found {thumbs}; using '{thumbs[0]}'")
        src_name = thumbs[0]
        thumb_dest = drive_path(client, "done", "Thumbnails", thumb_name)
        print(f"  archive: moving thumbnail '{src_name}' -> {thumb_dest}")
        run(["rclone", "moveto", drive_path(client) + f"/{src_name}", thumb_dest])
        raw_thumb = PROJECTS_DIR / client / "raw" / src_name
        if raw_thumb.exists():
            local_thumb = raw_thumb

    # 2. Upload finished reel -> done/Processed_Video/Processed_<ts>.mp4
    proc_name = f"Processed_{ts}.mp4"
    proc_dest = drive_path(client, "done", "Processed_Video")
    print(f"  archive: uploading reel -> {proc_dest}/{proc_name}")
    print("  archive: (large uploads can take several minutes on slow connections)")
    # rclone copyto renames in one step; -P streams live progress so a slow
    # upload looks healthy instead of hung. --stats forces periodic updates.
    run(["rclone", "copyto", str(final), f"{proc_dest}/{proc_name}",
         "-P", "--stats", "5s"], capture=False)

    # 3. Local copy -> delivered/<client>/Processed_<ts>.mp4
    local_dir = DELIVERED_DIR / client
    local_dir.mkdir(parents=True, exist_ok=True)
    local_out = local_dir / proc_name
    shutil.copy2(final, local_out)
    print(f"  archive: local copy -> {local_out}")

    # 3b. Local thumbnail copy -> delivered/<client>/Thumbnail_<ts>.png
    local_thumb_out = None
    if thumb_name:
        local_thumb_out = local_dir / thumb_name
        if local_thumb and local_thumb.exists():
            shutil.copy2(local_thumb, local_thumb_out)
            print(f"  archive: thumbnail copy -> {local_thumb_out}")
        else:
            print(f"  archive: thumbnail not found locally ({local_thumb}); Instagram will skip cover.")
            local_thumb_out = None

    # 4. Shareable Drive link for the email preview ("anyone with the link").
    remote_file = f"{proc_dest}/{proc_name}"
    share_url = ""
    try:
        r = run(["rclone", "link", remote_file])
        share_url = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        if share_url:
            print(f"  archive: share link -> {share_url}")
    except Exception as e:
        print(f"  archive: could not make share link ({e}) - email will omit preview.")

    # Persist link + drive path into edit/caption.json so the email builder
    # has everything in one place. Merge, don't clobber, the caption fields.
    import json as _json
    cap_path = PROJECTS_DIR / client / "edit" / "caption.json"
    data = {}
    if cap_path.exists():
        try:
            data = _json.loads(cap_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["reel_url"] = share_url
    data["drive_path"] = remote_file
    data["processed_name"] = proc_name
    data["timestamp"] = ts
    if thumb_name and local_thumb_out and local_thumb_out.exists():
        data["thumbnail_name"] = thumb_name
        data["thumbnail_path"] = str(local_thumb_out)
    try:
        cap_path.parent.mkdir(parents=True, exist_ok=True)
        cap_path.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  archive: could not update caption.json ({e})")

    print(f"  archive: done. Timestamp {ts} links the raw set to the reel.")
    return ts

# ── cli ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Google Drive sync for the reel pipeline")
    ap.add_argument("op", choices=["fetch", "archive", "list"])
    ap.add_argument("client", nargs="?", help="client/project folder name on Drive")
    a = ap.parse_args()

    if a.op == "list":
        list_clients(); return
    if not a.client:
        sys.exit(f"ERROR: '{a.op}' needs a client name. e.g. python rclone_sync.py {a.op} TEST_CLIENT")

    if a.op == "fetch":
        fetch(a.client)
    elif a.op == "archive":
        archive(a.client)

if __name__ == "__main__":
    main()