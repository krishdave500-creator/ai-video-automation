"""Animated film maker: voices (one per character, human neural voices), word-timed captions,
camera plan, ambience + ducked music, multi-core rendering with ffmpeg."""
import math
import os
import subprocess
import wave
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image

from . import cinema as C
from .config import CFG
from . import local_tts
from . import generate_voice as gv
from .generate_voice import _synth, estimate_words
from .subtitles import build_ass
from .util import duration, log, run

SR = 22050
PAUSE = 0.42


def fps() -> int:
    return int(os.getenv("CINEMA_FPS", "24"))


# ------------------------------------------------------------------ voices
VOICE_POOL = {
    "en": {"female": ["en-IN-NeerjaNeural", "en-US-JennyNeural", "en-GB-SoniaNeural", "en-US-AriaNeural"],
           "male": ["en-IN-PrabhatNeural", "en-US-GuyNeural", "en-GB-RyanNeural", "en-US-DavisNeural"]},
    "gu": {"female": ["gu-IN-DhwaniNeural"], "male": ["gu-IN-NiranjanNeural"]},
    "hi": {"female": ["hi-IN-SwaraNeural"], "male": ["hi-IN-MadhurNeural"]},
}
CHILD_GIRL = {"en": "en-US-AnaNeural"}            # a real child-sounding neural voice (English only)
AGE_ADJ = {"child": (30, 6), "adult": (0, 0), "elder": (-12, -10)}   # (pitch Hz, rate %)
SEPARATION = [0, 14, -14, 26]


def assign_voices(chars: list) -> list:
    """One distinct, human-sounding voice per character. Returns [{voice, pitch, rate}]."""
    lang = CFG.get("language", "en")
    pool = {**VOICE_POOL.get(lang, {"female": [CFG["voice"]], "male": [CFG["voice"]]}), **(CFG.get("voices") or {})}
    used = {"female": 0, "male": 0}
    out = []
    for ch in chars:
        g = ch.get("gender", "male"); age = ch.get("age", "adult"); v = ch.get("voice", {}) or {}
        pitch, rate = AGE_ADJ.get(age, (0, 0))
        if age == "child" and g == "female" and lang in CHILD_GIRL:
            voice, pitch, rate = CHILD_GIRL[lang], 0, 2          # native child voice: no extra shifting
        else:
            n = used[g]; used[g] += 1
            voice = pool[g][n % len(pool[g])]
            pitch += SEPARATION[(n // len(pool[g])) % len(SEPARATION)]
        out.append({"voice": v.get("edge") or voice, "pitch": int(v.get("pitch_hz", pitch)), "rate": int(v.get("rate_pct", rate))})
    return out


NARRATOR = dict(name="Narrator", gender="male", age="adult", color="#cbd5e1")


def narrator_voice() -> dict:
    """Deep, calm male voice - the last male voice of the pool so it rarely clashes with a character."""
    lang = CFG.get("language", "en")
    pool = {**VOICE_POOL.get(lang, {"male": [CFG["voice"]]}), **(CFG.get("voices") or {})}["male"]
    return {"voice": pool[-1], "pitch": -12, "rate": -8}


_ENGINE = {}


def pick_engine() -> str:
    """'edge' (Microsoft neural voices, best) when reachable; otherwise 'local' (runs on this machine).
    GitHub's machines are blocked by Edge TTS (HTTP 403), so there it always becomes 'local'."""
    mode = CFG.get("tts_engine", "auto")
    if mode in ("edge", "local"):
        return mode
    import asyncio, tempfile
    try:
        asyncio.run(gv._stream_scene("Hello.", os.path.join(tempfile.mkdtemp(), "probe.mp3")))
        return "edge"
    except Exception as e:  # noqa: BLE001
        log(f"[Voice] Edge TTS not reachable ({type(e).__name__}); using the built-in local neural voices")
        return "local"


def synth_line(text: str, vp: dict, wav: Path) -> list:
    """Speak one line. Falls back to the default channel voice if a voice name is unavailable."""
    if _ENGINE.get("name") == "local":
        local_tts.speak(text, vp, wav)
        return []
    mp3 = wav.with_suffix(".mp3")
    try:
        words = _synth(text, mp3, voice=vp["voice"], rate=f"{vp['rate']:+d}%", pitch=f"{vp['pitch']:+d}Hz")
    except Exception as e:  # noqa: BLE001
        log(f"[Voice] {vp['voice']} failed ({type(e).__name__}); using channel default voice")
        words = _synth(text, mp3, voice=CFG["voice"], rate=f"{vp['rate']:+d}%", pitch=f"{vp['pitch']:+d}Hz")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR), "-sample_fmt", "s16", str(wav)])
    return words


# ------------------------------------------------------------------ audio helpers
def read_wav(p) -> np.ndarray:
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(p, x) -> None:
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def lp(x, k):
    return np.convolve(x, np.ones(k) / k, mode="same")


def ambience(name, dur, rng, thunder=()):
    n = int(dur * SR); tt = np.arange(n) / SR; noise = rng.standard_normal(n).astype(np.float32)
    wind = lp(noise, 300) * 3.5 * (1 + .4 * np.sin(2 * np.pi * .13 * tt)); out = wind * .5
    if name == "rain":
        out = (noise - lp(noise, 6)) * .06 + lp(noise, 60) * .5 + wind * .6
        for th in thunder:
            s = int(th * SR)
            if 0 <= s < n:
                m = min(int(3 * SR), n - s); out[s:s + m] += lp(noise, 800)[:m] * 14 * np.exp(-np.arange(m) / SR * 1.4)
    if name in ("night", "sunset", "forest"):
        gate = ((tt % 1.1) < .55) & (((tt * 22) % 1) < .55)
        out = out + np.sin(2 * np.pi * 4300 * tt) * gate * (.012 if name == "night" else .005)
    if name in ("village_day", "sunset", "forest"):
        for _ in range(int(dur / 2.2)):
            s = int(rng.uniform(0, max(0.1, dur - .4)) * SR); m = int(.18 * SR)
            if s + m < n:
                u = np.arange(m) / SR; f0 = rng.uniform(2200, 3400)
                out[s:s + m] += np.sin(2 * np.pi * (f0 * u + 4000 * u * u)) * np.sin(np.pi * u / .18) * .02
    return out / (np.abs(out).max() + 1e-9) * (.10 if name == "rain" else .07)


def cinematic_music(total, seed=3):
    n = int(total * SR); out = np.zeros(n, dtype=np.float32)
    chords = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63], [261.63, 329.63, 392.0], [196.0, 246.94, 293.66]]
    bass = [110.0, 87.31, 130.81, 98.0]; seg = 4.0
    for i in range(int(np.ceil(total / seg))):
        s = int(i * seg * SR); ln = min(int(seg * 1.3 * SR), n - s)
        if ln <= 0: break
        tt = np.arange(ln) / SR; env = np.minimum(1, tt / 1.4) * np.minimum(1, (seg * 1.3 - tt) / 1.4)
        pad = sum(np.sin(2 * np.pi * f * tt) + .5 * np.sin(4 * np.pi * f * tt + .3) + .35 * np.sin(2 * np.pi * f * 1.004 * tt) for f in chords[i % 4]) / 5.4
        out[s:s + ln] += ((pad * .7 + np.sin(2 * np.pi * bass[i % 4] * tt) * .45) * env).astype(np.float32)
    rng = np.random.default_rng(seed); tm = 2.0
    while tm < total - 1:
        f = rng.choice([440, 523.25, 587.33, 659.25, 783.99, 880]); s = int(tm * SR); ln = min(int(2.4 * SR), n - s); tt = np.arange(ln) / SR
        out[s:s + ln] += (.3 * (np.sin(2 * np.pi * f * tt) + .4 * np.sin(4 * np.pi * f * tt) + .15 * np.sin(6 * np.pi * f * tt)) * np.exp(-tt * 2.2)).astype(np.float32)
        tm += rng.choice([1.2, 1.6, 2.4, 3.2])
    return out / (np.abs(out).max() + 1e-9) * .24


# ------------------------------------------------------------------ camera
def head_y(ch) -> float:
    a = C.AGE[ch.get("age", "adult")]
    return C.FEET - C.K * ch.get("scale", 1.0) * (a["leg"] + a["body"] + a["hr"] * .8)


def shot_target(shot, sc, line, chars, prev_x):
    LY = C.LY; S = LY.S
    cast_cx = sum(sc["cast_x"].values()) / len(sc["cast_x"])
    if line["who"] < 0 or shot == "wide":
        z = LY.zoom["wide"]; return cast_cx, C.FEET - (LY.ff_wide - .5) * LY.AH / (z * S), z
    sx = sc["cast_x"][line["who"]]
    if shot == "close":
        z = LY.zoom["close"]; return sx, head_y(chars[line["who"]]) + (.5 - LY.fh) * LY.AH / (z * S), z
    if shot == "two" and prev_x is not None:
        z = LY.zoom["two"]; return (sx + prev_x) / 2, C.FEET - (LY.ff_med - .5) * LY.AH / (z * S), z
    z = LY.zoom["medium"]; return sx, C.FEET - (LY.ff_med - .5) * LY.AH / (z * S), z


def clampcam(c):
    LY = C.LY; cx, cy, z = c
    half = LY.AW / (2 * z * LY.S); cx = min(max(cx, half), C.WW - half)
    if LY.name == "landscape":
        hy = LY.AH / (2 * z * LY.S); cy = min(max(cy, hy), 536 - hy)
    return (cx, cy, z)


# ------------------------------------------------------------------ plan
def build_plan(pkg: dict, run_dir: Path, portrait: bool, limit: float | None = None):
    layout = "portrait" if portrait else "landscape"
    C.set_layout(layout); LY = C.LY; F = fps()
    chars = pkg["characters"]; narr = dict(NARRATOR, name=pkg.get("narrator_name", NARRATOR["name"]))
    _ENGINE["name"] = pick_engine()
    lang = CFG.get("language", "en")
    log(f"[Voice] engine: {_ENGINE['name']}")
    vps = local_tts.local_voices(chars, lang) if _ENGINE["name"] == "local" else assign_voices(chars)
    intro = 1.3 if portrait else 3.4; gap = 0.3 if portrait else 0.45; fade_edge = .25 if portrait else .5
    work = Path(run_dir) / "film"; work.mkdir(parents=True, exist_ok=True)
    t = 0.0; scenes = []; tl = []; words = []; n = 0
    for si, sc in enumerate(pkg["scenes"]):
        cast = list(sc.get("cast", []))
        for ln in sc["lines"]:
            if ln["who"] >= 0 and ln["who"] not in cast: cast.append(ln["who"])
        if not cast: cast = [0]
        sp = LY.spacing.get(len(cast), 160 if portrait else 230)
        cast_x = {c: 1150 + (i - (len(cast) - 1) / 2) * sp for i, c in enumerate(cast)}
        t0 = t; t = t0 + (intro if si == 0 else 0.4); prev_x = None
        for k, ln in enumerate(sc["lines"]):
            n += 1; wav = work / f"l{n:02d}.wav"
            vp = (local_tts.narrator_voice(lang) if _ENGINE["name"] == "local" else narrator_voice()) if ln["who"] < 0 else vps[ln["who"]]
            w = synth_line(ln["text"], vp, wav)
            x = read_wav(wav); dur = len(x) / SR
            if len(w) < max(1, len(ln["text"].split()) // 2): w = estimate_words(ln["text"], dur)
            for s, e, tx in w: words.append({"start": t + s, "end": t + min(e, dur), "text": tx})
            nf = int(dur * F) + 1
            env = np.array([float(np.sqrt(np.mean(x[int(i / F * SR):int((i + 1) / F * SR)] ** 2))) if len(x[int(i / F * SR):int((i + 1) / F * SR)]) else 0.0 for i in range(nf)])
            env = np.convolve(np.minimum(1, env / (np.percentile(env, 92) + 1e-6)), [.25, .5, .25], mode="same")
            emo = ln.get("emotion", "neutral")
            shot = ln.get("shot") or ("wide" if ln["who"] < 0 or (k == 0 and not portrait) else ("close" if emo in ("surprised", "sad") else "medium"))
            tl.append(dict(start=t, dur=dur, end=t + dur + PAUSE, who=ln["who"], text=ln["text"], emo=emo, shot=shot, scene=si, env=env, prev_x=prev_x, x=x))
            if ln["who"] >= 0: prev_x = cast_x[ln["who"]]
            t += dur + PAUSE
        t1 = t + 0.25
        scenes.append(dict(setting=sc.get("setting", "village_day"), cast=cast, cast_x=cast_x, t0=t0, t1=t1, title=sc.get("title", "")))
        t = t1 + gap
    total = scenes[-1]["t1"] + 1.4
    if limit: total = min(total, limit)
    frames = int(total * F)
    for l in tl:
        sc = scenes[l["scene"]]
        l["target"] = shot_target(l["shot"], sc, l, chars, l["prev_x"])
    fscene = np.full(frames, -1, int); fline = np.full(frames, -1, int); cam = np.zeros((frames, 3)); fade = np.ones(frames, np.float32); flash = np.zeros(frames, np.float32)
    state = None; last = -1
    for f in range(frames):
        tt = f / F
        si = next((i for i, s in enumerate(scenes) if s["t0"] <= tt < s["t1"]), -1); fscene[f] = si
        if si < 0:
            cam[f] = state if state is not None else (1150, 266, 1.0); fade[f] = 0; continue
        s = scenes[si]
        fi = [i for i, l in enumerate(tl) if l["scene"] == si and l["start"] <= tt]
        cur = fi[-1] if fi else -1; fline[f] = cur
        if cur < 0:
            c0 = sum(s["cast_x"].values()) / len(s["cast_x"]); z0 = LY.zoom["wide"]
            u = min(1, tt / intro); u = u * u * (3 - 2 * u)
            cy0 = C.FEET - (LY.ff_wide - .5) * LY.AH / (z0 * LY.S)
            tgt = (c0 - (0 if portrait else 380) * (1 - u), cy0, z0 * (1 + .05 * u)) if si == 0 else (c0, cy0, z0)
        else:
            l = tl[cur]; pr = min(1, (tt - l["start"]) / max(.5, l["dur"] + PAUSE)); cx_, cy_, z_ = l["target"]
            tgt = (cx_ + (pr - .5) * 30, cy_, z_ * (1 + (.04 if l["shot"] != "wide" else .03) * pr))
        tgt = clampcam(tgt)
        if state is None or si != last or (si == 0 and cur < 0): state = np.array(tgt, float)
        else: state += (np.array(tgt) - state) * (1 - math.exp(-1 / F / .38))
        cam[f] = state; last = si
        fa = min(1, (tt - s["t0"]) / (1.0 if si == 0 else fade_edge), (s["t1"] - tt) / (1.2 if si == len(scenes) - 1 else fade_edge)); fade[f] = max(0, fa)
        if C.PAL[s["setting"]].get("rain"):
            for th in (5.0, 11.5, 19.0):
                q = tt - (s["t0"] + th)
                if 0 <= q < .5: flash[f] = max(flash[f], max(0, 1 - q / .22) if q < .22 else (max(0, 1 - (q - .3) / .2) * .7 if q >= .3 else 0))
    plan = dict(layout=layout, fps=F, chars=chars, scenes=scenes, words=words, total=total, frames=frames, intro=intro,
                tl=[{k: v for k, v in l.items() if k != "x"} for l in tl], fscene=fscene, fline=fline, cam=cam, fade=fade, flash=flash)
    return plan, tl, work


def mix_audio(plan, tl, work: Path) -> Path:
    total = plan["total"]; totaln = int(total * SR)
    voice = np.zeros(totaln + SR)
    for l in tl:
        a = int(l["start"] * SR)
        if a < totaln: voice[a:a + len(l["x"])] += l["x"][:totaln + SR - a]
    voice = voice[:totaln] / (np.abs(voice).max() + 1e-9) * .92
    rng = np.random.default_rng(5); amb = np.zeros(totaln)
    for s in plan["scenes"]:
        a = max(0, int((s["t0"] - .4) * SR)); b = min(totaln, int((s["t1"] + .5) * SR))
        if b <= a: continue
        th = [s["t0"] + x - (s["t0"] - .4) + .3 for x in (5.0, 11.5, 19.0)]
        seg = ambience(s["setting"], (b - a) / SR, rng, th)[:b - a]; m = len(seg)
        env = np.minimum(1, np.arange(m) / (.5 * SR)) * np.minimum(1, (m - np.arange(m)) / (.5 * SR)); amb[a:a + m] += seg * env
    hop = 220; m = len(voice) // hop
    ve = np.sqrt((voice[:m * hop].reshape(m, hop) ** 2).mean(1)); ve = np.clip(lp(np.clip(ve / .02, 0, 1), 25), 0, 1)
    duck = np.repeat(1 - .62 * ve, hop); duck = np.pad(duck, (0, totaln - len(duck)), constant_values=1)
    mus = cinematic_music(total) * duck * np.minimum(1, np.arange(totaln) / (2 * SR)) * np.minimum(1, (totaln - np.arange(totaln)) / (2.5 * SR))
    out = work / "master.wav"
    write_wav(out, np.clip(voice + mus + amb, -1, 1))
    return out


# ------------------------------------------------------------------ render
def make_film(pkg: dict, run_dir: Path, portrait: bool, limit: float | None = None) -> dict:
    plan, tl, work = build_plan(pkg, run_dir, portrait, limit)
    log(f"[Film] {len(plan['scenes'])} scenes, {len(tl)} lines, {plan['total']:.1f}s, {plan['frames']} frames @ {plan['fps']}fps")
    master = mix_audio(plan, tl, work)
    build_ass(plan["words"], work / "sub.ass", portrait, mode="bar", title=pkg.get("title", ""), title_end=plan["intro"] - 0.1)
    LY = C.LY
    out_w, out_h = (1080, 1920) if portrait else (1920, 1080)
    final = work / "final.mp4"
    procs = int(os.getenv("RENDER_PROCS", os.cpu_count() or 2))
    with Pool(procs, initializer=C.init_worker, initargs=(plan,)) as pool:
        pr = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{LY.FW}x{LY.FH}", "-r", str(plan["fps"]), "-i", "-",
                               "-i", str(master.resolve()), "-vf", f"scale={out_w}:{out_h}:flags=lanczos,ass=sub.ass", "-t", f"{plan['total']:.3f}",
                               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p", "-r", str(plan["fps"]),
                               "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", "final.mp4"], stdin=subprocess.PIPE, cwd=str(work))
        try:
            for i, fb in enumerate(pool.imap(C.render_frame, range(plan["frames"]), chunksize=4)):
                pr.stdin.write(fb)
                if i % 240 == 0: log(f"[Film] frame {i}/{plan['frames']}")
        finally:
            pr.stdin.close(); pr.wait()
    if pr.returncode:
        raise RuntimeError("ffmpeg failed while encoding the film")
    log(f"[Film] done: {final} ({duration(final):.1f}s)")
    return {"final": final, "duration": duration(final), "plan": plan}


def thumbnail_frame(plan: dict, out: Path) -> Path:
    """A clean 16:9 frame (no letterbox bars, no captions) of the most expressive moment."""
    C.set_layout("thumb")
    tl = plan["tl"]
    pick = next((i for i, l in enumerate(tl) if l["who"] >= 0 and l["emo"] in ("surprised", "happy", "sad")), next((i for i, l in enumerate(tl) if l["who"] >= 0), 0))
    l = tl[pick]; sc = plan["scenes"][l["scene"]]
    chars = plan["chars"]; shot = "close" if l["shot"] != "wide" else "medium"
    cam = clampcam(shot_target(shot, sc, l, chars, l["prev_x"]))
    t = l["start"] + min(l["dur"] * .45, 1.2)
    frame = C.compose(plan, t, int(t * plan["fps"]), l["scene"], cam, pick, 0.0, 1.0)
    out = Path(out); Image.fromarray(frame).save(out, quality=95)
    C.set_layout(plan["layout"])
    return out
