"""
build_pdf.py — Step 5 (final) of the Audio-to-Storybook Pipeline  (v5)

Purpose:  Assemble the cover image, 15 scene illustrations, and narrative text
          into a polished illustrated children's picture book PDF using the
          reportlab Canvas API for pixel-precise layout.

          v5 improvements (template-inspired — Ruben Stom Design minimal style):
            - Spectral SemiBold body font — elegant literary serif for picture books
            - 24pt body text — generous, comfortable for early readers
            - caption_bottom: clean white/cream page background; image with margins;
              thin warm rule separator; text sits directly in open white space (no container)
            - full_bleed: soft white semi-transparent strip at bottom; open text (no rounded rect)
            - Text color: warm dark #3D3325 (not stark black)
            - Overall feel: minimal, premium, editorial — no amber boxes or parchment

Required .env keys: (none required)
    STORYBOOK_AUTHOR — author name displayed on the cover (optional)

Input:  .tmp/storyboard.json       — book title + cover_prompt + 15 scene texts
        .tmp/images/cover.png      — hero cover illustration
        .tmp/images/scene_01.png … — generated scene illustrations
Output: .tmp/storybook.pdf         — final illustrated picture book

Layout types:
    full_bleed    — image fills entire page; decorated amber overlay at bottom 32%
    sidebar_right — image left 74%; amber panel right 26%; text centered in panel
    sidebar_left  — image right 74%; amber panel left 26%; text centered in panel
    caption_bottom— image top 74%; amber strip bottom 26%; text centered in strip

Pipeline complete after this step.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image as PILImage
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.pagesizes import landscape, LETTER
from reportlab.lib.units import inch
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
OUTPUT_FILE = TMP_DIR / "storybook.pdf"
FONTS_DIR = TMP_DIR / "fonts"

PAGE_W, PAGE_H = landscape(LETTER)   # 792 × 612 pts  (11 × 8.5 in)
MARGIN = 0.40 * inch

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
PAGE_BG        = HexColor("#FAFAF7")   # very soft warm white — clean page background
TEXT_COLOR     = HexColor("#3D3325")   # warm dark brown — body text (template style)
RULE_COLOR     = HexColor("#C4956A")   # warm amber-brown thin rule separator (girl/neutral)
BOY_RULE_COLOR = HexColor("#2C5F2E")   # forest green thin rule separator (boy stories)
AMBER          = HexColor("#FFF0CC")   # warm amber (kept for sidebar fallback)
WARM_DARK      = HexColor("#2E1A0E")   # deep chocolate — cover text
GOLD_ACCENT    = HexColor("#D4880A")   # gold for cover rules
OVERLAY_BG     = HexColor("#1A0E05")   # near-black for cover text overlay

# ---------------------------------------------------------------------------
# Layout assignment per scene  (1-indexed, 15 scenes)
# ---------------------------------------------------------------------------
LAYOUTS = {
    1:  "full_bleed",      # ocean opening — wide, immersive
    2:  "caption_bottom",  # Ocean princess + pink horse — character intro
    3:  "full_bleed",      # Snow princess riding waves
    4:  "caption_bottom",  # Forest princess from the woods (was sidebar_left — had blank space bug)
    5:  "full_bleed",      # three princesses galloping together
    6:  "caption_bottom",  # Mountain princess in the cave
    7:  "full_bleed",      # AUDREY APPEARS — hero moment, max visual impact
    8:  "full_bleed",      # all princesses + Audrey together
    9:  "caption_bottom",  # baby horses hatching — discovery moment
    10: "caption_bottom",  # babies with mommies — tender
    11: "full_bleed",      # Rainbow with babies — colorful
    12: "caption_bottom",  # horses nuzzling — emotional
    13: "caption_bottom",  # princesses sharing stories — calm
    14: "full_bleed",      # sunset — dramatic closing
    15: "full_bleed",      # ocean + stars — mid-story climax
    16: "caption_bottom",  # scenes 16-24: extended story (24-scene pipeline)
    17: "full_bleed",
    18: "caption_bottom",
    19: "full_bleed",
    20: "caption_bottom",
    21: "full_bleed",
    22: "caption_bottom",
    23: "caption_bottom",
    24: "full_bleed",      # finale
}

# ---------------------------------------------------------------------------
# Font management
# ---------------------------------------------------------------------------
FONT_URLS = {
    "Chewy-Regular.ttf":      "https://github.com/google/fonts/raw/main/apache/chewy/Chewy-Regular.ttf",
    "Spectral-SemiBold.ttf":  "https://github.com/google/fonts/raw/main/ofl/spectral/Spectral-SemiBold.ttf",
}

FONT_DISPLAY = "Chewy"
FONT_BODY    = "Spectral SemiBold"   # Elegant literary serif — minimal picture book template style


def download_fonts():
    """Download Google Fonts to .tmp/fonts/. Returns {font_name: success}."""
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
    """Register downloaded fonts. Returns True if custom fonts loaded."""
    font_status = download_fonts()
    chewy_ok = font_status.get("Chewy-Regular.ttf", False)
    spectral_ok = font_status.get("Spectral-SemiBold.ttf", False)

    if chewy_ok:
        pdfmetrics.registerFont(TTFont(FONT_DISPLAY, str(FONTS_DIR / "Chewy-Regular.ttf")))
    if spectral_ok:
        pdfmetrics.registerFont(TTFont(FONT_BODY, str(FONTS_DIR / "Spectral-SemiBold.ttf")))

    return chewy_ok and spectral_ok


def get_fonts(custom_loaded):
    """Return (display_font, body_font) — falls back to built-ins."""
    if custom_loaded:
        return FONT_DISPLAY, FONT_BODY
    return "Helvetica-Bold", "Times-Roman"


# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------

def load_image_reader(img_path: Path) -> ImageReader:
    """Open image for reportlab, converting RGBA → RGB if needed."""
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
    """Draw image filling area exactly — scale to cover, crop edges, no stretching ever."""
    ir = load_image_reader(img_path)
    with PILImage.open(img_path) as im:
        orig_w, orig_h = im.size
    # Use MAX scale so both dimensions are fully covered (crop rather than letterbox)
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
    """Word-wrap text to fit within max_width. Returns list of line strings."""
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
    """Draw word-wrapped centered text block. cx/cy is top-center. Returns total height drawn."""
    lines = wrap_text(text, font, size, max_width)
    total_h = len(lines) * leading
    y = cy - size  # first baseline
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
                   font_size: float = 24) -> None:
    """
    Template-inspired open text rendering — no container box, no decorations.
    Text sits directly in open white space (Ruben Stom Design minimal style):
    - Spectral SemiBold at 24pt
    - Warm dark #3D3325 text color
    - Centered, generous 1.65x leading
    - Vertically centered in the zone
    """
    leading = font_size * 1.65
    text_max_w = zone_w - 2 * MARGIN
    lines = wrap_text(text, font_body, font_size, text_max_w)
    total_h = len(lines) * leading
    # Vertically center text within the zone
    text_cy = zone_y + zone_h / 2 + total_h / 2

    draw_text_block(c, text, font_body, font_size, leading,
                    TEXT_COLOR, zone_x + zone_w / 2, text_cy, text_max_w)


def draw_clean_text_box(c: rl_canvas.Canvas, text: str,
                         font_body: str, font_display: str,
                         box_x: float, box_y: float,
                         box_w: float, box_h: float) -> None:
    """Clean white semi-transparent text box — used for sidebar fallback."""
    BOX_BORDER = HexColor("#D8D0C0")

    c.saveState()
    c.setFillColor(white)
    c.setFillAlpha(0.88)
    c.roundRect(box_x, box_y, box_w, box_h, 10, fill=1, stroke=0)
    c.restoreState()

    c.setStrokeColor(BOX_BORDER)
    c.setLineWidth(0.75)
    c.roundRect(box_x, box_y, box_w, box_h, 10, fill=0, stroke=1)

    draw_open_text(c, text, font_body, box_x, box_y, box_w, box_h, font_size=20)


# Alias — draw_sidebar calls this name
draw_decorated_text_box = draw_clean_text_box


# ---------------------------------------------------------------------------
# Page drawing functions
# ---------------------------------------------------------------------------

def draw_cover(c: rl_canvas.Canvas, cover_path: Path, title: str, author: str,
               font_display: str, font_body: str) -> None:
    c.setPageSize(landscape(LETTER))

    if cover_path.exists():
        draw_image_fill_crop(c, cover_path, 0, 0, PAGE_W, PAGE_H)

        # Semi-opaque dark overlay over bottom 30%
        overlay_h = PAGE_H * 0.30
        c.saveState()
        c.setFillColor(OVERLAY_BG)
        c.setFillAlpha(0.75)
        c.rect(0, 0, PAGE_W, overlay_h, fill=1, stroke=0)
        c.restoreState()

        text_cy = overlay_h * 0.76
        title_size = 62
        author_size = 24
        text_color = white
        shadow_color = HexColor("#000000")
    else:
        c.setFillColor(AMBER)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        text_cy = PAGE_H * 0.55
        title_size = 56
        author_size = 22
        text_color = WARM_DARK
        shadow_color = None

    if shadow_color:
        draw_text_block(c, title, font_display, title_size, title_size * 1.15,
                        shadow_color, PAGE_W / 2 + 2.5, text_cy - 2.5, PAGE_W * 0.82)
    draw_text_block(c, title, font_display, title_size, title_size * 1.15,
                    text_color, PAGE_W / 2, text_cy, PAGE_W * 0.82)

    if author:
        author_y = text_cy - title_size * 1.5
        draw_text_block(c, f"by {author}", font_body, author_size, author_size * 1.3,
                        text_color, PAGE_W / 2, author_y, PAGE_W * 0.7)

    if cover_path.exists():
        rule_y = PAGE_H * 0.30 - 3
        c.setStrokeColor(GOLD_ACCENT)
        c.setLineWidth(2.5)
        c.line(MARGIN * 2, rule_y, PAGE_W - MARGIN * 2, rule_y)

    c.showPage()


def draw_full_bleed(c: rl_canvas.Canvas, img_path: Path, text: str,
                    font_body: str, font_display: str) -> None:
    """Image fills entire page; soft white strip at bottom for open text (no rounded rect)."""
    draw_image_fill_crop(c, img_path, 0, 0, PAGE_W, PAGE_H)

    overlay_h = PAGE_H * 0.30

    # Soft white overlay — no decorative box, just a clean reading area
    c.saveState()
    c.setFillColor(white)
    c.setFillAlpha(0.85)
    c.rect(0, 0, PAGE_W, overlay_h, fill=1, stroke=0)
    c.restoreState()

    # Thin warm rule at top edge of overlay
    c.saveState()
    c.setStrokeColor(RULE_COLOR)
    c.setLineWidth(1.0)
    c.setStrokeAlpha(0.5)
    c.line(MARGIN, overlay_h, PAGE_W - MARGIN, overlay_h)
    c.restoreState()

    # Text directly in overlay — open, no container
    draw_open_text(c, text, font_body, 0, 0, PAGE_W, overlay_h, font_size=22)
    c.showPage()


def draw_sidebar(c: rl_canvas.Canvas, img_path: Path, text: str,
                 font_body: str, font_display: str, side: str = "right") -> None:
    """Image fills 74% of page width; decorated amber panel 26% for text."""
    img_frac = 0.74
    panel_frac = 1.0 - img_frac

    if side == "right":
        img_x = 0
        img_w = PAGE_W * img_frac
        panel_x = PAGE_W * img_frac
        panel_w = PAGE_W * panel_frac
        rule_x = PAGE_W * img_frac          # border at 74% mark
    else:
        panel_x = 0
        panel_w = PAGE_W * panel_frac
        img_x = PAGE_W * panel_frac         # FIX: image starts at 26%, not 74%
        img_w = PAGE_W * img_frac
        rule_x = PAGE_W * panel_frac        # FIX: border at 26% mark

    # Amber background for whole page (visible only in panel)
    c.setFillColor(AMBER)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    # Image — fill its column completely, crop to fit, no stretching
    draw_image_fill_crop(c, img_path, img_x, 0, img_w, PAGE_H)

    # Gold vertical separator rule
    c.setStrokeColor(GOLD_ACCENT)
    c.setLineWidth(3)
    c.line(rule_x, MARGIN * 0.5, rule_x, PAGE_H - MARGIN * 0.5)

    # Decorated text box inside panel
    box_pad = MARGIN * 0.5
    box_x = panel_x + box_pad
    box_y = MARGIN
    box_w = panel_w - box_pad * 2
    box_h = PAGE_H - 2 * MARGIN

    draw_decorated_text_box(c, text, font_body, font_display,
                             box_x, box_y, box_w, box_h)
    c.showPage()


def draw_caption_bottom(c: rl_canvas.Canvas, img_path: Path, text: str,
                         font_body: str, font_display: str) -> None:
    """
    Template-inspired: clean white page background; illustration with margins at top;
    thin warm rule separator; text sits directly in open white zone below (no container).
    Modeled on Ruben Stom Design minimal children's book template.
    """
    img_frac = 0.72
    strip_h = PAGE_H * (1.0 - img_frac)
    img_h = PAGE_H * img_frac

    # Clean white/cream page background
    c.setFillColor(PAGE_BG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    # Image with 10pt inset margins on top/left/right (no bottom margin — touches rule)
    img_pad = 10
    draw_image_fill_crop(c, img_path,
                          img_pad, strip_h,
                          PAGE_W - 2 * img_pad, img_h - img_pad)

    # Thin warm horizontal rule at the image/text boundary
    c.setStrokeColor(RULE_COLOR)
    c.setLineWidth(1.0)
    c.line(MARGIN, strip_h, PAGE_W - MARGIN, strip_h)

    # Text directly in open white zone — no container box
    draw_open_text(c, text, font_body, 0, 0, PAGE_W, strip_h, font_size=24)
    c.showPage()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global RULE_COLOR

    # Load story gender from style profile to select accent color
    style_profile_path = TMP_DIR / "story_style_profile.json"
    story_gender = "girl"
    if style_profile_path.exists():
        try:
            with open(style_profile_path, encoding="utf-8") as f:
                sp_data = json.load(f)
            story_gender = sp_data.get("story_gender", "girl")
        except Exception:
            pass
    if story_gender == "boy":
        RULE_COLOR = BOY_RULE_COLOR

    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run tools/generate_storyboard.py first.")
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

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("Loading fonts...")
    custom_fonts = register_fonts()
    font_display, font_body = get_fonts(custom_fonts)
    if custom_fonts:
        print(f"  Fonts loaded: {font_display} (display/cover), {font_body} (body 24pt)")
    else:
        print("  WARNING: Custom fonts unavailable — falling back to built-in fonts")
    print(f"  Story gender: {story_gender} — {'forest green' if story_gender == 'boy' else 'amber-brown'} accent")

    print(f"\nBuilding PDF: \"{title}\" — {len(scenes)} scenes")
    start = time.time()

    c = rl_canvas.Canvas(str(OUTPUT_FILE), pagesize=landscape(LETTER))

    cover_path = IMAGES_DIR / "cover.png"
    print("  [cover] Drawing cover page...")
    draw_cover(c, cover_path, title, author, font_display, font_body)

    for scene in scenes:
        n = scene["scene_number"]
        img_path = IMAGES_DIR / f"scene_{n:02d}.png"
        layout = LAYOUTS.get(n, "full_bleed")
        text = scene["text"]

        print(f"  [{n:02d}/{len(scenes)}] Scene {n:02d} — layout: {layout}")

        if layout == "full_bleed":
            draw_full_bleed(c, img_path, text, font_body, font_display)
        elif layout == "sidebar_right":
            draw_sidebar(c, img_path, text, font_body, font_display, side="right")
        elif layout == "sidebar_left":
            draw_sidebar(c, img_path, text, font_body, font_display, side="left")
        elif layout == "caption_bottom":
            draw_caption_bottom(c, img_path, text, font_body, font_display)
        else:
            draw_full_bleed(c, img_path, text, font_body, font_display)

    c.save()
    elapsed = time.time() - start

    size_kb = OUTPUT_FILE.stat().st_size // 1024
    print()
    print(f"  PDF built in {elapsed:.1f}s — {size_kb} KB")
    print(f"  Output: {OUTPUT_FILE}")
    print()
    print("Pipeline complete. Open .tmp/storybook.pdf to review your book.")


if __name__ == "__main__":
    main()
