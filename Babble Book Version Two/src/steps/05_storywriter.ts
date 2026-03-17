import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { z } from 'zod';
import type { RunContext } from '../context.js';
import type { RunOptions, StoryPlan, PagePlan } from '../types.js';

const STEP = 'storywriter';

// ─── Zod schema ───────────────────────────────────────────────────────────────

const PageSchema = z.object({
  page_number: z.number().int().positive(),
  page_text: z.string().refine(
    t => t.split(/\s+/).filter(Boolean).length <= 40,
    { message: 'page_text exceeds 40 words' },
  ),
  scene_description: z.string().min(1),
  characters_in_scene: z.array(z.string()),
  tone: z.string().min(1),
});

const StoryPlanSchema = z.object({
  page_count: z.number().int().positive(),
  title: z.string().min(1),
  pages: z.array(PageSchema),
}).refine(
  d => d.page_count === d.pages.length,
  { message: 'page_count does not match pages array length' },
).refine(
  d => d.pages.every((p, i) => p.page_number === i + 1),
  { message: 'page_numbers are not contiguous starting from 1' },
);

// ─── Mock story data (15 pages) ───────────────────────────────────────────────

function buildMockStory(pageCount: number): StoryPlan {
  const allPages: PagePlan[] = [
    {
      page_number: 1,
      page_text: 'One sunny morning, Lily found a tiny glowing door at the base of the old oak tree in her backyard.',
      scene_description: 'A young girl with braids crouches before a small luminous door set into the bark of a grand oak tree, morning light filtering through leaves',
      characters_in_scene: ['Lily'],
      tone: 'curious',
    },
    {
      page_number: 2,
      page_text: 'The door creaked open to reveal a winding path of sparkling stepping stones leading into a hidden garden.',
      scene_description: 'A glowing doorway in the oak tree opens onto a magical path of iridescent stepping stones curving into lush greenery',
      characters_in_scene: ['Lily'],
      tone: 'wonder',
    },
    {
      page_number: 3,
      page_text: 'Inside the garden, flowers sang soft melodies and butterflies carried tiny lanterns in their wings.',
      scene_description: 'Pastel flowers with open mouths singing; butterflies with glowing lantern spots on their wings drifting through warm air',
      characters_in_scene: ['Lily'],
      tone: 'magical',
    },
    {
      page_number: 4,
      page_text: 'A friendly rabbit in a blue velvet vest hopped up to Lily and bowed. "We have been waiting for you," he said.',
      scene_description: 'A dapper rabbit in a blue vest bowing politely to Lily on the sparkling garden path',
      characters_in_scene: ['Lily', 'Rabbit'],
      tone: 'warm',
    },
    {
      page_number: 5,
      page_text: 'The rabbit led Lily past a silver stream where fish leaped in graceful arcs, leaving rainbow trails.',
      scene_description: 'Lily and the rabbit walking beside a bright stream; silver fish arching through the air leaving rainbow-coloured light trails',
      characters_in_scene: ['Lily', 'Rabbit'],
      tone: 'joyful',
    },
    {
      page_number: 6,
      page_text: 'They came to a sunny meadow where a family of deer wore flower crowns and danced in slow circles.',
      scene_description: 'A clearing where three deer wearing flower crowns step gracefully in a circle dance on soft green grass',
      characters_in_scene: ['Lily', 'Rabbit', 'Deer family'],
      tone: 'serene',
    },
    {
      page_number: 7,
      page_text: 'Lily clapped her hands with delight. The music grew louder and the whole garden seemed to glow.',
      scene_description: 'Lily clapping and laughing while the meadow around her brightens with golden light and floating musical notes',
      characters_in_scene: ['Lily', 'Rabbit'],
      tone: 'joyful',
    },
    {
      page_number: 8,
      page_text: 'At the heart of the garden stood a treehouse built from woven starlight and the silver silk of spiders.',
      scene_description: 'A breathtaking treehouse woven from strands of starlight and glittering silk, nestled in an enormous ancient tree',
      characters_in_scene: ['Lily', 'Rabbit'],
      tone: 'awe',
    },
    {
      page_number: 9,
      page_text: 'Inside, tiny forest creatures shared plates of wild berries and tiny cups filled with honeydew tea.',
      scene_description: 'A cosy interior with small woodland animals seated around a low table with berries, acorn cups, and honeydew tea',
      characters_in_scene: ['Lily', 'Rabbit', 'Forest creatures'],
      tone: 'cosy',
    },
    {
      page_number: 10,
      page_text: '"This garden needs a keeper," said the rabbit. "Someone kind and curious and brave enough to care for it."',
      scene_description: 'The rabbit standing solemnly before Lily, one paw resting on a tiny glowing lantern post, the garden stretching behind him',
      characters_in_scene: ['Lily', 'Rabbit'],
      tone: 'earnest',
    },
    {
      page_number: 11,
      page_text: 'Lily looked around at the singing flowers, the leaping fish, and the dancing deer and felt something stir in her heart.',
      scene_description: 'Lily gazing wide-eyed across the whole garden scene — flowers, stream, meadow all visible at once in warm golden light',
      characters_in_scene: ['Lily'],
      tone: 'reflective',
    },
    {
      page_number: 12,
      page_text: 'She thought of her backyard at home, and how she always watered her mother\'s roses, even on cold mornings.',
      scene_description: 'A gentle memory panel showing Lily in a garden at home, carefully watering small rose bushes in soft morning mist',
      characters_in_scene: ['Lily'],
      tone: 'tender',
    },
    {
      page_number: 13,
      page_text: '"I would love to be the keeper," Lily said softly. The garden answered with a chorus of colour and song.',
      scene_description: 'Lily speaking with quiet confidence; behind her the garden erupts in swirling colour, petals rising, butterflies spiralling upward',
      characters_in_scene: ['Lily', 'Rabbit', 'All garden creatures'],
      tone: 'triumphant',
    },
    {
      page_number: 14,
      page_text: 'The rabbit tied a tiny golden key around Lily\'s wrist. "Come back whenever you like," he said with a warm smile.',
      scene_description: 'Close-up of the rabbit gently tying a golden key on a ribbon to Lily\'s wrist, both smiling',
      characters_in_scene: ['Lily', 'Rabbit'],
      tone: 'loving',
    },
    {
      page_number: 15,
      page_text: 'Lily stepped back through the little door just as the sun began to set, her heart full of wonder and her wrist gleaming gold.',
      scene_description: 'Lily stepping back through the oak door into the warm orange light of dusk, golden key glinting, smiling back at the garden',
      characters_in_scene: ['Lily'],
      tone: 'hopeful',
    },
  ];

  const pages = allPages.slice(0, pageCount);
  // Re-number in case fewer pages were requested
  const renumbered = pages.map((p, i) => ({ ...p, page_number: i + 1 }));

  return {
    page_count: renumbered.length,
    title: 'The Magic Garden',
    pages: renumbered,
  };
}

// ─── Step ─────────────────────────────────────────────────────────────────────

export async function storywriter(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', 'start (MOCK — no API call)');

  // Read cleaned transcript (not used by mock, but documents where real data would come from)
  const _clean = readFileSync(join(ctx.dirs.transcript, 'clean_transcript.txt'), 'utf-8');
  void _clean;

  const storyPlan = buildMockStory(opts.pages);

  // ── Validate ──────────────────────────────────────────────────────────────
  const parsed = StoryPlanSchema.safeParse(storyPlan);
  if (!parsed.success) {
    throw new Error(`page_plan validation failed: ${parsed.error.message}`);
  }

  // ── story.md ──────────────────────────────────────────────────────────────
  const storyMd = [
    `# ${storyPlan.title}`,
    '',
    ...storyPlan.pages.map(p => `**Page ${p.page_number}**\n\n${p.page_text}\n`),
  ].join('\n');

  const storyPath = join(ctx.dirs.story, 'story.md');
  writeFileSync(storyPath, storyMd);
  ctx.addToManifest(storyPath, STEP, { type: 'story_markdown', mock: true });

  // ── page_plan.json ────────────────────────────────────────────────────────
  const planPath = join(ctx.dirs.story, 'page_plan.json');
  writeFileSync(planPath, JSON.stringify(storyPlan, null, 2));
  ctx.addToManifest(planPath, STEP, { type: 'page_plan', mock: true });

  ctx.log(STEP, 'info', `done — "${storyPlan.title}", ${storyPlan.page_count} pages`);
}
