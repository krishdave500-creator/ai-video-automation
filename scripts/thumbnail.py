"""Thumbnail: a frame from the video + dark gradient + big outlined text (1280x720)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from .config import CFG
from .util import log, run

SIZE = (1280, 720)
FONTS = ["/usr/share/fonts/truetype/noto/NotoSansGujarati-Bold.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "NotoSans-Bold.ttf"]


def _font(size: int):
    order = FONTS if CFG.get("language") == "gu" else FONTS[1:] + FONTS[:1]
    for f in order:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def grab_frame(video: Path, out: Path, at: float = 1.0) -> Path:
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1", str(out)])
    return out


def _wrap(draw, text: str, font, max_w: int) -> list:
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def create_thumbnail(text: str, frame: Path, out: Path) -> Path:
    img = Image.open(frame).convert("RGB")
    scale = max(SIZE[0] / img.width, SIZE[1] / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    l, t = (img.width - SIZE[0]) // 2, (img.height - SIZE[1]) // 2
    img = img.crop((l, t, l + SIZE[0], t + SIZE[1]))
    img = ImageEnhance.Color(img).enhance(1.25); img = ImageEnhance.Contrast(img).enhance(1.1)
    grad = Image.new("L", (1, SIZE[1]))
    for y in range(SIZE[1]):
        grad.putpixel((0, y), int(190 * (y / SIZE[1]) ** 1.5))
    img = Image.composite(Image.new("RGB", SIZE, (0, 0, 0)), img, grad.resize(SIZE))
    d = ImageDraw.Draw(img)
    txt = text.upper() if CFG.get("language", "en") == "en" else text
    size = 150
    while size > 60:
        font = _font(size)
        lines = _wrap(d, txt, font, int(SIZE[0] * 0.86))
        if len(lines) <= 3 and all(d.textlength(x, font=font) <= SIZE[0] * 0.9 for x in lines):
            break
        size -= 8
    lh = size * 1.12
    y = SIZE[1] - 70 - lh * len(lines)
    for ln in lines:
        x = (SIZE[0] - d.textlength(ln, font=font)) / 2
        d.text((x, y), ln, font=font, fill=(255, 215, 0), stroke_width=max(6, size // 14), stroke_fill=(0, 0, 0))
        y += lh
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=92)
    log(f"[Thumbnail] saved {out}")
    return out
