// ─── Manifest & Logging ───────────────────────────────────────────────────────

export interface ManifestEntry {
  path: string;
  sha256: string;
  created_at: string;
  step: string;
  meta: Record<string, unknown>;
}

export interface Manifest {
  run_id: string;
  created_at: string;
  artifacts: ManifestEntry[];
}

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogEntry {
  run_id: string;
  step: string;
  level: LogLevel;
  msg: string;
  ts: string;
}

// ─── CLI / Orchestrator ────────────────────────────────────────────────────────

export interface RunOptions {
  audioPath: string;
  pages: number;
  outDir: string;
  demo: boolean;
}

// ─── Step 1: intake_job ───────────────────────────────────────────────────────

export interface JobMetadata {
  run_id: string;
  original_filename: string;
  raw_path: string;
  pages: number;
  created_at: string;
  demo: boolean;
}

// ─── Step 2: preprocess_audio ─────────────────────────────────────────────────

export interface AudioPrepResult {
  input: string;
  output: string;
  normalized: boolean;
  notes: string;
  created_at: string;
}

// ─── Step 3: asr_transcribe ───────────────────────────────────────────────────

export interface TimestampEntry {
  start_ms: number;
  end_ms: number;
  text: string;
  confidence: number;
}

export interface TranscriptTimestamps {
  source: string;
  entries: TimestampEntry[];
}

// ─── Step 4: transcript_cleaner ───────────────────────────────────────────────

export interface Assumption {
  original: string;
  interpreted_as: string;
  confidence: 'low' | 'medium' | 'high';
  note: string;
}

export interface AssumptionsLog {
  created_at: string;
  model: string;
  assumptions: Assumption[];
}

// ─── Step 5: storywriter ──────────────────────────────────────────────────────

export interface PagePlan {
  page_number: number;
  page_text: string;
  scene_description: string;
  characters_in_scene: string[];
  tone: string;
}

export interface StoryPlan {
  page_count: number;
  title: string;
  pages: PagePlan[];
}

// ─── Step 6: style_bible ──────────────────────────────────────────────────────

export interface StyleBible {
  art_style: string;
  color_palette: string[];
  mood: string;
  rendering_notes: string;
  negative_constraints: string[];
}

export interface CharacterDescriptor {
  name: string;
  age: string;
  appearance: string;
  clothing: string;
  distinguishing_features: string;
}

export interface CharacterBible {
  characters: CharacterDescriptor[];
}

// ─── Step 7: prompt_writer ────────────────────────────────────────────────────

export interface ImagePrompt {
  page_number: number;
  prompt: string;
  negative_prompt: string;
  style_reference: string;
}

export interface ImagePromptManifest {
  title: string;
  style_summary: string;
  prompts: ImagePrompt[];
}

// ─── Step 8: image_generator ──────────────────────────────────────────────────

export interface ImageEntry {
  page_number: number;
  path: string;
  prompt: string;
  mock: boolean;
}

export interface ImageManifest {
  run_id: string;
  entries: ImageEntry[];
}

// ─── Step 9: image_qc ─────────────────────────────────────────────────────────

export interface ImageQCResult {
  page_number: number;
  path: string;
  exists: boolean;
  valid_png: boolean;
  width: number | null;
  height: number | null;
  passes: boolean;
  error?: string;
}

export interface ImageQCReport {
  run_id: string;
  total_pages: number;
  all_pass: boolean;
  min_dimension_check: number;
  results: ImageQCResult[];
}

// ─── Step 10: layout_engine ───────────────────────────────────────────────────

export interface LayoutBox {
  x: number;
  y: number;
  width?: number;
  height: number;
}

export interface LayoutPlan {
  page_size: { width: number; height: number; unit: string };
  margins: { top: number; right: number; bottom: number; left: number };
  header: LayoutBox & { x: number; y: number };
  image_box: LayoutBox & { width: number };
  text_box: LayoutBox & { width: number };
  font_size: number;
}
