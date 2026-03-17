/**
 * Generates a minimal valid WAV file containing silence.
 * Used by the `demo` command to provide a zero-dependency audio input.
 */
export function generateDemoWAV(durationSeconds = 3): Buffer {
  const sampleRate    = 8000;
  const numChannels   = 1;
  const bitsPerSample = 16;
  const numSamples    = sampleRate * durationSeconds;
  const dataSize      = numSamples * numChannels * (bitsPerSample / 8);
  const buf           = Buffer.alloc(44 + dataSize, 0);
  let   off           = 0;

  // RIFF header
  buf.write('RIFF',   off); off += 4;
  buf.writeUInt32LE(36 + dataSize, off); off += 4;
  buf.write('WAVE',   off); off += 4;

  // fmt sub-chunk
  buf.write('fmt ',   off); off += 4;
  buf.writeUInt32LE(16, off); off += 4;            // chunk size
  buf.writeUInt16LE(1,  off); off += 2;            // PCM
  buf.writeUInt16LE(numChannels, off); off += 2;
  buf.writeUInt32LE(sampleRate,  off); off += 4;
  buf.writeUInt32LE(sampleRate * numChannels * (bitsPerSample / 8), off); off += 4;
  buf.writeUInt16LE(numChannels * (bitsPerSample / 8), off); off += 2; // block align
  buf.writeUInt16LE(bitsPerSample, off); off += 2;

  // data sub-chunk
  buf.write('data',   off); off += 4;
  buf.writeUInt32LE(dataSize, off);
  // remaining bytes are already zero (silence)

  return buf;
}
