"""AI video pipeline - one command: topic -> script -> voice -> visuals -> captions -> video -> thumbnail -> (upload).

  python main.py                                   # AI picks topic, makes a Short, does NOT upload
  python main.py --format video --topic "How bridges stay up" --upload
  python main.py "Topic" short true private         # old positional form (used by server.py / n8n)
"""
import argparse
import json
import os
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from scripts.config import CFG  # noqa: E402
from scripts.fetch_visuals import fetch_all  # noqa: E402
from scripts.generate_film import generate_film_package  # noqa: E402
from scripts.generate_script import generate_package, generate_topic  # noqa: E402
from scripts.film import make_film, thumbnail_frame  # noqa: E402
from scripts.packaging import make_chapters  # noqa: E402
from scripts.generate_voice import make_voice  # noqa: E402
from scripts.make_video import check_video, make_video  # noqa: E402
from scripts.thumbnail import create_thumbnail, grab_frame  # noqa: E402
from scripts.upload_youtube import upload_video  # noqa: E402
from scripts.util import log  # noqa: E402

ROOT = Path(__file__).resolve().parent
HISTORY = "data/topics_done.txt"


def parse_args(argv):
    if argv and not argv[0].startswith("-"):  # legacy: topic format upload privacy
        ns = argparse.Namespace(topic=argv[0], format=(argv[1].lower() if len(argv) > 1 else "short"),
                                upload=(len(argv) > 2 and argv[2].lower() == "true"),
                                privacy=(argv[3].lower() if len(argv) > 3 else "private"), publish_at=None, keep_work=False)
        return ns
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", default="", help="leave empty to let AI pick")
    ap.add_argument("--format", choices=["short", "video"], default="short")
    ap.add_argument("--upload", action="store_true", help="upload to YouTube (private unless ALLOW_PUBLIC=true)")
    ap.add_argument("--privacy", default="private")
    ap.add_argument("--publish-at", default=None, help="e.g. 2026-10-20T09:00:00+05:30 (schedules a private upload)")
    ap.add_argument("--keep-work", action="store_true", help="keep temporary files in runs/")
    return ap.parse_args(argv)


def read_history() -> list:
    p = ROOT / HISTORY
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            parts = line.split("\t")
            if len(parts) >= 3:
                out.append(parts[2])
    return out


def record_topic(fmt: str, topic: str, video_id: str) -> None:
    p = ROOT / HISTORY
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("# one line per finished video: date<TAB>format<TAB>topic<TAB>youtube_id\n", encoding="utf-8")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d}\t{fmt}\t{topic}\t{video_id}\n")


def run_pipeline(topic: str, fmt: str, upload: bool, privacy: str = "private", publish_at: str | None = None, keep_work: bool = False) -> dict:
    if fmt not in ("short", "video"):
        raise ValueError(f"format must be 'short' or 'video', got '{fmt}'")
    portrait = fmt == "short"
    style = CFG.get("style", "cinematic")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log("=" * 60 + f"\n  RUN {run_id} | {fmt.upper()} | style={style} | upload={upload}\n" + "=" * 60)

    if not topic:
        log("[1/7] Picking a fresh topic...")
        topic = generate_topic(read_history())
    log(f"  Topic: {topic}")

    log("[2/7] Writing the script (hook, dialogue, title, description)...")
    pkg, last = None, None
    make = generate_film_package if style == "cinematic" else generate_package
    for attempt in range(3):
        try:
            pkg = make(topic, fmt)
            break
        except ValueError as e:
            last = e; log(f"  script rejected ({e}); retrying {attempt + 1}/3")
    if pkg is None:
        raise RuntimeError(f"Could not get a valid script: {last}")
    log(f"  Title: {pkg['title']}")

    thumb, chapters, final, duration_s = None, "", None, 0.0
    if style == "cinematic":
        log("[3/7] Voices + animation + music (this is the long step)...")
        film = make_film(pkg, run_dir, portrait)
        final, duration_s = film["final"], film["duration"]
        check_video(final, portrait)
        log("[4/7] Packaging (thumbnail, chapters)...")
        if not portrait:
            try:
                frame = thumbnail_frame(film["plan"], run_dir / "frame.png")
                thumb = create_thumbnail(pkg["thumbnail_text"], frame, run_dir / "thumbnail.jpg")
            except Exception as e:
                log(f"  thumbnail failed (not fatal): {e}")
            chapters = make_chapters([{"title": s["title"], "t0": sc["t0"]} for s, sc in zip(pkg["scenes"], film["plan"]["scenes"])])
    else:
        log("[3/7] Recording voice-over...")
        voice = make_voice(pkg["scenes"], run_dir)
        log("[4/7] Fetching visuals...")
        visuals = fetch_all(pkg["scenes"], run_dir, portrait)
        log("[5/7] Building video...")
        vid = make_video(visuals, voice, run_dir, portrait)
        final, duration_s = vid["final"], vid["duration"]
        check_video(final, portrait)
        if not portrait:
            try:
                frame = grab_frame(vid["first_segment"], run_dir / "frame.jpg", 0.8)
                thumb = create_thumbnail(pkg["thumbnail_text"], frame, run_dir / "thumbnail.jpg")
            except Exception as e:
                log(f"  thumbnail failed (not fatal): {e}")

    description = pkg["description"] + (("\n\nChapters:\n" + chapters) if chapters else "")
    out_dir = ROOT / "output" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final, out_dir / "video.mp4")
    if thumb:
        shutil.copy2(thumb, out_dir / "thumbnail.jpg")

    video_id = ""
    if upload:
        log("[7/7] Uploading to YouTube...")
        video_id = upload_video(out_dir / "video.mp4", pkg["title"], description, pkg["tags"], privacy=privacy,
                                publish_at=publish_at, thumbnail_path=(out_dir / "thumbnail.jpg") if thumb else None, is_short=portrait)
        record_topic(fmt, topic, video_id)
    else:
        log("[7/7] Upload skipped (add --upload to publish privately).")

    meta = {"run_id": run_id, "topic": topic, "format": fmt, "style": style, "title": pkg["title"], "description": description, "tags": pkg["tags"],
            "duration_s": round(duration_s, 1), "video_id": video_id, "hook": pkg.get("hook", ""), "title_lint": pkg.get("lint"),
            "characters": [c["name"] for c in pkg.get("characters", [])], "scenes": pkg["scenes"]}
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if not keep_work:
        shutil.rmtree(run_dir, ignore_errors=True)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### {pkg['title']}\n- format: {fmt}, {meta['duration_s']}s, style {style}\n- uploaded: {('https://youtu.be/' + video_id) if video_id else 'no'}\n")
    log(f"\nDONE -> {out_dir}")
    return meta


def main(argv=None) -> int:
    a = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        run_pipeline(a.topic, a.format, a.upload, a.privacy, a.publish_at, a.keep_work)
        return 0
    except Exception as e:  # fail loudly so CI turns red
        traceback.print_exc()
        print(f"\nPIPELINE FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
