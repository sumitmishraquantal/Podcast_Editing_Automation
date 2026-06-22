# #!/usr/bin/env python3
# """
# run_all.py - discover every Drive client with clips waiting, process each one.

# This is the single entry point the Routine (or a cron job) calls. It:
#   1. lists client folders under gdrive:reel-projects/
#   2. for each client, checks whether its inbox (top level) has clips
#   3. runs run_client.py for each client that has work
#   4. prints a final summary: delivered / not-delivered / skipped / errored

# A client with an empty inbox is skipped (already processed, nothing new).
# run_client.py enforces the strict QC gate, so run_all just orchestrates + reports.

# Usage:
#     python run_all.py
# """
# import subprocess
# import sys
# from pathlib import Path

# HERE = Path(__file__).resolve().parent
# PY   = sys.executable

# # import the sync module to reuse its client discovery + inbox check
# sys.path.insert(0, str(HERE))
# import approval_mail
# import dotenv_util
# import rclone_sync as rs

# dotenv_util.load_dotenv()

# VERDICT = {0: "DELIVERED", 2: "NOT DELIVERED (failed QC)", 1: "ERROR"}


# def main():
#     print(f"\n{'='*64}\n  RUN ALL - reel pipeline batch\n{'='*64}")

#     rs.check_rclone()
#     clients = rs.list_clients()
#     if not clients:
#         print("\nNo client folders found on Drive. Nothing to do.")
#         return

#     results = {}
#     for client in clients:
#         # does this client have clips waiting in its inbox?
#         try:
#             clips = rs.inbox_clips(client)
#         except Exception as e:
#             print(f"\n[{client}] could not read inbox: {e}")
#             results[client] = "ERROR (inbox read)"
#             continue

#         if not clips:
#             print(f"\n[{client}] inbox empty - skipping.")
#             results[client] = "SKIPPED (no clips)"
#             continue

#         print(f"\n{'-'*64}\n  Processing {client} ({len(clips)} clip(s))\n{'-'*64}")
#         rc = subprocess.run([PY, str(HERE / "run_client.py"), client]).returncode
#         results[client] = VERDICT.get(rc, f"UNKNOWN (exit {rc})")

#     # ── final summary ────────────────────────────────────────────────────────
#     print(f"\n{'='*64}\n  SUMMARY\n{'='*64}")
#     for client, status in results.items():
#         print(f"  {client:24} -> {status}")
#     delivered = sum(1 for s in results.values() if s == "DELIVERED")
#     print(f"\n  {delivered}/{len(results)} client(s) delivered.")
#     # Tell the operator to review the human-eye flags
#     print("\n  Review delivered reels for the subjective flags (music/SFX feel,")
#     print("  transitions, caption taste) - see each project's edit/REVIEW.md.")

#     # ── approval email ───────────────────────────────────────────────────────
#     print(f"\n{'='*64}\n  APPROVAL EMAIL\n{'='*64}")
#     mail_report = approval_mail.send_batch_approval_email(results)
#     for recipient, status in mail_report.items():
#         print(f"  {recipient:32} -> {status}")


# if __name__ == "__main__":
#     main()


"""
run_all.py - discover every Drive client with clips waiting, process each one,
then email approval requests.

Pairs with start_services.py (the persistent approval server + tunnel). This is
the BATCH half: run it whenever you have new clips (manually, Routine, or cron).

Flow per run:
  1. preflight: is the approval server reachable? (warn if not - buttons would be dead)
  2. list Drive clients; for each with inbox clips, run run_client.py
  3. send the approval email (buttons -> approval server -> Instagram on click)

Usage:
    python run_all.py
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY   = sys.executable

sys.path.insert(0, str(HERE))
import dotenv_util
dotenv_util.load_dotenv()
import approval_mail
import rclone_sync as rs

VERDICT = {0: "DELIVERED", 2: "NOT DELIVERED (failed QC)", 1: "ERROR"}


def _preflight_server() -> None:
    """Warn (don't block) if the approval server isn't reachable - dead buttons."""
    base = os.environ.get("APPROVAL_BASE_URL", "").strip().rstrip("/")
    if not base:
        print("  [preflight] APPROVAL_BASE_URL not set - approval buttons will be inactive.")
        print("              Start the service first:  python start_services.py")
        return
    try:
        import requests
        r = requests.get(f"{base}/health", timeout=8)
        if r.status_code == 200 and "ok" in r.text.lower():
            print(f"  [preflight] approval server reachable at {base}")
        else:
            print(f"  [preflight] WARNING: {base}/health returned {r.status_code} - check the service.")
    except Exception as e:
        print(f"  [preflight] WARNING: approval server not reachable ({e}).")
        print("              Approve buttons in the email won't work until it's up.")
        print("              Start it with:  python start_services.py")


def main():
    print(f"\n{'='*64}\n  RUN ALL - reel pipeline batch\n{'='*64}")

    _preflight_server()

    rs.check_rclone()
    clients = rs.list_clients()
    if not clients:
        print("\nNo client folders found on Drive. Nothing to do.")
        return

    results = {}
    for client in clients:
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

    print(f"\n{'='*64}\n  SUMMARY\n{'='*64}")
    for client, status in results.items():
        print(f"  {client:24} -> {status}")
    delivered = sum(1 for s in results.values() if s == "DELIVERED")
    print(f"\n  {delivered}/{len(results)} client(s) delivered.")

    print(f"\n{'='*64}\n  APPROVAL EMAIL\n{'='*64}")
    mail_report = approval_mail.send_batch_approval_email(results)
    for recipient, status in mail_report.items():
        print(f"  {recipient:32} -> {status}")
    print("\n  Click Approve in the email to post a reel to Instagram.")
    print("  (The approval service must stay running to receive the click.)")


if __name__ == "__main__":
    main()