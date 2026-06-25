
#!/usr/bin/env python3
"""
approval_server.py - Flask approval endpoint for reel posting.

Flow:
  email Approve/Decline buttons link here -> server records the decision in
  decisions.json (SHARED STATE) -> on approve, posts the SPECIFIC reel to
  Instagram in a BACKGROUND thread (the click returns instantly).

Shared-decision behaviour (the requested fix):
  - First click records {client, timestamp, decision, who, when}.
  - Any later click on the SAME reel shows "already <decided> by <who> at <when>"
    and does NOT act again. No double-posting, no conflicting decisions.

Routes:
  GET /approve/<client>/<timestamp>?who=<name>
  GET /decline/<client>/<timestamp>?who=<name>
  GET /status/<client>/<timestamp>
  GET /health

Run:
  python approval_server.py            # listens on 0.0.0.0:8000
Then expose it with a tunnel:
  cloudflared tunnel --url http://localhost:8000
Put the printed https URL into .env as APPROVAL_BASE_URL.

Env (.env):
  APPROVAL_PORT     default 8000
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dotenv_util
dotenv_util.load_dotenv()

from flask import Flask, request

import instagram_post
import rclone_sync
import subprocess

HERE = Path(__file__).resolve().parent
PROJECTS_DIR = HERE / "projects"
DECISIONS_FILE = HERE / "decisions.json"
_LOCK = threading.Lock()

app = Flask(__name__)


# ── shared decision state ────────────────────────────────────────────────────
def _load_decisions() -> dict:
    if DECISIONS_FILE.exists():
        try:
            return json.loads(DECISIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_decisions(data: dict) -> None:
    DECISIONS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _key(client: str, ts: str) -> str:
    return f"{client}::{ts}"


def _get(client: str, ts: str) -> dict | None:
    with _LOCK:
        return _load_decisions().get(_key(client, ts))


def _record(client: str, ts: str, decision: str, who: str) -> tuple[bool, dict]:
    """Atomically record a decision. Returns (is_new, existing_or_new_record)."""
    with _LOCK:
        data = _load_decisions()
        k = _key(client, ts)
        if k in data:
            return False, data[k]  # already decided
        rec = {
            "client": client, "timestamp": ts, "decision": decision,
            "who": who or "someone", "when": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "post_status": "pending" if decision == "approved" else "n/a",
        }
        data[k] = rec
        _save_decisions(data)
        return True, rec


def _update_post_status(client: str, ts: str, status: str, detail: str = "") -> None:
    with _LOCK:
        data = _load_decisions()
        k = _key(client, ts)
        if k in data:
            data[k]["post_status"] = status
            if detail:
                data[k]["post_detail"] = detail
            _save_decisions(data)


# ── background posting ───────────────────────────────────────────────────────
def _post_in_background(client: str, ts: str) -> None:
    """On approval: finalize (move source clips to done/) THEN post to Instagram."""
    def worker():
        # 1. finalize - move the raw clips + thumbnail to their archive home.
        try:
            rclone_sync.finalize(client, ts)
            print(f"[approval] finalized {client}/{ts} (clips moved to done/)")
        except Exception as e:  # noqa: BLE001
            # Don't abort posting if the move hiccups; just record it.
            print(f"[approval] finalize WARNING {client}/{ts}: {e}")
        # 2. post the reel.
        try:
            result = instagram_post.post_reel(client, dry=False, timestamp=ts)
            _update_post_status(client, ts, "posted", result.get("post_id", ""))
            print(f"[approval] posted {client}/{ts} -> {result.get('post_id')}")
        except Exception as e:  # noqa: BLE001
            _update_post_status(client, ts, "failed", str(e))
            print(f"[approval] post FAILED {client}/{ts}: {e}")
    threading.Thread(target=worker, daemon=True).start()


def _rerun_in_background(client: str) -> None:
    """On rerun: re-run the Python pipeline immediately (Path B).

    Clips are still in the inbox (preview didn't move them), so run_client.py
    re-fetches/re-edits and produces a FRESH reel with a new timestamp, then
    run_all-style emailing is handled by re-sending the approval email here.
    """
    def worker():
        try:
            print(f"[approval] RERUN starting for {client} (Python pipeline)...")
            rc = subprocess.run(
                [sys.executable, str(HERE / "run_client.py"), client]
            ).returncode
            print(f"[approval] rerun pipeline exit={rc} for {client}")
            if rc == 0:
                # fresh reel delivered -> send a new approval email for it
                try:
                    import approval_mail
                    approval_mail.send_batch_approval_email({client: "DELIVERED"})
                    print(f"[approval] fresh approval email sent for {client}")
                except Exception as e:  # noqa: BLE001
                    print(f"[approval] rerun email failed: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[approval] RERUN FAILED {client}: {e}")
    threading.Thread(target=worker, daemon=True).start()


# ── pages ────────────────────────────────────────────────────────────────────
def _page(title: str, body: str, color: str = "#111") -> str:
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title></head>
<body style="font-family:Arial,sans-serif;background:#f4f5f7;margin:0;padding:40px 20px">
  <div style="max-width:520px;margin:auto;background:#fff;border-radius:12px;padding:32px;
              border:1px solid #e5e7eb;text-align:center">
    <h2 style="color:{color};margin:0 0 12px">{title}</h2>
    <div style="color:#444;font-size:15px;line-height:1.6">{body}</div>
  </div></body></html>"""


@app.route("/health")
def health():
    return "ok", 200


@app.route("/approve/<client>/<ts>")
def approve(client, ts):
    who = request.args.get("who", "").strip()
    is_new, rec = _record(client, ts, "approved", who)
    if not is_new:
        d = rec["decision"]
        return _page(
            "Already decided",
            f"This reel was already <b>{d}</b> by <b>{rec['who']}</b> on {rec['when']}.<br><br>"
            f"No action taken. (Posting status: {rec.get('post_status','n/a')})",
            "#d97706",
        )
    _post_in_background(client, ts)
    return _page(
        "✓ Approved — posting now",
        f"<b>{client}</b> reel ({ts}) approved by <b>{who or 'you'}</b>.<br><br>"
        f"It's being posted to Instagram in the background. You can close this page.<br>"
        f"<a href='/status/{client}/{ts}'>Check posting status</a>",
        "#16a34a",
    )


def _current_ts(client: str) -> str | None:
    """The timestamp of the CURRENT preview reel for this client (from caption.json).

    Used to detect stale button clicks: if an old email's timestamp no longer
    matches the current preview, that email is out of date (a rerun happened).
    """
    cap = PROJECTS_DIR / client / "edit" / "caption.json"
    if cap.exists():
        try:
            return json.loads(cap.read_text(encoding="utf-8")).get("timestamp")
        except Exception:
            return None
    return None


@app.route("/rerun/<client>/<ts>")
def rerun(client, ts):
    who = request.args.get("who", "").strip()

    # If this reel was already decided (approved), don't rerun over it.
    existing = _get(client, ts)
    if existing and existing.get("decision") == "approved":
        return _page(
            "Already approved",
            f"This reel was already <b>approved</b> by <b>{existing['who']}</b> "
            f"on {existing['when']}. Rerun is not available after approval.",
            "#d97706",
        )

    # Stale-click guard: only the CURRENT preview can be rerun.
    cur = _current_ts(client)
    if cur and cur != ts:
        return _page(
            "This email is out of date",
            f"A newer version of <b>{client}</b>'s reel already exists "
            f"(current: {cur}). Please use the most recent approval email.",
            "#6b7280",
        )

    # Record the rerun request (shared state) and kick off the Python re-edit.
    is_new, rec = _record(client, ts, "rerun", who)
    if not is_new and rec.get("decision") != "rerun":
        return _page(
            "Already decided",
            f"This reel was already <b>{rec['decision']}</b> by <b>{rec['who']}</b> "
            f"on {rec['when']}. No action taken.",
            "#d97706",
        )

    _rerun_in_background(client)
    return _page(
        "↻ Re-editing now",
        f"<b>{client}</b> is being re-edited by the pipeline.<br><br>"
        f"You'll get a fresh approval email with the new version in a few minutes. "
        f"The source clips stay in place until you approve a version.",
        "#2563eb",
    )


@app.route("/status/<client>/<ts>")
def status(client, ts):
    rec = _get(client, ts)
    if not rec:
        return _page("No decision yet", f"No decision recorded for {client} ({ts}).", "#6b7280")
    ps = rec.get("post_status", "n/a")
    extra = f"<br>Detail: {rec.get('post_detail','')}" if rec.get("post_detail") else ""
    return _page(
        f"Status: {rec['decision']}",
        f"<b>{client}</b> ({ts})<br>Decision: <b>{rec['decision']}</b> by {rec['who']} on {rec['when']}"
        f"<br>Posting: <b>{ps}</b>{extra}",
        "#111",
    )


def main():
    port = int(os.environ.get("APPROVAL_PORT", "8000") or "8000")
    print(f"Approval server on http://0.0.0.0:{port}")
    print("Expose with:  cloudflared tunnel --url http://localhost:%d" % port)
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()