#!/usr/bin/env python3
"""
instagram_post.py - publish a delivered reel to Instagram via the Graph API.

Mirrors the proven n8n flow:
    1. upload local reel mp4 -> Cloudinary (public video_url)
    2. POST /{ig_id}/media  (media_type=REELS, video_url, caption)  -> container id
    3. poll GET /{container_id}?fields=status_code  until FINISHED
    4. POST /{ig_id}/media_publish  (creation_id)  -> live post

Env (.env):
    IG_ACCESS_TOKEN            (required) long-lived Graph API token
    IG_BUSINESS_ID             default 17841421996308337
    GRAPH_API_VERSION          default v22.0
    CLOUDINARY_CLOUD_NAME      default dpptaeeiu
    CLOUDINARY_UPLOAD_PRESET   default instagram_n8n_post

Usage (standalone test):
    python instagram_post.py <CLIENT>          # posts newest delivered reel for client
    python instagram_post.py <CLIENT> --dry    # do everything EXCEPT the final publish
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dotenv_util
dotenv_util.load_dotenv()

import requests

HERE = Path(__file__).resolve().parent
PROJECTS_DIR = HERE / "projects"
DELIVERED_DIR = HERE / "delivered"

IG_ID    = os.environ.get("IG_BUSINESS_ID", "17841421996308337")
TOKEN    = os.environ.get("IG_ACCESS_TOKEN", "").strip()
GVER     = os.environ.get("GRAPH_API_VERSION", "v22.0")
CL_CLOUD = os.environ.get("CLOUDINARY_CLOUD_NAME", "dpptaeeiu")
CL_PRESET= os.environ.get("CLOUDINARY_UPLOAD_PRESET", "instagram_n8n_post")

GRAPH = f"https://graph.facebook.com/{GVER}"

# Reel video processing can be slow; poll up to this long.
POLL_INTERVAL_S = 20
POLL_MAX_TRIES  = 30   # 30 x 20s = up to 10 min


class PostError(Exception):
    pass


def _reel_for(client: str, timestamp: str | None = None) -> Path:
    """Return a specific reel by timestamp, or the newest if none given.

    The approval server passes the exact timestamp from the email so that a
    delayed click posts the reel that was reviewed - not whatever is newest
    at click time (which could be a different, later run).
    """
    folder = DELIVERED_DIR / client
    if timestamp:
        exact = folder / f"Processed_{timestamp}.mp4"
        if exact.exists():
            return exact
        raise PostError(f"No reel for {client} with timestamp {timestamp} ({exact})")
    reels = sorted(folder.glob("Processed_*.mp4"))
    if not reels:
        raise PostError(f"No delivered reel found in {folder}")
    return reels[-1]


def _thumbnail_for(client: str, timestamp: str | None = None) -> Path | None:
    """Return the archived thumbnail for a reel, if one exists."""
    folder = DELIVERED_DIR / client
    if timestamp:
        exact = folder / f"Thumbnail_{timestamp}.png"
        if exact.exists():
            return exact
        cap_path = PROJECTS_DIR / client / "edit" / "caption.json"
        if cap_path.exists():
            try:
                data = json.loads(cap_path.read_text(encoding="utf-8"))
                p = Path(data.get("thumbnail_path", ""))
                if p.exists():
                    return p
            except Exception:
                pass
        return None
    thumbs = sorted(folder.glob("Thumbnail_*.png"))
    return thumbs[-1] if thumbs else None


def _load_caption(client: str) -> str:
    """Build the Instagram caption (caption text + hashtags) from caption.json."""
    cap_path = PROJECTS_DIR / client / "edit" / "caption.json"
    if not cap_path.exists():
        return ""
    try:
        data = json.loads(cap_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    caption = str(data.get("caption", "")).strip()
    hashtags = data.get("hashtags", []) or []
    tags = " ".join(hashtags) if hashtags else ""
    return (caption + ("\n\n" + tags if tags else "")).strip()


def upload_to_cloudinary(video_path: Path) -> str:
    """Unsigned upload of the local mp4 -> returns the public secure_url."""
    url = f"https://api.cloudinary.com/v1_1/{CL_CLOUD}/video/upload"
    print(f"  [cloudinary] uploading {video_path.name} ({video_path.stat().st_size/1e6:.1f} MB)...")
    with open(video_path, "rb") as f:
        r = requests.post(url, data={"upload_preset": CL_PRESET},
                          files={"file": (video_path.name, f, "video/mp4")}, timeout=300)
    if r.status_code not in (200, 201):
        raise PostError(f"Cloudinary upload failed: {r.status_code} {r.text[:300]}")
    secure_url = r.json().get("secure_url", "")
    if not secure_url:
        raise PostError(f"Cloudinary returned no secure_url: {r.text[:300]}")
    print(f"  [cloudinary] secure_url -> {secure_url}")
    return secure_url


def upload_image_to_cloudinary(image_path: Path) -> str:
    """Unsigned upload of a PNG cover -> returns the public secure_url."""
    url = f"https://api.cloudinary.com/v1_1/{CL_CLOUD}/image/upload"
    print(f"  [cloudinary] uploading cover {image_path.name} ({image_path.stat().st_size/1e3:.0f} KB)...")
    with open(image_path, "rb") as f:
        r = requests.post(url, data={"upload_preset": CL_PRESET},
                          files={"file": (image_path.name, f, "image/png")}, timeout=120)
    if r.status_code not in (200, 201):
        raise PostError(f"Cloudinary image upload failed: {r.status_code} {r.text[:300]}")
    secure_url = r.json().get("secure_url", "")
    if not secure_url:
        raise PostError(f"Cloudinary returned no secure_url: {r.text[:300]}")
    print(f"  [cloudinary] cover_url -> {secure_url}")
    return secure_url


def create_container(video_url: str, caption: str, cover_url: str | None = None) -> str:
    print("  [graph] creating REELS container...")
    payload = {"media_type": "REELS", "video_url": video_url, "caption": caption}
    if cover_url:
        payload["cover_url"] = cover_url
        print(f"  [graph] using custom cover thumbnail")
    r = requests.post(f"{GRAPH}/{IG_ID}/media",
                      params={"access_token": TOKEN},
                      data=payload,
                      timeout=60)
    if r.status_code != 200:
        raise PostError(f"create container failed: {r.status_code} {r.text[:300]}")
    cid = r.json().get("id", "")
    if not cid:
        raise PostError(f"no container id: {r.text[:300]}")
    print(f"  [graph] container id -> {cid}")
    return cid


def wait_until_finished(container_id: str) -> None:
    print("  [graph] polling container status (video processing is slow)...")
    for attempt in range(1, POLL_MAX_TRIES + 1):
        r = requests.get(f"{GRAPH}/{container_id}",
                        params={"access_token": TOKEN, "fields": "status_code"}, timeout=30)
        status = r.json().get("status_code", "?") if r.status_code == 200 else f"HTTP {r.status_code}"
        print(f"    try {attempt}/{POLL_MAX_TRIES}: status={status}")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise PostError(f"container processing ERROR: {r.text[:300]}")
        time.sleep(POLL_INTERVAL_S)
    raise PostError("container did not reach FINISHED within the poll window")


def publish(container_id: str) -> str:
    print("  [graph] publishing...")
    r = requests.post(f"{GRAPH}/{IG_ID}/media_publish",
                      params={"access_token": TOKEN},
                      data={"creation_id": container_id}, timeout=60)
    if r.status_code != 200:
        raise PostError(f"publish failed: {r.status_code} {r.text[:300]}")
    post_id = r.json().get("id", "")
    print(f"  [graph] PUBLISHED. media id -> {post_id}")
    return post_id


def post_reel(client: str, dry: bool = False, timestamp: str | None = None) -> dict:
    """Full chain. Returns {ok, post_id, video_url, container_id} or raises PostError."""
    if not TOKEN:
        raise PostError("IG_ACCESS_TOKEN not set in .env")
    reel = _reel_for(client, timestamp)
    caption = _load_caption(client)
    thumb = _thumbnail_for(client, timestamp)
    print(f"\n  posting reel for '{client}': {reel.name}")
    if thumb:
        print(f"  thumbnail: {thumb.name}")
    else:
        print("  thumbnail: none (Instagram will auto-pick a frame)")
    print(f"  caption preview: {caption[:80]!r}{'...' if len(caption) > 80 else ''}")

    video_url = upload_to_cloudinary(reel)
    cover_url = upload_image_to_cloudinary(thumb) if thumb else None
    container_id = create_container(video_url, caption, cover_url=cover_url)
    wait_until_finished(container_id)

    if dry:
        print("  [dry] skipping final publish. Container is ready and would post.")
        return {"ok": True, "dry": True, "video_url": video_url,
                "cover_url": cover_url, "container_id": container_id}

    post_id = publish(container_id)
    return {"ok": True, "post_id": post_id, "video_url": video_url,
            "cover_url": cover_url, "container_id": container_id}


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python instagram_post.py <CLIENT> [--dry]")
    client = sys.argv[1]
    dry = "--dry" in sys.argv[2:]
    # optional positional timestamp (e.g. 2026-06-18_1616) after client
    timestamp = None
    for a in sys.argv[2:]:
        if a != "--dry":
            timestamp = a
    try:
        result = post_reel(client, dry=dry, timestamp=timestamp)
        print(f"\n[OK] {json.dumps(result, indent=2)}")
    except PostError as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()