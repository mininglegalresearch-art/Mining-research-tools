# Babel Books — North Star Product Contract

## Goal

Transform an audio recording of a child (ages 3–10) into a polished 15-page illustrated children's book, delivered as a print-ready PDF and screen-optimised PDF.

---

## Inputs

| Input | Type | Required | Notes |
|---|---|---|---|
| `audio_file` | `.wav`, `.mp3`, `.m4a`, `.ogg` | **Yes** | Raw recording of child narrating or babbling a story |
| `pages` | integer | No | Defaults to 15 |
| `metadata.author` | string | No | Author name for title page |
| `metadata.title_override` | string | No | Override auto-generated title |

---

## Outputs

| Output | Format | Description |
|---|---|---|
| `book_screen.pdf` | PDF/A screen | RGB colour, 72 dpi, suitable for digital reading |
| `book_print.pdf` | PDF print | CMYK-ready, 300 dpi artwork, bleed marks (placeholder in Phase 1) |
| `archive_bundle` | `.zip` | All intermediates + PDFs (Phase 2+) |

---

## Constraints

### Privacy
- No audio leaves the local machine (ASR is local or opt-in cloud in future phases).
- No personally identifiable information written to logs beyond the run_id.
- All intermediate files stay in `runs/<run_id>/` and can be deleted at any time.

### Determinism & Auditability
- Every run is isolated in its own directory (`runs/<run_id>/`).
- Every artifact is indexed in `manifest.json` with a SHA-256 hash.
- Every step logs start/end + any errors to `logs/run.jsonl` (structured JSONL).
- A run can be fully re-inspected after the fact using `babelbooks inspect --run <id>`.

### Cost Tracking (placeholders — Phase 2+)
- ASR step will record `{ api: 'openai_whisper', chars: N, estimated_cost_usd: 0 }` in its output JSON.
- Story writer step will record token counts and estimated costs.
- A `cost_summary.json` will aggregate costs per run (structure reserved, not implemented in Phase 1).

---

## Success Criteria

| Criterion | Measure |
|---|---|
| End-to-end completion | `npm run demo` exits 0 with all 15 pages in both PDFs |
| Artifact integrity | `manifest.json` contains all expected artifacts with valid SHA-256 |
| Reproducibility | Two runs on the same input produce structurally identical PDFs (same page count, text) |
| Auditability | `babelbooks inspect --run <id>` prints a grouped artifact summary |
| QC gate | If any page image is missing, `image_qc` step fails the run with a clear error message |

---

## Phase Roadmap

| Phase | Scope |
|---|---|
| **Phase 0** | North star docs, workflow contract, artifact schema |
| **Phase 1** | Local deterministic engine, mock ASR/AI, real PDF output |
| **Phase 2** | Real ASR (Whisper), real story writer (GPT-4o), real image gen (SDXL/DALL·E) |
| **Phase 3** | KDP upload integration, cost tracking, archive bundle |
| **Phase 4** | Web UI, user accounts, order management |
