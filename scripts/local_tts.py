"""Offline neural voices that run ON the GitHub machine (Edge TTS is blocked there with HTTP 403).
English: Kokoro (very natural). Hindi: 3 Piper voices. Gujarati: Mimic3 (only free model; lower quality, so
characters are separated with pitch/speed). Models are free, downloaded once from GitHub releases."""
import os
import shutil
import subprocess
import tarfile
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
import requests

from .config import ROOT
from .util import log, run

BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models"
SR = 22050
MODELS = {
    "kokoro_en": dict(archive="kokoro-int8-en-v0_19", kind="kokoro", onnx="model.int8.onnx"),
    "mimic_gu": dict(archive="vits-mimic3-gu_IN-cmu-indic_low", kind="vits", onnx="gu_IN-cmu-indic_low.onnx"),
    "piper_hi_f": dict(archive="vits-piper-hi_IN-priyamvada-medium-int8", kind="vits", onnx="hi_IN-priyamvada-medium.onnx"),
    "piper_hi_m1": dict(archive="vits-piper-hi_IN-pratham-medium-int8", kind="vits", onnx="hi_IN-pratham-medium.onnx"),
    "piper_hi_m2": dict(archive="vits-piper-hi_IN-rohan-medium-int8", kind="vits", onnx="hi_IN-rohan-medium.onnx"),
}
# Kokoro v0.19 speakers: 0 af, 1 af_bella, 2 af_nicole, 3 af_sarah, 4 af_sky, 5 am_adam, 6 am_michael, 7 bf_emma, 8 bf_isabella, 9 bm_george, 10 bm_lewis
BANK = {
    "en": {"female": [("kokoro_en", 1), ("kokoro_en", 7), ("kokoro_en", 3), ("kokoro_en", 8)],
           "male": [("kokoro_en", 5), ("kokoro_en", 6), ("kokoro_en", 9)], "girl": ("kokoro_en", 4), "boy": ("kokoro_en", 6),
           "elder_f": ("kokoro_en", 8), "elder_m": ("kokoro_en", 9), "narrator": ("kokoro_en", 10), "male_ratio": 1.0,
           "girl_ratio": 1.27, "boy_ratio": 1.5},
    "hi": {"female": [("piper_hi_f", 0)], "male": [("piper_hi_m2", 0), ("piper_hi_m1", 0)], "girl": ("piper_hi_f", 0), "boy": ("piper_hi_m2", 0),
           "elder_f": ("piper_hi_f", 0), "elder_m": ("piper_hi_m1", 0), "narrator": ("piper_hi_m1", 0), "male_ratio": 1.0,
           "girl_ratio": 1.22, "boy_ratio": 1.45},
    "gu": {"female": [("mimic_gu", 1), ("mimic_gu", 2)], "male": [("mimic_gu", 1), ("mimic_gu", 2)], "girl": ("mimic_gu", 0), "boy": ("mimic_gu", 0),
           "elder_f": ("mimic_gu", 2), "elder_m": ("mimic_gu", 2), "narrator": ("mimic_gu", 1), "male_ratio": 0.68,
           "girl_ratio": 1.0, "boy_ratio": 0.88},
}
# (pitch ratio, speed) per type
ADJ = {"girl": (1.16, 1.03), "boy": (1.28, 1.05), "elder_f": (0.97, 0.92), "elder_m": (0.95, 0.92), "adult": (1.0, 1.0), "narrator": (0.95, 0.95)}


def models_dir() -> Path:
    return Path(os.getenv("MODELS_DIR", ROOT / "models"))


def ensure_model(key: str) -> Path:
    m = MODELS[key]; d = models_dir() / m["archive"]
    if (d / m["onnx"]).exists():
        return d
    d.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE}/{m['archive']}.tar.bz2"
    log(f"[LocalTTS] downloading voice model {m['archive']} (one time)...")
    tmp = d.parent / (m["archive"] + ".tar.bz2")
    for attempt in range(3):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            break
        except requests.RequestException:
            if attempt == 2:
                raise
    with tarfile.open(tmp, "r:bz2") as t:
        t.extractall(d.parent)
    tmp.unlink(missing_ok=True)
    if not (d / m["onnx"]).exists():
        raise RuntimeError(f"Voice model {m['archive']} is incomplete")
    return d


@lru_cache(maxsize=None)
def _engine(key: str):
    import sherpa_onnx
    m = MODELS[key]; d = ensure_model(key)
    if m["kind"] == "kokoro":
        mc = sherpa_onnx.OfflineTtsModelConfig(kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(d / m["onnx"]), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"), data_dir=str(d / "espeak-ng-data")),
            num_threads=max(2, os.cpu_count() or 2), provider="cpu")
    else:
        mc = sherpa_onnx.OfflineTtsModelConfig(vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(d / m["onnx"]), tokens=str(d / "tokens.txt"), data_dir=str(d / "espeak-ng-data")),
            num_threads=max(2, os.cpu_count() or 2), provider="cpu")
    return sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=mc))


@lru_cache(maxsize=None)
def _has_rubberband() -> bool:
    return "rubberband" in subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout


def _pitch(wav: Path, ratio: float) -> None:
    if abs(ratio - 1) < 0.01:
        return
    ratio = min(1.8, max(0.5, ratio)); tmp = wav.with_name(wav.stem + "_p.wav")
    af = f"rubberband=pitch={ratio}" if _has_rubberband() else f"asetrate={SR * ratio:.0f},aresample={SR},atempo={min(2.0, max(0.5, 1 / ratio)):.4f}"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", af, "-ac", "1", "-ar", str(SR), "-sample_fmt", "s16", str(tmp)])
    shutil.move(str(tmp), str(wav))


def speak(text: str, spec: dict, wav: Path) -> None:
    """Synthesize `text` with a voice spec {model, sid, ratio, speed} into a 22.05 kHz mono wav."""
    tts = _engine(spec["model"])
    a = tts.generate(text, sid=spec["sid"], speed=spec["speed"])
    x = np.array(a.samples, dtype=np.float32)
    if len(x) < 100:
        raise RuntimeError("Local TTS produced no audio")
    if a.sample_rate != SR:
        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * SR / a.sample_rate)), np.arange(len(x)), x).astype(np.float32)
    x = x / max(1.0, float(np.abs(x).max()))
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    _pitch(Path(wav), spec["ratio"])


def local_voices(chars: list, lang: str) -> list:
    """One distinct voice spec per character."""
    bank = BANK.get(lang, BANK["en"]); used = {"female": 0, "male": 0}; out = []
    for ch in chars:
        g = ch.get("gender", "male"); age = ch.get("age", "adult")
        if age == "child":
            kind = "girl" if g == "female" else "boy"
        elif age == "elder":
            kind = "elder_f" if g == "female" else "elder_m"
        else:
            kind = "adult"
        if kind == "adult":
            lst = bank[g]; n = used[g]; used[g] += 1
            model, sid = lst[n % len(lst)]
            ratio, speed = ADJ["adult"]
            ratio *= (bank["male_ratio"] if g == "male" else 1.0) * (1.0 + 0.07 * (n // len(lst)) * (1 if n % 2 else -1))
        else:
            model, sid = bank[kind]; ratio, speed = ADJ[kind]
            if kind == "girl": ratio = bank["girl_ratio"]
            elif kind == "boy": ratio = bank["boy_ratio"]
            elif kind == "elder_m": ratio *= bank["male_ratio"]
        out.append({"model": model, "sid": sid, "ratio": round(ratio, 3), "speed": speed})
    return out


def narrator_voice(lang: str) -> dict:
    bank = BANK.get(lang, BANK["en"]); model, sid = bank["narrator"]; ratio, speed = ADJ["narrator"]
    return {"model": model, "sid": sid, "ratio": round(ratio * bank["male_ratio"], 3), "speed": speed}
