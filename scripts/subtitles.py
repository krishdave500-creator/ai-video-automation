"""Captions from Edge TTS word timings -> ASS file (word-by-word highlight).
No Whisper, no GPU, no big downloads."""
import re
from pathlib import Path

from .config import CFG

SAFE = re.compile(r"[{}\\]")


def _t(sec: float) -> str:
    sec = max(0.0, sec)
    return f"{int(sec // 3600)}:{int(sec % 3600 // 60):02d}:{sec % 60:05.2f}"


def group_words(words: list, size: int) -> list:
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= size or re.search(r"[.!?,;:।]$", w["text"]):
            groups.append(cur); cur = []
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list, path: Path, portrait: bool, mode: str = "stock", title: str = "", title_end: float = 0.0) -> Path:
    """mode "stock": captions in the picture. mode "bar": captions inside the black cinema bar (landscape)."""
    W, H = (1080, 1920) if portrait else (1920, 1080)
    size = 78 if portrait else 56
    margin_v = 520 if portrait else 110
    if mode == "bar":
        size, margin_v = (74, 400) if portrait else (50, 44)
    font = CFG.get("subtitle_font", "DejaVu Sans")
    upper = CFG.get("subtitle_uppercase", True) and CFG.get("language", "en") == "en"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Title,{font},{92 if portrait else 84},&H00FFFFFF,&H00FFFFFF,&H00301040,&H80000000,1,0,0,0,100,100,2,0,1,6,4,8,80,80,{300 if portrait else 165},1
Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,{7 if portrait else 5},2,2,{90 if portrait else 200},{90 if portrait else 200},{margin_v},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = []
    if title and title_end > 0.5:
        lines.append(f"Dialogue: 1,{_t(0.3)},{_t(title_end)},Title,,0,0,0,,{{\\fad(500,500)}}{SAFE.sub('', title)}")
    groups = group_words(words, 3 if portrait else 6)
    for gi, grp in enumerate(groups):
        next_start = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else None
        texts = []
        for w in grp:
            tx = SAFE.sub("", w["text"])
            texts.append(tx.upper() if upper else tx)
        for i, w in enumerate(grp):
            start = w["start"]
            end = grp[i + 1]["start"] if i + 1 < len(grp) else max(w["end"], start + 0.2) + 0.15
            if next_start is not None and i + 1 == len(grp):
                end = min(end, next_start)      # never overlap the next caption group
            if end <= start:
                end = start + 0.05
            parts = [("{\\c&H00D7FF&}%s{\\c&HFFFFFF&}" % t) if j == i else t for j, t in enumerate(texts)]
            lines.append(f"Dialogue: 0,{_t(start)},{_t(end)},Cap,,0,0,0,,{' '.join(parts)}")
    Path(path).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return Path(path)
