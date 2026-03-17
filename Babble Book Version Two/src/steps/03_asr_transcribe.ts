import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { RunContext } from '../context.js';
import type { RunOptions, TranscriptTimestamps } from '../types.js';

const STEP = 'asr_transcribe';

// ── Mock transcript ────────────────────────────────────────────────────────────
// Contains [babble] and [unclear] tokens that the cleaner will interpret.
const MOCK_RAW_TRANSCRIPT = `
One day [babble] I went to the big garden behind [unclear] house.
There was a [babble] tiny door at the bottom of the [unclear] tree.
I pushed it open and [babble] inside was the most [unclear] beautiful place.
There were [babble] flowers that were singing [unclear] little songs.
A rabbit [babble] with a blue jacket [unclear] hopped up to me.
He said [babble] welcome we have been [unclear] waiting for you.
We walked past [babble] a sparkly stream where [unclear] fish were jumping.
The fish made [babble] rainbow splashes [unclear] in the water.
Then we got to [babble] a meadow where [unclear] deer were dancing.
They wore [babble] flower crowns on their [unclear] heads.
In the middle [babble] was a treehouse made of [unclear] starlight.
Inside the treehouse [babble] everyone was having [unclear] a tea party.
The rabbit [babble] said this garden needs [unclear] a keeper.
I said [babble] I would like to be [unclear] the keeper please.
He tied [babble] a golden key around [unclear] my wrist and smiled.
`.trim();

export async function asrTranscribe(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', 'start (MOCK — no API call)');
  void opts;

  // ── raw_transcript.txt ────────────────────────────────────────────────────
  const transcriptPath = join(ctx.dirs.transcript, 'raw_transcript.txt');
  writeFileSync(transcriptPath, MOCK_RAW_TRANSCRIPT);
  ctx.addToManifest(transcriptPath, STEP, { type: 'raw_transcript', mock: true });

  // ── timestamps.json (mocked word-level timing) ────────────────────────────
  const words = MOCK_RAW_TRANSCRIPT.replace(/\[babble\]|\[unclear\]/g, '???').split(/\s+/);
  let ms = 0;
  const timestamps: TranscriptTimestamps = {
    source: 'mock',
    entries: words.map(w => {
      const dur = 200 + Math.floor(Math.random() * 300);
      const entry = { start_ms: ms, end_ms: ms + dur, text: w, confidence: 0.72 };
      ms += dur + 50;
      return entry;
    }),
  };
  const tsPath = join(ctx.dirs.transcript, 'timestamps.json');
  writeFileSync(tsPath, JSON.stringify(timestamps, null, 2));
  ctx.addToManifest(tsPath, STEP, { type: 'timestamps', mock: true });

  ctx.log(STEP, 'info', `done — ${words.length} tokens`);
}
