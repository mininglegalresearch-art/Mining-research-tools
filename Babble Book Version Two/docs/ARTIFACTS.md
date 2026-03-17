# Babel Books — Artifact Reference

## Run Directory Layout

```
runs/
└── <run_id>/
    ├── manifest.json            ← Index of every artifact (SHA-256, step, timestamp)
    ├── final_report.md          ← Step 12 QC summary
    ├── 00_raw/
    │   ├── <original_filename>  ← Copy of input audio
    │   └── metadata.json
    ├── 01_audio/
    │   ├── normalized.wav       ← Pre-processed audio
    │   └── audio_prep.json
    ├── 02_transcript/
    │   ├── raw_transcript.txt   ← ASR output (may contain [babble]/[unclear])
    │   ├── timestamps.json      ← Word-level timestamps (optional)
    │   ├── clean_transcript.txt ← Cleaned narrative
    │   └── assumptions.json     ← Inference log from cleaner
    ├── 03_story/
    │   ├── story.md             ← Full narrative prose
    │   ├── page_plan.json       ← Structured 15-page breakdown
    │   ├── style_bible.json     ← Visual style directives
    │   └── character_bible.json ← Per-character stable descriptors
    ├── 04_prompts/
    │   └── image_prompts.json   ← One prompt per page
    ├── 05_images/
    │   ├── page_01.png          ← Illustration for page 1
    │   ├── ...
    │   ├── page_15.png          ← Illustration for page 15
    │   ├── image_manifest.json  ← Per-image metadata
    │   └── image_qc.json        ← QC pass/fail per page
    ├── 06_layout/
    │   └── layout_plan.json     ← Page size, margins, box positions
    ├── 07_pdf/
    │   ├── book_screen.pdf      ← Screen-optimised PDF
    │   └── book_print.pdf       ← Print-ready PDF
    └── logs/
        └── run.jsonl            ← Structured log (one JSON object per line)
```

---

## Artifact Definitions

### `manifest.json`

Root index file. Written after every artifact is produced.

```json
{
  "run_id": "string",
  "created_at": "ISO8601",
  "artifacts": [
    {
      "path": "/absolute/path/to/artifact",
      "sha256": "hex string (64 chars)",
      "created_at": "ISO8601",
      "step": "step_name",
      "meta": {}
    }
  ]
}
```

### `logs/run.jsonl`

One JSON object per line. Every log entry must contain:

```json
{
  "run_id": "string",
  "step": "string",
  "level": "debug | info | warn | error",
  "msg": "string",
  "ts": "ISO8601"
}
```

### `00_raw/metadata.json`

```json
{
  "run_id": "string",
  "original_filename": "string",
  "raw_path": "string",
  "pages": 15,
  "created_at": "ISO8601",
  "demo": false
}
```

### `01_audio/audio_prep.json`

```json
{
  "input": "string",
  "output": "string",
  "normalized": false,
  "notes": "string",
  "created_at": "ISO8601"
}
```

### `02_transcript/timestamps.json`

```json
{
  "source": "mock | whisper",
  "entries": [
    {
      "start_ms": 0,
      "end_ms": 500,
      "text": "string",
      "confidence": 0.95
    }
  ]
}
```

### `02_transcript/assumptions.json`

```json
{
  "created_at": "ISO8601",
  "model": "mock | gpt-4o",
  "assumptions": [
    {
      "original": "[babble]",
      "interpreted_as": "I went",
      "confidence": "low | medium | high",
      "note": "string"
    }
  ]
}
```

### `03_story/page_plan.json`

```json
{
  "page_count": 15,
  "title": "string",
  "pages": [
    {
      "page_number": 1,
      "page_text": "string (≤40 words)",
      "scene_description": "string",
      "characters_in_scene": ["string"],
      "tone": "string"
    }
  ]
}
```

### `03_story/style_bible.json`

```json
{
  "art_style": "string",
  "color_palette": ["#hex"],
  "mood": "string",
  "rendering_notes": "string",
  "negative_constraints": ["string"]
}
```

### `03_story/character_bible.json`

```json
{
  "characters": [
    {
      "name": "string",
      "age": "string",
      "appearance": "string",
      "clothing": "string",
      "distinguishing_features": "string"
    }
  ]
}
```

### `04_prompts/image_prompts.json`

```json
{
  "title": "string",
  "style_summary": "string",
  "prompts": [
    {
      "page_number": 1,
      "prompt": "string",
      "negative_prompt": "no text, no words, no letters, ...",
      "style_reference": "string"
    }
  ]
}
```

### `05_images/image_manifest.json`

```json
{
  "run_id": "string",
  "entries": [
    {
      "page_number": 1,
      "path": "string",
      "prompt": "string",
      "mock": true
    }
  ]
}
```

### `05_images/image_qc.json`

```json
{
  "run_id": "string",
  "total_pages": 15,
  "all_pass": true,
  "min_dimension_check": 1,
  "results": [
    {
      "page_number": 1,
      "path": "string",
      "exists": true,
      "valid_png": true,
      "width": 200,
      "height": 150,
      "passes": true
    }
  ]
}
```

### `06_layout/layout_plan.json`

```json
{
  "page_size": { "width": 612, "height": 792, "unit": "pt" },
  "margins": { "top": 40, "right": 50, "bottom": 40, "left": 50 },
  "header": { "x": 50, "y": 762, "height": 20 },
  "image_box": { "x": 50, "y": 362, "width": 512, "height": 380 },
  "text_box": { "x": 50, "y": 80, "width": 512, "height": 260 },
  "font_size": 14
}
```

---

## Naming Conventions

- `run_id` format: `run_YYYYMMDD_HHMMss` for live runs, `demo_YYYYMMDD_HHMMss` for demo runs.
- Image files: zero-padded to 2 digits, e.g., `page_01.png` through `page_15.png`.
- All timestamps: ISO 8601 UTC, e.g., `2024-03-01T12:00:00.000Z`.
- SHA-256 hashes: lowercase hex, 64 characters.
