# Babel Books — Workflow Reference

## Overview

The pipeline is a sequential series of 12 steps. Each step is a pure function:
- Reads from its declared inputs + prior step artifacts in the run directory
- Writes its declared outputs to the run directory
- Logs start/end + any errors to `logs/run.jsonl`
- Registers every artifact in `manifest.json` with SHA-256

Steps must not reach outside the run directory except for the original audio input in Step 1.

---

## Step Definitions

### Step 1 — `intake_job`

| | |
|---|---|
| **Input** | audio filepath (CLI arg), pages (CLI arg, default 15) |
| **Output** | `00_raw/<original_filename>`, `00_raw/metadata.json` |
| **Validation** | File exists; file extension is audio type; size > 0 |
| **Duration check** | Placeholder: logged but not enforced in Phase 1 |
| **Retry** | None (deterministic I/O) |

`metadata.json` schema:
```json
{
  "run_id": "string",
  "original_filename": "string",
  "raw_path": "string",
  "pages": "number",
  "created_at": "ISO8601",
  "demo": "boolean"
}
```

---

### Step 2 — `preprocess_audio`

| | |
|---|---|
| **Input** | `00_raw/metadata.json` → `raw_path` |
| **Output** | `01_audio/normalized.wav`, `01_audio/audio_prep.json` |
| **Mock** | Yes — copies raw audio; real impl would apply ITU-R BS.1770 normalization |
| **Retry** | None |

---

### Step 3 — `asr_transcribe`

| | |
|---|---|
| **Input** | `01_audio/normalized.wav` |
| **Output** | `02_transcript/raw_transcript.txt`, `02_transcript/timestamps.json` |
| **Mock** | Yes — returns hardcoded babble transcript with `[babble]`/`[unclear]` tokens |
| **Real impl** | OpenAI Whisper API or local Whisper model (Phase 2) |
| **Retry** | Up to 3 on API timeout (Phase 2) |

---

### Step 4 — `transcript_cleaner`

| | |
|---|---|
| **Input** | `02_transcript/raw_transcript.txt` |
| **Output** | `02_transcript/clean_transcript.txt`, `02_transcript/assumptions.json` |
| **Mock** | Yes — applies simple token cleanup; real impl uses GPT-4o |
| **assumptions.json** | Lists every inference made (e.g., "[babble] interpreted as 'I went'") |
| **Retry** | Up to 3 on API error (Phase 2) |

---

### Step 5 — `storywriter_15_pages`

| | |
|---|---|
| **Input** | `02_transcript/clean_transcript.txt` |
| **Output** | `03_story/story.md`, `03_story/page_plan.json` |
| **Mock** | Yes — returns a fixed 15-page story; real impl uses GPT-4o JSON mode |
| **Validation** | `page_count` matches requested pages; page_numbers are contiguous 1..N; each `page_text` ≤ 40 words |
| **Retry** | Up to 3 with schema re-prompt on validation failure (Phase 2) |

`page_plan.json` schema:
```json
{
  "page_count": "number",
  "title": "string",
  "pages": [{
    "page_number": "number",
    "page_text": "string (≤40 words)",
    "scene_description": "string",
    "characters_in_scene": ["string"],
    "tone": "string"
  }]
}
```

---

### Step 6 — `style_bible`

| | |
|---|---|
| **Input** | `03_story/page_plan.json` |
| **Output** | `03_story/style_bible.json`, `03_story/character_bible.json` |
| **Mock** | Yes — returns fixed style; real impl derives from story content |
| **Purpose** | Defines stable visual descriptors reused across all image prompts |

---

### Step 7 — `prompt_writer`

| | |
|---|---|
| **Input** | `03_story/page_plan.json`, `03_story/style_bible.json`, `03_story/character_bible.json` |
| **Output** | `04_prompts/image_prompts.json` |
| **Rule** | Every prompt **must** include `"no text, no words, no letters"` in negative_prompt |
| **Mock** | No — constructs prompts from structured inputs |

---

### Step 8 — `image_generator`

| | |
|---|---|
| **Input** | `04_prompts/image_prompts.json` |
| **Output** | `05_images/page_01.png` … `05_images/page_N.png`, `05_images/image_manifest.json` |
| **Mock** | Yes — generates solid-colour placeholder PNGs (no external API) |
| **Checkpoint** | Skips pages where PNG already exists (resume on re-run) |
| **Real impl** | SDXL local or DALL·E API (Phase 2) |

---

### Step 9 — `image_qc`

| | |
|---|---|
| **Input** | `05_images/page_NN.png` (all N pages), `03_story/page_plan.json` |
| **Output** | `05_images/image_qc.json` |
| **Real checks** | File exists; valid PNG signature; width ≥ MIN_DIM; height ≥ MIN_DIM |
| **MIN_DIM** | 1px in Phase 1 (placeholder); raise to 512px in Phase 2 |
| **On failure** | Throws error with list of failing pages; run is aborted |

---

### Step 10 — `layout_engine`

| | |
|---|---|
| **Input** | `03_story/page_plan.json` |
| **Output** | `06_layout/layout_plan.json` |
| **Mock** | Yes — returns fixed Letter portrait layout |
| **Real impl** | Configurable per book format (A4, square, etc.) |

---

### Step 11 — `pdf_builder`

| | |
|---|---|
| **Input** | `03_story/page_plan.json`, `05_images/page_NN.png`, `06_layout/layout_plan.json` |
| **Output** | `07_pdf/book_screen.pdf`, `07_pdf/book_print.pdf` |
| **Real** | Yes — uses pdf-lib; embeds images; lays out text |
| **Validation** | Both PDFs exist; size > 0; page count = N |

---

### Step 12 — `final_qc`

| | |
|---|---|
| **Input** | `manifest.json`, `05_images/image_qc.json`, `03_story/page_plan.json` |
| **Output** | `final_report.md` |
| **Checks** | Summarises artifact count, image QC pass/fail, PDF sizes |

---

## Error Handling

- Orchestrator wraps each step in try/catch.
- On failure: logs `error` entry with step name, message, and stack trace to `run.jsonl`.
- Run is aborted; partial artifacts remain for debugging.
- Re-running with the same run_id is not currently supported (new run_id each time).

## Retry Policy (Phase 1)

No automatic retries in Phase 1. All steps are mocked or deterministic. Phase 2 will add retry logic with exponential back-off for external API calls.
