"""
generate_storyboard.py — Step 3 of the Audio-to-Storybook Pipeline

Purpose:  Use GPT-4o to divide the cleaned narrative into exactly 24 scenes,
          each with narrative text and a detailed illustration prompt.
          Also generates a cover_prompt for a hero cover composition.
          Validates the response and retries up to 3 times on failure.
          v2: Character Visual Bible embedded in every prompt for consistency.
          v3: Gender-aware routing — selects CHARACTER_BIBLE_GIRL or CHARACTER_BIBLE_BOY
              based on story_gender from story_style_profile.json.

Required .env keys:
    OPENAI_API_KEY            — OpenAI API key
    STORYBOOK_TITLE_OVERRIDE  — (optional) override the GPT-generated book title

Input:  .tmp/narrative_clean.txt — polished narrative from clean_narrative.py
Output: .tmp/storyboard.json     — cover_prompt + 24-scene storyboard with image prompts

Schema:
    {
      "title": "...",
      "cover_prompt": "...",
      "scenes": [
        { "scene_number": 1, "text": "...", "image_prompt": "..." },
        ...
      ]
    }

Next step: run tools/generate_images.py
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import openai

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
TMP_DIR = PROJECT_DIR / ".tmp"
INPUT_FILE = TMP_DIR / "narrative_clean.txt"
OUTPUT_FILE = TMP_DIR / "storyboard.json"
ERROR_FILE = TMP_DIR / "storyboard_error.json"
STYLE_PROFILE_FILE = TMP_DIR / "story_style_profile.json"

MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# Character Visual Bible — GIRL STORY (Audrey story — specific characters)
# For a new girl story, update these character descriptions to match.
# ---------------------------------------------------------------------------
CHARACTER_BIBLE_GIRL = """\
CHARACTER VISUAL BIBLE — EXACT SPECIFICATIONS (apply identically to every image):

AUDREY (child protagonist — appears from scene 7 onward):
  • Age: 4 years old, small and round — big soft round head, chubby rosy cheeks, pudgy little hands
  • Hair: straight, shoulder-length, warm golden-yellow — the colour of ripe wheat in late afternoon sun
  • Eyes: gently large and soft, warm sky-blue — naturally proportioned, NOT oversized or flat anime-style;
    real child eyes with soft lashes
  • Skin: warm peachy-cream, very round chubby cheeks, small snub nose — looks like a real 4-year-old
  • Outfit: simple sky-blue dress with a white Peter Pan collar and a small lilac ribbon at the waist
  • Expression: naturally joyful — soft open smile, wide gentle eyes; real child expressions, NOT
    exaggerated anime reactions (no oversized sweat drops, no sharp angular brows, no dramatic gasps)

RAINBOW (Audrey's water horse — present in all 24 scenes and cover):
  • Large graceful horse with a softly rainbow-hued watercolour coat — gentle bands of colour
    flowing from nose to tail: soft rose-red, warm orange, muted gold, sage green, dusty blue, soft violet
  • The colours are painterly and naturalistic — like watercolour pigments blending on wet paper —
    NOT neon, NOT glowing, NOT a vivid prism effect
  • Mane and tail: long flowing, with the same soft rainbow tones blending gently together
  • Eyes: large warm amber, gentle and loving — real horse eyes, NOT anime-style flat graphic eyes
  • Rainbow is the most colourful element on the page, but in a subtle, painterly way

SUPPORTING PRINCESSES (consistent visual identity throughout ALL scenes):
  • Ariel:  long wavy auburn-red hair; sea-green dress; warm brown eyes; gentle smile; rides PINK horse
  • Elsa:   straight pale silver-blonde hair to shoulders; soft ice-blue dress; grey-blue eyes; calm
            expression; rides BLUE horse
  • Belle:  curly warm chestnut-brown hair; soft golden-yellow dress; hazel eyes; cheerful smile;
            rides YELLOW horse
  • Anna:   auburn hair in two loose braids; teal-and-rose dress; blue eyes; bright expression;
            rides VIOLET horse
  All four princesses have naturally proportioned real-girl faces — NOT anime: no oversized graphic
  eyes, no sharp angular jaws, no cel-shaded faces, no flat colour blocks.

SUPPORTING WATER HORSES (always softer in colour than Rainbow):
  • Pink horse:   soft dusty rose, gentle matte watercolour coat
  • Blue horse:   pale ice-blue, quiet and calm
  • Yellow horse: warm muted amber-gold, soft and glowing
  • Violet horse: soft plum-lavender, gentle and flowing

CRITICAL CHARACTER CONSISTENCY RULES:
  1. In the `text` field (narrative): freely use characters' names — Ariel, Elsa, Belle, Anna,
     Audrey, Rainbow — to tell a warm, gentle story.
  2. In `image_prompt` fields: describe each character ONLY by visual appearance (hair colour/length,
     eye colour, outfit, proportions). Do NOT include any character names in image_prompt — describe
     appearances inline instead. Example format:
     "a small 4-year-old girl with shoulder-length warm golden-yellow hair, soft sky-blue eyes,
     simple sky-blue dress with white collar and lilac ribbon, naturally proportioned real-child face
     (not anime), chubby cheeks, joyful soft smile, riding a gently rainbow-hued watercolour horse
     with soft blended colour bands (rose-red, orange, gold, sage green, dusty blue, violet)"
     Apply the same inline appearance restatement for every character and horse visible in the scene.

ART STYLE — MANDATORY, IDENTICAL IN EVERY SINGLE IMAGE:
  • "SIMPLE NATURALISTIC WATERCOLOUR PICTURE BOOK ILLUSTRATION"
  • Style reference: classic English watercolour picture books — loose, tender, softly painted
  • Loose spontaneous watercolour washes with natural pigment blooms and visible paper texture
  • Colours: as specified in the STORY STYLE PROFILE below — earthy and naturalistic by default.
    NOT oversaturated neon. NOT flat digital colours.
  • Line work: light expressive pencil or fine ink outlines — natural and slightly sketchy;
    NOT heavy bold black outlines; NOT sharp angular anime lines
  • STRICTLY NO ANIME/MANGA FEATURES anywhere in the image:
      — no oversized flat graphic eyes (anime eyes are unnaturally large, perfectly round, with
        flat white highlight shapes and solid colour irises — avoid completely)
      — no sharp angular jawlines or pointed chins
      — no bold black cel-shading or hard flat colour fills
      — no speed lines, no star-shaped blush marks, no exaggerated sweat drops
      — no spiky or perfectly smooth solid-colour hair blocks
      — characters must look like real children and real horses, painted in watercolour
  • CONSISTENT DEPTH across all 24 scenes:
      Foreground = characters: slightly richer watercolour, gentle soft detail
      Midground = supporting elements: softer washes, less defined edges
      Background = very dilute washes, soft shapes, almost abstract colour fields
  • Lighting: gentle diffuse natural daylight or soft warm afternoon light — no dramatic neon glows,
    no sharp spotlights
  • Mood: gentle, warm, tender, quietly magical — never dark, never scary
  • NOT photorealistic. NOT anime. NOT manga. NOT 3D CGI. NOT flat digital design.
  • NO text, NO words, NO numbers, NO letters anywhere in the image.\
"""

# ---------------------------------------------------------------------------
# Character Visual Bible — BOY STORY (manually customizable per story)
# Fill in the bracketed placeholders with the specific characters from the story.
# Pattern mirrors CHARACTER_BIBLE_GIRL above — same structure, different content.
# ---------------------------------------------------------------------------
CHARACTER_BIBLE_BOY = """\
CHARACTER VISUAL BIBLE — EXACT SPECIFICATIONS (apply identically to every image):

JOHNNY (boy protagonist — present in ALL 24 scenes and cover):
  • Age: 5 years old — sturdy, stocky real-child proportions; rosy cheeks from outdoor play
  • Hair: short, dark brown, slightly messy and tousled — consistently this exact colour and length
  • Eyes: bright hazel-green, wide with curiosity and spark — naturally proportioned, NOT oversized
    or flat anime-style; real child eyes with life and determination
  • Skin: warm golden-tan, lightly sun-kissed from playing outside
  • Outfit: bold red t-shirt, navy blue cargo shorts, scuffed white-and-red trainers — consistent
    throughout ALL scenes
  • Expression: naturally adventurous — curious, brave, determined, or gleefully triumphant;
    real child expressions, NOT exaggerated anime reactions

THE MONSTER (antagonist creature — appears from scene 3 onward):
  • Large, lumpy, round-bellied creature — about twice the height of Johnny but comically clumsy
  • Skin: rough green-grey bumpy hide, like a warty toad
  • Eyes: big round yellow eyes with black pupils — wide and startled-looking, NOT menacing
  • Mouth: wide rubbery grin with blunt rounded teeth — goofy rather than frightening
  • Arms: stubby with big clumsy mitteny hands — no sharp claws
  • Overall: silly-scary, like a cartoon monster — designed to make children laugh not shudder;
    the monster looks more baffled and clumsy than truly threatening

SUPPORTING CHARACTERS (consistent visual identity throughout ALL scenes):
  • Johnny's friends: cheerful mixed group of 2-3 small children in bright play clothes —
    secondary background characters; less detailed than Johnny; warm and joyful expressions

CRITICAL CHARACTER CONSISTENCY RULES:
  1. In the `text` field (narrative): freely use characters' names to tell the story.
  2. In `image_prompt` fields: describe each character ONLY by visual appearance (hair
     colour/length, eye colour, outfit, proportions). Do NOT include character names in
     image_prompt — describe appearances inline instead. Example format:
     "a sturdy [X]-year-old boy with short sandy-brown tousled hair, warm brown eyes,
     navy blue t-shirt and cargo shorts, naturally proportioned real-child face (not anime),
     excited expression"
     Apply the same inline appearance restatement for every character visible in the scene.

ART STYLE — MANDATORY, IDENTICAL IN EVERY SINGLE IMAGE:
  • "BOLD EXPRESSIVE WATERCOLOUR PICTURE BOOK ILLUSTRATION"
  • Style reference: classic adventure picture book illustration — energetic, lively, confident
  • Bold spontaneous watercolour washes with visible texture and natural pigment blooms
  • Colours: rich naturalistic earth tones with bold accents — deep blues, forest greens,
    warm oranges, rich ambers, earthy browns — saturated but NOT neon, NOT flat digital
  • Line work: confident expressive ink outlines — energetic and naturalistic;
    NOT delicate or wispy; NOT heavy black anime lines
  • DYNAMIC COMPOSITIONS across all 15 scenes: characters in action or mid-movement;
    strong diagonal arrangements; clear foreground/midground/background separation
  • STRICTLY NO ANIME/MANGA FEATURES anywhere in the image:
      — no oversized flat graphic eyes (anime eyes are unnaturally large, perfectly round, with
        flat white highlight shapes and solid colour irises — avoid completely)
      — no sharp angular jawlines or pointed chins
      — no bold black cel-shading or hard flat colour fills
      — no speed lines, no star-shaped blush marks, no exaggerated sweat drops
      — no spiky or perfectly smooth solid-colour hair blocks
      — characters must look like real children and real animals, painted in watercolour
  • CONSISTENT DEPTH across all 24 scenes:
      Foreground = characters: richer watercolour, confident bold detail
      Midground = supporting elements: softer washes, slightly less defined
      Background = dilute washes, simplified shapes, atmospheric colour
  • Lighting: bright natural daylight, warm golden afternoon sun, or dramatic adventure
    atmosphere — NO neon glows, no sharp spotlight effects
  • Mood: adventurous, exciting, fun, sometimes humorous — never dark, never scary
  • NOT photorealistic. NOT anime. NOT manga. NOT 3D CGI. NOT flat digital design.
  • NO text, NO words, NO numbers, NO letters anywhere in the image.\
"""

# ---------------------------------------------------------------------------
# Style locks — appended to every image_prompt; one per gender
# ---------------------------------------------------------------------------
STYLE_LOCK_GIRL = (
    "simple naturalistic watercolour picture book illustration, "
    "loose watercolour washes, soft muted earthy colours, gentle natural light, "
    "light ink outlines, no anime, no manga, no photorealism, no text"
)

STYLE_LOCK_BOY = (
    "bold expressive watercolour picture book illustration, "
    "confident energetic brushwork, rich earth tones and bold colour accents, "
    "dynamic action composition, expressive ink outlines, "
    "no anime, no manga, no photorealism, no text"
)

# ---------------------------------------------------------------------------
# Language guidance — tone and reading level per gender
# ---------------------------------------------------------------------------
LANGUAGE_GIRL = (
    "1-3 very short simple sentences written for preschool children ages 3-5. "
    "Use the simplest everyday words a 4-year-old would understand. "
    "Short, gentle, warm. Present tense."
)

LANGUAGE_BOY = (
    "1-3 short punchy sentences for young children ages 3-6. "
    "Use active verbs and exciting language. Short, fun, adventurous. Present tense."
)

SYSTEM_PROMPT_TEMPLATE = """\
You are a children's book author and illustrator. Your task is to adapt a story into exactly \
24 illustrated scenes for a picture book, plus one hero cover composition.

{character_bible}

For each scene produce:
- text: {language_guidance}
- image_prompt: richly detailed DALL-E 3 prompt that (1) RESTATES every visible character's \
  full appearance inline (hair, eyes, outfit, proportions — do not abbreviate), \
  (2) describes the specific scene composition, action, and emotional moment, \
  (3) specifies the lighting and colour mood, \
  (4) explicitly states "no anime features, naturally proportioned real-child faces", and \
  (5) ALWAYS ends with this exact phrase: "{style_lock}"

For the cover produce:
- cover_prompt: a wide composition showing the main character(s) and setting from the story; \
  all figures have naturally proportioned faces (no anime); \
  upper third kept as open sky or neutral space so a title can be placed there; \
  end with: "{style_lock}"

STORY STYLE PROFILE (derived from the actual story content — use this to calibrate all image prompts):
{style_profile_block}

Respond ONLY with valid JSON. No preamble, no markdown code fences, no explanation.\
"""

USER_PROMPT_TEMPLATE = """\
Story text:
---
{narrative}
---

Return a JSON object with exactly this structure (24 scenes total):
{{
  "title": "book title here",
  "cover_prompt": "wide cinematic cover illustration prompt here",
  "scenes": [
    {{
      "scene_number": 1,
      "text": "narrative text for this scene (1-3 short simple sentences, preschool ages 3-5, present tense)",
      "image_prompt": "detailed DALL-E 3 prompt applying the full character visual bible, \
scene composition, lighting and colour mood, no anime features, simple naturalistic watercolour style, no text"
    }}
  ]
}}\
"""


def get_storyboard_config(story_gender: str) -> tuple:
    """Return (character_bible, style_lock, language_guidance) for the story gender."""
    if story_gender == "boy":
        return CHARACTER_BIBLE_BOY, STYLE_LOCK_BOY, LANGUAGE_BOY
    else:  # "girl" or "neutral"
        return CHARACTER_BIBLE_GIRL, STYLE_LOCK_GIRL, LANGUAGE_GIRL


def validate_storyboard(data: dict) -> tuple[bool, str]:
    """Return (is_valid, error_message)."""
    if not isinstance(data, dict):
        return False, "Response is not a JSON object"
    if "title" not in data:
        return False, "Missing 'title' key"
    if "cover_prompt" not in data or not str(data.get("cover_prompt", "")).strip():
        return False, "Missing or empty 'cover_prompt' key"
    if "scenes" not in data:
        return False, "Missing 'scenes' key"
    scenes = data["scenes"]
    if not isinstance(scenes, list):
        return False, "'scenes' is not a list"
    if len(scenes) != 24:
        return False, f"Expected 24 scenes, got {len(scenes)}"
    for i, scene in enumerate(scenes, 1):
        for field in ("scene_number", "text", "image_prompt"):
            if field not in scene:
                return False, f"Scene {i} missing field '{field}'"
        if not str(scene["text"]).strip():
            return False, f"Scene {i} has empty text"
        if not str(scene["image_prompt"]).strip():
            return False, f"Scene {i} has empty image_prompt"
    return True, ""


def call_gpt(client: openai.OpenAI, messages: list) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.6,
        max_tokens=16000,
        response_format={"type": "json_object"},
        messages=messages,
    )
    return response.choices[0].message.content.strip()


def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run tools/clean_narrative.py first.")
        sys.exit(1)

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    narrative = INPUT_FILE.read_text(encoding="utf-8").strip()
    print(f"Input: {len(narrative.split())} words")

    # Load story style profile if available (from analyze_story_style.py)
    style_profile_block = "  No style profile found — using default naturalistic watercolour."
    story_gender = "girl"  # default
    if STYLE_PROFILE_FILE.exists():
        try:
            with open(STYLE_PROFILE_FILE, encoding="utf-8") as f:
                sp = json.load(f)
            style_profile_block = (
                f"  Colour intensity: {sp.get('colour_intensity', 'vibrant_magical')}\n"
                f"  Mood: {sp.get('mood', 'joyful, magical')}\n"
                f"  Setting: {sp.get('setting', 'magical')}\n"
                f"  Colour guidance: {sp.get('colour_guidance', '')}\n"
                f"  Style notes: {sp.get('style_notes', '')}\n"
                f"  Key magical elements: {sp.get('key_magical_elements', 'none')}"
            )
            story_gender = sp.get("story_gender", "girl")
            print(f"  Style profile: {sp.get('colour_intensity')} / {sp.get('mood', '')[:60]}")
            print(f"  Story gender:  {story_gender}")
        except Exception as e:
            print(f"  WARNING: Could not load style profile: {e}")
    else:
        print("  NOTE: No story_style_profile.json found — run analyze_story_style.py first for best results.")

    character_bible, style_lock, language_guidance = get_storyboard_config(story_gender)
    print("  Generating cover + 24-scene storyboard with GPT-4o...")

    system_prompt_filled = SYSTEM_PROMPT_TEMPLATE.format(
        character_bible=character_bible,
        style_lock=style_lock,
        language_guidance=language_guidance,
        style_profile_block=style_profile_block,
    )

    client = openai.OpenAI(api_key=api_key)
    messages = [
        {"role": "system", "content": system_prompt_filled},
        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(narrative=narrative)},
    ]

    data = None
    raw = ""
    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            print(f"  Retry {attempt}/{MAX_RETRIES}...")

        start = time.time()
        raw = call_gpt(client, messages)
        elapsed = time.time() - start

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"    WARNING: JSON parse error on attempt {attempt}: {e}")
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": "Your response was not valid JSON. Return only valid JSON — no markdown, no explanation.",
            })
            data = None
            continue

        valid, err = validate_storyboard(data)
        if valid:
            print(f"  Done in {elapsed:.1f}s — validated 24 scenes + cover_prompt")
            break
        else:
            print(f"    WARNING: Validation failed on attempt {attempt}: {err}")
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": f"Correction needed: {err}. Return the complete corrected JSON with exactly 24 scenes and a cover_prompt.",
            })
            data = None

    if data is None:
        print(f"ERROR: Failed to generate valid storyboard after {MAX_RETRIES} attempts.")
        print(f"  Raw response saved to: {ERROR_FILE}")
        ERROR_FILE.write_text(raw, encoding="utf-8")
        sys.exit(1)

    # Apply title override if set
    title_override = os.getenv("STORYBOOK_TITLE_OVERRIDE", "").strip()
    if title_override:
        data["title"] = title_override
        print(f"  Title overridden to: \"{title_override}\"")

    OUTPUT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  Title:    \"{data['title']}\"")
    print(f"  Cover:    {data['cover_prompt'][:80]}...")
    print(f"  Scene 1:  {data['scenes'][0]['text'][:80]}...")
    print(f"  Output written to: {OUTPUT_FILE}")
    print()
    print("Next step: run tools/generate_images.py")


if __name__ == "__main__":
    main()
