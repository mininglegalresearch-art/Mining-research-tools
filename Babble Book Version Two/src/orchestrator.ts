import { RunContext } from './context.js';
import type { RunOptions } from './types.js';

import { intakeJob }        from './steps/01_intake_job.js';
import { preprocessAudio }  from './steps/02_preprocess_audio.js';
import { asrTranscribe }    from './steps/03_asr_transcribe.js';
import { transcriptCleaner }from './steps/04_transcript_cleaner.js';
import { storywriter }      from './steps/05_storywriter.js';
import { styleBible }       from './steps/06_style_bible.js';
import { promptWriter }     from './steps/07_prompt_writer.js';
import { imageGenerator }   from './steps/08_image_generator.js';
import { imageQC }          from './steps/09_image_qc.js';
import { layoutEngine }     from './steps/10_layout_engine.js';
import { pdfBuilder }       from './steps/11_pdf_builder.js';
import { finalQC }          from './steps/12_final_qc.js';

type StepFn = (ctx: RunContext, opts: RunOptions) => Promise<void>;

const PIPELINE: Array<{ name: string; fn: StepFn }> = [
  { name: 'intake_job',          fn: intakeJob },
  { name: 'preprocess_audio',    fn: preprocessAudio },
  { name: 'asr_transcribe',      fn: asrTranscribe },
  { name: 'transcript_cleaner',  fn: transcriptCleaner },
  { name: 'storywriter',         fn: storywriter },
  { name: 'style_bible',         fn: styleBible },
  { name: 'prompt_writer',       fn: promptWriter },
  { name: 'image_generator',     fn: imageGenerator },
  { name: 'image_qc',            fn: imageQC },
  { name: 'layout_engine',       fn: layoutEngine },
  { name: 'pdf_builder',         fn: pdfBuilder },
  { name: 'final_qc',            fn: finalQC },
];

/**
 * Optional callback fired at the start and end of every step.
 * @param step  Step name (e.g. 'intake_job')
 * @param done  false = step is starting, true = step just completed
 */
export type StepCallback = (step: string, done: boolean) => void;

export async function runWorkflow(
  ctx: RunContext,
  opts: RunOptions,
  onStep?: StepCallback,
): Promise<void> {
  ctx.init();
  ctx.log('orchestrator', 'info', `Pipeline start — ${PIPELINE.length} steps`);

  for (const step of PIPELINE) {
    ctx.log('orchestrator', 'info', `>>> ${step.name}`);
    onStep?.(step.name, false);
    try {
      await step.fn(ctx, opts);
      onStep?.(step.name, true);
      ctx.log('orchestrator', 'info', `<<< ${step.name} OK`);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      ctx.log('orchestrator', 'error', `FAILED at ${step.name}: ${error.message}`);
      if (error.stack) {
        ctx.log('orchestrator', 'error', error.stack);
      }
      throw error;
    }
  }

  ctx.log('orchestrator', 'info', 'Pipeline complete.');
}
