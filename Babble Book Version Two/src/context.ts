import { createHash } from 'node:crypto';
import { readFileSync, appendFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import type { ManifestEntry, Manifest, LogLevel } from './types.js';

export interface RunDirs {
  raw: string;
  audio: string;
  transcript: string;
  story: string;
  prompts: string;
  images: string;
  layout: string;
  pdf: string;
  logs: string;
}

export class RunContext {
  readonly run_id: string;
  readonly run_dir: string;
  readonly dirs: RunDirs;
  readonly manifestPath: string;
  private readonly logPath: string;
  private manifest: Manifest;

  constructor(run_id: string, baseDir: string) {
    this.run_id = run_id;
    this.run_dir = join(baseDir, run_id);

    this.dirs = {
      raw:        join(this.run_dir, '00_raw'),
      audio:      join(this.run_dir, '01_audio'),
      transcript: join(this.run_dir, '02_transcript'),
      story:      join(this.run_dir, '03_story'),
      prompts:    join(this.run_dir, '04_prompts'),
      images:     join(this.run_dir, '05_images'),
      layout:     join(this.run_dir, '06_layout'),
      pdf:        join(this.run_dir, '07_pdf'),
      logs:       join(this.run_dir, 'logs'),
    };

    this.manifestPath = join(this.run_dir, 'manifest.json');
    this.logPath      = join(this.dirs.logs, 'run.jsonl');

    this.manifest = {
      run_id,
      created_at: new Date().toISOString(),
      artifacts: [],
    };
  }

  /** Create all run subdirectories and write an initial manifest. */
  init(): void {
    mkdirSync(this.run_dir, { recursive: true });
    for (const dir of Object.values(this.dirs)) {
      mkdirSync(dir, { recursive: true });
    }
    this.saveManifest();
    this.log('init', 'info', `Run initialised: ${this.run_id}`);
  }

  /** Write a structured log entry to run.jsonl and stdout/stderr. */
  log(step: string, level: LogLevel, msg: string): void {
    const entry = {
      run_id: this.run_id,
      step,
      level,
      msg,
      ts: new Date().toISOString(),
    };
    try {
      appendFileSync(this.logPath, JSON.stringify(entry) + '\n');
    } catch {
      // logPath directory may not exist on the very first log call before init()
    }
    const tag = `[${level.toUpperCase().padEnd(5)}][${step.padEnd(22)}]`;
    if (level === 'error') {
      console.error(`${tag} ${msg}`);
    } else {
      console.log(`${tag} ${msg}`);
    }
  }

  /** Compute SHA-256 hex digest of a file. */
  sha256(filePath: string): string {
    const buf = readFileSync(filePath);
    return createHash('sha256').update(buf).digest('hex');
  }

  /** Register an artifact in manifest.json. */
  addToManifest(filePath: string, step: string, meta: Record<string, unknown> = {}): void {
    const entry: ManifestEntry = {
      path: filePath,
      sha256: this.sha256(filePath),
      created_at: new Date().toISOString(),
      step,
      meta,
    };
    this.manifest.artifacts.push(entry);
    this.saveManifest();
  }

  getManifest(): Manifest {
    return this.manifest;
  }

  private saveManifest(): void {
    writeFileSync(this.manifestPath, JSON.stringify(this.manifest, null, 2));
  }
}
