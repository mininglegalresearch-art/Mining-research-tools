import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { RunContext } from '../context.js';
import type { RunOptions, StoryPlan, LayoutPlan } from '../types.js';

const STEP = 'layout_engine';

export async function layoutEngine(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', 'start (MOCK — fixed Letter portrait layout)');
  void opts;

  const plan: StoryPlan = JSON.parse(
    readFileSync(join(ctx.dirs.story, 'page_plan.json'), 'utf-8'),
  );
  void plan;

  // US Letter portrait: 8.5" × 11" = 612 × 792 pt
  // All coords in pdf-lib points (origin = bottom-left)
  //
  //  792 ┌──────────────────────────────────┐
  //      │  [HEADER]  y=762, h=20           │
  //      │  ─────────────────────────────── │
  //      │  [IMAGE BOX]                     │
  //      │  x=50  y=362  w=512  h=380       │  (top edge at 742)
  //      │  ─────────────────────────────── │
  //      │  [TEXT BOX]                      │
  //      │  x=50  y=80   w=512  h=260       │  (top edge at 340)
  //    0 └──────────────────────────────────┘
  //
  const layout: LayoutPlan = {
    page_size: { width: 612, height: 792, unit: 'pt' },
    margins:   { top: 40, right: 50, bottom: 40, left: 50 },
    header:    { x: 50, y: 762, height: 20 },
    image_box: { x: 50, y: 362, width: 512, height: 380 },
    text_box:  { x: 50, y: 80,  width: 512, height: 260 },
    font_size: 14,
  };

  const layoutPath = join(ctx.dirs.layout, 'layout_plan.json');
  writeFileSync(layoutPath, JSON.stringify(layout, null, 2));
  ctx.addToManifest(layoutPath, STEP, { type: 'layout_plan' });

  ctx.log(STEP, 'info', 'done');
}
