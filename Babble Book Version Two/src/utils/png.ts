/**
 * Minimal PNG generator — no external dependencies.
 * Builds a valid RGB PNG from raw pixel data using Node's built-in zlib.
 */
import { deflateSync } from 'node:zlib';

// ─── CRC-32 table (precomputed) ───────────────────────────────────────────────

const CRC_TABLE: number[] = (() => {
  const t: number[] = [];
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
    }
    t[n] = c;
  }
  return t;
})();

function crc32(buf: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of buf) {
    crc = (crc >>> 8) ^ (CRC_TABLE[(crc ^ byte) & 0xff] ?? 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function makeChunk(type: string, data: Buffer): Buffer {
  const typeBytes = Buffer.from(type, 'ascii');
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBytes, data])), 0);
  return Buffer.concat([len, typeBytes, data, crcBuf]);
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Generate a solid-colour placeholder PNG.
 * @param width  Image width in pixels
 * @param height Image height in pixels
 * @param r      Red channel 0–255
 * @param g      Green channel 0–255
 * @param b      Blue channel 0–255
 */
export function generatePlaceholderPNG(
  width: number,
  height: number,
  r: number,
  g: number,
  b: number,
): Buffer {
  // PNG file signature
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

  // IHDR chunk
  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData[8]  = 8; // bit depth
  ihdrData[9]  = 2; // color type: RGB
  ihdrData[10] = 0; // compression method
  ihdrData[11] = 0; // filter method
  ihdrData[12] = 0; // interlace method
  const ihdr = makeChunk('IHDR', ihdrData);

  // Raw image data: each row starts with filter byte 0 (None)
  const raw: number[] = [];
  for (let y = 0; y < height; y++) {
    raw.push(0); // filter byte
    for (let x = 0; x < width; x++) {
      raw.push(r, g, b);
    }
  }
  const idat = makeChunk('IDAT', deflateSync(Buffer.from(raw)));

  // IEND chunk
  const iend = makeChunk('IEND', Buffer.alloc(0));

  return Buffer.concat([sig, ihdr, idat, iend]);
}

/** 15 distinct pastel colours for per-page placeholders. */
export const PAGE_PALETTE: Array<[number, number, number]> = [
  [255, 182, 193], // light pink
  [173, 216, 230], // light blue
  [144, 238, 144], // light green
  [255, 255, 153], // light yellow
  [221, 160, 221], // plum
  [255, 200, 150], // peach
  [152, 251, 152], // pale green
  [135, 206, 250], // light sky blue
  [255, 218, 185], // peach puff
  [216, 191, 216], // thistle
  [240, 230, 140], // khaki
  [176, 224, 230], // powder blue
  [255, 160, 122], // light salmon
  [152, 245, 230], // aquamarine
  [230, 180, 255], // lavender
];
