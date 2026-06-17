#!/usr/bin/env python3
"""
run_all.py - discover every Drive client with clips waiting, process each one.

This is the single entry point the Routine (or a cron job) calls. It:
  1. lists client folders under gdrive:reel-projects/
  2. for each client, checks whether its inbox (top level) has clips
  3. runs run_client.py for each client that has work
  4. prints a final summary: delivered / not-delivered / skipped / errored

A client with an empty inbox is skipped (already processed, nothing new).
run_client.py enforces the strict QC gate, so run_all just orchestrates + reports.

Usage:
    python run_all.py
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY   = sys.executable

# import the sync module to reuse its client discovery + inbox check
sys.path.insert(0, str(HERE))
import rclone_sync as rs

VERDICT = {0: "DELIVERED", 2: "NOT DELIVERED (failed QC)", 1: "ERROR"}


def main():
    print(f"\n{'='*64}\n  RUN ALL - reel pipeline batch\n{'='*64}")

    rs.check_rclone()
    clients = rs.list_clients()
    if not clients:
        print("\nNo client folders found on Drive. Nothing to do.")
        return

    results = {}
    for client in clients:
        # does this client have clips waiting in its inbox?
        try:
            clips = rs.inbox_clips(client)
        except Exception as e:
            print(f"\n[{client}] could not read inbox: {e}")
            results[client] = "ERROR (inbox read)"
            continue

        if not clips:
            print(f"\n[{client}] inbox empty - skipping.")
            results[client] = "SKIPPED (no clips)"
            continue

        print(f"\n{'-'*64}\n  Processing {client} ({len(clips)} clip(s))\n{'-'*64}")
        rc = subprocess.run([PY, str(HERE / "run_client.py"), client]).returncode
        results[client] = VERDICT.get(rc, f"UNKNOWN (exit {rc})")

    # ── final summary ────────────────────────────────────────────────────────
    print(f"\n{'='*64}\n  SUMMARY\n{'='*64}")
    for client, status in results.items():
        print(f"  {client:24} -> {status}")
    delivered = sum(1 for s in results.values() if s == "DELIVERED")
    print(f"\n  {delivered}/{len(results)} client(s) delivered.")
    # Tell the operator to review the human-eye flags
    print("\n  Review delivered reels for the subjective flags (music/SFX feel,")
    print("  transitions, caption taste) - see each project's edit/REVIEW.md.")


if __name__ == "__main__":
    main()