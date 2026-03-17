import { copyFileSync, existsSync, statSync } from 'node:fs';
import { writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';
import type { RunContext } from '../context.js';
import type { RunOptions, JobMetadata } from '../types.js';

const STEP = 'intake_job';

export async function intakeJob(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', 'start');

  // ── Validation ───────────────────────────────────────────────────────────
  if (!existsSync(opts.audioPath)) {
    throw new Error(`Audio file not found: ${opts.audioPath}`);
  }

  const stat = statSync(opts.audioPath);
  if (stat.size === 0) {
    throw new Error(`Audio file is empty: ${opts.audioPath}`);
  }

  // Duration check is a placeholder — real impl would call ffprobe/libsox
  ctx.log(STEP, 'info', `Audio file: ${opts.audioPath} (${stat.size} bytes) — duration check: placeholder`);

  // ── Copy audio to raw dir ─────────────────────────────────────────────────
  const originalName = basename(opts.audioPath);
  const destPath     = join(ctx.dirs.raw, originalName);
  copyFileSync(opts.audioPath, destPath);
  ctx.addToManifest(destPath, STEP, { type: 'audio_raw', original_path: opts.audioPath });
  ctx.log(STEP, 'info', `Copied audio → ${destPath}`);

  // ── Write metadata.json ───────────────────────────────────────────────────
  const metadata: JobMetadata = {
    run_id:            ctx.run_id,
    original_filename: originalName,
    raw_path:          destPath,
    pages:             opts.pages,
    created_at:        new Date().toISOString(),
    demo:              opts.demo,
  };
  const metaPath = join(ctx.dirs.raw, 'metadata.json');
  writeFileSync(metaPath, JSON.stringify(metadata, null, 2));
  ctx.addToManifest(metaPath, STEP, { type: 'metadata' });

  ctx.log(STEP, 'info', `done (pages=${opts.pages})`);
}
