#!/usr/bin/env python3
"""
start_services.py - launch the approval service (Flask server + cloudflared tunnel)
as one command, auto-capture the tunnel URL, and write it into .env.

This removes the manual "copy the new tunnel URL into .env each restart" step:
the launcher reads cloudflared's output, grabs the https://...trycloudflare.com
URL, and updates APPROVAL_BASE_URL automatically.

Run:
    python start_services.py
Leave it running. Ctrl+C stops both the server and the tunnel.

This is the PERSISTENT half of the system. The pipeline (run_all.py) is run
separately whenever you have new clips.

Env (.env):
    APPROVAL_PORT       default 8000
    CLOUDFLARED_EXE     full path to cloudflared.exe (auto-discovered if unset)
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dotenv_util
dotenv_util.load_dotenv()

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"
PORT = int(os.environ.get("APPROVAL_PORT", "8000") or "8000")
PY = sys.executable

_procs = []


def _find_cloudflared() -> str:
    override = os.environ.get("CLOUDFLARED_EXE", "").strip()
    if override and Path(override).exists():
        return override
    found = shutil.which("cloudflared")
    if found:
        return found
    # known install locations
    import glob
    candidates = [
        r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        r"C:\Program Files\cloudflared\cloudflared.exe",
        str(Path.home() / "AppData/Local/Microsoft/WinGet/Packages/Cloudflare.cloudflared_*/cloudflared.exe"),
        "/usr/local/bin/cloudflared", "/usr/bin/cloudflared", "/opt/homebrew/bin/cloudflared",
    ]
    for pat in candidates:
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    sys.exit("ERROR: cloudflared not found. Install it or set CLOUDFLARED_EXE in .env.")


def _update_env_url(url: str) -> None:
    """Write/replace APPROVAL_BASE_URL in .env without touching other lines."""
    lines = []
    found = False
    if ENV_FILE.exists():
        for ln in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("APPROVAL_BASE_URL="):
                lines.append(f"APPROVAL_BASE_URL={url}")
                found = True
            else:
                lines.append(ln)
    if not found:
        lines.append(f"APPROVAL_BASE_URL={url}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["APPROVAL_BASE_URL"] = url
    print(f"\n  [launcher] APPROVAL_BASE_URL updated in .env -> {url}\n")


def _start_server():
    print("  [launcher] starting approval server on port", PORT)
    p = subprocess.Popen([PY, str(HERE / "approval_server.py")])
    _procs.append(p)
    return p


def _start_tunnel_and_capture():
    cf = _find_cloudflared()
    print("  [launcher] starting cloudflared tunnel:", cf)
    p = subprocess.Popen(
        [cf, "tunnel", "--url", f"http://localhost:{PORT}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    _procs.append(p)

    url_re = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com")
    captured = {"url": None}

    def reader():
        for line in p.stdout:
            sys.stdout.write("  [tunnel] " + line)
            if not captured["url"]:
                m = url_re.search(line)
                if m:
                    captured["url"] = m.group(0)
                    _update_env_url(captured["url"])
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    return p, captured


def _shutdown(*_):
    print("\n  [launcher] shutting down server + tunnel...")
    for p in _procs:
        try:
            p.terminate()
        except Exception:
            pass
    time.sleep(1)
    for p in _procs:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("="*64)
    print("  REEL STUDIO - APPROVAL SERVICE")
    print("  Leave this running. Ctrl+C stops everything.")
    print("="*64)

    _start_server()
    time.sleep(2)  # let Flask bind the port before the tunnel points at it
    _, captured = _start_tunnel_and_capture()

    # wait for the tunnel URL to be captured
    for _ in range(30):
        if captured["url"]:
            break
        time.sleep(1)
    if not captured["url"]:
        print("\n  [launcher] WARNING: tunnel URL not captured yet. Check the tunnel output above.")
    else:
        print("="*64)
        print(f"  SERVICE READY")
        print(f"  Public URL : {captured['url']}")
        print(f"  Health     : {captured['url']}/health")
        print(f"  .env updated automatically. Now run:  python run_all.py")
        print("="*64)

    # keep alive until Ctrl+C; also surface if either child dies
    while True:
        time.sleep(2)
        for p in _procs:
            if p.poll() is not None:
                print(f"\n  [launcher] a child process exited (code {p.returncode}). Shutting down.")
                _shutdown()


if __name__ == "__main__":
    main()