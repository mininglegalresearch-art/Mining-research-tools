"""
generate_images.py — Step 4 of the Audio-to-Storybook Pipeline

Purpose:  Generate one PNG illustration per scene.
          Supports two providers selected via IMAGE_PROVIDER in .env:
            - "dalle3" — OpenAI DALL-E 3 API (fast, ~$0.04/image, recommended)
            - "sdxl"   — Local Stable Diffusion XL (free, requires GPU, slow on MPS)
          Checkpoint/resume: skips any scene whose output file already exists.

Required .env keys:
    IMAGE_PROVIDER         — "dalle3" or "sdxl" (default: sdxl)

  DALL-E 3 provider:
    OPENAI_API_KEY         — OpenAI API key (required)
    DALLE_IMAGE_SIZE       — "1024x1024", "1792x1024", "1024x1792" (default: 1024x1024)
    DALLE_IMAGE_QUALITY    — "standard" or "hd" (default: standard, ~$0.04/image)

  SDXL provider:
    SD_MODEL_ID            — HuggingFace model ID (default: stabilityai/stable-diffusion-xl-base-1.0)
    SD_USE_REFINER         — "true" to enable SDXL refiner (default: false)
    SD_NUM_INFERENCE_STEPS — denoising steps (default: 20)

Input:  .tmp/storyboard.json          — storyboard from generate_storyboard.py
Output: .tmp/images/scene_01.png … scene_15.png

Next step: run tools/build_pdf.py
"""

import base64
import io
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image as PILImage

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
TMP_DIR = PROJECT_DIR / ".tmp"
INPUT_FILE = TMP_DIR / "storyboard.json"
OUTPUT_DIR = TMP_DIR / "images"
STYLE_PROFILE_FILE = TMP_DIR / "story_style_profile.json"

# ---------------------------------------------------------------------------
# Style definitions per colour intensity
# These are selected dynamically based on the story's style profile
# ---------------------------------------------------------------------------

_STYLE_CONFIGS = {
    "vibrant_magical": {
        "prefix_colour": (
            "rich vibrant watercolour washes — luminous ocean blues, seafoam greens, warm golden ambers, "
            "soft rose, and glowing magical light; colours are rich and saturated like a magical fairy tale "
            "but still painted in genuine watercolour technique — NOT neon, NOT flat digital. "
            "Magical elements (rainbow creatures, sparkles, water) have vivid watercolour accents. "
            "Think Brian Wildsmith's rich watercolour animal books. "
        ),
        "suffix_colour": (
            "rich vibrant watercolour colouring — luminous blues, seafoam greens, golden ambers, warm rose; "
            "magical painterly quality; vivid foreground characters on softer painted backgrounds; "
        ),
    },
    "pastel_gentle": {
        "prefix_colour": (
            "very soft pastel watercolour washes — pale lavender, soft peach, sky blue, mint green, "
            "gentle cream — delicate and tender, quiet and calm. "
        ),
        "suffix_colour": (
            "soft pastel watercolour colouring — pale lavender, soft peach, gentle sky blue, mint; "
            "very gentle and tender; "
        ),
    },
    "muted_earthy": {
        "prefix_colour": (
            "soft muted naturalistic colouring — dusty sage greens, warm wheat yellows, pale rose, "
            "soft sky blue, warm ochre — earthy and gentle. "
        ),
        "suffix_colour": (
            "soft muted earthy colouring — dusty sage green, warm wheat yellow, pale rose, warm ochre; "
            "gentle natural light; "
        ),
    },
    "bold_playful": {
        "prefix_colour": (
            "bright bold watercolour washes — vivid primary colours (red, yellow, blue) with energetic "
            "playful contrasts; vibrant and fun, still in a genuine watercolour painted style. "
        ),
        "suffix_colour": (
            "bright bold watercolour colouring — vivid primary colours, energetic and playful; "
        ),
    },
}

_ANTI_ANIME_BLOCK = (
    "STRICTLY NO ANIME OR MANGA: no oversized flat graphic eyes (anime eyes are unnaturally large "
    "perfectly-round irises with flat stark white highlight shapes — avoid completely), "
    "no sharp angular faces, no cel-shading, no bold black outlines, no flat colour blocks, "
    "no speed lines. Characters must look like real children and real animals painted in watercolour. "
)

_SUFFIX_CLOSE = (
    "light expressive pencil or fine-ink outlines, not heavy or bold; "
    "characters with naturally proportioned real faces — no anime: "
    "no oversized flat graphic eyes, no sharp angular features, no cel-shading, no flat colour fills; "
    "no photorealism, no anime, no manga, no 3D CGI, no text, no words, no letters, "
    "no color swatches, no borders"
)


def _load_style_config() -> dict:
    """Load the story style profile and return the matching style config dict."""
    intensity = "vibrant_magical"  # default for magical stories
    colour_guidance = ""
    story_gender = "girl"  # default
    if STYLE_PROFILE_FILE.exists():
        try:
            with open(STYLE_PROFILE_FILE, encoding="utf-8") as f:
                sp = json.load(f)
            intensity = sp.get("colour_intensity", "vibrant_magical")
            colour_guidance = sp.get("colour_guidance", "")
            story_gender = sp.get("story_gender", "girl")
        except Exception:
            pass
    cfg = _STYLE_CONFIGS.get(intensity, _STYLE_CONFIGS["vibrant_magical"])
    return {"intensity": intensity, "colour_guidance": colour_guidance,
            "story_gender": story_gender, **cfg}


def build_style_prompts() -> tuple:
    """
    Build STYLE_PREFIX and STYLE_SUFFIX dynamically from the story style profile.
    Gender-aware: boy stories use bold expressive adventure style;
    girl/neutral stories use soft naturalistic watercolour style.
    Returns (prefix, suffix).
    """
    cfg = _load_style_config()
    is_boy = cfg.get("story_gender") == "boy"
    colour_hint = (f"Story-specific colour note: {cfg['colour_guidance']} " if cfg["colour_guidance"] else "")

    if is_boy:
        prefix = (
            "MANDATORY ART STYLE — BOLD EXPRESSIVE WATERCOLOUR PICTURE BOOK ILLUSTRATION: "
            + cfg["prefix_colour"]
            + colour_hint
            + "Bright natural daylight or dramatic adventure atmospheric light. "
            "Confident expressive ink outlines — bold and energetic, not heavy or decorative. "
            "DYNAMIC COMPOSITIONS: characters in action or mid-movement, strong angles. "
            "Style reference: classic adventure picture book illustration. "
            + _ANTI_ANIME_BLOCK
            + "NOT photorealistic. NOT 3D CGI. NOT flat digital design. "
            "SCENE: "
        )
        suffix = (
            ". REQUIRED ART STYLE (identical across all scenes): "
            "bold expressive watercolour picture book illustration with visible energetic brushwork "
            "and natural pigment texture; "
            + cfg["suffix_colour"]
            + _SUFFIX_CLOSE
        )
    else:
        prefix = (
            "MANDATORY ART STYLE — WATERCOLOUR PICTURE BOOK ILLUSTRATION: "
            + cfg["prefix_colour"]
            + colour_hint
            + "Gentle diffuse natural light. Light expressive fine-ink or pencil outlines, not heavy or bold. "
            "Style reference: classic watercolour picture book illustration. "
            + _ANTI_ANIME_BLOCK
            + "NOT photorealistic. NOT 3D CGI. NOT flat digital design. "
            "SCENE: "
        )
        suffix = (
            ". REQUIRED ART STYLE (identical across all scenes): "
            "watercolour picture book illustration with visible paper texture and natural pigment blooms; "
            + cfg["suffix_colour"]
            + _SUFFIX_CLOSE
        )

    return prefix, suffix


# Build prompts at import time (so they can be imported by check_character_consistency.py)
STYLE_PREFIX, STYLE_SUFFIX = build_style_prompts()

NEGATIVE_PROMPT = (
    "photorealistic, realistic, 3D render, CGI, "
    "anime, manga, anime style, anime eyes, large flat graphic eyes, oversized irises, "
    "stark white eye highlights, cel-shading, bold black outlines, flat colour blocks, "
    "sharp angular features, pointed chin, speed lines, "
    "cartoon network style, bright neon colors, oversaturated, vivid jewel tones, glowing, "
    "dark, scary, frightening, text, words, letters, numbers, watermark, "
    "blurry, low quality, deformed, ugly, nsfw, violence, adult content, "
    "flat digital design, color swatches"
)

# DALL-E 3 rate limit: 5 images/min on standard tier → 13s between requests
DALLE_DELAY_SECONDS = 13

# Vision consistency check — max regeneration attempts per image
VISION_MAX_RETRIES = 2

VISION_CHECK_PROMPT = """\
You are a quality-control reviewer for a children's picture book illustration.
Examine this image and answer the following checklist. Reply with ONLY "PASS" or "FAIL: <one-line reason>".

CHECKLIST:
1. WATERCOLOUR STYLE — Is this a genuine watercolour illustration with loose washes, \
visible paper texture, and a painted organic feel? \
(Fail if: photorealistic, 3D CGI render, or flat digital graphic design.)
2. NO ANIME — Are all characters free of anime/manga features? \
Anime features to FAIL on: oversized perfectly-round flat graphic eyes with stark white highlights, \
sharp angular jawlines or pointed chins, bold black cel-shading, hard flat colour-block fills, \
speed lines, or exaggerated anime expressions. Characters should look like real children or real \
animals painted in watercolour.
3. NO COLOUR SWATCHES — Does the illustration contain ZERO colour swatches, colour chips, \
colour bars, colour strips, or any sample squares/rectangles of colour? \
(Fail immediately if ANY colour swatch, sample strip, or colour reference chart appears anywhere.)
4. AUDREY — If a young girl appears, does she have golden-yellow hair and a sky-blue dress, \
with naturally proportioned real-child features (not anime-style)?
5. MOOD — Is the overall mood warm, magical, and wonder-filled (not dark or frightening)?

If ALL visible elements match their criteria, reply: PASS
If ANY major deviation exists, reply: FAIL: <brief description of the problem>
"""


# ---------------------------------------------------------------------------
# DALL-E 3 provider
# ---------------------------------------------------------------------------

def _dalle3_generate_one(client, prompt: str, size: str, quality: str, output_path: Path, label: str) -> bool:
    """Generate one image via DALL-E 3 and save to output_path. Returns True on success."""
    import openai
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
            response_format="b64_json",
        )
        image_bytes = base64.b64decode(response.data[0].b64_json)
        image = PILImage.open(io.BytesIO(image_bytes))
        image.save(output_path)
        return True
    except Exception as e:
        print(f"    WARNING: {label} failed: {e}")
        return False


def check_image_consistency(client, img_path: Path, label: str) -> tuple:
    """Use GPT-4o Vision to verify image matches required style. Returns (passed, feedback)."""
    try:
        with open(img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_CHECK_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "low"},
                        },
                    ],
                }
            ],
        )
        verdict = response.choices[0].message.content.strip()
        passed = verdict.upper().startswith("PASS")
        return passed, verdict
    except Exception as e:
        # If vision check fails (network, quota, etc.) — pass through so generation continues
        print(f"    WARNING: Vision check for {label} failed ({e}) — skipping check")
        return True, "SKIP (vision check error)"


def _dalle3_generate_with_check(
    client, prompt: str, size: str, quality: str,
    output_path: Path, label: str, skip_vision: bool = False
) -> bool:
    """Generate one DALL-E 3 image with GPT-4o Vision consistency check + auto-retry."""
    for attempt in range(1, VISION_MAX_RETRIES + 2):  # +2: 1 initial + VISION_MAX_RETRIES
        if attempt > 1:
            print(f"    Vision retry {attempt - 1}/{VISION_MAX_RETRIES} for {label}...")
            time.sleep(DALLE_DELAY_SECONDS)

        ok = _dalle3_generate_one(client, prompt, size, quality, output_path, label)
        if not ok:
            return False

        if skip_vision:
            return True

        passed, verdict = check_image_consistency(client, output_path, label)
        if passed:
            print(f"    Vision check: PASS ({label})")
            return True
        else:
            print(f"    Vision check: {verdict}")
            if attempt < VISION_MAX_RETRIES + 1:
                output_path.unlink(missing_ok=True)
            else:
                print(f"    WARNING: {label} did not pass vision check after {VISION_MAX_RETRIES} retries — keeping last attempt")
                return True  # Keep the last attempt rather than leaving a gap

    return True


def generate_dalle3(scenes: list, api_key: str, storyboard=None) -> None:
    import openai

    size = os.getenv("DALLE_IMAGE_SIZE", "1024x1024").strip()
    quality = os.getenv("DALLE_IMAGE_QUALITY", "standard").strip()

    client = openai.OpenAI(api_key=api_key)

    print(f"Provider: DALL-E 3 | size: {size} | quality: {quality}")
    print(f"Output:   {OUTPUT_DIR}")
    print()

    # --- Cover image ---
    cover_path = OUTPUT_DIR / "cover.png"
    if not cover_path.exists():
        cover_prompt = (storyboard or {}).get("cover_prompt", "").strip()
        if cover_prompt:
            print("  [cover] Generating cover image...")
            cover_start = time.time()
            ok = _dalle3_generate_with_check(client, STYLE_PREFIX + cover_prompt + STYLE_SUFFIX, size, quality, cover_path, "Cover")
            if ok:
                print(f"  [cover] Done ({time.time() - cover_start:.1f}s) → cover.png")
                time.sleep(DALLE_DELAY_SECONDS)
        else:
            print("  [cover] No cover_prompt in storyboard — skipping cover image.")
    else:
        print("  [cover] cover.png already exists — skipping.")

    done_scenes = {p.stem for p in OUTPUT_DIR.glob("scene_*.png")}
    to_generate = [s for s in scenes if f"scene_{s['scene_number']:02d}" not in done_scenes]

    if done_scenes:
        print(f"  Checkpoint: {len(done_scenes)} already generated, {len(to_generate)} remaining.")

    if not to_generate:
        print(f"  All {len(scenes)} scenes already generated. Nothing to do.")
        print()
        print("Next step: run tools/build_pdf.py")
        return

    generated = 0
    total_start = time.time()

    for i, scene in enumerate(to_generate, 1):
        n = scene["scene_number"]
        output_path = OUTPUT_DIR / f"scene_{n:02d}.png"
        prompt = STYLE_PREFIX + scene["image_prompt"] + STYLE_SUFFIX

        print(f"  [{i}/{len(to_generate)}] Scene {n:02d} — generating...")
        img_start = time.time()

        ok = _dalle3_generate_with_check(client, prompt, size, quality, output_path, f"Scene {n:02d}")
        if not ok:
            print(f"    ERROR: Scene {n:02d} failed to generate — will report at end.")
            continue

        elapsed = time.time() - img_start
        generated += 1
        print(f"  [{i}/{len(to_generate)}] Scene {n:02d} — done ({elapsed:.1f}s) → {output_path.name}")

        # Respect rate limit — pause between requests (skip after last image)
        if i < len(to_generate):
            time.sleep(DALLE_DELAY_SECONDS)

    total_elapsed = time.time() - total_start
    skipped = len(scenes) - len(to_generate)
    print()
    print(f"  Generated: {generated} | Skipped (checkpoint): {skipped} | Total: {total_elapsed:.1f}s")
    print(f"  Images saved to: {OUTPUT_DIR}")

    # Hard failure if any scene image is missing — prevents downstream steps from silently failing
    missing = [
        s["scene_number"] for s in scenes
        if not (OUTPUT_DIR / f"scene_{s['scene_number']:02d}.png").exists()
    ]
    if missing:
        print()
        print(f"ERROR: {len(missing)} scene image(s) were not generated: {missing}")
        print("  DALL-E 3 likely refused the prompt (content policy or API error).")
        print("  Re-run generate_images.py to retry only the missing scenes.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# SDXL provider
# ---------------------------------------------------------------------------

def generate_sdxl(scenes: list) -> None:
    import torch
    from diffusers import StableDiffusionXLPipeline

    DEFAULT_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
    model_id = os.getenv("SD_MODEL_ID", DEFAULT_MODEL_ID).strip()
    use_refiner = os.getenv("SD_USE_REFINER", "false").lower() == "true"
    num_steps = int(os.getenv("SD_NUM_INFERENCE_STEPS", "20"))

    def get_device() -> str:
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available() and torch.backends.mps.is_built():
            return "mps"
        return "cpu"

    device = get_device()
    dtype = torch.float16 if device in ("cuda", "mps") else torch.float32

    if device == "cpu":
        print("WARNING: Running on CPU — image generation will be very slow (~5–20 min per image).")

    print(f"Provider: SDXL | device: {device} | steps: {num_steps}")
    print(f"Model:    {model_id}")
    print(f"Output:   {OUTPUT_DIR}")
    print()

    done_scenes = {p.stem for p in OUTPUT_DIR.glob("scene_*.png")}
    to_generate = [s for s in scenes if f"scene_{s['scene_number']:02d}" not in done_scenes]

    if done_scenes:
        print(f"  Checkpoint: {len(done_scenes)} already generated, {len(to_generate)} remaining.")

    if not to_generate:
        print(f"  All {len(scenes)} scenes already generated. Nothing to do.")
        print()
        print("Next step: run tools/build_pdf.py")
        return

    print("  Loading pipeline (first run downloads ~6.5 GB from HuggingFace)...")
    load_start = time.time()

    pipe = StableDiffusionXLPipeline.from_pretrained(
        model_id,
        torch_dtype=dtype,
        use_safetensors=True,
        variant="fp16" if dtype == torch.float16 else None,
    ).to(device)
    pipe.enable_attention_slicing()
    pipe.vae.enable_tiling()
    pipe.vae.enable_slicing()

    print(f"  Pipeline loaded in {time.time() - load_start:.1f}s")
    print()

    refiner = None
    if use_refiner:
        print("  Loading SDXL refiner (~6 GB download)...")
        from diffusers import StableDiffusionXLImg2ImgPipeline
        refiner = StableDiffusionXLImg2ImgPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-refiner-1.0",
            torch_dtype=dtype,
            use_safetensors=True,
            variant="fp16" if dtype == torch.float16 else None,
        ).to(device)
        print("  Refiner loaded.")
        print()

    generated = 0
    total_start = time.time()

    for i, scene in enumerate(to_generate, 1):
        n = scene["scene_number"]
        output_path = OUTPUT_DIR / f"scene_{n:02d}.png"
        prompt = STYLE_PREFIX + scene["image_prompt"] + STYLE_SUFFIX

        print(f"  [{i}/{len(to_generate)}] Scene {n:02d} — generating...")
        img_start = time.time()

        result = pipe(
            prompt=prompt,
            negative_prompt=NEGATIVE_PROMPT,
            num_inference_steps=num_steps,
            height=512,
            width=768,
        )
        image = result.images[0]

        if refiner is not None:
            image = refiner(prompt=prompt, image=image).images[0]

        image.save(output_path)
        elapsed = time.time() - img_start
        generated += 1
        print(f"  [{i}/{len(to_generate)}] Scene {n:02d} — done ({elapsed:.1f}s) → {output_path.name}")

        if device == "mps":
            torch.mps.empty_cache()

    del pipe
    if refiner:
        del refiner
    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "mps":
        torch.mps.empty_cache()

    total_elapsed = time.time() - total_start
    skipped = len(scenes) - len(to_generate)
    print()
    print(f"  Generated: {generated} | Skipped (checkpoint): {skipped} | Total: {total_elapsed:.1f}s")
    print(f"  Images saved to: {OUTPUT_DIR}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run tools/generate_storyboard.py first.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(INPUT_FILE, encoding="utf-8") as f:
        storyboard = json.load(f)

    scenes = storyboard.get("scenes", [])
    if not scenes:
        print("ERROR: storyboard.json has no scenes.")
        sys.exit(1)

    provider = os.getenv("IMAGE_PROVIDER", "sdxl").strip().lower()

    if provider == "dalle3":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            print("ERROR: OPENAI_API_KEY not set. Required for IMAGE_PROVIDER=dalle3.")
            sys.exit(1)
        generate_dalle3(scenes, api_key, storyboard=storyboard)
    elif provider == "sdxl":
        generate_sdxl(scenes)
    else:
        print(f"ERROR: Unknown IMAGE_PROVIDER='{provider}'. Use 'dalle3' or 'sdxl'.")
        sys.exit(1)

    print()
    print("Next step: run tools/build_pdf.py")


if __name__ == "__main__":
    main()
