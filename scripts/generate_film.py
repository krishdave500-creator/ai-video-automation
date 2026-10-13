"""Story script for the animated film, written by Gemini in ONE call and then validated.
Applies hook formulas, retention rules and title/thumbnail linting."""
import re

from . import cinema as C
from .config import CFG
from .gemini_client import generate_json
from .packaging import fix_thumb_text, hook_menu, lint_title
from .util import strip_markup

EMOTIONS = {"neutral", "happy", "sad", "surprised", "thinking"}
SHOTS = {"wide", "medium", "close", "two"}
HAIR = {"short", "bun", "long", "pigtails", "cap", "pagdi"}
PALETTE = ["#f97316", "#ec4899", "#65a30d", "#6366f1", "#14b8a6", "#e11d48"]


def build_prompt(topic: str, fmt: str) -> str:
    short = fmt == "short"
    spec = CFG["short" if short else "video"]
    structure = (
        "1-2 scenes, 9-13 lines in total, about 35-50 seconds when spoken. The FIRST line is the hook and must be spoken within the first 3 seconds. "
        "End with a line that loops back to the opening idea so the Short replays smoothly."
        if short else
        "4-6 scenes, 24-34 lines in total, about 120-170 seconds when spoken. Give every scene a short chapter 'title'. "
        "Open a new question (re-hook) at least every 30 seconds, deliver the promised payoff explicitly, and close with ONE short ask."
    )
    return f"""You write scripts for a faceless YouTube channel made of cinematic animated mini-films. Niche: {CFG['niche']}.
Language of all spoken text: {CFG['language_name']} (native script). Topic: {topic}
Format: {'YouTube Short (vertical)' if short else 'YouTube video (horizontal)'}. Structure: {structure}

CHARACTERS: 3 or 4 DIFFERENT characters. Character 0 MUST be a girl about 12 years old (age "child", gender "female"), the curious lead who asks questions
and has the most lines. The others are realistic people (mix of adult/elder, male/female, maybe one child). Give each a distinct personality and way of talking.
A narrator (who = -1) may speak at most 3 short lines. Dialogue must sound like real people talking: short sentences, contractions, reactions, no lecturing.

{hook_menu()}
Write 5 hook candidates (one per different formula), choose the best one, and make it the very first spoken line.
Never open with a greeting, with who you are, or with a subscribe request. No intro, no "welcome".

FACTS: accurate only. Never invent statistics, quotes or sources. If unsure, leave it out. No medical, legal or financial advice. Nothing hateful, violent or adult.

TITLE: max 60 characters, subject in the first 3 words, a concrete number/name if it is true, at most 2 all-caps words, no clickbait lies.
thumbnail_text: max 3 words and it must NOT repeat words from the title (different words, same promise).

Scene setting must be one of: {', '.join(C.SETTINGS)}. Pick what fits the story. cast = indices of characters present. emotion: {', '.join(sorted(EMOTIONS))}. shot (optional): wide, medium, close, two.
Character fields: name, gender (male|female), age (child|adult|elder), color (shirt hex), pants (hex), hair (hex), skin (hex, natural skin tone),
hairstyle ({'|'.join(sorted(HAIR))}), outfit (shirt|dress), glasses, mustache, bindi (booleans), hatcolor (hex), shawl (hex, optional).

Return ONLY JSON:
{{"title":"..","description":"2-3 sentences that contain the main search phrase, then 3-5 hashtags","tags":["8 tags"],"thumbnail_text":"..",
 "hook_candidates":[{{"formula":"..","text":".."}}],"hook":"..",
 "characters":[{{"name":"..","gender":"female","age":"child","color":"#ec4899","pants":"#334155","hair":"#1f1410","skin":"#e0ad7a","hairstyle":"pigtails","outfit":"dress"}}],
 "scenes":[{{"title":"..","setting":"village_day","cast":[0,1],"lines":[{{"who":0,"text":"..","emotion":"surprised","shot":"close"}}]}}]}}"""


def _hex(v, default):
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default


def validate_film(pkg, fmt: str) -> dict:
    if not isinstance(pkg, dict):
        raise ValueError("Package is not a JSON object")
    chars = []
    for i, c in enumerate((pkg.get("characters") or [])[:4]):
        if not isinstance(c, dict):
            continue
        age = c.get("age") if c.get("age") in ("child", "adult", "elder") else "adult"
        gender = c.get("gender") if c.get("gender") in ("male", "female") else "male"
        chars.append({"name": strip_markup(c.get("name", f"Person {i + 1}"))[:20] or f"Person {i + 1}", "gender": gender, "age": age,
                      "color": _hex(c.get("color"), PALETTE[i % len(PALETTE)]), "pants": _hex(c.get("pants"), "#334155"),
                      "hair": _hex(c.get("hair"), "#2b1b17"), "skin": _hex(c.get("skin"), "#e0ad7a"),
                      "hairstyle": c.get("hairstyle") if c.get("hairstyle") in HAIR else "short",
                      "outfit": c.get("outfit") if c.get("outfit") in ("shirt", "dress") else ("dress" if gender == "female" else "shirt"),
                      "glasses": bool(c.get("glasses")), "mustache": bool(c.get("mustache")), "bindi": bool(c.get("bindi")),
                      "hatcolor": _hex(c.get("hatcolor"), "#ef4444"), **({"shawl": c["shawl"]} if _hex(c.get("shawl"), "") else {})})
    if len(chars) < 2:
        raise ValueError("Need at least 2 characters")
    # the lead is a 12-year-old girl
    lead = chars[0]; lead.update(gender="female", age="child")
    if lead["outfit"] != "dress": lead["outfit"] = "dress"
    scenes, nlines = [], 0
    for sc in pkg.get("scenes") or []:
        if not isinstance(sc, dict):
            continue
        lines = []
        for ln in sc.get("lines") or []:
            if not isinstance(ln, dict):
                continue
            text = strip_markup(ln.get("text", ""))
            who = ln.get("who", 0)
            if not text or not isinstance(who, int) or who < -1 or who >= len(chars):
                continue
            lines.append({"who": who, "text": text[:260], "emotion": ln.get("emotion") if ln.get("emotion") in EMOTIONS else "neutral",
                          **({"shot": ln["shot"]} if ln.get("shot") in SHOTS else {})})
        if lines:
            setting = sc.get("setting") if sc.get("setting") in C.PAL else "village_day"
            cast = [c for c in (sc.get("cast") or []) if isinstance(c, int) and 0 <= c < len(chars)]
            scenes.append({"title": strip_markup(sc.get("title", ""))[:50], "setting": setting, "cast": cast, "lines": lines})
            nlines += len(lines)
    need_lines, max_scenes = (7, 3) if fmt == "short" else (16, 8)
    if nlines < need_lines or not scenes:
        raise ValueError(f"Too few lines ({nlines})")
    scenes = scenes[:max_scenes]
    title = strip_markup(pkg.get("title", ""))
    if len(title) < 5:
        raise ValueError("Missing title")
    tags, total = [], 0
    for t in pkg.get("tags") or []:
        t = strip_markup(t).replace(",", "")
        if t and total + len(t) < 450:
            tags.append(t[:40]); total += len(t)
    thumb = strip_markup(pkg.get("thumbnail_text", "")) or title[:24]
    thumb = fix_thumb_text(thumb, title)
    return {"title": title[:95], "description": re.sub(r"[ \t]+", " ", str(pkg.get("description", "")).replace("**", "")).strip()[:4500],
            "tags": tags[:12], "thumbnail_text": thumb, "hook": strip_markup(pkg.get("hook", "")), "characters": chars, "scenes": scenes}


def shorten_title(title: str) -> str:
    """If the title is too long for search/feeds, ask Gemini for a tighter one (never fails the run)."""
    if len(title) <= 60:
        return title
    try:
        out = generate_json(f'Rewrite this YouTube title in at most 55 characters, same language, keep the subject first and the curiosity. Title: "{title}". Return ONLY JSON {{"title": ".."}}', temperature=0.4)
        new = strip_markup(out.get("title", "")) if isinstance(out, dict) else ""
        return new if 5 < len(new) <= 60 else title
    except Exception:  # noqa: BLE001
        return title


def generate_film_package(topic: str, fmt: str) -> dict:
    pkg = validate_film(generate_json(build_prompt(topic, fmt)), fmt)
    pkg["title"] = shorten_title(pkg["title"])
    pkg["thumbnail_text"] = fix_thumb_text(pkg["thumbnail_text"], pkg["title"])
    pkg["lint"] = lint_title(pkg["title"], pkg["thumbnail_text"])
    return pkg
