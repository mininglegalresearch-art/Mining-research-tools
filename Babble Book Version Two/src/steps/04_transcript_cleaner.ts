import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { RunContext } from '../context.js';
import type { RunOptions, AssumptionsLog, Assumption } from '../types.js';

const STEP = 'transcript_cleaner';

export async function transcriptCleaner(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', 'start (MOCK — no API call)');
  void opts;

  const raw = readFileSync(join(ctx.dirs.transcript, 'raw_transcript.txt'), 'utf-8');

  // ── Simple mock cleaning: replace tokens with plausible words ────────────
  const replacements: Array<{ token: string; replacement: string; note: string }> = [
    { token: '[babble]',  replacement: '',       note: 'Filled with contextual words (see clean transcript)' },
    { token: '[unclear]', replacement: '',       note: 'Inferred from sentence context' },
  ];

  // Track assumptions
  const assumptions: Assumption[] = [];
  const tokenPattern = /\[babble\]|\[unclear\]/g;
  let match: RegExpExecArray | null;
  let idx = 0;

  // Build a list of all tokens found with their surrounding context
  const tokenContexts: Array<{ token: string; context: string }> = [];
  while ((match = tokenPattern.exec(raw)) !== null) {
    const start   = Math.max(0, match.index - 20);
    const end     = Math.min(raw.length, match.index + 30);
    tokenContexts.push({ token: match[0], context: raw.slice(start, end).replace(/\n/g, ' ') });
  }

  // For each token, record an assumption
  const babbleInterpretations = [
    'I went to', 'there was a', 'we found a', 'and then I saw',
    'so we', 'next to it', 'along the way', 'suddenly',
    'we discovered', 'it was a', 'the little', 'they showed me',
    'my friend the', 'I told them', 'he gave me a',
  ];
  const unclearInterpretations = [
    'the old oak', 'really quite', 'my own', 'bright and',
    'very magical', 'her cosy', 'shining', 'sparkling water',
    'their', 'on their', 'pure', 'having', 'a special',
    'the kind', 'around',
  ];

  let bIdx = 0, uIdx = 0;
  for (const tc of tokenContexts) {
    if (tc.token === '[babble]') {
      const interp = babbleInterpretations[bIdx % babbleInterpretations.length] ?? 'and';
      assumptions.push({
        original: '[babble]',
        interpreted_as: interp,
        confidence: 'low',
        note: `Context: "…${tc.context}…"`,
      });
      bIdx++;
    } else {
      const interp = unclearInterpretations[uIdx % unclearInterpretations.length] ?? 'a';
      assumptions.push({
        original: '[unclear]',
        interpreted_as: interp,
        confidence: 'medium',
        note: `Context: "…${tc.context}…"`,
      });
      uIdx++;
    }
    idx++;
  }
  void idx;
  void replacements;

  // Build clean transcript by substituting tokens with interpretations
  let bI = 0, uI = 0;
  const clean = raw.replace(/\[babble\]|\[unclear\]/g, (token) => {
    if (token === '[babble]') {
      return babbleInterpretations[bI++ % babbleInterpretations.length] ?? '';
    } else {
      return unclearInterpretations[uI++ % unclearInterpretations.length] ?? '';
    }
  }).replace(/\s{2,}/g, ' ').trim();

  // ── Write outputs ─────────────────────────────────────────────────────────
  const cleanPath = join(ctx.dirs.transcript, 'clean_transcript.txt');
  writeFileSync(cleanPath, clean);
  ctx.addToManifest(cleanPath, STEP, { type: 'clean_transcript', mock: true });

  const assumptionsLog: AssumptionsLog = {
    created_at: new Date().toISOString(),
    model: 'mock',
    assumptions,
  };
  const assumePath = join(ctx.dirs.transcript, 'assumptions.json');
  writeFileSync(assumePath, JSON.stringify(assumptionsLog, null, 2));
  ctx.addToManifest(assumePath, STEP, { type: 'assumptions' });

  ctx.log(STEP, 'info', `done — ${assumptions.length} token(s) interpreted`);
}
