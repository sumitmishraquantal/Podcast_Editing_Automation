#!/usr/bin/env python3
"""
caption_gen.py - generate a professional Instagram caption + hashtags from the
reel transcript, using Groq (llama-3.3-70b-versatile by default).

Writes edit/caption.json:
    {"caption": "...", "hashtags": ["#x", "#y", ...], "model": "...", "source": "groq"|"fallback"}

Env:
    GROQ_API_KEY     required for live generation
    GROQ_MODEL       default "llama-3.3-70b-versatile"

If the key is missing or the call fails, a safe fallback caption is written so
the pipeline never breaks over caption generation.

Usage (standalone):
    python caption_gen.py <CLIENT>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dotenv_util
dotenv_util.load_dotenv()

HERE = Path(__file__).resolve().parent
PROJECTS_DIR = HERE / "projects"

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a social media manager writing professional Instagram captions for "
    "short-form vertical reels. Given a transcript of the reel's spoken content, "
    "write a polished, engaging caption and a set of relevant hashtags.\n\n"
    "Rules:\n"
    "- Caption: 2-4 short sentences, professional but warm. Start with a hook. "
    "Do NOT use clickbait, ALL CAPS, or more than one emoji.\n"
    "- Hashtags: 8-12 relevant, specific hashtags (mix of broad and niche). "
    "No spaces inside a hashtag.\n"
    "- Return ONLY valid JSON, no markdown fences, in exactly this shape:\n"
    '{"caption": "<caption text>", "hashtags": ["#one", "#two", ...]}'
)


def _fallback(transcript: str) -> dict:
    snippet = transcript.strip()[:120]
    return {
        "caption": (snippet + ("…" if len(transcript) > 120 else "")) or "New reel.",
        "hashtags": ["#reels", "#podcast", "#shorts", "#viral", "#instagram"],
        "model": GROQ_MODEL,
        "source": "fallback",
    }


def generate(transcript: str) -> dict:
    """Return {caption, hashtags, model, source}. Never raises."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key or not transcript.strip():
        return _fallback(transcript)
    try:
        import requests
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Transcript:\n\"\"\"\n{transcript.strip()}\n\"\"\""},
                ],
                "temperature": 0.7,
                "max_tokens": 500,
                "response_format": {"type": "json_object"},
            },
            timeout=45,
        )
        if r.status_code != 200:
            print(f"  caption_gen: Groq HTTP {r.status_code}: {r.text[:160]} -> fallback")
            return _fallback(transcript)
        content = r.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        caption = str(data.get("caption", "")).strip()
        hashtags = data.get("hashtags", [])
        # normalise hashtags
        clean = []
        for h in hashtags:
            h = str(h).strip().replace(" ", "")
            if h and not h.startswith("#"):
                h = "#" + h
            if h:
                clean.append(h)
        if not caption:
            return _fallback(transcript)
        return {"caption": caption, "hashtags": clean, "model": GROQ_MODEL, "source": "groq"}
    except Exception as e:  # noqa: BLE001
        print(f"  caption_gen: failed ({e}) -> fallback")
        return _fallback(transcript)


def generate_for_client(client: str) -> dict:
    """Read the client's transcript, generate caption, write edit/caption.json."""
    edit = PROJECTS_DIR / client / "edit"
    words_path = edit / "words.json"
    transcript = ""
    if words_path.exists():
        try:
            words = json.loads(words_path.read_text(encoding="utf-8"))
            transcript = " ".join(w.get("word", "") for w in words)
        except Exception:  # noqa: BLE001
            transcript = ""
    result = generate(transcript)
    out = edit / "caption.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"  caption_gen: wrote {out} (source={result['source']}, "
          f"{len(result['hashtags'])} hashtags)")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python caption_gen.py <CLIENT>")
    generate_for_client(sys.argv[1])