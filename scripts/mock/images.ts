// Radar and smoke pictures, PRD 6.8. 8x8 px per cell, 640x640, "SIMULATED" watermark in every image.
import { PNG } from 'pngjs';
import type { ClassId } from '../../src/contract';
import { GRID, type Landscape } from './landscape';
import { type Rng, smoothField } from './rng';

export const PX = 8;
export const SIZE = GRID.cols * PX; // 640

const BASE: Record<ClassId, number> = {
  intact_forest: 150, reference_forest: 155, plantation: 125, rewetted: 105, drained: 92, settlement: 190,
};

// 5x7 bitmap glyphs for the watermark.
const GLYPHS: Record<string, string[]> = {
  S: ['01111', '10000', '10000', '01110', '00001', '00001', '11110'],
  I: ['11111', '00100', '00100', '00100', '00100', '00100', '11111'],
  M: ['10001', '11011', '10101', '10101', '10001', '10001', '10001'],
  U: ['10001', '10001', '10001', '10001', '10001', '10001', '01110'],
  L: ['10000', '10000', '10000', '10000', '10000', '10000', '11111'],
  A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001'],
  T: ['11111', '00100', '00100', '00100', '00100', '00100', '00100'],
  E: ['11111', '10000', '10000', '11110', '10000', '10000', '11111'],
  D: ['11110', '10001', '10001', '10001', '10001', '10001', '11110'],
};

type Img = { data: Uint8Array; channels: 1 | 3 };

function watermark(img: Img) {
  const text = 'SIMULATED', scale = 2;
  const w = text.length * 6 * scale;
  const x0 = SIZE - w - 8, y0 = SIZE - 7 * scale - 8;
  // Dark box then white glyphs, so it reads on any background.
  for (let y = y0 - 4; y < y0 + 7 * scale + 4; y++)
    for (let x = x0 - 4; x < x0 + w + 2; x++) set(img, x, y, [20, 20, 20]);
  [...text].forEach((ch, i) =>
    GLYPHS[ch].forEach((row, gy) =>
      [...row].forEach((bit, gx) => {
        if (bit !== '1') return;
        for (let dy = 0; dy < scale; dy++)
          for (let dx = 0; dx < scale; dx++) set(img, x0 + (i * 6 + gx) * scale + dx, y0 + gy * scale + dy, [245, 245, 245]);
      }),
    ),
  );
}

function set(img: Img, x: number, y: number, rgb: [number, number, number]) {
  if (x < 0 || y < 0 || x >= SIZE || y >= SIZE) return;
  const k = y * SIZE + x;
  if (img.channels === 1) img.data[k] = Math.round((rgb[0] + rgb[1] + rgb[2]) / 3);
  else img.data.set(rgb, k * 3);
}

function encode(img: Img): Buffer {
  const png = new PNG({ width: SIZE, height: SIZE });
  const rgba = png.data;
  for (let k = 0; k < SIZE * SIZE; k++) {
    const [r, g, b] = img.channels === 1 ? [img.data[k], img.data[k], img.data[k]] : [img.data[k * 3], img.data[k * 3 + 1], img.data[k * 3 + 2]];
    rgba[k * 4] = r; rgba[k * 4 + 1] = g; rgba[k * 4 + 2] = b; rgba[k * 4 + 3] = 255;
  }
  return PNG.sync.write(png, { colorType: img.channels === 1 ? 0 : 2, inputColorType: 6, deflateLevel: 9 });
}

const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)));

/** Multiplicative speckle: mean of 4 exponentials (gamma, looks = 4), as in multi-looked SAR. */
const speckle = (rng: Rng) => -(Math.log(1 - rng()) + Math.log(1 - rng()) + Math.log(1 - rng()) + Math.log(1 - rng())) / 4;

export function radarPng(rng: Rng, land: Landscape, Dt: (number | null)[]): Buffer {
  const img: Img = { data: new Uint8Array(SIZE * SIZE), channels: 1 };
  land.cells.forEach((c, i) => {
    const base = BASE[c.cls] + 9 * (Dt[i] ?? 0);
    for (let y = 0; y < PX; y++)
      for (let x = 0; x < PX; x++) img.data[(c.row * PX + y) * SIZE + c.col * PX + x] = clamp(base * speckle(rng));
  });
  // Water cells stay 0 (black): smooth open water reflects the pulse away.
  watermark(img);
  return encode(img);
}

export function droppedPng(): Buffer {
  const img: Img = { data: new Uint8Array(SIZE * SIZE).fill(232), channels: 1 };
  for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) if ((x + y) % 24 < 3) img.data[y * SIZE + x] = 170;
  watermark(img);
  return encode(img);
}

/** Optical view on the reveal date: brown-grey haze, denser plumes drifting north-west from fire cells. */
export function opticalHazePng(rng: Rng, land: Landscape, fireCells: number[]): Buffer {
  const img: Img = { data: new Uint8Array(SIZE * SIZE * 3), channels: 3 };
  const lowRes = smoothField(rng, GRID.rows, GRID.cols, 3, 3);
  // Plume density per grid cell: Gaussian blobs elongated to the north-west of each fire.
  const plume = new Float64Array(GRID.rows * GRID.cols);
  for (const i of fireCells) {
    const { row, col } = land.cells[i];
    for (let r = 0; r < GRID.rows; r++)
      for (let c = 0; c < GRID.cols; c++) {
        const dr = row - r, dc = col - c; // positive = north-west of fire
        const along = (dr + dc) / Math.SQRT2, across = (dr - dc) / Math.SQRT2;
        if (along < -3) continue;
        plume[r * GRID.cols + c] += Math.exp(-(across * across) / (2 * (2 + along * 0.4) ** 2) - Math.max(along, 0) / 25);
      }
  }
  const pmax = Math.max(...plume) || 1;
  const ground = new Map(land.cells.map((c) => [c.row * GRID.cols + c.col, c]));
  for (let y = 0; y < SIZE; y++)
    for (let x = 0; x < SIZE; x++) {
      const gr = Math.floor(y / PX), gc = Math.floor(x / PX), k = gr * GRID.cols + gc;
      const p = Math.min(1, plume[k] / pmax * 1.6);
      const haze = 0.82 + 0.1 * lowRes[k] + 0.18 * p;
      // A few patches of ground show through where the haze is thinnest.
      const cell = ground.get(k);
      const groundTone = cell ? (cell.cls.includes('forest') ? [58, 78, 52] : [98, 84, 62]) : [40, 52, 60];
      const t = Math.min(1, Math.max(0, haze + (rng() - 0.5) * 0.04));
      const smoke = [168 - 30 * p, 152 - 32 * p, 132 - 30 * p];
      set(img, x, y, [0, 1, 2].map((ch) => clamp(groundTone[ch] * (1 - t) + smoke[ch] * t)) as [number, number, number]);
    }
  watermark(img);
  return encode(img);
}
