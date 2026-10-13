"""Packaging helpers: hook formulas for the prompt, title/thumbnail linter, chapters.
Rules adapted (MIT) from github.com/Jakeschincariol/youtube-agent-skill - see NOTICE."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP, MOBILE, HARD = 60, 40, 100
STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "with", "your", "you", "my", "i", "this", "that", "it", "how", "what", "why"}
VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "ultimate", "best", "powerful", "secret", "revolutionary", "mindblowing", "epic", "perfect"}


def hook_formulas() -> dict:
    return json.loads((ROOT / "data" / "hook_formulas.json").read_text(encoding="utf-8"))


def hook_menu() -> str:
    h = hook_formulas()
    lines = [f"- {x['id']}: {x['shape']}" for x in h["hooks"]]
    rules = "\n".join(f"- {r}" for r in h["rules"])
    return "HOOK FORMULAS (pick the best fit):\n" + "\n".join(lines) + "\n\nHOOK RULES:\n" + rules


def _words(t: str) -> list:
    return re.findall(r"\w+", t.lower())


def lint_title(title: str, thumb: str = "") -> dict:
    """Returns {"issues": [(code, message)], "score": 0-100}. Works for any language (length/duplicate/shouting)."""
    t = title.strip(); n = len(t); issues = []
    if n > HARD: issues.append(("length", f"{n} chars, hard limit {HARD}"))
    elif n > DESKTOP: issues.append(("length", f"{n} chars, desktop search cuts near {DESKTOP}"))
    caps = [w for w in t.split() if len(w) > 2 and w.isupper()]
    if len(caps) > 2: issues.append(("shouting", "more than 2 all-caps words"))
    if [w for w in _words(t) if w in VAGUE]: issues.append(("vague", "vague hype word; use a number, name or date"))
    if thumb:
        shared = (set(_words(t)) - STOP) & (set(_words(thumb)) - STOP)
        if shared: issues.append(("duplicate", "thumbnail repeats title words: " + ", ".join(sorted(shared))))
        if len(_words(thumb)) > 3: issues.append(("thumb-length", f"{len(_words(thumb))} words on thumbnail, 3 is the ceiling"))
    return {"issues": issues, "score": max(0, 100 - 18 * len(issues))}


def fix_thumb_text(thumb: str, title: str) -> str:
    """Deterministic repair: drop words that repeat the title, keep at most 3 words."""
    tw = set(_words(title)) - STOP
    kept = [w for w in thumb.split() if not (set(_words(w)) & tw)] or thumb.split()
    return " ".join(kept[:3])


def _mmss(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def make_chapters(scenes: list) -> str:
    """scenes: [{"title": str, "t0": seconds}]. Returns chapter text valid for YouTube, or "" if the rules cannot be met.
    Rules: first chapter at 0:00, at least 3 chapters, each at least 10 seconds."""
    items = [(s["t0"], s["title"].strip()) for s in scenes if s.get("title", "").strip()]
    if len(items) < 3:
        return ""
    items[0] = (0.0, items[0][1])
    out = []
    for i, (t0, title) in enumerate(items):
        nxt = items[i + 1][0] if i + 1 < len(items) else t0 + 999
        if nxt - t0 < 10 and i + 1 < len(items):
            continue
        out.append((t0, title))
    if len(out) < 3 or out[0][0] != 0:
        return ""
    return "\n".join(f"{_mmss(t)} {title}" for t, title in out)
