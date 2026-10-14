"""Offline tests: no internet, no API keys. Network calls are replaced by fakes;
ffmpeg / Pillow / subtitle / audio code is REAL."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("PEXELS_API_KEY", "test")

import main  # noqa: E402
from scripts import fetch_visuals, generate_script, generate_voice, gemini_client, upload_youtube  # noqa: E402
from scripts.util import strip_markup  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vidtest_"))


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)


def make_assets():
    ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=6", "-pix_fmt", "yuv420p", str(TMP / "clip_p.mp4"))
    ff("-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=6", "-pix_fmt", "yuv420p", str(TMP / "clip_l.mp4"))
    from PIL import Image
    Image.effect_mandelbrot((900, 600), (-2.2, -1.2, 1.0, 1.2), 80).convert("RGB").save(TMP / "photo.jpg")


def scenes_pkg(n, words=8):
    return {"title": "Why Bridges Do Not Fall Down", "description": "A quick look at bridges.\n#science #engineering", "tags": ["bridges", "engineering"],
            "thumbnail_text": "BRIDGES DON'T FALL",
            "scenes": [{"narration": " ".join(f"word{n_}{i}" for i in range(words)) + ".", "visual": "bridge sunset"} for n_ in range(n)]}


async def fake_stream(text, mp3_path, **kw):
    ws = text.split(); dur = max(1.2, 0.33 * len(ws))
    freq = 180 + (sum(map(ord, str(kw.get('voice', '')))) % 200)
    ff("-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}", "-af", "tremolo=f=4:d=0.9", mp3_path)
    return [(i * dur / len(ws), (i + 1) * dur / len(ws) - 0.02, w) for i, w in enumerate(ws)]


async def fake_stream_no_words(text, mp3_path, **kw):
    await fake_stream(text, mp3_path, **kw)
    return []


def fake_get(url, params):
    if url == fetch_visuals.VIDEO_API:
        port = params["orientation"] == "portrait"
        return {"videos": [{"id": i, "duration": 8, "video_files": [
            {"file_type": "video/mp4", "width": 640, "height": 360, "link": "x"},
            {"file_type": "video/mp4", "width": 1080 if port else 1920, "height": 1920 if port else 1080, "link": "local://" + ("p" if port else "l")}]} for i in range(1, 30)]}
    return {"photos": [{"id": i, "src": {"large2x": "local://photo"}} for i in range(1, 30)]}


def fake_download(url, dest):
    src = {"local://p": "clip_p.mp4", "local://l": "clip_l.mp4", "local://photo": "photo.jpg"}[url]
    shutil.copy(TMP / src, dest)


class FakeReq:
    def __init__(self, svc): self.svc = svc
    def next_chunk(self): return None, {"id": "FAKEID123"}


class FakeService:
    def __init__(self): self.body = None; self.thumb = False
    def videos(self):
        outer = self
        class V:
            def insert(self, part, body, media_body):
                outer.body = body; return FakeReq(outer)
        return V()
    def thumbnails(self):
        outer = self
        class T:
            def set(self, videoId, media_body):
                outer.thumb = True
                class E:
                    def execute(self_): return {}
                return E()
        return T()


class UnitTests(unittest.TestCase):
    def test_strip_markup(self):
        s = strip_markup("**Narrator:** Hello *world* 😀 [pause] #hook `x`")
        self.assertEqual(s, "Hello world hook x")

    def test_validate_rejects_few_scenes_and_cleans(self):
        with self.assertRaises(ValueError):
            generate_script.validate_package({"title": "Hello there", "scenes": [{"narration": "a", "visual": "b"}]}, "short")
        pkg = generate_script.validate_package({"title": "**Big** title!", "description": "**d**", "tags": ["a,b", "c"],
                                                "scenes": [{"narration": "**Hi** there friend", "visual": "x"}] * 6}, "short")
        self.assertEqual(pkg["title"], "Big title!"); self.assertEqual(pkg["scenes"][0]["narration"], "Hi there friend")
        self.assertEqual(pkg["tags"], ["ab", "c"])

    def test_estimate_words(self):
        w = generate_voice.estimate_words("one two three", 3.0)
        self.assertEqual(len(w), 3); self.assertAlmostEqual(w[-1][1], 3.0, places=2); self.assertLess(w[0][1], w[1][1])

    def test_privacy_forced_private(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALLOW_PUBLIC", None)
            self.assertEqual(upload_youtube.effective_privacy("public"), "private")
            self.assertEqual(upload_youtube.effective_privacy("unlisted"), "private")
        with mock.patch.dict(os.environ, {"ALLOW_PUBLIC": "true"}):
            self.assertEqual(upload_youtube.effective_privacy("public"), "public")

    def test_publish_at_validation(self):
        with self.assertRaises(ValueError): upload_youtube._parse_publish_at("2020-01-01T00:00:00+05:30")
        with self.assertRaises(ValueError): upload_youtube._parse_publish_at("2099-01-01T00:00:00")
        self.assertTrue(upload_youtube._parse_publish_at("2099-01-01T09:00:00+05:30").endswith("Z"))

    def test_legacy_and_new_args(self):
        a = main.parse_args(["Some topic", "short", "true", "public"])
        self.assertEqual((a.topic, a.format, a.upload, a.privacy), ("Some topic", "short", True, "public"))
        b = main.parse_args(["--format", "video", "--upload"])
        self.assertEqual((b.topic, b.format, b.upload), ("", "video", True))
        c = main.parse_args([])
        self.assertEqual((c.format, c.upload), ("short", False))

    def _resp(self, code, body=None):
        r = mock.Mock(); r.status_code = code; r.text = json.dumps(body or {}); r.json.return_value = body or {}; return r

    def test_gemini_model_fallback_and_retry(self):
        ok = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"topic":"x"}'}]}}]}
        seq = [self._resp(404), self._resp(503), self._resp(200, ok)]
        with mock.patch.object(gemini_client.requests, "post", side_effect=seq) as p, mock.patch.object(gemini_client.time, "sleep"):
            self.assertEqual(gemini_client.generate_json("hi"), {"topic": "x"})
            models = [c.args[0] for c in p.call_args_list]
            self.assertEqual(models[0].split("/models/")[1].split(":")[0], gemini_client.CFG["gemini_model"])
            self.assertNotEqual(models[0], models[1])      # moved to the fallback model after a 404
            self.assertEqual(models[1], models[2])         # retried the same model after a 503
            self.assertNotIn("key=", models[0])            # key never in URL

    def test_gemini_all_fail(self):
        with mock.patch.object(gemini_client.requests, "post", return_value=self._resp(404)), mock.patch.object(gemini_client.time, "sleep"):
            with self.assertRaises(gemini_client.GeminiError): gemini_client.generate_json("hi")

    def test_gemini_ignores_thought_parts(self):
        data = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "secret thinking", "thought": True}, {"text": '{"a":1}'}]}}]}
        with mock.patch.object(gemini_client.requests, "post", return_value=self._resp(200, data)):
            self.assertEqual(gemini_client.generate_json("hi"), {"a": 1})


@mock.patch.dict(main.CFG, {"style": "stock"})
@mock.patch.object(generate_voice, "_stream_scene", fake_stream)
@mock.patch.object(fetch_visuals, "_get", fake_get)
@mock.patch.object(fetch_visuals, "_download", fake_download)
class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        make_assets()

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="root_", dir=TMP))
        (self.root / "data").mkdir()

    def run_pipeline(self, fmt, n, upload=False, **kw):
        svc = FakeService()
        with mock.patch.object(main, "ROOT", self.root), \
             mock.patch.object(main, "generate_package", lambda t, f: generate_script.validate_package(scenes_pkg(n), f)), \
             mock.patch.object(upload_youtube, "_build_service", lambda: svc):
            meta = main.run_pipeline("Why bridges stand", fmt, upload, **kw)
        return meta, svc, next((self.root / "output").iterdir())

    def info(self, p):
        out = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)]))
        v = next(s for s in out["streams"] if s["codec_type"] == "video")
        return v["width"], v["height"], float(out["format"]["duration"]), any(s["codec_type"] == "audio" for s in out["streams"])

    def test_short_end_to_end_with_upload(self):
        meta, svc, out = self.run_pipeline("short", 5, upload=True, privacy="public")
        w, h, d, audio = self.info(out / "video.mp4")
        self.assertEqual((w, h), (1080, 1920)); self.assertTrue(audio); self.assertGreater(d, 10)
        self.assertEqual(meta["video_id"], "FAKEID123")
        self.assertEqual(svc.body["status"]["privacyStatus"], "private")       # forced private
        self.assertIn("#Shorts", svc.body["snippet"]["description"])
        self.assertEqual(svc.body["snippet"]["categoryId"], "27")
        self.assertIn("Why bridges stand", (self.root / "data" / "topics_done.txt").read_text(encoding="utf-8"))
        self.assertFalse((out / "thumbnail.jpg").exists())                     # shorts: no thumbnail
        self.assertFalse((self.root / "runs" / meta["run_id"]).exists())       # temp files cleaned
        # captions are really burned in: yellow highlight pixels exist in a frame
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5", "-i", str(out / "video.mp4"), "-frames:v", "1", str(TMP / "f.png")], check=True)
        from PIL import Image
        import numpy as np
        a = np.asarray(Image.open(TMP / "f.png").convert("RGB")).reshape(-1, 3).astype(int)
        yellow = int(((a[:, 0] > 230) & (a[:, 1] > 180) & (a[:, 1] < 240) & (a[:, 2] < 60)).sum())
        self.assertGreater(yellow, 500, "no highlighted caption pixels found")

    def test_video_format_and_thumbnail_no_upload(self):
        meta, svc, out = self.run_pipeline("video", 8)
        w, h, d, audio = self.info(out / "video.mp4")
        self.assertEqual((w, h), (1920, 1080)); self.assertTrue(audio)
        from PIL import Image
        self.assertEqual(Image.open(out / "thumbnail.jpg").size, (1280, 720))
        self.assertIsNone(svc.body)                                             # no upload requested
        self.assertEqual(meta["video_id"], "")
        self.assertNotIn("Why bridges stand", (self.root / "data" / "topics_done.txt").read_text(encoding="utf-8") if (self.root / "data" / "topics_done.txt").exists() else "")

    def test_photo_fallback_and_color_fallback(self):
        with mock.patch.object(fetch_visuals, "_try_video", lambda *a, **k: None):
            meta, _, out = self.run_pipeline("short", 5)
            self.assertGreater(self.info(out / "video.mp4")[2], 10)
        shutil.rmtree(self.root / "output")
        with mock.patch.object(fetch_visuals, "_try_video", lambda *a, **k: None), mock.patch.object(fetch_visuals, "_try_photo", lambda *a, **k: None):
            meta, _, out = self.run_pipeline("short", 5)
            self.assertGreater(self.info(out / "video.mp4")[2], 10)

    def test_caption_timing_fallback_when_tts_gives_no_words(self):
        with mock.patch.object(generate_voice, "_stream_scene", fake_stream_no_words):
            meta, _, out = self.run_pipeline("short", 5, keep_work=True)
        ass = (self.root / "runs" / meta["run_id"] / "sub.ass").read_text(encoding="utf-8")
        self.assertGreater(ass.count("Dialogue:"), 20)

    def test_captions_never_overlap(self):
        from scripts.subtitles import build_ass
        words = [{"start": i * 0.4, "end": i * 0.4 + 0.38, "text": f"w{i}"} for i in range(40)]
        p = build_ass(words, TMP / "ov.ass", True)
        def sec(t):
            h, m, s = t.split(":"); return int(h) * 3600 + int(m) * 60 + float(s)
        ev = [l.split(",")[1:3] for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue:")]
        for (s1, e1), (s2, e2) in zip(ev, ev[1:]):
            self.assertLessEqual(sec(e1), sec(s2) + 1e-6)
            self.assertLess(sec(s2), sec(e2))

    def test_failure_returns_nonzero(self):
        with mock.patch.object(main, "ROOT", self.root), mock.patch.object(main, "generate_package", side_effect=ValueError("bad")):
            self.assertEqual(main.main(["--topic", "x"]), 1)


# ===================================================================== cinematic style
from scripts import cinema as C, film, generate_film, packaging  # noqa: E402


def film_pkg(n_lines=18):
    chars = [
        {"name": "Mia", "gender": "female", "age": "child", "color": "#ec4899", "hairstyle": "pigtails", "outfit": "dress"},
        {"name": "Grandpa", "gender": "male", "age": "elder", "color": "#6366f1", "hairstyle": "cap", "glasses": True, "mustache": True},
        {"name": "Dr Rao", "gender": "female", "age": "adult", "color": "#14b8a6", "hairstyle": "bun", "outfit": "dress"},
        {"name": "Ravi", "gender": "male", "age": "adult", "color": "#65a30d", "hairstyle": "pagdi"}]
    texts = ["Why does the bridge have tiny gaps in it?", "Good eyes. The bridge is alive in a way.", "Steel grows in heat and shrinks in cold.",
             "So it changes size every single day?", "Yes, by several centimetres on a long one.", "The gaps give the steel room to move.",
             "Without them the road could buckle in summer.", "That bump in the car is the gap working!"]
    settings = ["village_day", "sunset", "rain", "night", "forest", "space"]
    scenes = []
    per = max(2, n_lines // 3)
    k = 0
    for si in range(3):
        lines = []
        for j in range(per):
            who = [0, 1, 2, 3, -1][(k) % 5]
            lines.append({"who": who, "text": texts[k % len(texts)], "emotion": ["surprised", "happy", "neutral", "thinking", "sad"][k % 5]})
            k += 1
        scenes.append({"title": f"Part {si + 1}", "setting": settings[si], "cast": [0, 1, 2], "lines": lines})
    return {"title": "Why Bridges Have Tiny Gaps", "description": "Bridges move every day.\n#science", "tags": ["bridges"], "thumbnail_text": "IT MOVES",
            "hook": "Why does the bridge have tiny gaps?", "characters": chars, "scenes": scenes}


class FilmUnit(unittest.TestCase):
    def test_validate_forces_girl_lead_and_cleans(self):
        pkg = generate_film.validate_film(film_pkg(), "short")
        self.assertEqual((pkg["characters"][0]["gender"], pkg["characters"][0]["age"]), ("female", "child"))
        bad = film_pkg(); bad["characters"][0].update(gender="male", age="adult", color="red"); bad["scenes"][0]["lines"][0]["who"] = 99
        bad["scenes"][0]["lines"][1]["text"] = "**Narrator:** Hello 😀"
        p2 = generate_film.validate_film(bad, "short")
        self.assertEqual((p2["characters"][0]["gender"], p2["characters"][0]["age"]), ("female", "child"))
        self.assertTrue(p2["characters"][0]["color"].startswith("#"))
        self.assertEqual(p2["scenes"][0]["lines"][0]["text"], "Hello")
        with self.assertRaises(ValueError): generate_film.validate_film({"title": "abcdef", "characters": [], "scenes": []}, "short")
        with self.assertRaises(ValueError): generate_film.validate_film(film_pkg(6), "video")   # too few lines for a long video

    def test_voices_distinct_and_child_girl(self):
        v = film.assign_voices(generate_film.validate_film(film_pkg(), "short")["characters"])
        self.assertEqual(v[0]["voice"], "en-US-AnaNeural")                      # 12-year-old girl voice
        self.assertEqual(len({x["voice"] for x in v}), 4)                       # four different voices
        with mock.patch.dict(film.CFG, {"language": "gu", "voice": "gu-IN-DhwaniNeural"}):
            g = film.assign_voices(generate_film.validate_film(film_pkg(), "short")["characters"])
        self.assertEqual(g[0]["voice"], "gu-IN-DhwaniNeural"); self.assertGreater(g[0]["pitch"], 0)   # shifted up for a child
        self.assertNotEqual((g[0]["voice"], g[0]["pitch"]), (g[2]["voice"], g[2]["pitch"]))            # two females differ

    def test_narrator_is_a_male_voice_distinct_from_leads(self):
        n = film.narrator_voice()
        self.assertEqual(n["voice"], "en-US-DavisNeural")
        v = film.assign_voices(generate_film.validate_film(film_pkg(), "short")["characters"])
        self.assertNotIn(n["voice"], [x["voice"] for x in v])

    def test_packaging_rules(self):
        self.assertIn("length", [c for c, _ in packaging.lint_title("x" * 70)["issues"]])
        r = packaging.lint_title("Why bridges move", "BRIDGES MOVE NOW TODAY")
        self.assertIn("duplicate", [c for c, _ in r["issues"]]); self.assertIn("thumb-length", [c for c, _ in r["issues"]])
        self.assertEqual(packaging.fix_thumb_text("BRIDGES MOVE A LOT TODAY", "Why bridges move"), "A LOT TODAY")
        ch = packaging.make_chapters([{"title": "A", "t0": 3}, {"title": "B", "t0": 40}, {"title": "C", "t0": 90}])
        self.assertTrue(ch.startswith("0:00 A") and "1:30 C" in ch)
        self.assertEqual(packaging.make_chapters([{"title": "A", "t0": 0}, {"title": "B", "t0": 40}]), "")   # needs 3 chapters
        self.assertEqual(packaging.hook_formulas()["hooks"][0]["id"], "the-statistic")
        self.assertEqual(len(packaging.hook_formulas()["hooks"]), 21)

    def test_every_setting_renders_in_every_layout(self):
        import numpy as np
        pkg = generate_film.validate_film(film_pkg(), "short")
        for layout, cam in (("landscape", (1150, 330, 1.32)), ("portrait", (1150, 540, 1.45)), ("thumb", (1150, 300, 1.75))):
            C.set_layout(layout)
            for name in C.SETTINGS:
                plan = {"scenes": [{"setting": name, "cast": [0, 1, 2], "cast_x": {0: 1000, 1: 1150, 2: 1300}, "t0": 0, "t1": 10}], "tl": [], "chars": pkg["characters"], "fps": 24}
                arr = C.compose(plan, 1.0, 3, 0, cam, -1, 0.0, 1.0)
                self.assertEqual(arr.shape, (C.LY.FH, C.LY.FW, 3), (layout, name))
                self.assertGreater(float(arr.std()), 5, f"{layout}/{name} looks blank")
        C.set_layout("landscape")


@mock.patch.dict(main.CFG, {"style": "cinematic"})
@mock.patch.object(generate_voice, "_stream_scene", fake_stream)
@mock.patch.dict(os.environ, {"CINEMA_FPS": "8", "RENDER_PROCS": "1"})
class CinemaPipeline(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="croot_", dir=TMP)); (self.root / "data").mkdir()

    def run_it(self, fmt, n_lines, **kw):
        svc = FakeService()
        with mock.patch.object(main, "ROOT", self.root), \
             mock.patch.object(main, "generate_film_package", lambda t, f: generate_film.validate_film(film_pkg(n_lines), f)), \
             mock.patch.object(upload_youtube, "_build_service", lambda: svc):
            meta = main.run_pipeline("Why bridges stand", fmt, kw.pop("upload", False), **kw)
        return meta, svc, next((self.root / "output").iterdir())

    def probe(self, p):
        o = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)]))
        v = next(s for s in o["streams"] if s["codec_type"] == "video")
        return v["width"], v["height"], float(o["format"]["duration"]), any(s["codec_type"] == "audio" for s in o["streams"])

    def test_short_vertical(self):
        meta, svc, out = self.run_it("short", 12, upload=True, privacy="public")
        w, h, d, audio = self.probe(out / "video.mp4")
        self.assertEqual((w, h), (1080, 1920)); self.assertTrue(audio); self.assertGreater(d, 12)
        self.assertEqual(meta["style"], "cinematic"); self.assertEqual(svc.body["status"]["privacyStatus"], "private")
        self.assertIn("#Shorts", svc.body["snippet"]["description"])
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "4", "-i", str(out / "video.mp4"), "-frames:v", "1", str(TMP / "cs.png")], check=True)
        from PIL import Image
        import numpy as np
        a = np.asarray(Image.open(TMP / "cs.png").convert("RGB")).reshape(-1, 3).astype(int)
        self.assertGreater(int(((a[:, 0] > 230) & (a[:, 1] > 180) & (a[:, 1] < 240) & (a[:, 2] < 60)).sum()), 150, "highlighted caption not found")
        self.assertGreater(len({tuple(p) for p in a[::997]}), 400, "frame looks flat")

    def test_long_horizontal_with_thumbnail_and_chapters(self):
        meta, svc, out = self.run_it("video", 18)
        w, h, d, audio = self.probe(out / "video.mp4")
        self.assertEqual((w, h), (1920, 1080)); self.assertTrue(audio)
        from PIL import Image
        with Image.open(out / "thumbnail.jpg") as th: self.assertEqual(th.size, (1280, 720))
        self.assertIn("Chapters:", meta["description"]); self.assertIn("0:00 Part 1", meta["description"])
        # letterbox: top and bottom rows of the 16:9 frame are black bars
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "5", "-i", str(out / "video.mp4"), "-frames:v", "1", str(TMP / "cl.png")], check=True)
        import numpy as np
        self.assertLess(int(np.asarray(Image.open(TMP / "cl.png").convert("L"))[:100].max()), 30)

    def test_camera_plan_is_sane(self):
        import numpy as np
        pkg = generate_film.validate_film(film_pkg(18), "video")
        with mock.patch.object(main, "ROOT", self.root):
            plan, tl, _ = film.build_plan(pkg, self.root / "runs" / "x", False)
        self.assertTrue(np.isfinite(plan["cam"]).all())
        self.assertTrue((plan["cam"][:, 2] >= 0.9).all() and (plan["cam"][:, 2] <= 2.0).all())
        self.assertTrue(((plan["fade"] >= 0) & (plan["fade"] <= 1)).all())
        self.assertEqual(plan["fscene"][0], 0); self.assertLess(plan["fade"][0], 0.2)           # starts from black
        self.assertTrue(any(v < 0.05 for v in plan["fade"]))                                      # fades between scenes


from scripts import local_tts  # noqa: E402


class LocalVoices(unittest.TestCase):
    def test_distinct_voices_in_every_language(self):
        chars = generate_film.validate_film(film_pkg(), "short")["characters"]
        for lang in ("en", "hi", "gu"):
            specs = local_tts.local_voices(chars, lang)
            keys = [(s["model"], s["sid"], s["ratio"]) for s in specs]
            self.assertEqual(len(set(keys)), len(keys), lang)                # nobody shares the exact same voice
            self.assertGreater(specs[0]["ratio"] * (1 if lang != "gu" else 1), 0.9)
        en = local_tts.local_voices(chars, "en")
        self.assertGreater(en[0]["ratio"], 1.2)                               # the girl is pitched up
        self.assertEqual(en[0]["sid"], 4)

    def test_engine_choice(self):
        async def blocked(text, mp3, **kw):
            raise RuntimeError("403 blocked")
        with mock.patch.dict(film.CFG, {"tts_engine": "auto"}):
            with mock.patch.object(generate_voice, "_stream_scene", blocked):
                self.assertEqual(film.pick_engine(), "local")
            with mock.patch.object(generate_voice, "_stream_scene", fake_stream):
                self.assertEqual(film.pick_engine(), "edge")
        with mock.patch.dict(film.CFG, {"tts_engine": "local"}):
            self.assertEqual(film.pick_engine(), "local")

    def test_film_builds_with_local_engine(self):
        def fake_speak(text, spec, wav):
            ff("-f", "lavfi", "-i", f"sine=frequency={150 + spec['sid'] * 20}:duration={max(1.2, 0.33 * len(text.split()))}", "-ac", "1", "-ar", "22050", "-sample_fmt", "s16", str(wav))
        async def blocked(text, mp3, **kw):
            raise RuntimeError("403 blocked")
        pkg = generate_film.validate_film(film_pkg(12), "short")
        with mock.patch.dict(film.CFG, {"tts_engine": "auto"}), mock.patch.object(generate_voice, "_stream_scene", blocked), \
             mock.patch.object(local_tts, "speak", fake_speak), mock.patch.dict(os.environ, {"CINEMA_FPS": "8"}):
            plan, tl, _ = film.build_plan(pkg, TMP / "local_plan", True)
        self.assertGreater(len(plan["words"]), 30)                            # captions come from estimated timings
        self.assertTrue(all(w["end"] >= w["start"] for w in plan["words"]))


if __name__ == "__main__":
    unittest.main()
