#!/usr/bin/env python3
"""
caption_gen.py - generate a professional, reach-oriented Instagram caption +
hashtags from the reel transcript, using Groq (llama-3.3-70b-versatile).

Writes edit/caption.json:
    {"caption": "...", "hashtags": ["#x", ...], "topic": "...",
     "model": "...", "source": "groq"|"fallback"}

Reach strategy (why the hashtags are structured the way they are):
    Instagram reach comes from a TIERED hashtag mix, not from chasing a single
    "trending" tag. We ask the model for three tiers:
      - BROAD  (large, high-volume tags -> maximum impressions, lots of competition)
      - NICHE  (mid-size, topic-community tags -> the sweet spot for discovery)
      - SPECIFIC (long-tail, tightly on-topic -> easiest to rank/surface in)
    This spread is what actually drives reach for a new post.

    HONEST LIMITATION: neither this script nor the Groq model can know what is
    *trending on Instagram right now* - there is no live trends feed here. The
    tags below are popular/evergreen tags the model associates with the topic,
    tiered for reach. For truly real-time trending tags you'd wire in a live
    hashtag API (e.g. an IG-data provider) and merge its results in _live_tags().

Env:
    GROQ_API_KEY     required for live generation
    GROQ_MODEL       default "llama-3.3-70b-versatile"

Usage:
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

# How many hashtags total (Instagram allows 30; research says ~8-15 performs best).
HASHTAG_MIN = int(os.environ.get("CAPTION_HASHTAG_MIN", "12"))
HASHTAG_MAX = int(os.environ.get("CAPTION_HASHTAG_MAX", "15"))

SYSTEM_PROMPT = (
    "You are an expert Instagram growth strategist and social media copywriter "
    "for short-form vertical Reels. You are given the transcript of a reel's "
    "spoken content. Produce a scroll-stopping caption and a reach-optimized, "
    "tiered hashtag set.\n\n"

    "STEP 1 - Identify the core TOPIC of the reel in 2-5 words (e.g. "
    "'overcoming the inner critic', 'family recovery from addiction'). Base "
    "everything on what is ACTUALLY said in the transcript - never invent facts.\n\n"

    "STEP 2 - Write the CAPTION:\n"
    "- Open with a strong hook line (a question or a bold, relatable statement) "
    "that makes someone stop scrolling.\n"
    "- 2-4 short sentences total. Warm, human, and professional - not corporate.\n"
    "- Tie directly to the transcript's actual message/value.\n"
    "- End with ONE light call-to-action (save, share, follow, or 'link in bio') "
    "that fits the content.\n"
    "- At most ONE emoji, only if it fits naturally. No clickbait, no ALL CAPS, "
    "no fake urgency.\n\n"

    "STEP 3 - Build a TIERED hashtag set for maximum reach. Provide a single "
    f"combined list of {HASHTAG_MIN}-{HASHTAG_MAX} hashtags, intentionally mixing "
    "these tiers:\n"
    "- BROAD (3-4 tags): large high-traffic tags relevant to the theme "
    "(e.g. #motivation, #mentalhealth, #reels). Maximize impressions.\n"
    "- NICHE (5-6 tags): mid-size community tags specific to the topic "
    "(e.g. #innercritic, #selfcompassion, #anxietyrelief). Best for discovery.\n"
    "- SPECIFIC (3-5 tags): long-tail, tightly on-topic phrases "
    "(e.g. #rewiringnegativethoughts, #healingfromwithin). Easiest to surface in.\n"
    "Rules for hashtags: all lowercase, no spaces inside a tag, no duplicates, "
    "no banned/spammy tags (#follow4follow, #like4like, #f4f), and every tag must "
    "be plausibly relevant to the topic - relevance beats volume.\n\n"

    "Return ONLY valid JSON, no markdown, in EXACTLY this shape:\n"
    '{"topic": "<2-5 word topic>", "caption": "<caption text>", '
    '"hashtags": ["#one", "#two", ...]}'
)

# Tags Instagram is known to suppress or that scream spam - filtered out always.
BANNED = {
    "#follow4follow", "#f4f", "#like4like", "#l4l", "#followme", "#followforfollow",
    "#likeforlike", "#tagsforlikes", "#instagood4you", "#spam", "#sex", "#nude",
}


def _live_tags(topic: str) -> list[str]:
    """Hook for real-time trending tags. No live source wired in -> returns [].

    To add real trending tags later: call an IG hashtag-data API here, return the
    tag strings, and they'll be merged + de-duped into the final set.
    """
    return []


def _clean_tags(raw) -> list[str]:
    out, seen = [], set()
    for h in raw or []:
        h = str(h).strip().replace(" ", "").lower()
        if h and not h.startswith("#"):
            h = "#" + h
        if not h or len(h) < 3:
            continue
        if h in BANNED or h in seen:
            continue
        seen.add(h)
        out.append(h)
    return out


def _fallback(transcript: str) -> dict:
    snippet = transcript.strip()[:120]
    return {
        "topic": "",
        "caption": (snippet + ("…" if len(transcript) > 120 else "")) or "New reel.",
        "hashtags": ["#reels", "#reelsinstagram", "#explore", "#podcast",
                     "#motivation", "#mindset", "#growth", "#inspiration"],
        "model": GROQ_MODEL,
        "source": "fallback",
    }


def generate(transcript: str) -> dict:
    """Return {topic, caption, hashtags, model, source}. Never raises."""
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
                "temperature": 0.75,
                "max_tokens": 600,
                "response_format": {"type": "json_object"},
            },
            timeout=45,
        )
        if r.status_code != 200:
            print(f"  caption_gen: Groq HTTP {r.status_code}: {r.text[:160]} -> fallback")
            return _fallback(transcript)
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        caption = str(data.get("caption", "")).strip()
        topic = str(data.get("topic", "")).strip()
        tags = _clean_tags(data.get("hashtags", []))

        # merge any live/trending tags (none by default) then trim to the cap
        for t in _live_tags(topic):
            t = t.lower()
            if t not in tags and t not in BANNED:
                tags.append(t)
        tags = tags[:HASHTAG_MAX]

        if not caption or len(tags) < 5:
            print("  caption_gen: weak result (short caption or <5 tags) -> fallback")
            return _fallback(transcript)
        return {"topic": topic, "caption": caption, "hashtags": tags,
                "model": GROQ_MODEL, "source": "groq"}
    except Exception as e:  # noqa: BLE001
        print(f"  caption_gen: failed ({e}) -> fallback")
        return _fallback(transcript)


def generate_for_client(client: str) -> dict:
    """Read the client's transcript, generate caption, merge into edit/caption.json."""
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

    # Merge into existing caption.json (preview() later adds reel_url etc).
    out = edit / "caption.json"
    existing = {}
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing.update(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(f"  caption_gen: wrote {out} (source={result['source']}, "
          f"topic={result.get('topic','?')!r}, {len(result['hashtags'])} hashtags)")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python caption_gen.py <CLIENT>")
    generate_for_client(sys.argv[1])