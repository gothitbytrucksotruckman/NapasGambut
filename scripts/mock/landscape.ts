// Procedural landscape (PRD 6.1, 6.2). Works in km on a local plane, x east, y south from the NW corner.
import type { ClassId } from '../../src/contract';
import { type Rng, randInt, uniform } from './rng';

export const GRID = { rows: 80, cols: 80, cellKm: 0.5, deg: 0.0045, west: 113.9, north: -2.59 } as const;
export const BBOX: [number, number, number, number] = [113.9, -2.95, 114.26, -2.59];

type XY = [number, number];
export type LonLat = [number, number];

export interface LandCell {
  id: string;
  row: number;
  col: number;
  cls: ClassId;
  canalDensity: number; // km per km2 within 1 km of the centroid
  cf: number; // canal density scaled 0..1 across all cells
  treeCover: number;
  nPixels: number;
  centroid: LonLat;
}

export interface Landscape {
  cells: LandCell[]; // water cells excluded
  canals: LonLat[][];
  river: LonLat[];
  dams: LonLat[];
  town: LonLat;
  /** true where a grid cell is water, indexed row * cols + col */
  water: boolean[];
}

const round5 = (v: number) => Math.round(v * 1e5) / 1e5;
export const toLonLat = ([x, y]: XY): LonLat => [
  round5(GRID.west + (x / GRID.cellKm) * GRID.deg),
  round5(GRID.north - (y / GRID.cellKm) * GRID.deg),
];
export const cellId = (r: number, c: number) => `r${String(r).padStart(3, '0')}c${String(c).padStart(3, '0')}`;

const EAST_KM = GRID.cols * GRID.cellKm;
const SOUTH_KM = GRID.rows * GRID.cellKm;
const REF_ROWS = 6; // reference forest strip on the north-west edge
const REF_COLS = 54;
const PLANT = { r0: 51, r1: 79, c0: 0, c1: 28 };
const REWET = { r0: 14, r1: 35, c0: 30, c1: 52 };

function sampleLine(a: XY, b: XY, step = 0.05): XY[] {
  const n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / step));
  return Array.from({ length: n + 1 }, (_, i) => [a[0] + ((b[0] - a[0]) * i) / n, a[1] + ((b[1] - a[1]) * i) / n] as XY);
}

export function buildLandscape(rng: Rng): Landscape {
  const { rows, cols, cellKm } = GRID;
  const centre = (r: number, c: number): XY => [(c + 0.5) * cellKm, (r + 0.5) * cellKm];

  // River: meanders north to south in the western third.
  const p1 = uniform(rng, 0, 2 * Math.PI), p2 = uniform(rng, 0, 2 * Math.PI);
  const riverXY: XY[] = [];
  for (let y = 0; y <= SOUTH_KM + 1e-9; y += 0.1) riverXY.push([8 + 2.6 * Math.sin(y / 6 + p1) + 0.9 * Math.sin(y / 2.3 + p2), y]);
  const riverDist = (p: XY) => {
    let d = Infinity;
    for (const q of riverXY) d = Math.min(d, Math.hypot(p[0] - q[0], p[1] - q[1]));
    return d;
  };

  // Forest boundary wiggles around column 55.
  const forestStart = (r: number) => 55 + Math.round(2 * Math.sin(r / 7 + p1));

  // Canals: grid every 2.5 km over the western two-thirds (south of the reference strip), plus two diagonals.
  const westKm = REF_COLS * cellKm;
  const topKm = REF_ROWS * cellKm;
  const canalXY: XY[][] = [];
  for (let x = 1.25; x < westKm; x += 2.5) canalXY.push([[x, topKm], [x, SOUTH_KM]]);
  for (let y = topKm + 1.25; y < SOUTH_KM; y += 2.5) canalXY.push([[0, y], [westKm, y]]);
  canalXY.push([[1, topKm + 2], [westKm - 1, SOUTH_KM - 6]]);
  canalXY.push([[westKm - 2, topKm + 1], [3, SOUTH_KM - 1]]);

  // Bucket canal samples by grid cell so density lookups stay local.
  const buckets: XY[][] = Array.from({ length: rows * cols }, () => []);
  for (const line of canalXY)
    for (const p of sampleLine(line[0], line[1])) {
      const r = Math.min(rows - 1, Math.floor(p[1] / cellKm)), c = Math.min(cols - 1, Math.floor(p[0] / cellKm));
      buckets[r * cols + c].push(p);
    }
  const canalDensity = (p: XY, r: number, c: number) => {
    let n = 0;
    for (let rr = r - 3; rr <= r + 3; rr++)
      for (let cc = c - 3; cc <= c + 3; cc++) {
        if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
        for (const q of buckets[rr * cols + cc]) if (Math.hypot(p[0] - q[0], p[1] - q[1]) <= 1) n++;
      }
    return (n * 0.05) / Math.PI;
  };

  // Water mask and river clipping.
  const water: boolean[] = new Array(rows * cols).fill(false);
  const rd: number[] = new Array(rows * cols);
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      rd[r * cols + c] = riverDist(centre(r, c));
      water[r * cols + c] = rd[r * cols + c] < 0.55;
    }

  // Town sits beside the river at a random latitude; settlement = 32 nearest dry cells (0.5%).
  const townRow = randInt(rng, 24, 44);
  const ty = (townRow + 0.5) * cellKm;
  const rx = riverXY.reduce((best, q) => (Math.abs(q[1] - ty) < Math.abs(best[1] - ty) ? q : best))[0];
  const townXY: XY = [rx + 1.4, ty];
  const settlement = new Set(
    Array.from({ length: rows * cols }, (_, k) => k)
      .filter((k) => !water[k])
      .sort((a, b) => {
        const da = Math.hypot(centre((a / cols) | 0, a % cols)[0] - townXY[0], centre((a / cols) | 0, a % cols)[1] - townXY[1]);
        const db = Math.hypot(centre((b / cols) | 0, b % cols)[0] - townXY[0], centre((b / cols) | 0, b % cols)[1] - townXY[1]);
        return da - db || a - b;
      })
      .slice(0, 32),
  );

  const classify = (r: number, c: number): ClassId => {
    if (settlement.has(r * cols + c)) return 'settlement';
    if (c >= forestStart(r)) return 'intact_forest';
    if (r < REF_ROWS && c < REF_COLS) return 'reference_forest';
    if (r >= PLANT.r0 && r <= PLANT.r1 && c >= PLANT.c0 && c <= PLANT.c1) return 'plantation';
    if (r >= REWET.r0 && r <= REWET.r1 && c >= REWET.c0 && c <= REWET.c1) return 'rewetted';
    return 'drained';
  };
  const treeRange: Record<ClassId, [number, number]> = {
    intact_forest: [80, 95],
    reference_forest: [80, 95],
    plantation: [50, 70],
    rewetted: [10, 35],
    drained: [5, 30],
    settlement: [0, 8],
  };

  const raw: Omit<LandCell, 'cf'>[] = [];
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      const k = r * cols + c;
      if (water[k]) continue;
      const cls = classify(r, c);
      const p = centre(r, c);
      const [t0, t1] = treeRange[cls];
      // Cells just outside the water band lose pixels to the river; the closest drop under half (no_data).
      const nPixels = rd[k] < 0.9 ? Math.round(300 + ((rd[k] - 0.55) / 0.35) * 300) : 625;
      raw.push({
        id: cellId(r, c),
        row: r,
        col: c,
        cls,
        canalDensity: Math.round(canalDensity(p, r, c) * 1000) / 1000,
        treeCover: Math.round(uniform(rng, t0, t1)),
        nPixels,
        centroid: toLonLat(p),
      });
    }
  const maxD = Math.max(...raw.map((c) => c.canalDensity));
  const cells: LandCell[] = raw.map((c) => ({ ...c, cf: maxD > 0 ? c.canalDensity / maxD : 0 }));

  // Dams: 15 to 25 points on canal samples inside the rewetted block.
  const inRewet = (p: XY) =>
    p[1] >= REWET.r0 * cellKm && p[1] < (REWET.r1 + 1) * cellKm && p[0] >= REWET.c0 * cellKm && p[0] < (REWET.c1 + 1) * cellKm;
  const damCandidates = canalXY.flatMap((l) => sampleLine(l[0], l[1], 0.5)).filter(inRewet);
  const nDams = randInt(rng, 15, 25);
  const dams: LonLat[] = [];
  const pool = [...damCandidates];
  for (let i = 0; i < nDams && pool.length; i++) dams.push(toLonLat(pool.splice(Math.floor(rng() * pool.length), 1)[0]));

  return {
    cells,
    canals: canalXY.map((l) => l.map(toLonLat)),
    river: riverXY.filter((_, i) => i % 5 === 0 || i === riverXY.length - 1).map(toLonLat),
    dams,
    town: toLonLat(townXY),
    water,
  };
}

export const EXTENT_KM = { east: EAST_KM, south: SOUTH_KM };
