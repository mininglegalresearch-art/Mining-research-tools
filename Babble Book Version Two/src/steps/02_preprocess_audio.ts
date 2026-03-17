import { copyFileSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { RunContext } from '../context.js';
import type { RunOptions, AudioPrepResult, JobMetadata } from '../types.js';

const STEP = 'preprocess_audio';

export async function preprocessAudio(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', 'start');
  void opts; // opts not directly used — reads from prior artifact

  // ── Read prior artifact ───────────────────────────────────────────────────
  const meta: JobMetadata = JSON.parse(
    readFileSync(join(ctx.dirs.raw, 'metadata.json'), 'utf-8'),
  );
  const srcPath  = meta.raw_path;
  const destPath = join(ctx.dirs.audio, 'normalized.wav');

  // ── Copy (placeholder for real normalization) ─────────────────────────────
  copyFileSync(srcPath, destPath);
  ctx.addToManifest(destPath, STEP, { type: 'audio_normalized', mock: true });
  ctx.log(STEP, 'info', 'Audio copied (normalisation is placeholder)');

  // ── Write audio_prep.json ─────────────────────────────────────────────────
  const result: AudioPrepResult = {
    input:      srcPath,
    output:     destPath,
    normalized: false,
    notes: [
      'PLACEHOLDER: Real implementation would apply:',
      '  • ITU-R BS.1770 loudness normalisation (-23 LUFS target)',
      '  • Noise reduction (RNNoise or spectral subtraction)',
      '  • Voice Activity Detection (VAD) — trim leading/trailing silence',
      '  • Resample to 16 kHz mono (Whisper-optimised)',
    ].join('\n'),
    created_at: new Date().toISOString(),
  };
  const prepPath = join(ctx.dirs.audio, 'audio_prep.json');
  writeFileSync(prepPath, JSON.stringify(result, null, 2));
  ctx.addToManifest(prepPath, STEP, { type: 'audio_prep_notes' });

  ctx.log(STEP, 'info', 'done');
}
