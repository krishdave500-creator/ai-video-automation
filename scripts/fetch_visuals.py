"""Visuals from Pexels (free API): real video clips first, photos as fallback.
Never crashes the run because one scene has no match."""
import os
import random
from pathlib import Path

import requests

from .util import log, retry

VIDEO_API = "https://api.pexels.com/videos/search"
PHOTO_API = "https://api.pexels.com/v1/search"


def _key() -> str:
    k = os.getenv("PEXELS_API_KEY")
    if not k:
        raise RuntimeError("PEXELS_API_KEY is not set")
    return k


@retry(times=3, delay=2.0, exceptions=(requests.RequestException,))
def _get(url: str, params: dict) -> dict:
    r = requests.get(url, headers={"Authorization": _key()}, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


@retry(times=3, delay=2.0, exceptions=(requests.RequestException,))
def _download(url: str, dest: str) -> None:
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def pick_video_file(video: dict, portrait: bool):
    files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
    if not files:
        return None
    want = 1080 if portrait else 1920          # ideal width in pixels
    floor = 720 if portrait else 1280          # below this the picture looks soft

    def score(f):
        return (0 if f["width"] >= floor else 1, abs(f["width"] - want))
    return sorted(files, key=score)[0]


def _try_video(query: str, dest: Path, portrait: bool, used: set):
    data = _get(VIDEO_API, {"query": query, "per_page": 15, "orientation": "portrait" if portrait else "landscape", "size": "medium"})
    cands = [v for v in data.get("videos", []) if v.get("id") not in used and v.get("duration", 0) >= 3]
    top = cands[:6]
    random.shuffle(top)
    for v in top:
        f = pick_video_file(v, portrait)
        if f:
            _download(f["link"], str(dest))
            used.add(v["id"])
            return {"kind": "video", "path": dest}
    return None


def _try_photo(query: str, dest: Path, portrait: bool, used: set):
    data = _get(PHOTO_API, {"query": query, "per_page": 10, "orientation": "portrait" if portrait else "landscape"})
    for p in data.get("photos", []):
        if ("p%s" % p.get("id")) in used:
            continue
        url = p["src"].get("large2x") or p["src"].get("large") or p["src"].get("original")
        _download(url, str(dest))
        used.add("p%s" % p.get("id"))
        return {"kind": "photo", "path": dest}
    return None


def fetch_scene_visual(query: str, run_dir: Path, idx: int, portrait: bool, used: set):
    vid_dest = Path(run_dir) / "visuals" / f"v{idx:02d}.mp4"
    img_dest = Path(run_dir) / "visuals" / f"v{idx:02d}.jpg"
    words = query.split()
    attempts = [query, " ".join(words[:2]) if len(words) > 2 else None, "abstract background"]
    for q in [a for a in attempts if a]:
        for fn, dest in ((_try_video, vid_dest), (_try_photo, img_dest)):
            try:
                got = fn(q, dest, portrait, used)
                if got:
                    return got
            except Exception as e:  # keep going: a missing visual must not kill the run
                log(f"[Visuals] '{q}' ({fn.__name__}) failed: {type(e).__name__}")
    return None


def fetch_all(scenes: list, run_dir: Path, portrait: bool) -> list:
    (Path(run_dir) / "visuals").mkdir(parents=True, exist_ok=True)
    used, out = set(), []
    for i, sc in enumerate(scenes):
        got = fetch_scene_visual(sc["visual"], run_dir, i, portrait, used)
        if got is None and out:
            got = out[-1]   # reuse the previous picture rather than fail
            log(f"[Visuals] scene {i + 1}: no match, reusing previous visual")
        elif got is None:
            log(f"[Visuals] scene {i + 1}: no match, using colour background")
        else:
            log(f"[Visuals] scene {i + 1}: {got['kind']} <- '{sc['visual']}'")
        out.append(got)
    return out
