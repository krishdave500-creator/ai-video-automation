"""Video assembly with plain ffmpeg (fast, no MoviePy):
per-scene clips -> colour grade -> concat -> captions + voice + ducked music."""
from pathlib import Path

from .music import make_music
from .subtitles import build_ass
from .util import duration, log, run

FPS = 30
GRADE = "eq=contrast=1.05:saturation=1.12,vignette=angle=PI/6"


def _segment(vis, dur: float, W: int, H: int, out: Path) -> None:
    enc = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS), "-t", f"{dur:.3f}", str(out)]
    base = ["ffmpeg", "-y", "-loglevel", "error"]
    if vis and vis["kind"] == "video":
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},{GRADE}"
        run(base + ["-stream_loop", "-1", "-i", str(vis["path"]), "-vf", vf] + enc)
    elif vis and vis["kind"] == "photo":
        frames = int(dur * FPS) + 2
        vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
              f"zoompan=z='min(1+0.2*on/{frames},1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},setsar=1,{GRADE}")
        run(base + ["-i", str(vis["path"]), "-vf", vf] + enc)
    else:
        run(base + ["-f", "lavfi", "-i", f"color=c=0x14202e:s={W}x{H}:r={FPS}"] + enc)


def make_video(visuals: list, voice: dict, run_dir: Path, portrait: bool) -> dict:
    W, H = (1080, 1920) if portrait else (1920, 1080)
    run_dir = Path(run_dir); seg_dir = run_dir / "segments"; seg_dir.mkdir(exist_ok=True)
    segs = []
    for i, (vis, dur) in enumerate(zip(visuals, voice["durations"])):
        seg = seg_dir / f"seg{i:02d}.mp4"
        _segment(vis, dur, W, H, seg)
        segs.append(seg)
        log(f"[Video] scene {i + 1}/{len(visuals)} rendered ({dur:.1f}s)")
    lst = seg_dir / "list.txt"
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segs), encoding="utf-8")
    joined = run_dir / "joined.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])

    total = voice["total"]
    build_ass(voice["words"], run_dir / "sub.ass", portrait)
    music = run_dir / "music.wav"
    make_music(music, total + 1)
    final = run_dir / "final.mp4"
    fc = ("[0:v]ass=sub.ass[v];"
          "[1:a]asplit=2[va][vb];"
          "[2:a]volume=0.55[m];"
          "[m][vb]sidechaincompress=threshold=0.04:ratio=9:attack=20:release=500[md];"
          f"[va][md]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,afade=t=out:st={max(0, total - 1.0):.2f}:d=1.0[a]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", "joined.mp4", "-i", str(Path(voice["audio"]).resolve()), "-i", "music.wav",
         "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", "final.mp4"], cwd=str(run_dir))
    log(f"[Video] final: {final} ({duration(final):.1f}s)")
    return {"final": final, "first_segment": segs[0], "duration": duration(final)}


def check_video(path: Path, portrait: bool) -> None:
    """Refuse to upload broken output."""
    from .util import probe
    info = probe(path)
    streams = info["streams"]
    v = next((s for s in streams if s["codec_type"] == "video"), None)
    a = next((s for s in streams if s["codec_type"] == "audio"), None)
    if not v or not a:
        raise RuntimeError("Final video is missing a video or audio stream")
    want = (1080, 1920) if portrait else (1920, 1080)
    if (v["width"], v["height"]) != want:
        raise RuntimeError(f"Wrong resolution {v['width']}x{v['height']}, expected {want}")
    dur = float(info["format"]["duration"])
    if dur < 10:
        raise RuntimeError(f"Video too short ({dur:.1f}s)")
    if portrait and dur > 170:
        raise RuntimeError(f"Short is too long ({dur:.1f}s)")
