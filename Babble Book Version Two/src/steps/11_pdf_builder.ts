import { readFileSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { PDFDocument, StandardFonts, rgb, type PDFFont } from 'pdf-lib';
import type { RunContext } from '../context.js';
import type { RunOptions, StoryPlan, LayoutPlan } from '../types.js';

const STEP = 'pdf_builder';

// ─── Text helpers ─────────────────────────────────────────────────────────────

function wordWrap(text: string, font: PDFFont, size: number, maxWidth: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let current = '';

  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (font.widthOfTextAtSize(candidate, size) > maxWidth && current !== '') {
      lines.push(current);
      current = word;
    } else {
      current = candidate;
    }
  }
  if (current) lines.push(current);
  return lines;
}

// ─── Core PDF builder ─────────────────────────────────────────────────────────

async function buildPDF(
  plan: StoryPlan,
  layout: LayoutPlan,
  imagesDir: string,
): Promise<Uint8Array> {
  const pdfDoc = await PDFDocument.create();
  const font   = await pdfDoc.embedFont(StandardFonts.Helvetica);
  const fontB  = await pdfDoc.embedFont(StandardFonts.HelveticaBold);

  const { page_size, image_box, text_box, header, font_size } = layout;
  const LINE_HEIGHT = font_size * 1.5;

  for (const page of plan.pages) {
    const pdfPage = pdfDoc.addPage([page_size.width, page_size.height]);

    // ── Header ──────────────────────────────────────────────────────────────
    const headerText = page.page_number === 1
      ? plan.title
      : `Page ${page.page_number}`;
    const headerFont = page.page_number === 1 ? fontB : font;
    const headerSize = page.page_number === 1 ? 16 : 11;

    pdfPage.drawText(headerText, {
      x:    header.x,
      y:    header.y,
      size: headerSize,
      font: headerFont,
      color: rgb(0.2, 0.2, 0.2),
    });

    // Thin rule under header
    pdfPage.drawLine({
      start: { x: header.x, y: header.y - 4 },
      end:   { x: page_size.width - layout.margins.right, y: header.y - 4 },
      thickness: 0.5,
      color: rgb(0.7, 0.7, 0.7),
    });

    // ── Image ────────────────────────────────────────────────────────────────
    const imgName = `page_${String(page.page_number).padStart(2, '0')}.png`;
    const imgPath = join(imagesDir, imgName);
    try {
      const imgBytes = readFileSync(imgPath);
      const embImg   = await pdfDoc.embedPng(imgBytes);
      pdfPage.drawImage(embImg, {
        x:      image_box.x,
        y:      image_box.y,
        width:  image_box.width,
        height: image_box.height,
      });
    } catch (e) {
      // Fallback: draw a grey placeholder rectangle
      pdfPage.drawRectangle({
        x:      image_box.x,
        y:      image_box.y,
        width:  image_box.width,
        height: image_box.height,
        color:  rgb(0.9, 0.9, 0.9),
      });
      pdfPage.drawText(`[Image: ${imgName}]`, {
        x: image_box.x + 10, y: image_box.y + image_box.height / 2,
        size: 10, font, color: rgb(0.5, 0.5, 0.5),
      });
    }

    // ── Page text (word-wrapped) ──────────────────────────────────────────────
    const lines = wordWrap(page.page_text, font, font_size, text_box.width);
    const textStartY = text_box.y + text_box.height - LINE_HEIGHT;
    lines.forEach((line, i) => {
      pdfPage.drawText(line, {
        x:    text_box.x,
        y:    textStartY - i * LINE_HEIGHT,
        size: font_size,
        font,
        color: rgb(0.1, 0.1, 0.1),
      });
    });
  }

  return pdfDoc.save();
}

// ─── Step ─────────────────────────────────────────────────────────────────────

export async function pdfBuilder(ctx: RunContext, opts: RunOptions): Promise<void> {
  ctx.log(STEP, 'info', 'start');
  void opts;

  const plan: StoryPlan = JSON.parse(
    readFileSync(join(ctx.dirs.story, 'page_plan.json'), 'utf-8'),
  );
  const layout: LayoutPlan = JSON.parse(
    readFileSync(join(ctx.dirs.layout, 'layout_plan.json'), 'utf-8'),
  );

  ctx.log(STEP, 'info', `Building PDFs for "${plan.title}" (${plan.page_count} pages)…`);

  const pdfBytes = await buildPDF(plan, layout, ctx.dirs.images);

  // ── Write book_screen.pdf ─────────────────────────────────────────────────
  const screenPath = join(ctx.dirs.pdf, 'book_screen.pdf');
  writeFileSync(screenPath, pdfBytes);
  ctx.addToManifest(screenPath, STEP, {
    type: 'pdf_screen',
    pages: plan.page_count,
    size_bytes: statSync(screenPath).size,
  });
  ctx.log(STEP, 'info', `book_screen.pdf → ${statSync(screenPath).size} bytes`);

  // ── Write book_print.pdf (same content in Phase 1) ────────────────────────
  const printPath = join(ctx.dirs.pdf, 'book_print.pdf');
  writeFileSync(printPath, pdfBytes);
  ctx.addToManifest(printPath, STEP, {
    type: 'pdf_print',
    pages: plan.page_count,
    size_bytes: statSync(printPath).size,
    note: 'Phase 1: identical to screen PDF. Phase 2+ will apply CMYK conversion and bleed marks.',
  });
  ctx.log(STEP, 'info', `book_print.pdf  → ${statSync(printPath).size} bytes`);

  // ── Validate ──────────────────────────────────────────────────────────────
  for (const [label, path] of [['screen', screenPath], ['print', printPath]] as const) {
    const size = statSync(path).size;
    if (size === 0) throw new Error(`${label} PDF is empty: ${path}`);
    // Verify PDF magic bytes
    const magic = readFileSync(path).subarray(0, 5).toString('ascii');
    if (magic !== '%PDF-') throw new Error(`${label} PDF has invalid header: ${magic}`);
  }

  ctx.log(STEP, 'info', 'done — both PDFs valid');
}
