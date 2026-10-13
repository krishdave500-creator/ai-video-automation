"""Royalty-free background music generated in code (soft chord pads). No downloads, no copyright."""
import wave

import numpy as np

SR = 44100
CHORDS = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63], [261.63, 329.63, 392.0], [196.0, 246.94, 293.66]]
BASS = [110.0, 87.31, 130.81, 98.0]


def make_music(path, seconds: float, seed: int = 3) -> None:
    n = int(seconds * SR) + SR
    out = np.zeros(n, dtype=np.float32)
    seg = 4.0
    for i in range(int(np.ceil(seconds / seg)) + 1):
        s = int(i * seg * SR)
        ln = min(int(seg * 1.3 * SR), n - s)
        if ln <= 0:
            break
        tt = np.arange(ln) / SR
        env = np.minimum(1, tt / 1.4) * np.minimum(1, (seg * 1.3 - tt) / 1.4)
        pad = sum(np.sin(2 * np.pi * f * tt) + .5 * np.sin(4 * np.pi * f * tt + .3) + .35 * np.sin(2 * np.pi * f * 1.004 * tt)
                  for f in CHORDS[i % 4]) / 5.4
        out[s:s + ln] += ((pad * .7 + np.sin(2 * np.pi * BASS[i % 4] * tt) * .45) * env).astype(np.float32)
    rng = np.random.default_rng(seed)
    tm = 2.0
    while tm < seconds - 1:
        f = rng.choice([440, 523.25, 587.33, 659.25, 783.99, 880])
        s = int(tm * SR); ln = min(int(2.4 * SR), n - s)
        tt = np.arange(ln) / SR
        out[s:s + ln] += (.3 * (np.sin(2 * np.pi * f * tt) + .4 * np.sin(4 * np.pi * f * tt)) * np.exp(-tt * 2.2)).astype(np.float32)
        tm += rng.choice([1.4, 2.0, 2.8, 3.6])
    out = out[: int(seconds * SR)]
    out = out / (np.abs(out).max() + 1e-9) * 0.9
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((out * 32767).astype(np.int16).tobytes())
