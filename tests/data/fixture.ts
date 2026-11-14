import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const dir = join(__dirname, '../../public/bundle');
export const readJson = (name: string) => JSON.parse(readFileSync(join(dir, name), 'utf8'));

/** A fetch stand-in serving the committed bundle, with optional per-file overrides. */
export function fakeFetch(overrides: Record<string, unknown> = {}): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const name = String(input).split('/').pop()!;
    if (name in overrides) {
      const v = overrides[name];
      if (v === 404) return new Response('not found', { status: 404 });
      return new Response(typeof v === 'string' ? v : JSON.stringify(v));
    }
    return new Response(readFileSync(join(dir, name)));
  }) as typeof fetch;
}
