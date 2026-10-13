"""Voice-over with Edge TTS (free). One audio file per scene, so pictures and captions
line up exactly. Word timings come from Edge TTS itself (no Whisper needed)."""
import asyncio
from pathlib import Path

import edge_tts

from .config import CFG
from .util import duration, log, retry, run


async def _stream_scene(text: str, mp3_path: str, voice=None, rate=None, pitch=None) -> list:
    """Synthesize `text` to mp3. Returns [(start_s, end_s, word), ...] (may be empty)."""
    kwargs = {"rate": rate or CFG.get("voice_rate", "+0%")}
    if pitch:
        kwargs["pitch"] = pitch
    voice = voice or CFG["voice"]
    try:
        comm = edge_tts.Communicate(text, voice, boundary="WordBoundary", **kwargs)
    except TypeError:  # very old edge-tts without the boundary option
        comm = edge_tts.Communicate(text, voice, **kwargs)
    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                words.append((s, s + chunk["duration"] / 1e7, chunk["text"]))
    return words


def estimate_words(text: str, total: float) -> list:
    """Fallback caption timing when the TTS gave no word events: split by character count."""
    toks = text.split()
    if not toks:
        return []
    weights = [len(t) + 1 for t in toks]
    unit = total / sum(weights)
    out, t = [], 0.0
    for tok, w in zip(toks, weights):
        out.append((t, t + w * unit, tok)); t += w * unit
    return out


@retry(times=3, delay=3.0)
def _synth(text: str, mp3: Path, **voice_kw) -> list:
    words = asyncio.run(_stream_scene(text, str(mp3), **voice_kw))
    if not mp3.exists() or mp3.stat().st_size < 1000:
        raise RuntimeError("TTS produced no audio")
    return words


def make_voice(scenes: list, run_dir: Path) -> dict:
    """Returns {"audio": wav_path, "durations": [...], "words": [{start,end,text}], "total": seconds}."""
    audio_dir = Path(run_dir) / "audio"; audio_dir.mkdir(parents=True, exist_ok=True)
    wavs, durations, words_out, t0 = [], [], [], 0.0
    for i, sc in enumerate(scenes):
        mp3 = audio_dir / f"s{i:02d}.mp3"; wav = audio_dir / f"s{i:02d}.wav"
        words = _synth(sc["narration"], mp3)
        # 44.1 kHz mono wav + 0.3 s of silence after each scene (natural breathing room)
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af", "apad=pad_dur=0.3", "-ac", "1", "-ar", "44100", str(wav)])
        d = duration(wav)
        speech_end = max(0.1, d - 0.3)
        if len(words) < max(1, len(sc["narration"].split()) // 2):
            words = estimate_words(sc["narration"], speech_end)
        for s, e, w in words:
            words_out.append({"start": t0 + s, "end": t0 + min(e, speech_end), "text": w})
        wavs.append(wav); durations.append(d); t0 += d
        log(f"[Voice] scene {i + 1}/{len(scenes)}: {d:.1f}s, {len(words)} words")
    lst = audio_dir / "list.txt"
    lst.write_text("".join(f"file '{w.resolve()}'\n" for w in wavs), encoding="utf-8")
    full = audio_dir / "voice.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(full)])
    return {"audio": full, "durations": durations, "words": words_out, "total": t0}
