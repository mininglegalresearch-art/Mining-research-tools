import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { RunContext } from '../context.js';
import type { RunOptions, StoryPlan, ImageQCResult, ImageQCReport } from '../types.js';

const STEP = 'image_qc';
const PNG_SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

// In Phase 1 placeholder images can be 1×1; raise to 512 in Phase 2
const MIN_DIMENSION = 1;

/** Read PNG dimensions from IHDR without any external library. */
function readPNGDimensions(filepath: string): { width: number; height: number } | null {
  try {
    const buf = readFileSync(filepath);
    if (buf.length < 24) return null;
    if (!buf.subarray(0, 8).equals(PNG_SIG)) return null;
    // IHDR: 4 bytes length + 4 bytes type + 4 bytes width + 4 bytes height = starts at offset 8
    const width  = buf.readUInt32BE(16);
    const height = buf.readUInt32BE(20);
    return { width, height };
  } catch {
    return null;
  }
}

export async function imageQC(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', `start — checking ${opts.pages} images (MIN_DIM=${MIN_DIMENSION}px)`);

  const plan: StoryPlan = JSON.parse(
    readFileSync(join(ctx.dirs.story, 'page_plan.json'), 'utf-8'),
  );

  const results: ImageQCResult[] = [];
  const failures: number[] = [];

  for (const page of plan.pages) {
    const n    = page.page_number;
    const name = `page_${String(n).padStart(2, '0')}.png`;
    const path = join(ctx.dirs.images, name);

    const exists = existsSync(path);
    if (!exists) {
      results.push({ page_number: n, path, exists: false, valid_png: false, width: null, height: null, passes: false, error: 'file not found' });
      failures.push(n);
      continue;
    }

    const dims = readPNGDimensions(path);
    if (!dims) {
      results.push({ page_number: n, path, exists: true, valid_png: false, width: null, height: null, passes: false, error: 'not a valid PNG or unreadable header' });
      failures.push(n);
      continue;
    }

    const dimCheck = dims.width >= MIN_DIMENSION && dims.height >= MIN_DIMENSION;
    const passes   = dimCheck;

    results.push({
      page_number: n,
      path,
      exists:    true,
      valid_png: true,
      width:     dims.width,
      height:    dims.height,
      passes,
      ...(passes ? {} : { error: `dimensions ${dims.width}×${dims.height} below minimum ${MIN_DIMENSION}px` }),
    });

    if (!passes) failures.push(n);
  }

  const all_pass = failures.length === 0;

  const report: ImageQCReport = {
    run_id:              ctx.run_id,
    total_pages:         plan.pages.length,
    all_pass,
    min_dimension_check: MIN_DIMENSION,
    results,
  };

  const reportPath = join(ctx.dirs.images, 'image_qc.json');
  writeFileSync(reportPath, JSON.stringify(report, null, 2));
  ctx.addToManifest(reportPath, STEP, { type: 'image_qc_report' });

  if (!all_pass) {
    throw new Error(
      `image_qc FAILED — pages with issues: ${failures.join(', ')}. See ${reportPath}`,
    );
  }

  ctx.log(STEP, 'info', `done — all ${results.length} images pass`);
}
