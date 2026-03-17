/**
 * Babel Books — local HTTP server
 *
 * Receives audio file uploads from the Squarespace page,
 * triggers the workflow pipeline, and exposes a polling endpoint
 * so the browser can track per-step progress.
 *
 * Run:  npm run serve
 * Stop: Ctrl-C
 */
import http from 'node:http';
import { createWriteStream, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import Busboy from 'busboy';

import { RunContext }              from './context.js';
import { runWorkflow }             from './orchestrator.js';
import type { RunOptions }         from './types.js';

// ─── Config ───────────────────────────────────────────────────────────────────

const PORT        = parseInt(process.env.PORT ?? '3001', 10);
const UPLOADS_DIR = resolve('uploads');
const RUNS_DIR    = resolve('runs');
const MAX_MB      = 200;

// ─── In-memory run status store ───────────────────────────────────────────────

interface UploadStatus {
  status:     'uploading' | 'processing' | 'complete' | 'error';
  step?:      string;        // name of step currently running
  steps_done: string[];      // names of steps that have finished
  run_id?:    string;
  error?:     string;
}

const statuses = new Map<string, UploadStatus>();

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeId(prefix: string): string {
  const d   = new Date();
  const pad = (n: number) => n.toString().padStart(2, '0');
  const rnd = Math.random().toString(36).slice(2, 6);
  return `${prefix}_${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_` +
         `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}_${rnd}`;
}

function setCORS(res: http.ServerResponse): void {
  res.setHeader('Access-Control-Allow-Origin',  '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Accept');
}

function sendJSON(res: http.ServerResponse, code: number, data: unknown): void {
  setCORS(res);
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

// ─── Request handler ──────────────────────────────────────────────────────────

const server = http.createServer((req, res) => {
  setCORS(res);

  // Pre-flight
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  // ── POST /upload ────────────────────────────────────────────────────────────
  if (req.method === 'POST' && req.url === '/upload') {
    const uploadId = makeId('up');
    statuses.set(uploadId, { status: 'uploading', steps_done: [] });

    let savedPath = '';
    let fileError = '';

    const bb = Busboy({
      headers: req.headers,
      limits:  { fileSize: MAX_MB * 1024 * 1024 },
    });

    bb.on('file', (_field, stream, info) => {
      mkdirSync(UPLOADS_DIR, { recursive: true });
      // Sanitise filename before writing to disk
      const safe = info.filename.replace(/[^a-zA-Z0-9._\- ]/g, '_').slice(0, 120);
      savedPath  = join(UPLOADS_DIR, `${Date.now()}_${safe}`);
      const ws   = createWriteStream(savedPath);

      stream.on('limit', () => {
        fileError = `File exceeds the ${MAX_MB} MB limit`;
        stream.resume(); // drain so busboy finishes
      });
      stream.pipe(ws);
    });

    bb.on('finish', () => {
      if (fileError) {
        sendJSON(res, 413, { error: fileError });
        return;
      }
      if (!savedPath) {
        sendJSON(res, 400, { error: 'No audio file was received' });
        return;
      }

      // Respond immediately — client will poll for progress
      sendJSON(res, 200, { upload_id: uploadId, status: 'processing' });

      // Launch pipeline in the background (do not await)
      const run_id = makeId('run');
      statuses.set(uploadId, { status: 'processing', run_id, steps_done: [] });

      const ctx  = new RunContext(run_id, RUNS_DIR);
      const opts: RunOptions = {
        audioPath: savedPath,
        pages:     15,
        outDir:    RUNS_DIR,
        demo:      false,
      };

      runWorkflow(ctx, opts, (step, done) => {
        const cur = statuses.get(uploadId)!;
        statuses.set(uploadId, {
          ...cur,
          step,
          steps_done: done ? [...cur.steps_done, step] : cur.steps_done,
        });
      })
        .then(() => {
          const cur = statuses.get(uploadId)!;
          statuses.set(uploadId, { ...cur, status: 'complete', step: undefined });
          console.log(`\n✓ [${uploadId}] Run complete → runs/${run_id}`);
        })
        .catch((err: Error) => {
          const cur = statuses.get(uploadId)!;
          statuses.set(uploadId, { ...cur, status: 'error', error: err.message });
          console.error(`\n✗ [${uploadId}] Run failed: ${err.message}`);
        });
    });

    bb.on('error', (err: Error) => {
      sendJSON(res, 500, { error: `Upload error: ${err.message}` });
    });

    req.pipe(bb);
    return;
  }

  // ── GET /status/:upload_id ──────────────────────────────────────────────────
  if (req.method === 'GET' && req.url?.startsWith('/status/')) {
    const id = req.url.slice('/status/'.length);
    const s  = statuses.get(id);
    if (!s) {
      sendJSON(res, 404, { error: 'Unknown upload ID' });
      return;
    }
    sendJSON(res, 200, s);
    return;
  }

  // ── GET /health ─────────────────────────────────────────────────────────────
  if (req.method === 'GET' && req.url === '/health') {
    sendJSON(res, 200, { ok: true, ts: new Date().toISOString() });
    return;
  }

  sendJSON(res, 404, { error: 'Not found' });
});

// ─── Start ────────────────────────────────────────────────────────────────────

server.listen(PORT, '127.0.0.1', () => {
  console.log('\n┌─────────────────────────────────────────┐');
  console.log(`│  Babel Books server                     │`);
  console.log(`│  http://localhost:${PORT}                  │`);
  console.log('└─────────────────────────────────────────┘');
  console.log(`\n  Upload : POST http://localhost:${PORT}/upload`);
  console.log(`  Status : GET  http://localhost:${PORT}/status/:id`);
  console.log(`  Health : GET  http://localhost:${PORT}/health`);
  console.log('\nWaiting for uploads…\n');
});

server.on('error', (err: NodeJS.ErrnoException) => {
  if (err.code === 'EADDRINUSE') {
    console.error(`\n✗ Port ${PORT} is already in use. Change PORT env var or stop the other process.\n`);
  } else {
    console.error('\n✗ Server error:', err.message);
  }
  process.exit(1);
});
