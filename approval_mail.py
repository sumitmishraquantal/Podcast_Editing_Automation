#!/usr/bin/env python3
"""
approval_mail.py - send a batch approval email after run_all.py finishes.

Uses the same .env keys as Thai-s-Instagram-Automation:
    OWNER_EMAILS=owner1@x.com,owner2@y.com
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=youraddress@gmail.com
    SMTP_PASSWORD=your-app-password
    EMAIL_TRANSPORT=auto          # auto | smtp | file
    SEND_APPROVAL_EMAIL=true      # set false to skip

If SMTP is not configured, emails are written to sent_emails/ as .html files.
"""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECTS_DIR = HERE / "projects"
DELIVERED_DIR = HERE / "delivered"
FALLBACK_DIR = HERE / "sent_emails"

import dotenv_util

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _owner_emails() -> list[str]:
    return [e.strip() for e in os.environ.get("OWNER_EMAILS", "").split(",") if e.strip()]


def _client_details(client: str) -> dict:
    """Pull QC verdict, human-eye flags, transcript snippet, and reel path."""
    edit = PROJECTS_DIR / client / "edit"
    review_path = edit / "REVIEW.md"
    words_path = edit / "words.json"

    verdict = ""
    human_flags: list[str] = []
    if review_path.exists():
        text = review_path.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text.splitlines() else ""
        verdict = first.split("----")[-1].strip() if "----" in first else ""
        in_human = False
        for ln in text.splitlines():
            if ln.startswith("## Needs human"):
                in_human = True
                continue
            if in_human and ln.startswith("- "):
                human_flags.append(ln[2:].strip())
            elif in_human and ln.startswith("##"):
                break

    transcript = ""
    if words_path.exists():
        import json

        try:
            words = json.loads(words_path.read_text(encoding="utf-8"))
            transcript = " ".join(w.get("word", "") for w in words)[:400]
        except Exception:  # noqa: BLE001
            transcript = ""

    reel_path = ""
    delivered = sorted((DELIVERED_DIR / client).glob("Processed_*.mp4"))
    if delivered:
        reel_path = str(delivered[-1].relative_to(HERE))
    elif (edit / "final.mp4").exists():
        reel_path = str((edit / "final.mp4").relative_to(HERE))

    remote = os.environ.get("RCLONE_REMOTE", "gdrive")
    root = os.environ.get("RCLONE_ROOT", "reel-projects")
    drive_hint = f"{remote}:{root}/{client}/done/Processed_Video/"

    return {
        "verdict": verdict,
        "human_flags": human_flags,
        "transcript": transcript,
        "reel_path": reel_path,
        "drive_hint": drive_hint,
    }


def _status_color(status: str) -> str:
    if status == "DELIVERED":
        return "#16a34a"
    if status.startswith("NOT DELIVERED"):
        return "#dc2626"
    if status.startswith("SKIPPED"):
        return "#6b7280"
    return "#d97706"


def _batch_html(*, results: dict[str, str], run_at: str) -> str:
    delivered = {c: s for c, s in results.items() if s == "DELIVERED"}
    other = {c: s for c, s in results.items() if s != "DELIVERED"}

    rows = ""
    for client, status in results.items():
        color = _status_color(status)
        rows += (
            f'<tr><td style="padding:8px 12px;font-weight:600">{client}</td>'
            f'<td style="padding:8px 12px;color:{color}">{status}</td></tr>'
        )

    detail_blocks = ""
    for client in delivered:
        d = _client_details(client)
        flags_html = ""
        if d["human_flags"]:
            items = "".join(f"<li>{f}</li>" for f in d["human_flags"])
            flags_html = f'<ul style="margin:8px 0 0 18px;color:#92400e">{items}</ul>'
        transcript_html = ""
        if d["transcript"]:
            transcript_html = (
                f'<p style="margin:10px 0 0;color:#444;font-size:13px;line-height:1.5">'
                f'<em>Transcript:</em> "{d["transcript"]}{"…" if len(d["transcript"]) >= 400 else ""}"</p>'
            )
        reel_html = ""
        if d["reel_path"]:
            reel_html = (
                f'<p style="margin:8px 0 0;font-size:13px">'
                f'<strong>Reel:</strong> {d["reel_path"]}<br>'
                f'<strong>Drive:</strong> {d["drive_hint"]}</p>'
            )
        detail_blocks += f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin:14px 0">
          <h3 style="margin:0 0 6px;color:#111">{client}</h3>
          <p style="margin:0;color:#16a34a;font-weight:600">{d["verdict"] or "DELIVERED"}</p>
          {reel_html}
          {transcript_html}
          {"<p style='margin:10px 0 0;color:#92400e;font-weight:600'>Human review flags:</p>" + flags_html if flags_html else ""}
        </div>"""

    other_summary = ""
    if other:
        items = "".join(f"<li><strong>{c}</strong> — {s}</li>" for c, s in other.items())
        other_summary = f"""
        <h3 style="color:#111;margin:22px 0 8px">Not delivered / skipped</h3>
        <ul style="margin:0 0 0 18px;color:#555;line-height:1.6">{items}</ul>"""

    return f"""<!doctype html><html><body style="font-family:Arial,sans-serif;background:#f4f5f7;padding:20px">
  <div style="max-width:720px;margin:auto;background:#fff;border-radius:12px;padding:28px;border:1px solid #e5e7eb">
    <h2 style="margin:0 0 6px;color:#111">Reel batch complete — review needed</h2>
    <p style="color:#555;margin:0 0 18px">Run finished at {run_at}. {len(delivered)} of {len(results)} client(s) delivered.</p>

    <h3 style="color:#111;margin:18px 0 8px">Summary</h3>
    <table style="border-collapse:collapse;width:100%;font-size:14px;border:1px solid #e5e7eb">
      <tr style="background:#f9fafb">
        <th style="padding:8px 12px;text-align:left">Client</th>
        <th style="padding:8px 12px;text-align:left">Status</th>
      </tr>
      {rows}
    </table>

    {"<h3 style='color:#111;margin:26px 0 8px'>Delivered reels — please approve for posting</h3>" + detail_blocks if detail_blocks else ""}
    {other_summary}

    <p style="color:#999;font-size:12px;margin-top:24px">
      Review music/SFX feel, transitions, and caption taste in each project's edit/REVIEW.md.
      Reply to this thread or post in your usual channel once approved.
    </p>
  </div></body></html>"""


def _send_smtp(owner: str, subject: str, html: str, server: smtplib.SMTP | None) -> tuple[bool, str]:
    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587") or "587")

    if not (host and user and password):
        return False, "smtp not configured"

    own_server = server is None
    try:
        if own_server:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
            server.login(user, password)
        assert server is not None
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = owner
        msg.attach(MIMEText(html, "html"))
        server.sendmail(user, [owner], msg.as_string())
        return True, "sent (smtp)"
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    finally:
        if own_server and server is not None:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass


def send_batch_approval_email(results: dict[str, str]) -> dict:
    """Email all owners a batch summary. Returns per-recipient status report."""
    dotenv_util.load_dotenv()

    if not _env_bool("SEND_APPROVAL_EMAIL", True):
        logger.info("SEND_APPROVAL_EMAIL=false — skipping approval email.")
        return {"skipped": "SEND_APPROVAL_EMAIL=false"}

    owners = _owner_emails()
    if not owners:
        logger.warning("OWNER_EMAILS is empty — skipping approval email.")
        return {"skipped": "OWNER_EMAILS empty"}

    if not results:
        logger.info("No clients processed — skipping approval email.")
        return {"skipped": "no results"}

    run_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = _batch_html(results=results, run_at=run_at)
    delivered_count = sum(1 for s in results.values() if s == "DELIVERED")
    subject = f"[Approval] Reel batch — {delivered_count}/{len(results)} delivered"

    transport = (os.environ.get("EMAIL_TRANSPORT", "auto") or "auto").lower()
    want_smtp = transport in ("auto", "smtp")
    want_file = transport in ("auto", "file")

    smtp_server = None
    smtp_ready = want_smtp and all(
        os.environ.get(k, "").strip()
        for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")
    )
    if smtp_ready:
        try:
            smtp_server = smtplib.SMTP(
                os.environ["SMTP_HOST"],
                int(os.environ.get("SMTP_PORT", "587") or "587"),
                timeout=20,
            )
            smtp_server.starttls()
            smtp_server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        except Exception as e:  # noqa: BLE001
            logger.error("SMTP connect/login failed: %s", e)
            smtp_server = None
            smtp_ready = False

    report: dict[str, str] = {}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for owner in owners:
        sent = False

        if want_smtp and smtp_ready and smtp_server is not None:
            ok, msg = _send_smtp(owner, subject, html, smtp_server)
            if ok:
                report[owner] = msg
                sent = True
            else:
                logger.warning("SMTP send to %s failed: %s", owner, msg)

        if want_file and not sent:
            FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
            safe = owner.replace("@", "_at_")
            out = FALLBACK_DIR / f"batch_{stamp}_{safe}.html"
            out.write_text(html, encoding="utf-8")
            report[owner] = f"written to {out}"
            sent = True

        if not sent:
            report[owner] = "FAILED: no transport succeeded"

    if smtp_server is not None:
        try:
            smtp_server.quit()
        except Exception:  # noqa: BLE001
            pass

    logger.info("Batch approval email: %s", report)
    return report
