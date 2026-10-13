"""Topic + script + metadata in ONE Gemini call (structured JSON), with validation."""
import re

from .config import CFG
from .gemini_client import generate_json
from .util import strip_markup


def generate_topic(history: list[str]) -> str:
    recent = "\n".join(f"- {t}" for t in history[-60:]) or "(none yet)"
    prompt = (
        f"You plan topics for a faceless YouTube channel. Niche: {CFG['niche']}.\n"
        f"Pick ONE fresh, specific, curiosity-driven topic that is accurate and safe for a general audience.\n"
        f"Do NOT repeat or closely resemble these recent topics:\n{recent}\n\n"
        f'Return ONLY JSON: {{"topic": "..."}}'
    )
    data = generate_json(prompt, temperature=1.0)
    topic = strip_markup(data.get("topic", "") if isinstance(data, dict) else str(data))
    if len(topic) < 5:
        raise ValueError("Gemini returned an empty topic")
    return topic[:200]


def generate_package(topic: str, fmt: str) -> dict:
    spec = CFG["short" if fmt == "short" else "video"]
    prompt = f"""You write voice-over scripts for a faceless YouTube channel. Niche: {CFG['niche']}.
Write the script, in {CFG['language_name']}, for a {'YouTube Short (vertical)' if fmt == 'short' else 'YouTube video (horizontal)'} about:
TOPIC: {topic}

Rules:
- Spoken length about {spec['seconds']} seconds when read aloud, split into {spec['min_scenes']}-{spec['max_scenes']} scenes.
- Scene 1 is a strong hook. The last scene is a short, natural closing line (no begging for likes).
- Each scene's narration: 1-2 short sentences, plain spoken text only. No markdown, no labels, no emojis, no stage directions.
- Facts must be accurate. Do not invent statistics, quotes or sources. If unsure, leave it out.
- No medical, legal or financial advice. No hateful, violent or adult content.
- "visual" = 2-4 English words describing realistic stock footage for that scene (e.g. "ocean waves sunset").
- "thumbnail_text" = 2-4 punchy words.

Return ONLY JSON in exactly this shape:
{{"title": "max 70 chars, curiosity-driven, no clickbait lies",
 "description": "2-3 sentences, then 3-5 hashtags",
 "tags": ["8 short tags"],
 "thumbnail_text": "WORDS",
 "scenes": [{{"narration": "...", "visual": "..."}}]}}"""
    pkg = generate_json(prompt)
    return validate_package(pkg, fmt)


def validate_package(pkg, fmt: str) -> dict:
    spec = CFG["short" if fmt == "short" else "video"]
    if not isinstance(pkg, dict):
        raise ValueError("Package is not a JSON object")
    scenes = []
    for s in pkg.get("scenes") or []:
        narr = strip_markup(s.get("narration", "")) if isinstance(s, dict) else ""
        vis = strip_markup(s.get("visual", "")) if isinstance(s, dict) else ""
        if narr:
            scenes.append({"narration": narr[:500], "visual": (vis or "abstract background")[:80]})
    if len(scenes) < max(3, spec["min_scenes"] - 2):
        raise ValueError(f"Too few scenes ({len(scenes)})")
    scenes = scenes[: spec["max_scenes"] + 2]
    title = strip_markup(pkg.get("title", ""))
    if len(title) < 5:
        raise ValueError("Missing title")
    tags, total = [], 0
    for t in pkg.get("tags") or []:
        t = strip_markup(t).replace(",", "")
        if t and total + len(t) < 450:
            tags.append(t[:40]); total += len(t)
    desc = re.sub(r"[ \t]+", " ", str(pkg.get("description", "")).replace("**", "")).strip()
    return {
        "title": title[:95],
        "description": desc[:4500],
        "tags": tags[:12],
        "thumbnail_text": strip_markup(pkg.get("thumbnail_text", "")) or title[:30],
        "scenes": scenes,
    }
