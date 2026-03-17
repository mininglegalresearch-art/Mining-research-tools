/**
 * Minimal type declaration for busboy v1.x
 * (busboy does not ship its own .d.ts in v1.6.x)
 */
import type { IncomingHttpHeaders } from 'node:http';
import type { Readable } from 'node:stream';
import type { EventEmitter } from 'node:events';

declare module 'busboy' {
  interface FileInfo {
    filename: string;
    encoding: string;
    mimeType: string;
  }

  interface BusboyConfig {
    headers: IncomingHttpHeaders;
    limits?: {
      fieldSize?: number;
      fields?: number;
      fileSize?: number;
      files?: number;
      parts?: number;
    };
  }

  interface BusboyInstance extends EventEmitter {
    on(event: 'file',   listener: (field: string, stream: Readable, info: FileInfo) => void): this;
    on(event: 'field',  listener: (name: string, val: string) => void): this;
    on(event: 'finish', listener: () => void): this;
    on(event: 'error',  listener: (err: Error) => void): this;
    on(event: string,   listener: (...args: unknown[]) => void): this;
  }

  function Busboy(config: BusboyConfig): BusboyInstance;
  export default Busboy;
}
