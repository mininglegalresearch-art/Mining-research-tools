import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { RunContext } from '../context.js';
import type {
  RunOptions, StoryPlan, StyleBible, CharacterBible,
  ImagePrompt, ImagePromptManifest,
} from '../types.js';

const STEP = 'prompt_writer';

const BASE_NEGATIVE = [
  'no text', 'no words', 'no letters', 'no numbers', 'no watermarks',
  'no speech bubbles', 'no captions', 'no dark themes', 'no violence',
  'no photorealistic render', 'no 3D render', 'ugly', 'blurry',
].join(', ');

export async function promptWriter(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', 'start');
  void opts;

  const plan: StoryPlan = JSON.parse(
    readFileSync(join(ctx.dirs.story, 'page_plan.json'), 'utf-8'),
  );
  const style: StyleBible = JSON.parse(
    readFileSync(join(ctx.dirs.story, 'style_bible.json'), 'utf-8'),
  );
  const chars: CharacterBible = JSON.parse(
    readFileSync(join(ctx.dirs.story, 'character_bible.json'), 'utf-8'),
  );

  const styleRef = `${style.art_style}, ${style.mood}`;

  // Build a lookup for character appearance descriptors
  const charLookup: Record<string, string> = {};
  for (const c of chars.characters) {
    charLookup[c.name] = `${c.appearance}, wearing ${c.clothing}`;
  }

  const prompts: ImagePrompt[] = plan.pages.map(page => {
    // Attach character descriptors for characters present on this page
    const charDescs = page.characters_in_scene
      .map(name => charLookup[name])
      .filter(Boolean)
      .join('; ');

    const charClause = charDescs ? ` Characters: ${charDescs}.` : '';

    const prompt = [
      `${style.art_style}.`,
      `${page.scene_description}.${charClause}`,
      `Mood: ${page.tone}.`,
      `Colour palette: ${style.color_palette.join(', ')}.`,
      style.rendering_notes,
    ].join(' ');

    const negative = [
      BASE_NEGATIVE,
      style.negative_constraints.join(', '),
    ].join(', ');

    return {
      page_number: page.page_number,
      prompt,
      negative_prompt: negative,
      style_reference: styleRef,
    };
  });

  const manifest: ImagePromptManifest = {
    title: plan.title,
    style_summary: styleRef,
    prompts,
  };

  const outPath = join(ctx.dirs.prompts, 'image_prompts.json');
  writeFileSync(outPath, JSON.stringify(manifest, null, 2));
  ctx.addToManifest(outPath, STEP, { type: 'image_prompts' });

  ctx.log(STEP, 'info', `done — ${prompts.length} prompts written`);
}
