# SETUP GUIDE - do this once, then it runs by itself

After this guide you never need Claude (or any chat) to make or upload videos.
The daily work is done by GitHub (free machine) + Gemini (free script) + Edge TTS (free voice) + Pexels (free video).
Button names on Google/GitHub websites change now and then. If a name differs slightly, pick the closest one.
Time needed: about 40 minutes, once.

---------------------------------------------------------------------
## PART 1 - Put the project on GitHub  (5 min)
1. Open https://github.com/krishdave500-creator/ai-video-automation
2. Click **Add file** > **Upload files**.
3. Open the unzipped folder, press Ctrl+A, drag everything into the browser box.
   (The `.github` folder must go too. On Mac: Cmd+Shift+. shows hidden folders.)
4. Wait until all files finish uploading. Keep **Commit directly to the main branch** selected.
5. Click **Commit changes**.
6. Click the **Actions** tab. The run called **Tests** should turn green. If it is red, open it and copy the error.

## PART 2 - Free keys  (10 min)
**Gemini key (writes scripts)**
1. Open https://aistudio.google.com/apikey and sign in.
2. Click **Create API key**. Copy it into a private note.

**Pexels key (OPTIONAL - only for the old `stock` style; skip it for the animated films)**
1. Open https://www.pexels.com/api/ , click **Get Started**, sign up or log in.
2. Describe your project in one line ("faceless educational videos") and copy the API key.

## PART 3 - Let the project upload to YOUR YouTube channel  (20 min)
This is the longest part. Use the Google account that owns your YouTube channel.

**3A. Make a Google Cloud project**
1. Open https://console.cloud.google.com
2. Top bar project picker > **New project** > name `video-automation` > **Create**. Make sure it is selected.
3. Left menu > **APIs & Services** > **Library**. Search **YouTube Data API v3** > **Enable**.

**3B. Consent screen**
1. **APIs & Services** > **OAuth consent screen** (may be called "Google Auth Platform") > **Get started**.
2. App name `Video Automation`, your email for support and contact. Audience: **External**. Finish / Create.
3. Open **Audience** (or "Publishing status") and click **Publish app** > Confirm.
   IMPORTANT: if you skip this, your login expires every 7 days and uploads stop.
4. Open **Data Access** (or "Scopes") > **Add or remove scopes** > add `https://www.googleapis.com/auth/youtube.upload` > Save.

**3C. OAuth client**
1. **APIs & Services** > **Credentials** > **Create credentials** > **OAuth client ID**.
2. Application type: **Web application**. Name: `playground`.
3. Under **Authorized redirect URIs** click **Add URI** and paste exactly:
   `https://developers.google.com/oauthplayground`
4. **Create**. Copy the **Client ID** and **Client secret** into your private note.

**3D. Get the refresh token (the "key" the robot uses)**
1. Open https://developers.google.com/oauthplayground
2. Click the gear icon (top right). Tick **Use your own OAuth credentials**. Paste Client ID and Client secret. Close.
3. In the left box "Input your own scopes" type: `https://www.googleapis.com/auth/youtube.upload` and click **Authorize APIs**.
4. Choose your channel's Google account. If you see "Google hasn't verified this app": **Advanced** > **Go to Video Automation (unsafe)** > **Continue** / **Allow**.
   (That warning is normal for your own private app.)
5. Click **Exchange authorization code for tokens**. Copy the **Refresh token** into your private note.

## PART 4 - Give the keys to GitHub safely  (5 min)
1. Your repo > **Settings** > **Secrets and variables** > **Actions** > **New repository secret**.
2. Add these (PEXELS is optional), one by one (Name exactly as written, Secret = the value):

| Name | Value |
|---|---|
| GEMINI_API_KEY | key from Part 2 |
| PEXELS_API_KEY | optional (only for style `stock`) |
| YOUTUBE_CLIENT_ID | Client ID from 3C |
| YOUTUBE_CLIENT_SECRET | Client secret from 3C |
| YOUTUBE_REFRESH_TOKEN | Refresh token from 3D |

Never paste keys into chat, issues, README or any file in the repo.

## PART 5 - First test  (10 min)
1. Repo > **Actions** > **Create and upload video** > **Run workflow**.
2. format = `short`, topic empty, upload **unticked** > **Run workflow**. Wait 5-15 minutes.
3. Open the finished run > **Artifacts** > **video-output**. Watch `video.mp4`.
   Happy? Run again with **upload ticked**.
4. Open https://studio.youtube.com > **Content**. The video is there as **Private**.

## PART 6 - Turn on automatic daily videos
1. Repo > **Settings** > **Secrets and variables** > **Actions** > **Variables** tab > **New repository variable**.
2. Name `ENABLE_SCHEDULE`, Value `true` > **Add variable**.
3. Now: a Short every day at 09:00 India time, a long video every Sunday 10:30. To pause: delete that variable.

## WHAT YOU GET
- **Cinematic animated films** (default `"style": "cinematic"`): 3-4 characters with different looks and different voices, lip-sync, camera moves,
  parallax backgrounds, lighting, rain/fireflies, music and ambience, word-by-word captions.
  Shorts are vertical 1080x1920 (about 35-50 s). Long videos are 1920x1080 cinema-bar style (about 2-3 min) with a thumbnail and chapters.
- Character 0 is always a **12-year-old girl** (the curious lead). Voices are Microsoft neural voices (human-sounding, not robotic).
  English uses a real child-girl voice (`en-US-AnaNeural`). Gujarati and Hindi have no child voice in Edge TTS, so the girl is the normal
  female voice shifted up; the other characters get different voices/pitches.
- Scripts follow proven hook formulas (21 formulas, first line is the hook, no "welcome" intro), titles are length-checked (60 chars), and the
  thumbnail text never repeats the title.
- One video takes about 5-15 minutes on GitHub (the animation is drawn on their machine).
- To use the old stock-footage look instead: set `"style": "stock"` in `config.json`.

## HOW TO CHANGE THINGS (no coding)
Repo > click `config.json` > pencil icon > edit > **Commit changes**.
- `niche`: what your channel is about (the AI picks fresh topics inside this niche).
- Gujarati channel: set `"language": "gu"`, `"language_name": "Gujarati"`, `"voice": "gu-IN-DhwaniNeural"`, `"subtitle_font": "Noto Sans Gujarati"`.
- To use your own topics: Run workflow > type a topic.
- To force specific voices: add `"voices": {"female": ["en-US-JennyNeural"], "male": ["en-GB-RyanNeural"]}` to `config.json`. If a voice name is not available the run falls back to your default `voice` instead of failing.

## IMPORTANT TRUTHS
- Uploads stay **Private**. YouTube forces API uploads from unaudited projects to private. Each day, open Studio, watch the video, press **Visibility > Public**. (Public-by-API needs Google's audit form "YouTube API Services - Audit and Quota Extension".)
- Daily limit is about 6 uploads. One a day is fine.
- YouTube may refuse monetization for mass-produced, repetitive videos. Pick a clear niche, check each video, add your own value.
- Public repos show run logs to everyone. The project never prints keys, but never add secrets to files.

## IF SOMETHING FAILS (open the red run and read the last red lines)
| You see | Do this |
|---|---|
| All Gemini models failed | Open aistudio.google.com, see which model your key can use, put its name in `config.json` > `gemini_model` |
| GEMINI_API_KEY is not set / Missing YouTube credentials | A secret name is misspelled or empty (Part 4) |
| invalid_grant | Refresh token expired or revoked. Repeat 3D and replace YOUTUBE_REFRESH_TOKEN. Check you did 3B step 3 (Publish app) |
| quota exceeded | Wait until tomorrow |
| Pexels 401 / 403 | PEXELS_API_KEY wrong |
| Edge TTS connection error | Re-run. If it repeats, check https://pypi.org/project/edge-tts for a newer version and update the number in requirements.txt |
| Schedule never runs | The variable ENABLE_SCHEDULE must be `true`; scheduled runs only use the main branch; GitHub can pause schedules after 60 days of no activity |
