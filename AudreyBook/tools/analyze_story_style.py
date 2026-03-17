"""
analyze_story_style.py — Step 2b of the Audio-to-Storybook Pipeline

Purpose:  Analyze the cleaned narrative to determine the appropriate illustration
          style — colour intensity, mood, visual tone, story gender, and character
          list — that best matches the CONTENT of the story. This prevents style
          mismatches (e.g. applying a "muted earthy" style to a story about magical
          rainbow horses, or a soft watercolour treatment to a bold adventure story).

          The output style profile is then consumed by generate_storyboard.py,
          generate_images.py, build_pdf.py, and check_character_consistency.py.

Style intensity options:
    vibrant_magical  — rich saturated watercolour; luminous magical quality
                       (stories: fantasy, magic, rainbow creatures, princesses, adventure)
    pastel_gentle    — soft light pastels, very gentle and tender
                       (stories: quiet family moments, bedtime, newborn, lullabies)
    muted_earthy     — naturalistic earthy tones; organic and grounded
                       (stories: nature walks, real animals, seasons, gardens)
    bold_playful     — bright primary colours, energetic and humorous
                       (stories: silly characters, action-comedy, bold bright world)

Story gender options (detected from story CONTENT, not assumed):
    girl    — primary girl protagonist and/or magic/friendship/princess/fairy themes
    boy     — primary boy protagonist and/or adventure/humor/action/animals/vehicles themes
    neutral — mixed cast, ensemble, or themes that don't clearly lean either way

Required .env keys:
    OPENAI_API_KEY  — OpenAI API key

Input:  .tmp/narrative_clean.txt    — cleaned narrative from clean_narrative.py
Output: .tmp/story_style_profile.json

Next step: run tools/generate_storyboard.py
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import openai

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
TMP_DIR = PROJECT_DIR / ".tmp"
INPUT_FILE = TMP_DIR / "narrative_clean.txt"
OUTPUT_FILE = TMP_DIR / "story_style_profile.json"

ANALYSIS_SYSTEM_PROMPT = """\
You are an expert children's book art director. You analyze story text and determine
the appropriate watercolour illustration style AND story gender profile that best
matches the story's content, mood, setting, and characters.

Colour intensity options and when to choose each:
- "vibrant_magical"  → fantasy, magic, rainbow/iridescent creatures, royalty/princesses,
                       underwater wonders, adventures with magical beings, sparkling light
- "pastel_gentle"    → quiet tender moments, bedtime stories, family warmth, babies/toddlers,
                       soft domestic settings, lullabies, very calm/gentle narratives
- "muted_earthy"     → realistic nature, real animals, countryside/seasons, historical settings,
                       quiet realistic adventures (no magic or fantasy elements)
- "bold_playful"     → comedy, very energetic action, silly characters, playful humour,
                       broad bright cartoony feel requested

Story gender options (detect from story CONTENT — protagonist gender and dominant themes):
- "boy"     → primary boy protagonist AND/OR dominant themes are: adventure, humor, action,
              exploration, vehicles, sports, animals, pirates, robots, dinosaurs, mischief
- "girl"    → primary girl protagonist AND/OR dominant themes are: magic, friendship,
              princesses, fairies, nurturing, fashion, family warmth, gentle relationships
- "neutral" → mixed cast or ensemble, or themes that don't clearly lean either way

Story type options:
- "adventure"     → exploration, quests, outdoor action, problem-solving through action
- "humor"         → comedic situations, silly characters, funny mishaps
- "fantasy_magic" → magical worlds, creatures, spells, enchantment
- "friendship"    → bonding between characters, social dynamics
- "family"        → family relationships, home, siblings, parents
- "nature"        → animals, seasons, gardens, outdoor environments
- "mixed"         → combination of multiple types above

Always respond with valid JSON only. No preamble, no explanation.\
"""

ANALYSIS_USER_PROMPT = """\
Analyze this children's story and produce a comprehensive style and gender profile.

STORY TEXT:
---
{narrative}
---

Return a JSON object with these exact keys:
{{
  "colour_intensity": "<one of: vibrant_magical | pastel_gentle | muted_earthy | bold_playful>",
  "story_gender": "<one of: boy | girl | neutral>",
  "protagonist_name": "<main character's first name, or 'unknown' if unclear>",
  "story_type": "<one of: adventure | humor | fantasy_magic | friendship | family | nature | mixed>",
  "main_characters": [
    {{"name": "<character name>", "first_scene": null}},
    "..."
  ],
  "mood": "<comma-separated mood descriptors, e.g. 'joyful, magical, wonder-filled, adventurous'>",
  "setting": "<primary setting description, e.g. 'enchanted ocean, magical meadows, mystical forest'>",
  "themes": ["<theme1>", "<theme2>", "..."],
  "colour_guidance": "<1-2 sentences: specific colour recommendations reflecting this story's content>",
  "style_notes": "<1-2 sentences: specific illustration style guidance for this story's content>",
  "key_magical_elements": "<comma-separated list of any magical/fantastical visual elements, or 'none'>"
}}

For main_characters: list every named character that appears in the story (3-8 characters max).
Set first_scene to null — the pipeline will auto-detect which scene each character first appears in.
"""


def main():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        sys.exit(1)

    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run clean_narrative.py first.")
        sys.exit(1)

    narrative = INPUT_FILE.read_text(encoding="utf-8").strip()
    word_count = len(narrative.split())
    print(f"  Analyzing story style and gender... ({word_count} words)")

    client = openai.OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.3,
        max_tokens=800,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": ANALYSIS_USER_PROMPT.format(narrative=narrative)},
        ],
    )

    raw = response.choices[0].message.content.strip()

    try:
        profile = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse style analysis response: {e}")
        sys.exit(1)

    # Validate required keys
    required = ["colour_intensity", "mood", "colour_guidance", "style_notes"]
    for key in required:
        if key not in profile:
            print(f"ERROR: Missing key '{key}' in style profile.")
            sys.exit(1)

    valid_intensities = {"vibrant_magical", "pastel_gentle", "muted_earthy", "bold_playful"}
    if profile["colour_intensity"] not in valid_intensities:
        print(f"  WARNING: Unexpected colour_intensity '{profile['colour_intensity']}' — defaulting to vibrant_magical")
        profile["colour_intensity"] = "vibrant_magical"

    valid_genders = {"boy", "girl", "neutral"}
    if profile.get("story_gender") not in valid_genders:
        print(f"  WARNING: Unexpected story_gender '{profile.get('story_gender')}' — defaulting to neutral")
        profile["story_gender"] = "neutral"

    if not isinstance(profile.get("main_characters"), list):
        profile["main_characters"] = []

    OUTPUT_FILE.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  Colour intensity: {profile['colour_intensity']}")
    print(f"  Story gender:     {profile['story_gender']}")
    print(f"  Protagonist:      {profile.get('protagonist_name', 'unknown')}")
    print(f"  Story type:       {profile.get('story_type', 'n/a')}")
    print(f"  Mood:             {profile['mood']}")
    print(f"  Setting:          {profile.get('setting', 'n/a')}")
    print(f"  Colour guidance:  {profile['colour_guidance']}")
    chars = [c["name"] for c in profile.get("main_characters", [])]
    print(f"  Characters:       {', '.join(chars) if chars else 'none detected'}")
    print(f"  Output:           {OUTPUT_FILE}")
    print()
    print("Next step: run tools/generate_storyboard.py")


if __name__ == "__main__":
    main()
