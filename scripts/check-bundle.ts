// npm run check-bundle -- <dir>: loads a bundle folder exactly as the app does (zod schemas + alignment checks),
// then checks that every image the manifest names exists and that the PRD 5.11 size budget holds.
// Exit code 0 means the app will load this folder with no code change. Used by pipeline/08_export.py.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { BundleError, loadBundle } from '../src/data/load';

const BASE = 'bundle://';

export async function checkBundleDir(dir: string): Promise<string[]> {
  const problems: string[] = [];
  const fetchFile = (async (url: RequestInfo | URL) => {
    const p = join(dir, String(url).slice(BASE.length));
    return existsSync(p) ? new Response(readFileSync(p)) : new Response('not found', { status: 404 });
  }) as typeof fetch;

  let b;
  try {
    b = await loadBundle(BASE, fetchFile);
  } catch (e) {
    return [e instanceof BundleError ? e.message : String(e)];
  }

  const m = b.manifest;
  for (const f of [...m.images.radar.map((r) => r.file), m.images.reveal.optical_file, m.images.reveal.radar_file])
    if (!existsSync(join(dir, f))) problems.push(`manifest.json names ${f}, which is missing`);
  for (const r of m.images.radar) if (!m.dates.includes(r.date)) problems.push(`images.radar date ${r.date} is not in dates`);
  if (!m.dates.includes(m.images.reveal.date)) problems.push(`images.reveal.date ${m.images.reveal.date} is not in dates`);

  let data = 0, img = 0;
  const walk = (d: string) => {
    for (const name of readdirSync(d)) {
      const p = join(d, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (name.endsWith('.png')) img += statSync(p).size;
      else data += statSync(p).size;
    }
  };
  walk(dir);
  if (data > 6e6) problems.push(`non-image files are ${(data / 1e6).toFixed(2)} MB, over the 6 MB budget`);
  if (img > 10e6) problems.push(`images are ${(img / 1e6).toFixed(2)} MB, over the 10 MB budget`);
  if (!problems.length)
    console.log(`ok: ${b.series.cells.length} cells, ${m.dates.length} dates, data ${(data / 1e6).toFixed(2)} MB, images ${(img / 1e6).toFixed(2)} MB`);
  return problems;
}

if (process.argv[1]?.endsWith('check-bundle.ts')) {
  const dir = resolve(process.argv[2] ?? 'public/bundle');
  const problems = await checkBundleDir(dir);
  for (const p of problems) console.error(`bundle check failed: ${p}`);
  process.exit(problems.length ? 1 : 0);
}
