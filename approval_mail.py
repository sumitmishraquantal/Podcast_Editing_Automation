# #!/usr/bin/env python3
# """
# approval_mail.py - send a batch approval email after run_all.py finishes.

# .env keys:
#     OWNER_EMAILS=owner1@x.com,owner2@y.com
#     SMTP_HOST=smtp.gmail.com
#     SMTP_PORT=587
#     SMTP_USER=youraddress@gmail.com
#     SMTP_PASSWORD=your-app-password
#     EMAIL_TRANSPORT=auto          # auto | smtp | file
#     SEND_APPROVAL_EMAIL=true
# """
# from __future__ import annotations

# import json
# import logging
# import os
# import smtplib
# from datetime import datetime
# from email.mime.multipart import MIMEMultipart
# from email.mime.text import MIMEText
# from pathlib import Path
# from urllib.parse import quote

# HERE = Path(__file__).resolve().parent
# PROJECTS_DIR = HERE / "projects"
# DELIVERED_DIR = HERE / "delivered"
# FALLBACK_DIR = HERE / "sent_emails"

# import dotenv_util

# logger = logging.getLogger(__name__)


# def _env_bool(name: str, default: bool = True) -> bool:
#     raw = os.environ.get(name, "").strip().lower()
#     if not raw:
#         return default
#     return raw in ("1", "true", "yes", "on")


# def _owner_emails() -> list[str]:
#     return [e.strip() for e in os.environ.get("OWNER_EMAILS", "").split(",") if e.strip()]


# def _client_details(client: str) -> dict:
#     """QC verdict, human-eye flags, FULL transcript, caption+hashtags, reel link."""
#     edit = PROJECTS_DIR / client / "edit"
#     review_path = edit / "REVIEW.md"
#     words_path = edit / "words.json"
#     caption_path = edit / "caption.json"

#     verdict = ""
#     human_flags: list[str] = []
#     if review_path.exists():
#         text = review_path.read_text(encoding="utf-8")
#         first = text.splitlines()[0] if text.splitlines() else ""
#         verdict = first.split("----")[-1].strip() if "----" in first else ""
#         in_human = False
#         for ln in text.splitlines():
#             if ln.startswith("## Needs human"):
#                 in_human = True
#                 continue
#             if in_human and ln.startswith("- "):
#                 human_flags.append(ln[2:].strip())
#             elif in_human and ln.startswith("##"):
#                 break

#     # FULL transcript (no truncation)
#     transcript = ""
#     if words_path.exists():
#         try:
#             words = json.loads(words_path.read_text(encoding="utf-8"))
#             transcript = " ".join(w.get("word", "") for w in words).strip()
#         except Exception:  # noqa: BLE001
#             transcript = ""

#     # caption + hashtags + reel link (written by caption_gen + rclone_sync archive)
#     caption = ""
#     hashtags: list[str] = []
#     reel_url = ""
#     drive_path = ""
#     processed_name = ""
#     if caption_path.exists():
#         try:
#             cap = json.loads(caption_path.read_text(encoding="utf-8"))
#             caption = str(cap.get("caption", "")).strip()
#             hashtags = cap.get("hashtags", []) or []
#             reel_url = str(cap.get("reel_url", "")).strip()
#             drive_path = str(cap.get("drive_path", "")).strip()
#             processed_name = str(cap.get("processed_name", "")).strip()
#         except Exception:  # noqa: BLE001
#             pass

#     reel_path = ""
#     delivered = sorted((DELIVERED_DIR / client).glob("Processed_*.mp4"))
#     if delivered:
#         reel_path = str(delivered[-1].relative_to(HERE))
#     elif (edit / "final.mp4").exists():
#         reel_path = str((edit / "final.mp4").relative_to(HERE))

#     remote = os.environ.get("RCLONE_REMOTE", "gdrive")
#     root = os.environ.get("RCLONE_ROOT", "reel-projects")
#     drive_hint = f"{remote}:{root}/{client}/done/Processed_Video/"

#     return {
#         "verdict": verdict,
#         "human_flags": human_flags,
#         "transcript": transcript,
#         "caption": caption,
#         "hashtags": hashtags,
#         "reel_url": reel_url,
#         "drive_path": drive_path,
#         "processed_name": processed_name,
#         "reel_path": reel_path,
#         "drive_hint": drive_hint,
#     }


# def _status_color(status: str) -> str:
#     if status == "DELIVERED":
#         return "#16a34a"
#     if status.startswith("NOT DELIVERED"):
#         return "#dc2626"
#     if status.startswith("SKIPPED"):
#         return "#6b7280"
#     return "#d97706"


# def _approval_buttons(client: str, d: dict, owner_from: str) -> str:
#     """Approve / Decline as mailto links producing a structured reply.

#     A button in email can't run code without a server. mailto opens a pre-filled
#     reply the operator sends; the structured subject is machine-parseable later
#     when an endpoint (+ Meta Graph API posting) is added. For now, sending the
#     reply IS the approval record.
#     """
#     to = quote(owner_from)  # reply goes back to the sender (the SMTP_USER)
#     tag = d.get("processed_name") or client
#     approve_subj = quote(f"APPROVE {client} {tag} - upload to Instagram")
#     decline_subj = quote(f"DECLINE {client} {tag} - do not upload")
#     approve_body = quote(f"Approved {client} reel ({tag}) for Instagram upload.")
#     decline_body = quote(f"Declined {client} reel ({tag}). Not for upload.")
#     approve = f"mailto:{to}?subject={approve_subj}&body={approve_body}"
#     decline = f"mailto:{to}?subject={decline_subj}&body={decline_body}"
#     return f"""
#       <div style="margin:16px 0 4px">
#         <a href="{approve}" style="display:inline-block;background:#16a34a;color:#fff;
#            text-decoration:none;padding:11px 26px;border-radius:6px;font-weight:700;
#            font-size:14px;margin-right:10px">✓ Approve for Instagram</a>
#         <a href="{decline}" style="display:inline-block;background:#dc2626;color:#fff;
#            text-decoration:none;padding:11px 26px;border-radius:6px;font-weight:700;
#            font-size:14px">✕ Decline</a>
#       </div>
#       <p style="margin:6px 0 0;color:#9ca3af;font-size:11px">
#         Approving opens a pre-filled reply — just hit send. (Instagram auto-posting
#         connects later via the Meta Graph API.)</p>"""


# def _watch_button(d: dict) -> str:
#     url = d.get("reel_url", "")
#     if url:
#         return (f'<a href="{url}" style="display:inline-block;background:#111;color:#fff;'
#                 f'text-decoration:none;padding:11px 26px;border-radius:6px;font-weight:700;'
#                 f'font-size:14px">▶ Watch the reel</a>')
#     # no shareable link — fall back to showing the Drive location as text
#     return (f'<p style="margin:0;color:#555;font-size:13px">Reel on Drive: '
#             f'{d.get("drive_path") or d.get("drive_hint","")}</p>')


# def _batch_html(*, results: dict[str, str], run_at: str, reply_to: str) -> str:
#     delivered = {c: s for c, s in results.items() if s == "DELIVERED"}
#     other = {c: s for c, s in results.items() if s != "DELIVERED"}

#     rows = ""
#     for client, status in results.items():
#         color = _status_color(status)
#         rows += (
#             f'<tr><td style="padding:8px 12px;font-weight:600">{client}</td>'
#             f'<td style="padding:8px 12px;color:{color}">{status}</td></tr>'
#         )

#     detail_blocks = ""
#     for client in delivered:
#         d = _client_details(client)

#         flags_html = ""
#         if d["human_flags"]:
#             items = "".join(f"<li>{f}</li>" for f in d["human_flags"])
#             flags_html = ("<p style='margin:12px 0 0;color:#92400e;font-weight:600'>"
#                           "Human review flags:</p>"
#                           f"<ul style='margin:6px 0 0 18px;color:#92400e'>{items}</ul>")

#         transcript_html = ""
#         if d["transcript"]:
#             transcript_html = (
#                 '<p style="margin:14px 0 4px;color:#111;font-weight:600">Transcript</p>'
#                 f'<p style="margin:0;color:#444;font-size:13px;line-height:1.6;'
#                 f'background:#f9fafb;border:1px solid #eee;border-radius:6px;padding:10px">'
#                 f'{d["transcript"]}</p>'
#             )

#         caption_html = ""
#         if d["caption"]:
#             tags = " ".join(d["hashtags"]) if d["hashtags"] else ""
#             caption_html = (
#                 '<p style="margin:14px 0 4px;color:#111;font-weight:600">'
#                 'Suggested caption</p>'
#                 f'<p style="margin:0;color:#222;font-size:14px;line-height:1.6">{d["caption"]}</p>'
#                 + (f'<p style="margin:8px 0 0;color:#2563eb;font-size:13px">{tags}</p>' if tags else "")
#             )

#         detail_blocks += f"""
#         <div style="border:1px solid #e5e7eb;border-radius:8px;padding:18px;margin:14px 0">
#           <h3 style="margin:0 0 6px;color:#111">{client}</h3>
#           <p style="margin:0 0 12px;color:#16a34a;font-weight:600">{d["verdict"] or "DELIVERED"}</p>
#           <div style="margin:0 0 6px">{_watch_button(d)}</div>
#           {caption_html}
#           {transcript_html}
#           {flags_html}
#           {_approval_buttons(client, d, reply_to)}
#         </div>"""

#     other_summary = ""
#     if other:
#         items = "".join(f"<li><strong>{c}</strong> — {s}</li>" for c, s in other.items())
#         other_summary = ("<h3 style='color:#111;margin:22px 0 8px'>Not delivered / skipped</h3>"
#                          f"<ul style='margin:0 0 0 18px;color:#555;line-height:1.6'>{items}</ul>")

#     return f"""<!doctype html><html><body style="font-family:Arial,sans-serif;background:#f4f5f7;padding:20px">
#   <div style="max-width:720px;margin:auto;background:#fff;border-radius:12px;padding:28px;border:1px solid #e5e7eb">
#     <h2 style="margin:0 0 6px;color:#111">Reel batch complete — review needed</h2>
#     <p style="color:#555;margin:0 0 18px">Run finished at {run_at}. {len(delivered)} of {len(results)} client(s) delivered.</p>

#     <h3 style="color:#111;margin:18px 0 8px">Summary</h3>
#     <table style="border-collapse:collapse;width:100%;font-size:14px;border:1px solid #e5e7eb">
#       <tr style="background:#f9fafb">
#         <th style="padding:8px 12px;text-align:left">Client</th>
#         <th style="padding:8px 12px;text-align:left">Status</th>
#       </tr>
#       {rows}
#     </table>

#     {"<h3 style='color:#111;margin:26px 0 8px'>Delivered reels — please approve for posting</h3>" + detail_blocks if detail_blocks else ""}
#     {other_summary}

#     <p style="color:#999;font-size:12px;margin-top:24px">
#       Review music/SFX feel, transitions, and caption taste in each project's edit/REVIEW.md.
#     </p>
#   </div></body></html>"""


# def _send_smtp(owner: str, subject: str, html: str, server, reply_to: str) -> tuple[bool, str]:
#     host = os.environ.get("SMTP_HOST", "").strip()
#     user = os.environ.get("SMTP_USER", "").strip()
#     password = os.environ.get("SMTP_PASSWORD", "").strip()
#     port = int(os.environ.get("SMTP_PORT", "587") or "587")
#     if not (host and user and password):
#         return False, "smtp not configured"
#     own_server = server is None
#     try:
#         if own_server:
#             server = smtplib.SMTP(host, port, timeout=20)
#             server.starttls()
#             server.login(user, password)
#         msg = MIMEMultipart("alternative")
#         msg["Subject"] = subject
#         msg["From"] = user
#         msg["To"] = owner
#         msg["Reply-To"] = reply_to
#         msg.attach(MIMEText(html, "html"))
#         server.sendmail(user, [owner], msg.as_string())
#         return True, "sent (smtp)"
#     except Exception as e:  # noqa: BLE001
#         return False, str(e)
#     finally:
#         if own_server and server is not None:
#             try:
#                 server.quit()
#             except Exception:  # noqa: BLE001
#                 pass


# def send_batch_approval_email(results: dict[str, str]) -> dict:
#     dotenv_util.load_dotenv()

#     if not _env_bool("SEND_APPROVAL_EMAIL", True):
#         logger.info("SEND_APPROVAL_EMAIL=false — skipping.")
#         return {"skipped": "SEND_APPROVAL_EMAIL=false"}

#     owners = _owner_emails()
#     if not owners:
#         logger.warning("OWNER_EMAILS empty — skipping.")
#         return {"skipped": "OWNER_EMAILS empty"}
#     if not results:
#         return {"skipped": "no results"}

#     reply_to = os.environ.get("SMTP_USER", "").strip() or (owners[0] if owners else "")
#     run_at = datetime.now().strftime("%Y-%m-%d %H:%M")
#     html = _batch_html(results=results, run_at=run_at, reply_to=reply_to)
#     delivered_count = sum(1 for s in results.values() if s == "DELIVERED")
#     subject = f"[Approval] Reel batch — {delivered_count}/{len(results)} delivered"

#     transport = (os.environ.get("EMAIL_TRANSPORT", "auto") or "auto").lower()
#     want_smtp = transport in ("auto", "smtp")
#     want_file = transport in ("auto", "file")

#     smtp_server = None
#     smtp_ready = want_smtp and all(
#         os.environ.get(k, "").strip() for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))
#     if smtp_ready:
#         try:
#             smtp_server = smtplib.SMTP(
#                 os.environ["SMTP_HOST"],
#                 int(os.environ.get("SMTP_PORT", "587") or "587"), timeout=20)
#             smtp_server.starttls()
#             smtp_server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
#         except Exception as e:  # noqa: BLE001
#             logger.error("SMTP connect/login failed: %s", e)
#             smtp_server = None; smtp_ready = False

#     report: dict[str, str] = {}
#     stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

#     for owner in owners:
#         sent = False
#         if want_smtp and smtp_ready and smtp_server is not None:
#             ok, msg = _send_smtp(owner, subject, html, smtp_server, reply_to)
#             if ok:
#                 report[owner] = msg; sent = True
#             else:
#                 logger.warning("SMTP send to %s failed: %s", owner, msg)
#         if want_file and not sent:
#             FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
#             safe = owner.replace("@", "_at_")
#             out = FALLBACK_DIR / f"batch_{stamp}_{safe}.html"
#             out.write_text(html, encoding="utf-8")
#             report[owner] = f"written to {out}"; sent = True
#         if not sent:
#             report[owner] = "FAILED: no transport succeeded"

#     if smtp_server is not None:
#         try:
#             smtp_server.quit()
#         except Exception:  # noqa: BLE001
#             pass

#     logger.info("Batch approval email: %s", report)
#     return report



#!/usr/bin/env python3
"""
approval_mail.py - send a batch approval email after run_all.py finishes.

.env keys:
    OWNER_EMAILS=owner1@x.com,owner2@y.com
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=youraddress@gmail.com
    SMTP_PASSWORD=your-app-password
    EMAIL_TRANSPORT=auto          # auto | smtp | file
    SEND_APPROVAL_EMAIL=true
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

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
    """QC verdict, human-eye flags, FULL transcript, caption+hashtags, reel link."""
    edit = PROJECTS_DIR / client / "edit"
    review_path = edit / "REVIEW.md"
    words_path = edit / "words.json"
    caption_path = edit / "caption.json"

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

    # FULL transcript (no truncation)
    transcript = ""
    if words_path.exists():
        try:
            words = json.loads(words_path.read_text(encoding="utf-8"))
            transcript = " ".join(w.get("word", "") for w in words).strip()
        except Exception:  # noqa: BLE001
            transcript = ""

    # caption + hashtags + reel link (written by caption_gen + rclone_sync archive)
    caption = ""
    hashtags: list[str] = []
    reel_url = ""
    drive_path = ""
    processed_name = ""
    timestamp = ""
    if caption_path.exists():
        try:
            cap = json.loads(caption_path.read_text(encoding="utf-8"))
            caption = str(cap.get("caption", "")).strip()
            hashtags = cap.get("hashtags", []) or []
            reel_url = str(cap.get("reel_url", "")).strip()
            drive_path = str(cap.get("drive_path", "")).strip()
            processed_name = str(cap.get("processed_name", "")).strip()
            timestamp = str(cap.get("timestamp", "")).strip()
        except Exception:  # noqa: BLE001
            pass

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
        "caption": caption,
        "hashtags": hashtags,
        "reel_url": reel_url,
        "drive_path": drive_path,
        "processed_name": processed_name,
        "timestamp": timestamp,
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


def _approval_buttons(client: str, d: dict, owner_from: str) -> str:
    """Approve / Decline as links to the approval server.

    Clicking hits APPROVAL_BASE_URL/approve|decline/<client>/<timestamp>?who=<owner>.
    The server records the decision (shared state) and, on approve, posts the reel
    to Instagram in the background. A second viewer who clicks later sees
    "already decided by <who>".
    """
    base = os.environ.get("APPROVAL_BASE_URL", "").strip().rstrip("/")
    ts = d.get("timestamp") or ""
    if not base or not ts:
        # No server configured yet -> show a clear note instead of dead buttons.
        return ('<p style="margin:14px 0 0;color:#9ca3af;font-size:12px">'
                'Approval buttons inactive (APPROVAL_BASE_URL or reel timestamp missing).</p>')
    who = quote(owner_from.split("@")[0] if owner_from else "owner")
    approve = f"{base}/approve/{quote(client)}/{quote(ts)}?who={who}"
    decline = f"{base}/decline/{quote(client)}/{quote(ts)}?who={who}"
    return f"""
      <div style="margin:16px 0 4px">
        <a href="{approve}" style="display:inline-block;background:#16a34a;color:#fff;
           text-decoration:none;padding:11px 26px;border-radius:6px;font-weight:700;
           font-size:14px;margin-right:10px">✓ Approve &amp; post to Instagram</a>
        <a href="{decline}" style="display:inline-block;background:#dc2626;color:#fff;
           text-decoration:none;padding:11px 26px;border-radius:6px;font-weight:700;
           font-size:14px">✕ Decline</a>
      </div>
      <p style="margin:6px 0 0;color:#9ca3af;font-size:11px">
        One click posts the reviewed reel automatically. If someone already decided,
        you'll see who and when.</p>"""


def _watch_button(d: dict) -> str:
    url = d.get("reel_url", "")
    if url:
        return (f'<a href="{url}" style="display:inline-block;background:#111;color:#fff;'
                f'text-decoration:none;padding:11px 26px;border-radius:6px;font-weight:700;'
                f'font-size:14px">▶ Watch the reel</a>')
    # no shareable link — fall back to showing the Drive location as text
    return (f'<p style="margin:0;color:#555;font-size:13px">Reel on Drive: '
            f'{d.get("drive_path") or d.get("drive_hint","")}</p>')


def _batch_html(*, results: dict[str, str], run_at: str, reply_to: str) -> str:
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
            flags_html = ("<p style='margin:12px 0 0;color:#92400e;font-weight:600'>"
                          "Human review flags:</p>"
                          f"<ul style='margin:6px 0 0 18px;color:#92400e'>{items}</ul>")

        transcript_html = ""
        if d["transcript"]:
            transcript_html = (
                '<p style="margin:14px 0 4px;color:#111;font-weight:600">Transcript</p>'
                f'<p style="margin:0;color:#444;font-size:13px;line-height:1.6;'
                f'background:#f9fafb;border:1px solid #eee;border-radius:6px;padding:10px">'
                f'{d["transcript"]}</p>'
            )

        caption_html = ""
        if d["caption"]:
            tags = " ".join(d["hashtags"]) if d["hashtags"] else ""
            caption_html = (
                '<p style="margin:14px 0 4px;color:#111;font-weight:600">'
                'Suggested caption</p>'
                f'<p style="margin:0;color:#222;font-size:14px;line-height:1.6">{d["caption"]}</p>'
                + (f'<p style="margin:8px 0 0;color:#2563eb;font-size:13px">{tags}</p>' if tags else "")
            )

        detail_blocks += f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:18px;margin:14px 0">
          <h3 style="margin:0 0 6px;color:#111">{client}</h3>
          <p style="margin:0 0 12px;color:#16a34a;font-weight:600">{d["verdict"] or "DELIVERED"}</p>
          <div style="margin:0 0 6px">{_watch_button(d)}</div>
          {caption_html}
          {transcript_html}
          {flags_html}
          {_approval_buttons(client, d, reply_to)}
        </div>"""

    other_summary = ""
    if other:
        items = "".join(f"<li><strong>{c}</strong> — {s}</li>" for c, s in other.items())
        other_summary = ("<h3 style='color:#111;margin:22px 0 8px'>Not delivered / skipped</h3>"
                         f"<ul style='margin:0 0 0 18px;color:#555;line-height:1.6'>{items}</ul>")

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
    </p>
  </div></body></html>"""


def _send_smtp(owner: str, subject: str, html: str, server, reply_to: str) -> tuple[bool, str]:
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
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = owner
        msg["Reply-To"] = reply_to
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
    dotenv_util.load_dotenv()

    if not _env_bool("SEND_APPROVAL_EMAIL", True):
        logger.info("SEND_APPROVAL_EMAIL=false — skipping.")
        return {"skipped": "SEND_APPROVAL_EMAIL=false"}

    owners = _owner_emails()
    if not owners:
        logger.warning("OWNER_EMAILS empty — skipping.")
        return {"skipped": "OWNER_EMAILS empty"}
    if not results:
        return {"skipped": "no results"}

    reply_to = os.environ.get("SMTP_USER", "").strip() or (owners[0] if owners else "")
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = _batch_html(results=results, run_at=run_at, reply_to=reply_to)
    delivered_count = sum(1 for s in results.values() if s == "DELIVERED")
    subject = f"[Approval] Reel batch — {delivered_count}/{len(results)} delivered"

    transport = (os.environ.get("EMAIL_TRANSPORT", "auto") or "auto").lower()
    want_smtp = transport in ("auto", "smtp")
    want_file = transport in ("auto", "file")

    smtp_server = None
    smtp_ready = want_smtp and all(
        os.environ.get(k, "").strip() for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))
    if smtp_ready:
        try:
            smtp_server = smtplib.SMTP(
                os.environ["SMTP_HOST"],
                int(os.environ.get("SMTP_PORT", "587") or "587"), timeout=20)
            smtp_server.starttls()
            smtp_server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        except Exception as e:  # noqa: BLE001
            logger.error("SMTP connect/login failed: %s", e)
            smtp_server = None; smtp_ready = False

    report: dict[str, str] = {}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for owner in owners:
        sent = False
        if want_smtp and smtp_ready and smtp_server is not None:
            ok, msg = _send_smtp(owner, subject, html, smtp_server, reply_to)
            if ok:
                report[owner] = msg; sent = True
            else:
                logger.warning("SMTP send to %s failed: %s", owner, msg)
        if want_file and not sent:
            FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
            safe = owner.replace("@", "_at_")
            out = FALLBACK_DIR / f"batch_{stamp}_{safe}.html"
            out.write_text(html, encoding="utf-8")
            report[owner] = f"written to {out}"; sent = True
        if not sent:
            report[owner] = "FAILED: no transport succeeded"

    if smtp_server is not None:
        try:
            smtp_server.quit()
        except Exception:  # noqa: BLE001
            pass

    logger.info("Batch approval email: %s", report)
    return report