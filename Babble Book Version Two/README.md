# Babel Books — Phase 1

> Audio recording of a child (ages 3–10) → 15-page illustrated children's book PDF.

This is a **local-first, deterministic workflow engine**. No API keys are required for the demo. All steps are mocked in Phase 1; real ASR, story writing, and image generation are Phase 2.

---

## Setup

```bash
cd "Babble Book Version Two"
npm install
```

**Requirements:** Node.js 18+, npm 9+.

---

## Commands

### Demo (zero API keys)
```bash
npm run demo
```
Produces a complete run in `runs/demo_YYYYMMDD_HHMMss/` including:
- `manifest.json` — all artifact hashes
- `logs/run.jsonl` — structured JSONL logs
- `05_images/page_01.png` … `page_15.png` — placeholder PNGs
- `07_pdf/book_screen.pdf` — 15-page screen PDF
- `07_pdf/book_print.pdf`  — 15-page print PDF (same content in Phase 1)
- `final_report.md` — QC summary

### Run on a real audio file
```bash
npm run babelbooks -- run --audio path/to/recording.wav [--pages 15] [--out runs]
```

### Inspect a completed run
```bash
npm run babelbooks -- inspect --run <run_id> [--out runs]
```
Prints a grouped artifact summary with truncated SHA-256 hashes.

### Build TypeScript to dist/
```bash
npm run build
```

---

## Project Structure

```
Babble Book Version Two/
├── docs/
│   ├── NORTH_STAR.md    Phase 0: product contract
│   ├── WORKFLOW.md      Step-by-step workflow reference
│   └── ARTIFACTS.md     Run directory layout + JSON schemas
├── src/
│   ├── cli.ts           CLI entry point (commander)
│   ├── context.ts       RunContext: run_id, dirs, logger, manifest
│   ├── orchestrator.ts  Sequential step runner
│   ├── types.ts         All TypeScript interfaces
│   ├── utils/
│   │   ├── png.ts       Zero-dep PNG generator (CRC-32 + zlib)
│   │   └── demo_audio.ts Minimal WAV file generator
│   └── steps/
│       ├── 01_intake_job.ts
│       ├── 02_preprocess_audio.ts
│       ├── 03_asr_transcribe.ts
│       ├── 04_transcript_cleaner.ts
│       ├── 05_storywriter.ts
│       ├── 06_style_bible.ts
│       ├── 07_prompt_writer.ts
│       ├── 08_image_generator.ts
│       ├── 09_image_qc.ts
│       ├── 10_layout_engine.ts
│       ├── 11_pdf_builder.ts
│       └── 12_final_qc.ts
├── runs/                Created at runtime (gitignored)
├── package.json
├── tsconfig.json
└── README.md
```

---

## What is Mocked vs Real

| Component | Phase 1 Status |
|---|---|
| intake_job | **REAL** — copies file, validates existence |
| preprocess_audio | MOCK — copies file; notes real normalization steps |
| asr_transcribe | MOCK — fixed babble transcript with tokens |
| transcript_cleaner | MOCK — simple token substitution |
| storywriter | MOCK — fixed 15-page story |
| style_bible | MOCK — fixed watercolour style + character descriptors |
| prompt_writer | **REAL** — constructs prompts from structured inputs |
| image_generator | MOCK — solid-colour PNG per page (zero deps) |
| image_qc | **REAL** — validates PNG signature and dimensions |
| layout_engine | MOCK — fixed Letter portrait layout |
| pdf_builder | **REAL** — pdf-lib; embeds images; word-wraps text |
| final_qc | **REAL** — reads manifest + QC report; validates PDFs |

---

## Run Directory Layout

```
runs/<run_id>/
├── manifest.json         ← artifact index (SHA-256)
├── final_report.md       ← QC summary
├── 00_raw/               ← copy of input audio + metadata.json
├── 01_audio/             ← normalized audio + prep notes
├── 02_transcript/        ← raw + clean transcript + assumptions
├── 03_story/             ← story.md + page_plan.json + bibles
├── 04_prompts/           ← image_prompts.json
├── 05_images/            ← page_01.png…page_15.png + QC report
├── 06_layout/            ← layout_plan.json
├── 07_pdf/               ← book_screen.pdf + book_print.pdf
└── logs/
    └── run.jsonl         ← structured JSONL (one entry per line)
```

---

## Architecture

```
CLI (commander)
  └── RunContext (run_id, dirs, logger, manifest)
        └── Orchestrator
              ├── Step 1: intake_job
              ├── Step 2: preprocess_audio
              ├── ...
              └── Step 12: final_qc
```

Each step is a pure async function `(ctx, opts) => Promise<void>` that:
1. Reads from declared prior-step artifacts
2. Writes outputs to the run directory
3. Calls `ctx.addToManifest()` for every output file
4. Logs `start` and `done` via `ctx.log()`

The orchestrator stops on any error, logs the stack trace, and exits non-zero.
