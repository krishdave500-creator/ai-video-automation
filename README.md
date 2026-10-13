# AI Video Automation (faceless YouTube channel)

One command: **topic -> story script (hook formulas) -> animated multi-character film (own voice per character) -> captions -> music -> thumbnail + chapters -> private YouTube upload.**
Everything uses free tiers: Gemini (script), Edge TTS (voices), ffmpeg + Pillow (animation and assembly), YouTube Data API (upload). Pexels is only needed for the optional `"style": "stock"`.
Credits: hook formulas and title/chapter rules adapted from youtube-agent-skill (MIT), see `NOTICE`.

**New here? Follow `SETUP_GUIDE.md` (one-time, about 40 minutes).**

## Safe defaults
- Uploads are **always PRIVATE** (YouTube also locks API uploads of unaudited projects to private).
- Secrets live only in **GitHub Secrets** (or a local `.env`, which git ignores). Nothing secret is stored in the repo.
- A failed upload makes the GitHub run **red** (it never silently "succeeds").
- Every video is checked (resolution, audio, length) before upload.

## GitHub secrets needed
`GEMINI_API_KEY`, `PEXELS_API_KEY`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`
(Repository > Settings > Secrets and variables > Actions > New repository secret)

## Run it
GitHub > **Actions** > "Create and upload video" > **Run workflow**.
- First run: leave **upload** unticked. Download the video from the run page (Artifacts > video-output) and check it.
- Then tick **upload**. The video appears in YouTube Studio as **Private**.

Automatic schedule (daily Short at 09:00 IST, weekly video on Sunday): create a repository **variable**
(Settings > Secrets and variables > Actions > Variables) named `ENABLE_SCHEDULE` with value `true`. Delete it to pause.

## Local run (optional)
```
pip install -r requirements.txt      # needs ffmpeg installed
cp .env.example .env                 # fill in keys
python main.py --format short        # makes a video, does not upload
python main.py --format video --topic "How bridges stay up" --upload
python -m unittest discover -s tests # offline tests, no keys needed
```

## Settings (`config.json`)
Change niche, language, voice, model, scene counts. Gujarati example:
`"language": "gu", "language_name": "Gujarati", "voice": "gu-IN-DhwaniNeural", "subtitle_font": "Noto Sans Gujarati"`.

## Limits (be aware)
- GitHub Actions: no browser login (so the YouTube token is created once, outside), 6-hour job limit, free-minute quota on private repos, schedules can be delayed or paused after long inactivity.
- YouTube: about 6 uploads/day on the default quota. Public automatic uploads need Google's API audit; until then use Studio to review.
- Mass-produced, repetitive stock-footage videos can be rejected for monetization ("inauthentic content"). Keep a clear niche and add your own value.
- `gemini_model` names change over time: if a run fails with "All Gemini models failed", update `config.json`.

## Optional / legacy
`server.py` + `n8n/` trigger runs over HTTP. They are optional and not used by GitHub Actions. `server.py` needs `API_TOKEN` and only listens on localhost.
