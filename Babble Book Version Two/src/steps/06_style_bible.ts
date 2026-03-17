import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { RunContext } from '../context.js';
import type { RunOptions, StyleBible, CharacterBible, StoryPlan } from '../types.js';

const STEP = 'style_bible';

export async function styleBible(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', 'start (MOCK)');
  void opts;

  const plan: StoryPlan = JSON.parse(
    readFileSync(join(ctx.dirs.story, 'page_plan.json'), 'utf-8'),
  );

  // ── Style bible ────────────────────────────────────────────────────────────
  const style: StyleBible = {
    art_style: 'soft watercolour illustration, gentle brush strokes, painterly textures',
    color_palette: ['#FFF8E7', '#A8D8EA', '#FFB6B9', '#FAEEE7', '#B8F0C8'],
    mood: 'warm, whimsical, wonder-filled, safe and gentle',
    rendering_notes: [
      'All illustrations should feel hand-painted with visible watercolour blooms.',
      'Backgrounds are soft and out-of-focus; foreground subjects are clear.',
      'Light source is always warm and slightly golden.',
      'Edges are soft — avoid hard outlines.',
      'Characters are round and friendly-looking, never angular or threatening.',
    ].join(' '),
    negative_constraints: [
      'no text', 'no words', 'no letters', 'no numbers',
      'no watermarks', 'no speech bubbles', 'no captions',
      'no dark shadows', 'no violence', 'no scary imagery',
      'no photorealistic render', 'no 3D render',
    ],
  };

  const stylePath = join(ctx.dirs.story, 'style_bible.json');
  writeFileSync(stylePath, JSON.stringify(style, null, 2));
  ctx.addToManifest(stylePath, STEP, { type: 'style_bible' });

  // ── Character bible ────────────────────────────────────────────────────────
  // Collect unique characters from the story
  const allChars = new Set<string>();
  for (const p of plan.pages) {
    for (const c of p.characters_in_scene) {
      allChars.add(c);
    }
  }

  const CHAR_DESCRIPTORS: Record<string, {
    age: string; appearance: string; clothing: string; distinguishing_features: string;
  }> = {
    'Lily': {
      age: '6 years old',
      appearance: 'Small girl with warm brown skin, dark braided hair with yellow ribbons, bright curious eyes',
      clothing: 'Yellow sundress with white daisies, small brown sandals',
      distinguishing_features: 'Always has paint-stained fingers; wears a small golden key on a ribbon (from page 14)',
    },
    'Rabbit': {
      age: 'Timeless',
      appearance: 'Medium-sized rabbit, snow-white fur, large gentle eyes',
      clothing: 'Navy blue velvet vest with brass buttons, small round spectacles',
      distinguishing_features: 'Always carries a tiny lantern; fur glows faintly in darkness',
    },
    'Deer family': {
      age: 'Mix of adults and young',
      appearance: 'Three graceful deer — one large doe, two smaller fawns — all with soft brown coats',
      clothing: 'Flower crowns woven from wild roses and ferns',
      distinguishing_features: 'Hooves leave small flower prints when they dance',
    },
    'Forest creatures': {
      age: 'Various',
      appearance: 'Assorted small woodland animals: hedgehogs, mice, squirrels, bluebirds',
      clothing: 'Tiny aprons and waistcoats in pastel colours',
      distinguishing_features: 'Always appear in groups; use acorns as cups and leaf-plates',
    },
  };

  const characters = Array.from(allChars)
    .filter(name => name !== 'All garden creatures')
    .map(name => ({
      name,
      ...(CHAR_DESCRIPTORS[name] ?? {
        age: 'Unknown',
        appearance: 'A friendly garden creature',
        clothing: 'Natural colouring',
        distinguishing_features: 'Magical and welcoming',
      }),
    }));

  const charBible: CharacterBible = { characters };
  const charPath = join(ctx.dirs.story, 'character_bible.json');
  writeFileSync(charPath, JSON.stringify(charBible, null, 2));
  ctx.addToManifest(charPath, STEP, { type: 'character_bible' });

  ctx.log(STEP, 'info', `done — ${characters.length} characters defined`);
}
