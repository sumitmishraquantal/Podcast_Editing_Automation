# # #!/usr/bin/env python3
# # """
# # run_client.py - fully automated single-client reel run.

# # Chains the whole workflow for ONE client, with all gating in code:

# #     fetch  ->  pipeline (6 stages)  ->  qc  ->  [self-correct]  ->  archive (only if shippable)

# # Behaviour (decided with the user):
# #   - QC failure is STRICT: if objective checks fail after retries, DO NOT archive.
# #     Clips stay in the Drive inbox so the next run retries them. Nothing is delivered.
# #   - Self-correction: each objective QC failure re-runs the relevant stage, max 2
# #     attempts per issue, then re-runs QC. Never loops forever.
# #   - "SHIPPABLE" and "SHIPPABLE (with human-eye flags)" both count as pass -> archive.
# #     "BLOCKED - objective fail" and "FATAL" do NOT archive.

# # Usage:
# #     python run_client.py <CLIENT>

# # Exit codes:
# #     0  delivered (shippable + archived)
# #     2  processed but NOT shippable (left in inbox to retry)
# #     1  hard error (fetch failed, pipeline crashed, etc.)
# # """
# # import subprocess
# # import sys
# # from pathlib import Path

# # HERE = Path(__file__).resolve().parent
# # PY   = sys.executable

# # # Which pipeline stage to re-run for each failing objective QC check.
# # # Mirrors the SKILL.md / CLAUDE.md fix table.
# # FIX_STAGE = {
# #     "loudness -16..-12 LUFS":  "finalize",
# #     "true peak <= -0.5 dBTP":  "finalize",
# #     "no caption overlap":      "captions",
# #     "music bed audible":       "sound",
# #     "no black frames":         "effects",   # then captions+finalize (handled below)
# #     # "duration 12-90s" -> not fixable (footage length); do not retry
# #     # "caption tags well-formed" -> corruption; STOP, do not ship
# # }
# # # black-frames fix needs a cascade of stages, in order:
# # BLACK_CASCADE = ["effects", "captions", "finalize"]
# # MAX_ATTEMPTS  = 2


# # def run(cmd, **kw):
# #     """Run a subprocess, streaming output. Returns returncode."""
# #     print(f"\n  $ {' '.join(str(c) for c in cmd)}")
# #     return subprocess.run(cmd, **kw).returncode


# # def pipeline(client_path, stage=None, restart=False):
# #     cmd = [PY, str(HERE / "pipeline.py"), str(client_path)]
# #     if restart:
# #         cmd.append("--restart")
# #     if stage:
# #         cmd += ["--stage", stage]
# #     else:
# #         cmd.append("--all")
# #     return run(cmd)


# # def qc(client_path):
# #     """Run qc_check.py, then read the verdict + failed checks from REVIEW.md."""
# #     run([PY, str(HERE / "qc_check.py"), str(client_path)])
# #     review = client_path / "edit" / "REVIEW.md"
# #     if not review.exists():
# #         return "FATAL", []
# #     text = review.read_text(encoding="utf-8")
# #     # verdict is on the first line after "# REVIEW  ----  "
# #     first = text.splitlines()[0] if text.splitlines() else ""
# #     verdict = first.split("----")[-1].strip() if "----" in first else "UNKNOWN"
# #     # failed checks are listed under "## FAILED" as "- <name>: <detail>"
# #     failed = []
# #     in_failed = False
# #     for ln in text.splitlines():
# #         if ln.startswith("## FAILED"):
# #             in_failed = True; continue
# #         if in_failed and ln.startswith("- "):
# #             name = ln[2:].split(":")[0].strip()
# #             failed.append(name)
# #         elif in_failed and ln.startswith("##"):
# #             break
# #     return verdict, failed


# # def is_shippable(verdict):
# #     return verdict.startswith("SHIPPABLE")


# # def self_correct(client_path, failed):
# #     """Re-run the relevant stage(s) for each failing check, max MAX_ATTEMPTS each."""
# #     for check in failed:
# #         if check == "caption tags well-formed":
# #             print(f"  [STOP] '{check}' failed = reel_captions.py corrupted. Will NOT ship.")
# #             return False  # unrecoverable, do not keep trying
# #         if check == "duration 12-90s":
# #             print(f"  [skip] '{check}' is footage length - cannot fix, will flag.")
# #             continue
# #         if check == "no black frames":
# #             print(f"  [fix] '{check}' -> cascade {BLACK_CASCADE}")
# #             for st in BLACK_CASCADE:
# #                 pipeline(client_path, stage=st)
# #             continue
# #         stage = FIX_STAGE.get(check)
# #         if stage:
# #             print(f"  [fix] '{check}' -> re-run stage '{stage}'")
# #             pipeline(client_path, stage=stage)
# #         else:
# #             print(f"  [?] no known fix for '{check}' - leaving as is.")
# #     return True


# # def main():
# #     if len(sys.argv) < 2:
# #         sys.exit("Usage: python run_client.py <CLIENT>")
# #     client = sys.argv[1]
# #     client_path = HERE / "projects" / client

# #     print(f"\n{'='*64}\n  RUN CLIENT: {client}\n{'='*64}")

# #     # ── 1. FETCH from Drive ──────────────────────────────────────────────────
# #     print("\n[1/4] FETCH from Google Drive")
# #     rc = run([PY, str(HERE / "rclone_sync.py"), "fetch", client])
# #     if rc != 0:
# #         print(f"\n[FAIL] fetch failed for {client}. Aborting (exit 1).")
# #         sys.exit(1)

# #     raw = client_path / "raw"
# #     clips = list(raw.glob("*.mp4")) + list(raw.glob("*.mov")) if raw.exists() else []
# #     if not clips:
# #         print(f"\n[skip] No clips fetched for {client} (empty inbox). Nothing to do.")
# #         sys.exit(0)
# #     print(f"  fetched {len(clips)} clip(s).")

# #     # ── 2. PIPELINE (clean run, all stages) ──────────────────────────────────
# #     print("\n[2/4] PIPELINE (all stages, clean restart)")
# #     # wipe edit/ for a clean run (mirrors the Routine's behaviour)
# #     edit = client_path / "edit"
# #     if edit.exists():
# #         import shutil
# #         shutil.rmtree(edit)
# #     rc = pipeline(client_path, restart=True)
# #     if rc != 0:
# #         print(f"\n[FAIL] pipeline crashed for {client} (exit 1).")
# #         sys.exit(1)

# #     # ── 3. QC + SELF-CORRECT ─────────────────────────────────────────────────
# #     print("\n[3/4] QC + self-correct")
# #     verdict, failed = qc(client_path)
# #     print(f"  QC verdict: {verdict} | failed checks: {failed}")

# #     attempt = 0
# #     while failed and not is_shippable(verdict) and attempt < MAX_ATTEMPTS:
# #         attempt += 1
# #         print(f"\n  -- self-correct attempt {attempt}/{MAX_ATTEMPTS} --")
# #         recoverable = self_correct(client_path, failed)
# #         if not recoverable:
# #             break
# #         verdict, failed = qc(client_path)
# #         print(f"  QC verdict: {verdict} | failed checks: {failed}")

# #     # ── 4. ARCHIVE (only if shippable) ───────────────────────────────────────
# #     print("\n[4/4] ARCHIVE decision")
# #     if is_shippable(verdict):
# #         print(f"  {verdict} -> archiving to Drive + delivered/")
# #         rc = run([PY, str(HERE / "rclone_sync.py"), "archive", client])
# #         if rc != 0:
# #             print(f"\n[WARN] archive failed for {client} after a shippable reel. "
# #                   f"Reel is in edit/final.mp4 but not delivered. Exit 1.")
# #             sys.exit(1)
# #         print(f"\n[DONE] {client} delivered. (exit 0)")
# #         sys.exit(0)
# #     else:
# #         print(f"  {verdict} -> NOT shippable. Skipping archive.")
# #         print(f"  Clips remain in the Drive inbox for {client} - next run will retry.")
# #         print(f"\n[NOT DELIVERED] {client} did not pass QC. See projects/{client}/edit/REVIEW.md (exit 2).")
# #         sys.exit(2)


# # if __name__ == "__main__":
# #     main()

# #!/usr/bin/env python3
# """
# run_client.py - fully automated single-client reel run.

# Chains the whole workflow for ONE client, with all gating in code:

#     fetch  ->  pipeline (6 stages)  ->  qc  ->  [self-correct]  ->  archive (only if shippable)

# Behaviour (decided with the user):
#   - QC failure is STRICT: if objective checks fail after retries, DO NOT archive.
#     Clips stay in the Drive inbox so the next run retries them. Nothing is delivered.
#   - Self-correction: each objective QC failure re-runs the relevant stage, max 2
#     attempts per issue, then re-runs QC. Never loops forever.
#   - "SHIPPABLE" and "SHIPPABLE (with human-eye flags)" both count as pass -> archive.
#     "BLOCKED - objective fail" and "FATAL" do NOT archive.

# Usage:
#     python run_client.py <CLIENT>

# Exit codes:
#     0  delivered (shippable + archived)
#     2  processed but NOT shippable (left in inbox to retry)
#     1  hard error (fetch failed, pipeline crashed, etc.)
# """
# import subprocess
# import sys
# from pathlib import Path

# HERE = Path(__file__).resolve().parent
# PY   = sys.executable

# # Which pipeline stage to re-run for each failing objective QC check.
# # Mirrors the SKILL.md / CLAUDE.md fix table.
# FIX_STAGE = {
#     "loudness -16..-12 LUFS":  "finalize",
#     "true peak <= -0.5 dBTP":  "finalize",
#     "no caption overlap":      "captions",
#     "music bed audible":       "sound",
#     "whoosh audible at seams": "sound",
#     "no black frames":         "effects",   # then captions+finalize (handled below)
#     # "duration 12-90s" -> not fixable (footage length); do not retry
#     # "caption tags well-formed" -> corruption; STOP, do not ship
# }
# # black-frames fix needs a cascade of stages, in order:
# BLACK_CASCADE = ["effects", "captions", "finalize"]
# MAX_ATTEMPTS  = 2


# def run(cmd, **kw):
#     """Run a subprocess, streaming output. Returns returncode."""
#     print(f"\n  $ {' '.join(str(c) for c in cmd)}")
#     return subprocess.run(cmd, **kw).returncode


# def pipeline(client_path, stage=None, restart=False):
#     cmd = [PY, str(HERE / "pipeline.py"), str(client_path)]
#     if restart:
#         cmd.append("--restart")
#     if stage:
#         cmd += ["--stage", stage]
#     else:
#         cmd.append("--all")
#     return run(cmd)


# def qc(client_path):
#     """Run qc_check.py, then read the verdict + failed checks from REVIEW.md."""
#     run([PY, str(HERE / "qc_check.py"), str(client_path)])
#     review = client_path / "edit" / "REVIEW.md"
#     if not review.exists():
#         return "FATAL", []
#     text = review.read_text(encoding="utf-8")
#     # verdict is on the first line after "# REVIEW  ----  "
#     first = text.splitlines()[0] if text.splitlines() else ""
#     verdict = first.split("----")[-1].strip() if "----" in first else "UNKNOWN"
#     # failed checks are listed under "## FAILED" as "- <name>: <detail>"
#     failed = []
#     in_failed = False
#     for ln in text.splitlines():
#         if ln.startswith("## FAILED"):
#             in_failed = True; continue
#         if in_failed and ln.startswith("- "):
#             name = ln[2:].split(":")[0].strip()
#             failed.append(name)
#         elif in_failed and ln.startswith("##"):
#             break
#     return verdict, failed


# def is_shippable(verdict):
#     return verdict.startswith("SHIPPABLE")


# def self_correct(client_path, failed):
#     """Re-run the relevant stage(s) for each failing check, max MAX_ATTEMPTS each."""
#     for check in failed:
#         if check == "caption tags well-formed":
#             print(f"  [STOP] '{check}' failed = reel_captions.py corrupted. Will NOT ship.")
#             return False  # unrecoverable, do not keep trying
#         if check == "duration 12-90s":
#             print(f"  [skip] '{check}' is footage length - cannot fix, will flag.")
#             continue
#         if check == "no black frames":
#             print(f"  [fix] '{check}' -> cascade {BLACK_CASCADE}")
#             for st in BLACK_CASCADE:
#                 pipeline(client_path, stage=st)
#             continue
#         stage = FIX_STAGE.get(check)
#         if stage:
#             print(f"  [fix] '{check}' -> re-run stage '{stage}'")
#             pipeline(client_path, stage=stage)
#         else:
#             print(f"  [?] no known fix for '{check}' - leaving as is.")
#     return True


# def main():
#     if len(sys.argv) < 2:
#         sys.exit("Usage: python run_client.py <CLIENT>")
#     client = sys.argv[1]
#     client_path = HERE / "projects" / client

#     print(f"\n{'='*64}\n  RUN CLIENT: {client}\n{'='*64}")

#     # ── 1. FETCH from Drive ──────────────────────────────────────────────────
#     print("\n[1/4] FETCH from Google Drive")
#     rc = run([PY, str(HERE / "rclone_sync.py"), "fetch", client])
#     if rc != 0:
#         print(f"\n[FAIL] fetch failed for {client}. Aborting (exit 1).")
#         sys.exit(1)

#     raw = client_path / "raw"
#     clips = list(raw.glob("*.mp4")) + list(raw.glob("*.mov")) if raw.exists() else []
#     if not clips:
#         print(f"\n[skip] No clips fetched for {client} (empty inbox). Nothing to do.")
#         sys.exit(0)
#     print(f"  fetched {len(clips)} clip(s).")

#     # ── 2. PIPELINE (clean run, all stages) ──────────────────────────────────
#     print("\n[2/4] PIPELINE (all stages, clean restart)")
#     # wipe edit/ for a clean run (mirrors the Routine's behaviour)
#     edit = client_path / "edit"
#     if edit.exists():
#         import shutil
#         shutil.rmtree(edit)
#     rc = pipeline(client_path, restart=True)
#     if rc != 0:
#         print(f"\n[FAIL] pipeline crashed for {client} (exit 1).")
#         sys.exit(1)

#     # ── 3. QC + SELF-CORRECT ─────────────────────────────────────────────────
#     print("\n[3/4] QC + self-correct")
#     verdict, failed = qc(client_path)
#     print(f"  QC verdict: {verdict} | failed checks: {failed}")

#     attempt = 0
#     while failed and not is_shippable(verdict) and attempt < MAX_ATTEMPTS:
#         attempt += 1
#         print(f"\n  -- self-correct attempt {attempt}/{MAX_ATTEMPTS} --")
#         recoverable = self_correct(client_path, failed)
#         if not recoverable:
#             break
#         verdict, failed = qc(client_path)
#         print(f"  QC verdict: {verdict} | failed checks: {failed}")

#     # ── 4. ARCHIVE (only if shippable) ───────────────────────────────────────
#     print("\n[4/4] ARCHIVE decision")
#     if is_shippable(verdict):
#         print(f"  {verdict} -> archiving to Drive + delivered/")
#         rc = run([PY, str(HERE / "rclone_sync.py"), "archive", client])
#         if rc != 0:
#             print(f"\n[WARN] archive failed for {client} after a shippable reel. "
#                   f"Reel is in edit/final.mp4 but not delivered. Exit 1.")
#             sys.exit(1)
#         print(f"\n[DONE] {client} delivered. (exit 0)")
#         sys.exit(0)
#     else:
#         print(f"  {verdict} -> NOT shippable. Skipping archive.")
#         print(f"  Clips remain in the Drive inbox for {client} - next run will retry.")
#         print(f"\n[NOT DELIVERED] {client} did not pass QC. See projects/{client}/edit/REVIEW.md (exit 2).")
#         sys.exit(2)


# if __name__ == "__main__":
#     main()


#!/usr/bin/env python3
"""
run_client.py - fully automated single-client reel run.

Chains the whole workflow for ONE client, with all gating in code:

    fetch  ->  pipeline (6 stages)  ->  qc  ->  [self-correct]  ->  archive (only if shippable)

Behaviour (decided with the user):
  - QC failure is STRICT: if objective checks fail after retries, DO NOT archive.
    Clips stay in the Drive inbox so the next run retries them. Nothing is delivered.
  - Self-correction: each objective QC failure re-runs the relevant stage, max 2
    attempts per issue, then re-runs QC. Never loops forever.
  - "SHIPPABLE" and "SHIPPABLE (with human-eye flags)" both count as pass -> archive.
    "BLOCKED - objective fail" and "FATAL" do NOT archive.

Usage:
    python run_client.py <CLIENT>

Exit codes:
    0  delivered (shippable + archived)
    2  processed but NOT shippable (left in inbox to retry)
    1  hard error (fetch failed, pipeline crashed, etc.)
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY   = sys.executable

# Which pipeline stage to re-run for each failing objective QC check.
# Mirrors the SKILL.md / CLAUDE.md fix table.
FIX_STAGE = {
    "loudness -16..-12 LUFS":  "finalize",
    "true peak <= -0.5 dBTP":  "finalize",
    "no caption overlap":      "captions",
    "music bed audible":       "sound",
    "no black frames":         "effects",   # then captions+finalize (handled below)
    # "duration 12-90s" -> not fixable (footage length); do not retry
    # "caption tags well-formed" -> corruption; STOP, do not ship
}
# black-frames fix needs a cascade of stages, in order:
BLACK_CASCADE = ["effects", "captions", "finalize"]
MAX_ATTEMPTS  = 2


def run(cmd, **kw):
    """Run a subprocess, streaming output. Returns returncode."""
    print(f"\n  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, **kw).returncode


def pipeline(client_path, stage=None, restart=False):
    cmd = [PY, str(HERE / "pipeline.py"), str(client_path)]
    if restart:
        cmd.append("--restart")
    if stage:
        cmd += ["--stage", stage]
    else:
        cmd.append("--all")
    return run(cmd)


def qc(client_path):
    """Run qc_check.py, then read the verdict + failed checks from REVIEW.md."""
    run([PY, str(HERE / "qc_check.py"), str(client_path)])
    review = client_path / "edit" / "REVIEW.md"
    if not review.exists():
        return "FATAL", []
    text = review.read_text(encoding="utf-8")
    # verdict is on the first line after "# REVIEW  ----  "
    first = text.splitlines()[0] if text.splitlines() else ""
    verdict = first.split("----")[-1].strip() if "----" in first else "UNKNOWN"
    # failed checks are listed under "## FAILED" as "- <name>: <detail>"
    failed = []
    in_failed = False
    for ln in text.splitlines():
        if ln.startswith("## FAILED"):
            in_failed = True; continue
        if in_failed and ln.startswith("- "):
            name = ln[2:].split(":")[0].strip()
            failed.append(name)
        elif in_failed and ln.startswith("##"):
            break
    return verdict, failed


def is_shippable(verdict):
    return verdict.startswith("SHIPPABLE")


def self_correct(client_path, failed):
    """Re-run the relevant stage(s) for each failing check, max MAX_ATTEMPTS each."""
    for check in failed:
        if check == "caption tags well-formed":
            print(f"  [STOP] '{check}' failed = reel_captions.py corrupted. Will NOT ship.")
            return False  # unrecoverable, do not keep trying
        if check == "duration 12-90s":
            print(f"  [skip] '{check}' is footage length - cannot fix, will flag.")
            continue
        if check == "no black frames":
            print(f"  [fix] '{check}' -> cascade {BLACK_CASCADE}")
            for st in BLACK_CASCADE:
                pipeline(client_path, stage=st)
            continue
        stage = FIX_STAGE.get(check)
        if stage:
            print(f"  [fix] '{check}' -> re-run stage '{stage}'")
            pipeline(client_path, stage=stage)
        else:
            print(f"  [?] no known fix for '{check}' - leaving as is.")
    return True


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python run_client.py <CLIENT>")
    client = sys.argv[1]
    client_path = HERE / "projects" / client

    print(f"\n{'='*64}\n  RUN CLIENT: {client}\n{'='*64}")

    # ── 1. FETCH from Drive ──────────────────────────────────────────────────
    print("\n[1/4] FETCH from Google Drive")
    rc = run([PY, str(HERE / "rclone_sync.py"), "fetch", client])
    if rc != 0:
        print(f"\n[FAIL] fetch failed for {client}. Aborting (exit 1).")
        sys.exit(1)

    raw = client_path / "raw"
    clips = list(raw.glob("*.mp4")) + list(raw.glob("*.mov")) if raw.exists() else []
    if not clips:
        print(f"\n[skip] No clips fetched for {client} (empty inbox). Nothing to do.")
        sys.exit(0)
    print(f"  fetched {len(clips)} clip(s).")

    # ── 2. PIPELINE (clean run, all stages) ──────────────────────────────────
    print("\n[2/4] PIPELINE (all stages, clean restart)")
    # wipe edit/ for a clean run (mirrors the Routine's behaviour)
    edit = client_path / "edit"
    if edit.exists():
        import shutil
        shutil.rmtree(edit)
    rc = pipeline(client_path, restart=True)
    if rc != 0:
        print(f"\n[FAIL] pipeline crashed for {client} (exit 1).")
        sys.exit(1)

    # ── 3. QC + SELF-CORRECT ─────────────────────────────────────────────────
    print("\n[3/4] QC + self-correct")
    verdict, failed = qc(client_path)
    print(f"  QC verdict: {verdict} | failed checks: {failed}")

    attempt = 0
    while failed and not is_shippable(verdict) and attempt < MAX_ATTEMPTS:
        attempt += 1
        print(f"\n  -- self-correct attempt {attempt}/{MAX_ATTEMPTS} --")
        recoverable = self_correct(client_path, failed)
        if not recoverable:
            break
        verdict, failed = qc(client_path)
        print(f"  QC verdict: {verdict} | failed checks: {failed}")

    # ── 4. ARCHIVE (only if shippable) ───────────────────────────────────────
    print("\n[4/4] ARCHIVE decision")
    if is_shippable(verdict):
        print(f"  {verdict} -> archiving to Drive + delivered/")
        rc = run([PY, str(HERE / "rclone_sync.py"), "archive", client])
        if rc != 0:
            print(f"\n[WARN] archive failed for {client} after a shippable reel. "
                  f"Reel is in edit/final.mp4 but not delivered. Exit 1.")
            sys.exit(1)
        print(f"\n[DONE] {client} delivered. (exit 0)")
        sys.exit(0)
    else:
        print(f"  {verdict} -> NOT shippable. Skipping archive.")
        print(f"  Clips remain in the Drive inbox for {client} - next run will retry.")
        print(f"\n[NOT DELIVERED] {client} did not pass QC. See projects/{client}/edit/REVIEW.md (exit 2).")
        sys.exit(2)


if __name__ == "__main__":
    main()