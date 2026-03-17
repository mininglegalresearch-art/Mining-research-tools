import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { generatePlaceholderPNG, PAGE_PALETTE } from '../utils/png.js';
import type { RunContext } from '../context.js';
import type { RunOptions, ImagePromptManifest, ImageManifest, ImageEntry } from '../types.js';

const STEP = 'image_generator';
const IMG_WIDTH  = 200;
const IMG_HEIGHT = 150;

export async function imageGenerator(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', `start (MOCK — generating ${opts.pages} placeholder PNGs)`);

  const promptManifest: ImagePromptManifest = JSON.parse(
    readFileSync(join(ctx.dirs.prompts, 'image_prompts.json'), 'utf-8'),
  );

  const entries: ImageEntry[] = [];

  for (const promptEntry of promptManifest.prompts) {
    const n    = promptEntry.page_number;
    const name = `page_${String(n).padStart(2, '0')}.png`;
    const dest = join(ctx.dirs.images, name);

    // ── Checkpoint / resume ─────────────────────────────────────────────────
    if (existsSync(dest)) {
      ctx.log(STEP, 'info', `  page ${n}: already exists, skipping`);
    } else {
      const palette = PAGE_PALETTE[(n - 1) % PAGE_PALETTE.length] ?? [200, 200, 200];
      const [r, g, b] = palette;
      const pngBuf = generatePlaceholderPNG(IMG_WIDTH, IMG_HEIGHT, r, g, b);
      writeFileSync(dest, pngBuf);
      ctx.log(STEP, 'info', `  page ${n}: wrote ${pngBuf.length} bytes`);
    }

    ctx.addToManifest(dest, STEP, { type: 'image_png', page_number: n, mock: true });

    entries.push({
      page_number: n,
      path:        dest,
      prompt:      promptEntry.prompt,
      mock:        true,
    });
  }

  // ── image_manifest.json ───────────────────────────────────────────────────
  const imageManifest: ImageManifest = {
    run_id:  ctx.run_id,
    entries,
  };
  const manifestPath = join(ctx.dirs.images, 'image_manifest.json');
  writeFileSync(manifestPath, JSON.stringify(imageManifest, null, 2));
  ctx.addToManifest(manifestPath, STEP, { type: 'image_manifest' });

  ctx.log(STEP, 'info', `done — ${entries.length} images`);
}
