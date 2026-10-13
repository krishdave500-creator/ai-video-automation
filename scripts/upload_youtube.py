"""YouTube upload (YouTube Data API v3). Fully non-interactive: credentials come from
environment variables only, so it can never hang waiting for a browser login in CI."""
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import CFG
from .util import log

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
NEEDED = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]


def _build_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    missing = [n for n in NEEDED if not os.getenv(n)]
    if missing:
        raise RuntimeError("Missing YouTube credentials: " + ", ".join(missing))
    creds = Credentials(None, refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YOUTUBE_CLIENT_ID"], client_secret=os.environ["YOUTUBE_CLIENT_SECRET"], scopes=SCOPES)
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def effective_privacy(privacy: str | None) -> str:
    """Only 'private' unless ALLOW_PUBLIC=true is set (YouTube locks API uploads of unaudited projects to private anyway)."""
    p = (privacy or CFG.get("privacy", "private")).lower()
    if p not in ("private", "unlisted", "public"):
        p = "private"
    if p != "private" and os.getenv("ALLOW_PUBLIC", "").lower() != "true":
        log(f"[Upload] '{p}' requested but ALLOW_PUBLIC is not 'true' -> uploading as PRIVATE")
        return "private"
    return p


def _parse_publish_at(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("--publish-at needs a timezone, e.g. 2026-10-20T09:00:00+05:30")
    if dt <= datetime.now(timezone.utc):
        raise ValueError("--publish-at must be in the future")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def upload_video(video_path, title, description, tags, privacy="private", publish_at=None, thumbnail_path=None, is_short=False) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    status = {"privacyStatus": effective_privacy(privacy), "selfDeclaredMadeForKids": False}
    if publish_at:
        status["privacyStatus"] = "private"          # YouTube requires private + publishAt for scheduling
        status["publishAt"] = _parse_publish_at(publish_at)
    desc = description or ""
    if is_short and "#shorts" not in desc.lower():
        desc += "\n\n#Shorts"
    body = {"snippet": {"title": title[:100], "description": desc[:4900], "tags": list(tags or []),
                        "categoryId": str(CFG.get("category_id", "27")), "defaultLanguage": CFG.get("language", "en")},
            "status": status}
    yt = _build_service()
    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    log(f"[Upload] uploading '{title[:60]}' as {status['privacyStatus'].upper()}" + (f", publishes {status['publishAt']}" if publish_at else ""))
    resp, fails = None, 0
    while resp is None:
        try:
            st, resp = req.next_chunk()
            if st:
                log(f"[Upload] {int(st.progress() * 100)}%")
        except HttpError as e:
            code = getattr(e.resp, "status", 0)
            if code in (500, 502, 503, 504) and fails < 5:
                fails += 1; time.sleep(2 ** fails); continue
            if code == 403 and "quota" in str(e).lower():
                raise RuntimeError("YouTube API daily quota exceeded (about 6 uploads/day). Try again tomorrow.") from e
            raise
    vid = resp["id"]
    log(f"[Upload] done: https://youtu.be/{vid}")
    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")).execute()
            log("[Upload] thumbnail set")
        except Exception as e:  # needs a phone-verified channel; not fatal
            log(f"[Upload] thumbnail not set (channel may need phone verification): {type(e).__name__}")
    return vid
