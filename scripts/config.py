"""Settings: config.json + optional environment overrides. No secrets live here."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "niche": "surprising science and everyday facts",
    "language": "en",
    "language_name": "English",
    "voice": "en-IN-NeerjaNeural",
    "voice_rate": "+0%",
    "subtitle_font": "DejaVu Sans",
    "subtitle_uppercase": True,
    "gemini_model": "gemini-3.5-flash-lite",
    "gemini_fallbacks": ["gemini-2.5-flash", "gemini-3.8-flash"],
    "tts_engine": "auto",
    "category_id": "27",
    "privacy": "private",
    "short": {"min_scenes": 6, "max_scenes": 8, "seconds": "30-45"},
    "video": {"min_scenes": 10, "max_scenes": 14, "seconds": "90-150"},
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    path = ROOT / "config.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    for key, env in (("language", "LANGUAGE"), ("voice", "TTS_VOICE"), ("niche", "CHANNEL_NICHE"),
                     ("gemini_model", "GEMINI_MODEL"), ("subtitle_font", "SUBTITLE_FONT")):
        if os.getenv(env):
            cfg[key] = os.getenv(env)
    return cfg


CFG = load()
