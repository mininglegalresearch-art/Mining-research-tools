#!/usr/bin/env node
import { Command } from 'commander';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { RunContext }        from './context.js';
import { runWorkflow }       from './orchestrator.js';
import { generateDemoWAV }   from './utils/demo_audio.js';
import type { RunOptions, Manifest } from './types.js';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeRunId(prefix: string): string {
  const d   = new Date();
  const pad = (n: number, len = 2) => n.toString().padStart(len, '0');
  return [
    prefix,
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`,
    `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`,
  ].join('_');
}

// ─── CLI definition ───────────────────────────────────────────────────────────

const program = new Command();

program
  .name('babelbooks')
  .description('Babel Books — audio → children\'s book workflow engine')
  .version('0.1.0');

// ── run ──────────────────────────────────────────────────────────────────────
program
  .command('run')
  .description('Run the full workflow on an audio file')
  .requiredOption('--audio <path>', 'Path to the input audio file')
  .option('--pages <n>', 'Number of pages to generate', '15')
  .option('--out <dir>',  'Base output directory', 'runs')
  .action(async (options: { audio: string; pages: string; out: string }) => {
    const audioPath = resolve(options.audio);
    const outDir    = resolve(options.out);
    const pages     = parseInt(options.pages, 10);
    const run_id    = makeRunId('run');

    const ctx  = new RunContext(run_id, outDir);
    const opts: RunOptions = { audioPath, pages, outDir, demo: false };

    try {
      await runWorkflow(ctx, opts);
      console.log(`\n✓ Run complete → ${join(outDir, run_id)}`);
    } catch {
      console.error('\n✗ Run failed. See logs/run.jsonl for details.');
      process.exit(1);
    }
  });

// ── demo ─────────────────────────────────────────────────────────────────────
program
  .command('demo')
  .description('Run end-to-end with zero API keys (all steps mocked)')
  .option('--pages <n>', 'Number of pages', '15')
  .option('--out <dir>',  'Base output directory', 'runs')
  .action(async (options: { pages: string; out: string }) => {
    const outDir = resolve(options.out);
    const pages  = parseInt(options.pages, 10);

    // Create a synthetic demo audio file so Step 1 has a real file to copy
    const demoInputDir  = join(outDir, '_demo_input');
    mkdirSync(demoInputDir, { recursive: true });
    const demoAudioPath = join(demoInputDir, 'demo_audio.wav');
    writeFileSync(demoAudioPath, generateDemoWAV(3));
    console.log(`Demo audio written to ${demoAudioPath}`);

    const run_id = makeRunId('demo');
    const ctx    = new RunContext(run_id, outDir);
    const opts: RunOptions = {
      audioPath: demoAudioPath,
      pages,
      outDir,
      demo: true,
    };

    try {
      await runWorkflow(ctx, opts);
      console.log(`\n✓ Demo complete → ${join(outDir, run_id)}`);
      console.log(`  Inspect with: npm run babelbooks -- inspect --run ${run_id} --out ${options.out}`);
    } catch {
      console.error('\n✗ Demo failed. See logs/run.jsonl for details.');
      process.exit(1);
    }
  });

// ── inspect ──────────────────────────────────────────────────────────────────
program
  .command('inspect')
  .description('Print artifact summary for a completed run')
  .requiredOption('--run <run_id>', 'Run ID to inspect')
  .option('--out <dir>', 'Base output directory', 'runs')
  .action((options: { run: string; out: string }) => {
    const manifestPath = resolve(options.out, options.run, 'manifest.json');

    let manifest: Manifest;
    try {
      manifest = JSON.parse(readFileSync(manifestPath, 'utf-8')) as Manifest;
    } catch {
      console.error(`Cannot read manifest: ${manifestPath}`);
      process.exit(1);
    }

    console.log(`\n${'─'.repeat(60)}`);
    console.log(`Run ID  : ${manifest.run_id}`);
    console.log(`Created : ${manifest.created_at}`);
    console.log(`Total   : ${manifest.artifacts.length} artifacts`);
    console.log(`${'─'.repeat(60)}`);

    // Group by step
    const byStep = new Map<string, typeof manifest.artifacts>();
    for (const a of manifest.artifacts) {
      if (!byStep.has(a.step)) byStep.set(a.step, []);
      byStep.get(a.step)!.push(a);
    }

    for (const [step, arts] of byStep.entries()) {
      console.log(`\n  [${step}]  (${arts.length} artifact${arts.length !== 1 ? 's' : ''})`);
      for (const a of arts) {
        const name = a.path.split('/').pop() ?? a.path;
        const hash = a.sha256.slice(0, 12);
        console.log(`    ${name.padEnd(32)} sha256:${hash}…`);
      }
    }
    console.log(`\n${'─'.repeat(60)}\n`);
  });

program.parse();
