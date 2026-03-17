"""
lulu_format_pdf.py — Step 8 of the Audio-to-Storybook Pipeline

Purpose:  Rebuild the storybook as two Lulu-spec PDFs:
            1. Interior — 24 scene pages (matches Lulu's 24-page minimum exactly)
            2. Cover    — separate full-bleed PDF with title text overlay

          Trim size:    10" × 8"  landscape (softcover perfect-bound)
          With bleed:   10.25" × 8.25"  (0.125" bleed on all four sides)
          Page size:    738 × 594 pt  at 72 pt/in
          Safe margin:  0.375" from bleed edge = 27 pt  (Lulu recommended safe zone)

          DPI NOTE: DALL-E 3 generates 1792 px wide images.
          At 10.25" print width → 1792 / 10.25 ≈ 175 DPI.
          Lulu recommends 300 DPI for best print quality.
          These images will be accepted but may appear slightly soft in print.

Input:  .tmp/storyboard.json            — book title + 15 scene texts
        .tmp/story_style_profile.json   — story_gender for accent color
        .tmp/images/cover.png           — hero cover illustration
        .tmp/images/scene_01.png …      — 15 scene illustrations

Output: .tmp/storybook_lulu_interior.pdf
        .tmp/storybook_lulu_cover.pdf

Required .env keys: (none required)
    STORYBOOK_AUTHOR — author name displayed on the cover (optional)
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image as PILImage
from reportlab.lib.colors import HexColor, white
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
TMP_DIR = PROJECT_DIR / ".tmp"
INPUT_FILE = TMP_DIR / "storyboard.json"
IMAGES_DIR = TMP_DIR / "images"
FONTS_DIR = TMP_DIR / "fonts"
INTERIOR_OUTPUT = TMP_DIR / "storybook_lulu_interior.pdf"
COVER_OUTPUT = TMP_DIR / "storybook_lulu_cover.pdf"

# ---------------------------------------------------------------------------
# Lulu 10"×8" softcover — page dimensions with 0.125" bleed on all sides
# ---------------------------------------------------------------------------
LULU_PAGE_W = 738.0   # 10.25" × 72 pt/in  (10" trim + 0.125" bleed each side)
LULU_PAGE_H = 594.0   #  8.25" × 72 pt/in  ( 8" trim + 0.125" bleed each side)
SAFE_MARGIN = 27.0    #  0.375" × 72 — minimum safe zone from bleed edge
MIN_PAGES = 24        # Lulu perfect-bound softcover minimum
POD_PACKAGE_ID = "1000X0800FCSTDPB080CW444GXX"  # 10"×8" FC STD PB 080CW444 gloss

# ---------------------------------------------------------------------------
# Colors — same palette as build_pdf.py
# ---------------------------------------------------------------------------
PAGE_BG        = HexColor("#FAFAF7")
TEXT_COLOR     = HexColor("#3D3325")
RULE_COLOR     = HexColor("#C4956A")   # amber-brown (girl/neutral)
BOY_RULE_COLOR = HexColor("#2C5F2E")   # forest green (boy stories)
WARM_DARK      = HexColor("#2E1A0E")
GOLD_ACCENT    = HexColor("#D4880A")
OVERLAY_BG     = HexColor("#1A0E05")

# ---------------------------------------------------------------------------
# Layout map — same scene assignments as build_pdf.py
# ---------------------------------------------------------------------------
LAYOUTS = {
    1:  "full_bleed",
    2:  "caption_bottom",
    3:  "full_bleed",
    4:  "caption_bottom",
    5:  "full_bleed",
    6:  "caption_bottom",
    7:  "full_bleed",
    8:  "full_bleed",
    9:  "caption_bottom",
    10: "caption_bottom",
    11: "full_bleed",
    12: "caption_bottom",
    13: "caption_bottom",
    14: "full_bleed",
    15: "full_bleed",
    16: "caption_bottom",
    17: "full_bleed",
    18: "caption_bottom",
    19: "full_bleed",
    20: "caption_bottom",
    21: "full_bleed",
    22: "caption_bottom",
    23: "caption_bottom",
    24: "full_bleed",
}

# ---------------------------------------------------------------------------
# Font management (identical to build_pdf.py — shared cache)
# ---------------------------------------------------------------------------
FONT_URLS = {
    "Chewy-Regular.ttf":     "https://github.com/google/fonts/raw/main/apache/chewy/Chewy-Regular.ttf",
    "Spectral-SemiBold.ttf": "https://github.com/google/fonts/raw/main/ofl/spectral/Spectral-SemiBold.ttf",
}
FONT_DISPLAY = "Chewy"
FONT_BODY    = "Spectral SemiBold"


def download_fonts():
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    for filename, url in FONT_URLS.items():
        dest = FONTS_DIR / filename
        if dest.exists():
            results[filename] = True
            continue
        try:
            print(f"  Downloading font: {filename}...")
            urllib.request.urlretrieve(url, dest)
            results[filename] = True
        except Exception as e:
            print(f"  WARNING: Could not download {filename}: {e}")
            results[filename] = False
    return results


def register_fonts():
    font_status = download_fonts()
    chewy_ok = font_status.get("Chewy-Regular.ttf", False)
    spectral_ok = font_status.get("Spectral-SemiBold.ttf", False)
    if chewy_ok:
        pdfmetrics.registerFont(TTFont(FONT_DISPLAY, str(FONTS_DIR / "Chewy-Regular.ttf")))
    if spectral_ok:
        pdfmetrics.registerFont(TTFont(FONT_BODY, str(FONTS_DIR / "Spectral-SemiBold.ttf")))
    return chewy_ok and spectral_ok


def get_fonts(custom_loaded):
    if custom_loaded:
        return FONT_DISPLAY, FONT_BODY
    return "Helvetica-Bold", "Times-Roman"


# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------

def load_image_reader(img_path: Path) -> ImageReader:
    with PILImage.open(img_path) as im:
        if im.mode in ("RGBA", "P"):
            im = im.convert("RGB")
        import io as _io
        buf = _io.BytesIO()
        im.save(buf, format="PNG")
        buf.seek(0)
        return ImageReader(buf)


def draw_image_fill_crop(c: rl_canvas.Canvas, img_path: Path,
                          x: float, y: float, w: float, h: float) -> None:
    ir = load_image_reader(img_path)
    with PILImage.open(img_path) as im:
        orig_w, orig_h = im.size
    scale = max(w / orig_w, h / orig_h)
    draw_w = orig_w * scale
    draw_h = orig_h * scale
    draw_x = x + (w - draw_w) / 2
    draw_y = y + (h - draw_h) / 2
    c.saveState()
    clip = c.beginPath()
    clip.rect(x, y, w, h)
    c.clipPath(clip, fill=0, stroke=0)
    c.drawImage(ir, draw_x, draw_y, draw_w, draw_h)
    c.restoreState()


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

def wrap_text(text: str, font: str, size: float, max_width: float) -> list[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        if pdfmetrics.stringWidth(test, font, size) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_text_block(c: rl_canvas.Canvas, text: str, font: str, size: float,
                    leading: float, color, cx: float, cy: float,
                    max_width: float) -> float:
    lines = wrap_text(text, font, size, max_width)
    total_h = len(lines) * leading
    y = cy - size
    c.setFont(font, size)
    c.setFillColor(color)
    for line in lines:
        w = pdfmetrics.stringWidth(line, font, size)
        c.drawString(cx - w / 2, y, line)
        y -= leading
    return total_h


def draw_open_text(c: rl_canvas.Canvas, text: str,
                   font_body: str,
                   zone_x: float, zone_y: float,
                   zone_w: float, zone_h: float,
                   font_size: float = 22) -> None:
    leading = font_size * 1.65
    text_max_w = zone_w - 2 * SAFE_MARGIN
    lines = wrap_text(text, font_body, font_size, text_max_w)
    total_h = len(lines) * leading
    text_cy = zone_y + zone_h / 2 + total_h / 2
    draw_text_block(c, text, font_body, font_size, leading,
                    TEXT_COLOR, zone_x + zone_w / 2, text_cy, text_max_w)


# ---------------------------------------------------------------------------
# Lulu page drawing functions
# ---------------------------------------------------------------------------

def draw_lulu_full_bleed(c: rl_canvas.Canvas, img_path: Path, text: str,
                          font_body: str, rule_color) -> None:
    """Full-bleed image; soft white strip at bottom 30% for text."""
    draw_image_fill_crop(c, img_path, 0, 0, LULU_PAGE_W, LULU_PAGE_H)

    overlay_h = LULU_PAGE_H * 0.30

    c.saveState()
    c.setFillColor(white)
    c.setFillAlpha(0.85)
    c.rect(0, 0, LULU_PAGE_W, overlay_h, fill=1, stroke=0)
    c.restoreState()

    c.saveState()
    c.setStrokeColor(rule_color)
    c.setLineWidth(1.0)
    c.setStrokeAlpha(0.5)
    c.line(SAFE_MARGIN, overlay_h, LULU_PAGE_W - SAFE_MARGIN, overlay_h)
    c.restoreState()

    draw_open_text(c, text, font_body, 0, 0, LULU_PAGE_W, overlay_h, font_size=20)
    c.showPage()


def draw_lulu_caption_bottom(c: rl_canvas.Canvas, img_path: Path, text: str,
                               font_body: str, rule_color) -> None:
    """Clean white background; image top 72%; thin rule; open text below."""
    img_frac = 0.72
    strip_h = LULU_PAGE_H * (1.0 - img_frac)
    img_h = LULU_PAGE_H * img_frac

    c.setFillColor(PAGE_BG)
    c.rect(0, 0, LULU_PAGE_W, LULU_PAGE_H, fill=1, stroke=0)

    img_pad = 8
    draw_image_fill_crop(c, img_path,
                          img_pad, strip_h,
                          LULU_PAGE_W - 2 * img_pad, img_h - img_pad)

    c.setStrokeColor(rule_color)
    c.setLineWidth(1.0)
    c.line(SAFE_MARGIN, strip_h, LULU_PAGE_W - SAFE_MARGIN, strip_h)

    draw_open_text(c, text, font_body, 0, 0, LULU_PAGE_W, strip_h, font_size=22)
    c.showPage()


def draw_lulu_cover(c: rl_canvas.Canvas, cover_path: Path, title: str, author: str,
                     font_display: str, font_body: str) -> None:
    """Full-bleed cover with dark overlay and title text."""
    c.setPageSize((LULU_PAGE_W, LULU_PAGE_H))

    if cover_path.exists():
        draw_image_fill_crop(c, cover_path, 0, 0, LULU_PAGE_W, LULU_PAGE_H)

        overlay_h = LULU_PAGE_H * 0.30
        c.saveState()
        c.setFillColor(OVERLAY_BG)
        c.setFillAlpha(0.75)
        c.rect(0, 0, LULU_PAGE_W, overlay_h, fill=1, stroke=0)
        c.restoreState()

        text_cy = overlay_h * 0.76
        title_size = 54
        author_size = 20
        text_color = white
        shadow_color = HexColor("#000000")
    else:
        c.setFillColor(HexColor("#FFF0CC"))
        c.rect(0, 0, LULU_PAGE_W, LULU_PAGE_H, fill=1, stroke=0)
        text_cy = LULU_PAGE_H * 0.55
        title_size = 48
        author_size = 18
        text_color = WARM_DARK
        shadow_color = None

    title_max_w = LULU_PAGE_W * 0.82

    if shadow_color:
        draw_text_block(c, title, font_display, title_size, title_size * 1.15,
                        shadow_color, LULU_PAGE_W / 2 + 2, text_cy - 2, title_max_w)
    draw_text_block(c, title, font_display, title_size, title_size * 1.15,
                    text_color, LULU_PAGE_W / 2, text_cy, title_max_w)

    if author:
        author_y = text_cy - title_size * 1.5
        draw_text_block(c, f"by {author}", font_body, author_size, author_size * 1.3,
                        text_color, LULU_PAGE_W / 2, author_y, LULU_PAGE_W * 0.7)

    if cover_path.exists():
        rule_y = LULU_PAGE_H * 0.30 - 3
        c.setStrokeColor(GOLD_ACCENT)
        c.setLineWidth(2.0)
        c.line(SAFE_MARGIN * 2, rule_y, LULU_PAGE_W - SAFE_MARGIN * 2, rule_y)

    c.showPage()


def add_blank_page(c: rl_canvas.Canvas) -> None:
    """Insert a blank cream-white page (for padding to MIN_PAGES)."""
    c.setPageSize((LULU_PAGE_W, LULU_PAGE_H))
    c.setFillColor(PAGE_BG)
    c.rect(0, 0, LULU_PAGE_W, LULU_PAGE_H, fill=1, stroke=0)
    c.showPage()


# ---------------------------------------------------------------------------
# PDF builders
# ---------------------------------------------------------------------------

def build_interior_pdf(scenes: list, title: str, font_display: str, font_body: str,
                        rule_color) -> None:
    """Build interior PDF: 15 scene pages + blank padding to MIN_PAGES."""
    INTERIOR_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = rl_canvas.Canvas(str(INTERIOR_OUTPUT),
                          pagesize=(LULU_PAGE_W, LULU_PAGE_H))

    page_count = 0

    for scene in scenes:
        n = scene["scene_number"]
        img_path = IMAGES_DIR / f"scene_{n:02d}.png"
        layout = LAYOUTS.get(n, "full_bleed")
        text = scene["text"]

        print(f"  [{n:02d}/{len(scenes)}] Scene {n:02d} — {layout}")

        if layout == "full_bleed":
            draw_lulu_full_bleed(c, img_path, text, font_body, rule_color)
        elif layout == "caption_bottom":
            draw_lulu_caption_bottom(c, img_path, text, font_body, rule_color)
        else:
            draw_lulu_full_bleed(c, img_path, text, font_body, rule_color)

        page_count += 1

    # Pad to Lulu minimum
    while page_count < MIN_PAGES:
        add_blank_page(c)
        page_count += 1

    c.save()
    print(f"  Interior: {page_count} pages total ({page_count - len(scenes)} blank padding pages)")


def build_cover_pdf(cover_path: Path, title: str, author: str,
                    font_display: str, font_body: str) -> None:
    """Build single-page cover PDF."""
    COVER_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = rl_canvas.Canvas(str(COVER_OUTPUT),
                          pagesize=(LULU_PAGE_W, LULU_PAGE_H))
    draw_lulu_cover(c, cover_path, title, author, font_display, font_body)
    c.save()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global RULE_COLOR

    # --- Load style profile for gender-based accent color ---
    style_profile_path = TMP_DIR / "story_style_profile.json"
    story_gender = "girl"
    if style_profile_path.exists():
        try:
            with open(style_profile_path, encoding="utf-8") as f:
                sp_data = json.load(f)
            story_gender = sp_data.get("story_gender", "girl")
        except Exception:
            pass
    rule_color = BOY_RULE_COLOR if story_gender == "boy" else RULE_COLOR

    # --- Validate inputs ---
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run generate_storyboard.py first.")
        sys.exit(1)

    with open(INPUT_FILE, encoding="utf-8") as f:
        storyboard = json.load(f)

    scenes = storyboard.get("scenes", [])
    title = storyboard.get("title", "My Story")
    author = os.getenv("STORYBOOK_AUTHOR", "").strip()

    missing = [
        s["scene_number"]
        for s in scenes
        if not (IMAGES_DIR / f"scene_{s['scene_number']:02d}.png").exists()
    ]
    if missing:
        print(f"ERROR: Missing images for scenes: {missing}")
        print("  Run tools/generate_images.py first.")
        sys.exit(1)

    cover_path = IMAGES_DIR / "cover.png"

    # --- DPI advisory ---
    print()
    print("  DPI NOTE: DALL-E 3 source images are ~175 DPI at 10.25\" print width.")
    print("  Lulu recommends 300 DPI. Output will be accepted but may print slightly soft.")
    print()

    print(f"Loading fonts...")
    custom_fonts = register_fonts()
    font_display, font_body = get_fonts(custom_fonts)
    if custom_fonts:
        print(f"  Fonts loaded: {font_display}, {font_body}")
    else:
        print("  WARNING: Custom fonts unavailable — falling back to built-ins")
    print(f"  Story gender: {story_gender} — "
          f"{'forest green' if story_gender == 'boy' else 'amber-brown'} accent")
    print()

    print(f"Building Lulu interior PDF: \"{title}\" — {len(scenes)} scenes → {MIN_PAGES}-page minimum")
    start = time.time()
    build_interior_pdf(scenes, title, font_display, font_body, rule_color)

    print()
    print("Building Lulu cover PDF...")
    build_cover_pdf(cover_path, title, author, font_display, font_body)

    elapsed = time.time() - start

    interior_kb = INTERIOR_OUTPUT.stat().st_size // 1024
    cover_kb = COVER_OUTPUT.stat().st_size // 1024

    print()
    print(f"  Done in {elapsed:.1f}s")
    print(f"  Interior: {INTERIOR_OUTPUT}  ({interior_kb} KB)")
    print(f"  Cover:    {COVER_OUTPUT}  ({cover_kb} KB)")
    print()
    print(f"  Trim size: 10\" × 8\"  |  With bleed: 10.25\" × 8.25\"  |  Binding: perfect-bound softcover")
    print(f"  POD package ID: {POD_PACKAGE_ID}")
    print()
    print("Ready for Step 9: upload_to_lulu.py")


if __name__ == "__main__":
    main()
