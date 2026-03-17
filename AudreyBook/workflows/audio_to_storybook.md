# Workflow: Audio to Illustrated Storybook

## Objective
Take a single audio recording and produce a fully illustrated children's picture book PDF with:
1. Raw transcript (Whisper)
2. Cleaned narrative prose (GPT-4o)
3. 15-scene storyboard with image prompts (GPT-4o)
4. 15 watercolor-style illustrations (Stable Diffusion XL, local)
5. Final illustrated PDF book (reportlab)

---

## Prerequisites

### 1. Python dependencies
```bash
pip install -r AudreyBook/requirements.txt
```

**Important — PyTorch platform notes:**
- Apple Silicon (M1/M2/M3): `pip install torch` (standard pip, includes MPS)
- NVIDIA GPU (CUDA): `pip install torch --index-url https://download.pytorch.org/whl/cu121`
- CPU only: `pip install torch` (will work but image generation is very slow)

### 2. OpenAI API key
In `.env` at the project root, set:
```
OPENAI_API_KEY=sk-...
```
This is the only required key for steps 1–3.

### 3. First run — model download
Step 4 (`generate_images.py`) downloads ~6.5 GB of Stable Diffusion XL weights on
the first run. These are cached in `~/.cache/huggingface/hub/` and reused on all
subsequent runs. Make sure you have enough free disk space and a stable connection.

---

## Quick Run (full pipeline)
```bash
python AudreyBook/tools/run_storybook_pipeline.py --input "AudreyBook/Robinhood Rd.m4a"
```
Output: `AudreyBook/.tmp/storybook.pdf`

---

## Step-by-Step

### Step 1 — Transcribe Audio
**Tool:** `tools/transcribe_audio.py`
**Run:** `python AudreyBook/tools/transcribe_audio.py --input "AudreyBook/Robinhood Rd.m4a"`
**Output:** `AudreyBook/.tmp/transcript_raw.txt`
**What it does:** Sends the audio file to the OpenAI Whisper API (whisper-1) and writes
  the raw transcript as plain text.
**Timing:** ~30 seconds for a 5–10 minute recording.
**Cost:** ~$0.006/minute of audio.
**Check after:** Open `.tmp/transcript_raw.txt` — verify it has readable text in the
  expected language with no complete gibberish sections.
**Edge case — file over 25 MB:** The Whisper API rejects files larger than 25 MB.
  Split with ffmpeg first:
  ```bash
  ffmpeg -i input.m4a -f segment -segment_time 600 -c copy AudreyBook/part%02d.m4a
  ```
  Then run each part through Step 1 and manually concatenate the `.txt` outputs.

---

### Step 2 — Clean Narrative
**Tool:** `tools/clean_narrative.py`
**Run:** `python AudreyBook/tools/clean_narrative.py`
**Output:** `AudreyBook/.tmp/narrative_clean.txt`
**What it does:** Sends the raw transcript to GPT-4o with a prompt to rewrite it as
  warm, simple children's book prose (ages 4–8). Removes filler words, fixes transcription
  errors, smooths sentences — while preserving all story events and their order.
**Timing:** ~15–25 seconds.
**Cost:** ~$0.01–0.05 depending on transcript length.
**Check after:** Read `.tmp/narrative_clean.txt` — should be noticeably cleaner than the
  raw transcript, with simple vocabulary and flowing sentences.

---

### Step 3 — Generate Storyboard
**Tool:** `tools/generate_storyboard.py`
**Run:** `python AudreyBook/tools/generate_storyboard.py`
**Output:** `AudreyBook/.tmp/storyboard.json`
**What it does:** Sends the cleaned narrative to GPT-4o (JSON mode) and requests exactly
  15 scenes. Each scene includes:
  - `scene_number` (1–15)
  - `text` — 2-4 sentence narrative for that page
  - `image_prompt` — detailed watercolor illustration prompt for Stable Diffusion
  Validates the response and retries up to 3 times if the JSON is malformed or
  the scene count is wrong.
**Timing:** ~20–35 seconds.
**Cost:** ~$0.05–0.15 depending on narrative length.
**Check after:** Run `python -c "import json; d=json.load(open('AudreyBook/.tmp/storyboard.json')); print(d['title']); print(len(d['scenes']), 'scenes')"` — should print the book title and "15 scenes".
**Edge case — JSON retry failure:** If all 3 retries fail, the raw response is saved to
  `.tmp/storyboard_error.json` for debugging. Check it for GPT-4o refusals or malformed
  partial JSON. Usually re-running once resolves transient issues.
**Optional — override title:** Set `STORYBOOK_TITLE_OVERRIDE=My Custom Title` in `.env`
  before running. This replaces whatever title GPT-4o generates.

---

### Step 4 — Generate Images
**Tool:** `tools/generate_images.py`
**Run:** `python AudreyBook/tools/generate_images.py`
**Output:** `AudreyBook/.tmp/images/scene_01.png` … `scene_15.png` (1024×768 px each)
**What it does:** Loads Stable Diffusion XL locally and generates one illustration per
  scene. Automatically detects the best available device (MPS → CUDA → CPU). Each scene's
  `image_prompt` from the storyboard is appended with a watercolor style suffix and a
  negative prompt to keep images kid-friendly.
**Timing:**
  - Apple Silicon MPS (M1/M2/M3): ~20–40s per image → ~5–10 min total
  - NVIDIA GPU (CUDA): ~8–15s per image → ~2–4 min total
  - CPU: ~5–20 min per image → hours total (not recommended)
**First run:** Downloads ~6.5 GB of model weights (one-time, cached afterwards).
**Checkpoint/resume:** If the run is interrupted, re-running skips any `scene_NN.png`
  that already exists. You never lose completed images.
**Edge case — out of memory (OOM):** If you see a MPS/CUDA OOM error:
  1. Reduce `SD_NUM_INFERENCE_STEPS` in `.env` (e.g., from 30 to 20)
  2. Close other GPU-heavy apps
  3. On MPS: add `pipe.enable_model_cpu_offload()` after the pipeline load (edit the script)
**Optional — higher quality:** Set `SD_USE_REFINER=true` in `.env` to run the SDXL refiner
  pass. Adds ~6 GB download and roughly doubles generation time per image.
**Optional — different model:** Change `SD_MODEL_ID` in `.env` to any SDXL-compatible
  HuggingFace model (e.g., `SG161222/RealVisXL_V4.0` for photorealistic style).

---

### Step 5 — Build PDF
**Tool:** `tools/build_pdf.py`
**Run:** `python AudreyBook/tools/build_pdf.py`
**Output:** `AudreyBook/.tmp/storybook.pdf`
**What it does:** Assembles the book in landscape Letter format (11×8.5 in):
  - Page 1: Title page with book title and optional author name
  - Pages 2–16: One page per scene — image (top 65%) + narrative text (bottom 25%)
  Overwrites any existing `storybook.pdf` on each run.
**Timing:** ~5–10 seconds.
**Check after:** Open `.tmp/storybook.pdf` in Preview — verify title page, all 15 scenes
  have an image and text, no blank pages, text is readable.
**Optional — author name:** Set `STORYBOOK_AUTHOR=Your Name` in `.env` before running.

---

## Intermediate Files Reference

| File | Created by | Description |
|---|---|---|
| `.tmp/transcript_raw.txt` | Step 1 | Whisper raw output, plain text |
| `.tmp/narrative_clean.txt` | Step 2 | GPT-4o polished prose |
| `.tmp/storyboard.json` | Step 3 | 15-scene JSON with image prompts |
| `.tmp/images/scene_NN.png` | Step 4 | Generated illustrations (1024×768) |
| `.tmp/storybook.pdf` | Step 5 | Final illustrated book |
| `.tmp/storyboard_error.json` | Step 3 (on failure) | Raw GPT response for debugging |

All `.tmp/` files are disposable and regenerated by re-running the relevant step.

---

## .env Keys

| Key | Required | Default | Used by |
|---|---|---|---|
| `OPENAI_API_KEY` | **Yes** | — | Steps 1, 2, 3 |
| `SD_MODEL_ID` | No | `stabilityai/stable-diffusion-xl-base-1.0` | Step 4 |
| `SD_USE_REFINER` | No | `false` | Step 4 |
| `SD_NUM_INFERENCE_STEPS` | No | `30` | Step 4 |
| `STORYBOOK_AUTHOR` | No | `""` | Step 5 (title page) |
| `STORYBOOK_TITLE_OVERRIDE` | No | `""` | Step 3 (overrides GPT title) |

---

## Cost Estimate (per full run)

| Step | API | Estimated cost |
|---|---|---|
| Transcription (5 min audio) | OpenAI Whisper | ~$0.03 |
| Narrative clean | OpenAI GPT-4o | ~$0.02–0.05 |
| Storyboard | OpenAI GPT-4o | ~$0.05–0.15 |
| Image generation | Local (free) | $0 |
| PDF build | Local (free) | $0 |
| **Total** | | **~$0.10–0.23** |

---

## Known Constraints & Lessons Learned

- **Whisper 25 MB limit:** Split large audio files with ffmpeg before transcribing.
- **GPT-4o JSON mode:** Using `response_format={"type": "json_object"}` is reliable for
  15-scene output but the system prompt must explicitly say "exactly 15 scenes" — without
  it, GPT-4o sometimes generates 10–20 scenes.
- **SDXL on Apple Silicon:** `torch.float16` with `enable_attention_slicing()` keeps
  memory usage manageable on 16 GB M-series machines. 8 GB machines may need cpu offload.
- **Watercolor style prompts:** Adding "no text, no words, no letters" to both the prompt
  and negative prompt is critical — SD tends to hallucinate text overlaid on images.
- **PDF layout:** `KeepTogether` in reportlab ensures the image and its text always land
  on the same page and don't get split across a page boundary.
