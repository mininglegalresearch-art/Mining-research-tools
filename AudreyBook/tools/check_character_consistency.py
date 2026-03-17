"""
check_character_consistency.py — Step 4b of the Audio-to-Storybook Pipeline

Purpose:  After generate_images.py, enforce visual consistency across all 15 scene
          illustrations by:

          1. EXTRACT — For each named character, find their first-appearing scene and
             use GPT-4o Vision to extract a precise "canonical appearance" description
             from the actual generated image (what DALL-E 3 produced, not what we asked for).

          2. CHECK — For every subsequent scene featuring that character, use GPT-4o
             Vision to directly compare the canonical scene image against the scene image
             (image-to-image — no text description as intermediary). Falls back to text-
             based check if canonical image is unavailable.

          3. REGENERATE — For scenes where a character is visually inconsistent,
             delete the image and regenerate with the canonical appearance locked into
             the DALL-E 3 prompt. Up to REGEN_MAX_RETRIES attempts per scene.

          4. REGISTRY — Save .tmp/character_registry.json with canonical descriptions
             for reference.

Required .env keys:
    OPENAI_API_KEY   — OpenAI API key (DALL-E 3 + GPT-4o Vision)
    IMAGE_PROVIDER   — must be "dalle3" for regeneration (SDXL not supported here)

Input:  .tmp/storyboard.json      — 15 scene storyboard (text + image_prompts)
        .tmp/images/scene_*.png   — generated scene images

Output: .tmp/character_registry.json   — canonical appearance per character
        .tmp/images/                   — inconsistent scenes are replaced in-place

Next step: run tools/build_pdf.py
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
TMP_DIR = PROJECT_DIR / ".tmp"
STORYBOARD_FILE = TMP_DIR / "storyboard.json"
IMAGES_DIR = TMP_DIR / "images"
REGISTRY_FILE = TMP_DIR / "character_registry.json"
STYLE_PROFILE_FILE = TMP_DIR / "story_style_profile.json"

# Import style constants from generate_images so prompts stay in sync
sys.path.insert(0, str(SCRIPT_DIR))
from generate_images import (
    STYLE_PREFIX, STYLE_SUFFIX, DALLE_DELAY_SECONDS,
    _dalle3_generate_one
)

REGEN_MAX_RETRIES = 1      # max regeneration attempts per inconsistent scene
VISION_DELAY = 2           # seconds between Vision API calls (avoid rate limit)

# ---------------------------------------------------------------------------
# Character definitions — loaded dynamically from style profile
# Each entry has:
#   hint     — how to find them in an image (for Vision prompt)
#   triggers — substrings to look for in scene.text to detect presence
# ---------------------------------------------------------------------------

_AUDREY_STORY_CHARACTERS = {
    "Ariel": {
        "hint": "the young woman with auburn-red hair in a sea-green dress",
        "triggers": ["ariel"],
    },
    "Elsa": {
        "hint": "the young woman with pale silver-blonde hair in a soft ice-blue dress",
        "triggers": ["elsa"],
    },
    "Belle": {
        "hint": "the young woman with chestnut-brown hair in a golden-yellow dress",
        "triggers": ["belle"],
    },
    "Anna": {
        "hint": "the young woman with auburn braids in a teal-and-rose dress",
        "triggers": ["anna"],
    },
    "Audrey": {
        "hint": "the small 4-year-old girl with shoulder-length golden-yellow hair in a sky-blue dress",
        "triggers": ["audrey"],
    },
    "Rainbow": {
        "hint": (
            "the large horse with a softly rainbow-coloured watercolour coat — "
            "gentle bands of rose-red, orange, gold, sage green, dusty blue, and violet"
        ),
        "triggers": ["rainbow"],
    },
}


def load_characters_to_track() -> dict:
    """
    Load character definitions from the style profile (main_characters field),
    or fall back to the Audrey-story hardcoded defaults.
    Returns {name: {"hint": str, "triggers": [str]}} dict.
    """
    if STYLE_PROFILE_FILE.exists():
        try:
            with open(STYLE_PROFILE_FILE, encoding="utf-8") as f:
                sp = json.load(f)
            chars = sp.get("main_characters", [])
            if chars:
                result = {}
                for c in chars:
                    name = c.get("name", "").strip()
                    if not name:
                        continue
                    result[name] = {
                        "hint": (
                            f"the character named {name} — "
                            "look for any character who is likely the one this story is about"
                        ),
                        "triggers": [name.lower()],
                    }
                if result:
                    return result
        except Exception:
            pass
    # Fallback: Audrey-story hardcoded defaults
    return _AUDREY_STORY_CHARACTERS


def find_first_scene(character_name: str, scenes: list) -> int:
    """Find the first scene number where character_name appears in scene text."""
    name_lower = character_name.lower()
    for scene in scenes:
        if name_lower in scene.get("text", "").lower():
            return scene["scene_number"]
    return 1  # default to scene 1 if not found in any scene text

# ---------------------------------------------------------------------------
# Vision prompts
# ---------------------------------------------------------------------------

EXTRACT_PROMPT = """\
You are a character appearance analyst for a children's picture book.

In this illustration, find the character described as: {hint}

If this character IS visible, describe their exact visual appearance in 3-5 precise sentences:
- Hair: color, length, texture (e.g., "shoulder-length wavy auburn-red hair")
- Eyes: color, size relative to face, expression
- Face: shape, skin tone, key features
- Outfit: exact colors and style elements
- Body/size: proportions, scale relative to the scene

Be specific and factual — this description anchors consistency across all 15 scenes.
Reply with ONLY the appearance description. No preamble, no "The character has..." intro — \
start directly with the hair description.

If this character is NOT visible in the illustration, reply exactly with the single word: NOT_VISIBLE
"""

IMG2IMG_CONSISTENCY_PROMPT = """\
You are a character consistency reviewer for a children's picture book.

IMAGE 1 is the canonical reference — the first approved appearance of this character.
IMAGE 2 is a later scene illustration to check.

Find the character described as: {hint}

Compare the character's appearance between the two images. Focus on:
- Hair: color, length, texture, style
- Eyes: color, size relative to face
- Outfit: exact colors, garment style, key details
- Body proportions: size relative to scene, build

Reply with ONLY one of these three responses:
- CONSISTENT   (the same character is present in both images and their appearance matches well)
- INCONSISTENT: [one-line description of the specific visual differences seen]
- NOT_VISIBLE  (this character does not appear clearly in Image 2)

Do not explain your reasoning. Just reply with the single status line.
"""


# ---------------------------------------------------------------------------
# Vision helpers
# ---------------------------------------------------------------------------

def encode_image(img_path: Path) -> str:
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def vision_call(client, img_path: Path, prompt: str, max_tokens: int = 200) -> str:
    """Send one GPT-4o Vision request. Returns response text."""
    img_b64 = encode_image(img_path)
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}",
                            "detail": "low",
                        },
                    },
                ],
            }
        ],
    )
    return response.choices[0].message.content.strip()


def extract_canonical(client, img_path: Path, char_name: str, hint: str):
    """
    Extract the canonical appearance of a character from their first-scene image.
    Returns description string, or None if NOT_VISIBLE.
    """
    prompt = EXTRACT_PROMPT.format(hint=hint)
    try:
        result = vision_call(client, img_path, prompt, max_tokens=250)
        if result.strip().upper() == "NOT_VISIBLE":
            return None
        return result.strip()
    except Exception as e:
        print(f"    WARNING: Canonical extraction failed for {char_name}: {e}")
        return None


def vision_call_two_images(client, img1_path: Path, img2_path: Path,
                            prompt: str, max_tokens: int = 200) -> str:
    """
    Send two images to GPT-4o Vision in one request.
    img1_path = canonical reference image (Image 1).
    img2_path = scene image to check (Image 2).
    Returns response text.
    """
    img1_b64 = encode_image(img1_path)
    img2_b64 = encode_image(img2_path)
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=max_tokens,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "IMAGE 1 (canonical reference):"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img1_b64}", "detail": "low"},
                },
                {"type": "text", "text": "IMAGE 2 (scene to check):"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img2_b64}", "detail": "low"},
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return response.choices[0].message.content.strip()


def check_consistency_img2img(client, canonical_img_path: Path, scene_img_path: Path,
                               char_name: str, hint: str) -> tuple[str, str]:
    """
    Check a character's consistency by direct image-to-image comparison.
    Shows canonical reference image alongside scene image — no text description as intermediary.
    Returns (status, detail) where status is "CONSISTENT", "INCONSISTENT", or "NOT_VISIBLE".
    """
    prompt = IMG2IMG_CONSISTENCY_PROMPT.format(hint=hint)
    try:
        result = vision_call_two_images(client, canonical_img_path, scene_img_path,
                                        prompt, max_tokens=120).strip()
        if result.upper().startswith("CONSISTENT"):
            return "CONSISTENT", ""
        elif result.upper().startswith("NOT_VISIBLE"):
            return "NOT_VISIBLE", ""
        elif result.upper().startswith("INCONSISTENT"):
            detail = result[len("INCONSISTENT"):].lstrip(": ").strip()
            return "INCONSISTENT", detail
        else:
            return "CONSISTENT", f"(ambiguous img2img: {result[:60]})"
    except Exception as e:
        print(f"    WARNING: img2img check failed for {char_name}: {e}")
        return "CONSISTENT", "(img2img error — skipping)"


def check_consistency(client, img_path: Path, char_name: str, hint: str, canonical: str) -> tuple[str, str]:
    """
    Fallback: check a character's consistency using text canonical description.
    Used when the canonical image is unavailable (e.g. .tmp/ was cleaned between runs).
    Returns (status, detail) where status is "CONSISTENT", "INCONSISTENT", or "NOT_VISIBLE".
    """
    prompt = (
        f"You are a character consistency reviewer for a children's picture book.\n\n"
        f"The character ({hint}) should look like this:\n"
        f"CANONICAL APPEARANCE: {canonical}\n\n"
        f"Look at this illustration. Check if the character's appearance is visually "
        f"consistent with the canonical description. Focus on hair color/style, eye color, "
        f"outfit colors, and body proportions.\n\n"
        f"Reply with ONLY one of:\n"
        f"- CONSISTENT\n"
        f"- INCONSISTENT: [specific visual differences]\n"
        f"- NOT_VISIBLE"
    )
    try:
        result = vision_call(client, img_path, prompt, max_tokens=120)
        result = result.strip()
        if result.upper().startswith("CONSISTENT"):
            return "CONSISTENT", ""
        elif result.upper().startswith("NOT_VISIBLE"):
            return "NOT_VISIBLE", ""
        elif result.upper().startswith("INCONSISTENT"):
            detail = result[len("INCONSISTENT"):].lstrip(": ").strip()
            return "INCONSISTENT", detail
        else:
            # Ambiguous — treat as consistent to avoid unnecessary regeneration
            return "CONSISTENT", f"(ambiguous response: {result[:60]})"
    except Exception as e:
        print(f"    WARNING: Consistency check failed for {char_name}: {e}")
        return "CONSISTENT", "(vision check error — skipping)"


# ---------------------------------------------------------------------------
# Scene helpers
# ---------------------------------------------------------------------------

def scenes_containing(scenes: list, char_name: str, char_info: dict) -> list[dict]:
    """Return scenes whose text mentions the character (case-insensitive)."""
    triggers = char_info["triggers"]
    result = []
    for s in scenes:
        text_lower = s["text"].lower()
        if any(t in text_lower for t in triggers):
            result.append(s)
    return result


def regenerate_scene(client, scene: dict, canonical_dict: dict,
                     img_path: Path, size: str, quality: str,
                     inconsistent_chars: list[str]) -> bool:
    """
    Regenerate one scene image with canonical appearance descriptions locked in.
    Injects a CHARACTER LOCK prefix before the scene's original image_prompt.
    Returns True on success.
    """
    # Build the character appearance lock
    lock_parts = []
    for char_name in inconsistent_chars:
        if char_name in canonical_dict:
            lock_parts.append(
                f"{char_name} MUST appear exactly as: {canonical_dict[char_name]}"
            )

    if not lock_parts:
        return False

    lock_str = (
        "CHARACTER APPEARANCE LOCK — maintain these exact appearances: "
        + "; ".join(lock_parts)
        + ". "
    )

    original_prompt = scene["image_prompt"]
    enhanced_prompt = STYLE_PREFIX + lock_str + original_prompt + STYLE_SUFFIX

    # Delete existing image before regenerating
    img_path.unlink(missing_ok=True)
    time.sleep(DALLE_DELAY_SECONDS)

    ok = _dalle3_generate_one(client, enhanced_prompt, size, quality, img_path,
                              f"Scene {scene['scene_number']:02d} (consistency regen)")
    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        sys.exit(1)

    provider = os.getenv("IMAGE_PROVIDER", "sdxl").strip().lower()
    if provider != "dalle3":
        print(f"  NOTE: IMAGE_PROVIDER={provider}. Character consistency regeneration requires")
        print("  dalle3. Running check-only mode (no regeneration).")
        regen_enabled = False
    else:
        regen_enabled = True

    if not STORYBOARD_FILE.exists():
        print(f"ERROR: {STORYBOARD_FILE} not found. Run generate_storyboard.py first.")
        sys.exit(1)

    if not IMAGES_DIR.exists():
        print(f"ERROR: {IMAGES_DIR} not found. Run generate_images.py first.")
        sys.exit(1)

    with open(STORYBOARD_FILE, encoding="utf-8") as f:
        storyboard = json.load(f)

    scenes = storyboard.get("scenes", [])
    if not scenes:
        print("ERROR: storyboard.json has no scenes.")
        sys.exit(1)

    import openai
    client = openai.OpenAI(api_key=api_key)

    size = os.getenv("DALLE_IMAGE_SIZE", "1792x1024").strip()
    quality = os.getenv("DALLE_IMAGE_QUALITY", "hd").strip()

    characters = load_characters_to_track()

    print("=" * 60)
    print("  Character Consistency Check")
    print(f"  Tracking {len(characters)} characters across {len(scenes)} scenes")
    print("=" * 60)
    print()

    # ------------------------------------------------------------------
    # Phase 1: Extract canonical appearances
    # ------------------------------------------------------------------
    print("Phase 1: Building character registry from first-appearance scenes...")
    print()

    canonical_dict: dict[str, str] = {}
    canonical_img_paths: dict[str, Path] = {}   # in-memory only — NOT persisted to JSON

    # Load existing registry if present (allows partial resume)
    if REGISTRY_FILE.exists():
        with open(REGISTRY_FILE, encoding="utf-8") as f:
            canonical_dict = json.load(f)
        print(f"  Loaded existing registry: {list(canonical_dict.keys())}")
        # Rebuild canonical_img_paths from IMAGES_DIR for pre-existing registry entries
        for existing_name in list(canonical_dict.keys()):
            existing_info = characters.get(
                existing_name, {"hint": existing_name, "triggers": [existing_name.lower()]}
            )
            existing_scenes = scenes_containing(scenes, existing_name, existing_info)
            if existing_scenes:
                first_n = existing_scenes[0]["scene_number"]
                candidate = IMAGES_DIR / f"scene_{first_n:02d}.png"
                if candidate.exists():
                    canonical_img_paths[existing_name] = candidate
        print()

    for char_name, char_info in characters.items():
        if char_name in canonical_dict:
            print(f"  [{char_name}] Canonical already in registry — skipping extraction.")
            continue

        char_scenes = scenes_containing(scenes, char_name, char_info)
        if not char_scenes:
            print(f"  [{char_name}] Not mentioned in any scene — skipping.")
            continue

        first_scene = char_scenes[0]
        n = first_scene["scene_number"]
        img_path = IMAGES_DIR / f"scene_{n:02d}.png"

        if not img_path.exists():
            print(f"  [{char_name}] Scene {n:02d} image missing — skipping extraction.")
            continue

        print(f"  [{char_name}] Extracting canonical from Scene {n:02d}...")
        canonical = extract_canonical(client, img_path, char_name, char_info["hint"])

        if canonical:
            canonical_dict[char_name] = canonical
            canonical_img_paths[char_name] = img_path   # save canonical image path
            print(f"    → {canonical[:100]}{'...' if len(canonical) > 100 else ''}")
        else:
            print(f"    → NOT_VISIBLE in Scene {n:02d} — trying next scene...")
            # Try subsequent scenes if character not visible in first
            found = False
            for alt_scene in char_scenes[1:]:
                alt_n = alt_scene["scene_number"]
                alt_img = IMAGES_DIR / f"scene_{alt_n:02d}.png"
                if not alt_img.exists():
                    continue
                print(f"    → Trying Scene {alt_n:02d}...")
                canonical = extract_canonical(client, alt_img, char_name, char_info["hint"])
                if canonical:
                    canonical_dict[char_name] = canonical
                    canonical_img_paths[char_name] = alt_img   # save canonical image path
                    print(f"    → Found in Scene {alt_n:02d}: {canonical[:100]}{'...' if len(canonical) > 100 else ''}")
                    found = True
                    break
                time.sleep(VISION_DELAY)
            if not found:
                print(f"    → Could not extract canonical for {char_name} — skipping consistency check.")

        time.sleep(VISION_DELAY)

    # Save registry
    REGISTRY_FILE.write_text(json.dumps(canonical_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"  Registry saved: {list(canonical_dict.keys())}")
    print(f"  Output: {REGISTRY_FILE}")
    print()

    if not canonical_dict:
        print("  No canonical appearances extracted. Nothing to check.")
        print()
        print("Next step: run tools/build_pdf.py")
        return

    # ------------------------------------------------------------------
    # Phase 2: Check consistency across all scenes
    # ------------------------------------------------------------------
    print("Phase 2: Checking character consistency across all scenes...")
    print()

    # scenes_to_regen: {scene_number: [char_name, ...]}
    scenes_to_regen: dict[int, list[str]] = {}
    total_checks = 0
    total_inconsistent = 0

    for char_name, canonical in canonical_dict.items():
        char_info = characters.get(char_name, {"hint": char_name, "triggers": [char_name.lower()]})
        char_scenes = scenes_containing(scenes, char_name, char_info)
        if len(char_scenes) <= 1:
            continue  # only one scene — nothing to compare

        # Skip the first scene (it IS the canonical reference)
        check_scenes = char_scenes[1:]
        print(f"  [{char_name}] Checking {len(check_scenes)} scenes (skipping canonical Scene {char_scenes[0]['scene_number']:02d})...")

        for scene in check_scenes:
            n = scene["scene_number"]
            img_path = IMAGES_DIR / f"scene_{n:02d}.png"

            if not img_path.exists():
                print(f"    Scene {n:02d}: MISSING IMAGE — skipping")
                continue

            canonical_img_path = canonical_img_paths.get(char_name)
            if canonical_img_path is not None and canonical_img_path.exists():
                status, detail = check_consistency_img2img(
                    client, canonical_img_path, img_path, char_name, char_info["hint"]
                )
            else:
                status, detail = check_consistency(   # text-based fallback
                    client, img_path, char_name, char_info["hint"], canonical
                )
            total_checks += 1

            if status == "CONSISTENT":
                print(f"    Scene {n:02d}: CONSISTENT")
            elif status == "NOT_VISIBLE":
                print(f"    Scene {n:02d}: NOT_VISIBLE (character absent — ok)")
            else:  # INCONSISTENT
                print(f"    Scene {n:02d}: INCONSISTENT — {detail}")
                total_inconsistent += 1
                if n not in scenes_to_regen:
                    scenes_to_regen[n] = []
                if char_name not in scenes_to_regen[n]:
                    scenes_to_regen[n].append(char_name)

            time.sleep(VISION_DELAY)

        print()

    print(f"  Consistency check complete: {total_checks} checks, {total_inconsistent} inconsistencies")
    print(f"  Scenes needing regeneration: {sorted(scenes_to_regen.keys()) or 'none'}")
    print()

    # ------------------------------------------------------------------
    # Phase 3: Regenerate inconsistent scenes
    # ------------------------------------------------------------------
    if not scenes_to_regen:
        print("  All scenes are consistent. No regeneration needed.")
        print()
        print("Next step: run tools/build_pdf.py")
        return

    if not regen_enabled:
        print("  Regeneration skipped (IMAGE_PROVIDER != dalle3).")
        print()
        print("Next step: run tools/build_pdf.py")
        return

    print(f"Phase 3: Regenerating {len(scenes_to_regen)} inconsistent scenes...")
    print()

    scene_map = {s["scene_number"]: s for s in scenes}
    regen_success = 0
    regen_failed = 0

    for n in sorted(scenes_to_regen.keys()):
        inconsistent_chars = scenes_to_regen[n]
        scene = scene_map[n]
        img_path = IMAGES_DIR / f"scene_{n:02d}.png"

        print(f"  Scene {n:02d} — inconsistent characters: {', '.join(inconsistent_chars)}")

        for attempt in range(1, REGEN_MAX_RETRIES + 2):
            if attempt > 1:
                print(f"    Regen attempt {attempt}...")
                time.sleep(DALLE_DELAY_SECONDS)

            ok = regenerate_scene(
                client, scene, canonical_dict, img_path, size, quality, inconsistent_chars
            )
            if not ok:
                print(f"    WARNING: Regeneration failed for Scene {n:02d}")
                regen_failed += 1
                break

            # Verify the regenerated image for the first inconsistent character
            primary_char = inconsistent_chars[0]
            char_info = characters.get(primary_char, {"hint": primary_char, "triggers": [primary_char.lower()]})
            canonical = canonical_dict[primary_char]
            canonical_img_path = canonical_img_paths.get(primary_char)
            if canonical_img_path is not None and canonical_img_path.exists():
                status, detail = check_consistency_img2img(
                    client, canonical_img_path, img_path, primary_char, char_info["hint"]
                )
            else:
                status, detail = check_consistency(
                    client, img_path, primary_char, char_info["hint"], canonical
                )

            if status == "CONSISTENT":
                print(f"    Scene {n:02d}: Regenerated → CONSISTENT")
                regen_success += 1
                break
            elif attempt < REGEN_MAX_RETRIES + 1:
                print(f"    Scene {n:02d}: Still INCONSISTENT ({detail}) — retrying...")
                time.sleep(VISION_DELAY)
            else:
                print(f"    Scene {n:02d}: Keeping best attempt after {REGEN_MAX_RETRIES} retries")
                regen_success += 1  # Count as done regardless — don't leave a gap
                break

    print()
    print(f"  Regenerated: {regen_success} scenes | Failed: {regen_failed} scenes")
    print()
    print("Next step: run tools/build_pdf.py")


if __name__ == "__main__":
    main()
