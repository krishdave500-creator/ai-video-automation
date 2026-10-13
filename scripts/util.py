"""Small shared helpers: logging, subprocess, ffprobe, retry, text cleanup."""
import functools
import json
import re
import subprocess
import time


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed (exit {p.returncode}):\n{p.stderr[-1500:]}")
    return p


def probe(path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]).stdout
    return json.loads(out)


def duration(path) -> float:
    return float(probe(path)["format"]["duration"])


def retry(times: int = 3, delay: float = 2.0, exceptions=(Exception,)):
    """Retry a function with growing waits. Raises the last error."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            last = None
            for i in range(times):
                try:
                    return fn(*a, **kw)
                except exceptions as e:  # noqa: PERF203
                    last = e
                    if i < times - 1:
                        time.sleep(delay * (2 ** i))
            raise last
        return wrapper
    return deco


_EMOJI = re.compile("[\U00010000-\U0010ffff\u2600-\u27bf]")
_LABEL = re.compile(r"^\s*(narrator|voice ?over|scene\s*\d+|hook|cta|intro|outro)\s*[:\-–]\s*", re.I)


def strip_markup(text: str) -> str:
    """Remove markdown, labels, emojis and stage directions so TTS never reads them aloud."""
    t = re.sub(r"```.*?```", " ", str(text), flags=re.S)
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = _EMOJI.sub("", t)
    t = re.sub(r"[*_#`>~|]+", "", t)
    t = _LABEL.sub("", t)
    return re.sub(r"\s+", " ", t).strip()
