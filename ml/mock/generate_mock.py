"""Seeded mock training tables for the two planned models. SIMULATED, NOT MEASURED.

  landclass_cells_mock.csv  Model A (land class from NISAR features), one row per cell
  fire_risk_mock.csv        fire-risk logistic model, one row per cell and pass

Both come from one simulated landscape: the real study grid (110 x 111 cells of 500 m),
the real kept pass dates, and a simulated 2026 drought. Value anchors:
  - reference forest HH -8.0 dB, HV -15.0 dB, noise 0.12 dB: real medians in data/noise_floor.json
  - class offsets: CEOS "Layman's SAR Interpretation Guide" v3.0 (PALSAR-2 L-band, oil palm,
    secondary growth) and Torbick et al. 2016 (plantation HV below natural forest)
  - fire raises HH +1 to +4 dB (double bounce on fallen stems), per the architecture doc
Run: py ml/mock/generate_mock.py
"""
import csv
import math
from datetime import date
from pathlib import Path

import numpy as np

SEED = 20261114
OUT = Path(__file__).parent
ROWS, COLS, CELL_KM = 110, 111, 0.5
LON0, LON1, LAT0, LAT1 = 113.75, 114.25, -1.75, -2.25
PASSES = ["2026-06-22", "2026-07-04", "2026-07-16", "2026-08-21", "2026-09-02",
          "2026-09-14", "2026-09-26", "2026-10-08", "2026-10-20", "2026-11-01"]
# regional rain (mm) in the interval ending at each pass; dry El Nino Aug-Oct, rain back late Oct
RAIN = [0, 55, 38, 42, 6, 3, 9, 14, 31, 110]
ET_MM_DAY = 3.5
SIGMA = 0.12
CLASSES = ["forest", "degraded", "plantation", "built"]
N_SAMPLE, N_BUILT, N_HAND = 1000, 60, 100
NO_FIRE_KM = 30.0

rng = np.random.default_rng(SEED)
d = [date.fromisoformat(p) for p in PASSES]
DAYS = [0] + [(d[i] - d[i - 1]).days for i in range(1, len(d))]
T = len(PASSES)

# --- grid in a local km plane (x east, y south) -----------------------------------------
r_idx, c_idx = np.mgrid[0:ROWS, 0:COLS]
X = (c_idx + 0.5) * CELL_KM
Y = (r_idx + 0.5) * CELL_KM
LON = LON0 + (c_idx + 0.5) * (LON1 - LON0) / COLS
LAT = LAT0 + (r_idx + 0.5) * (LAT1 - LAT0) / ROWS


def km(lon, lat):
    return (lon - LON0) * 111.25, (LAT0 - lat) * 110.57


river = np.array([km(*p) for p in [(113.87, -1.75), (113.90, -1.95), (113.93, -2.10), (113.92, -2.25)]])


def dist_to_river(x, y):
    best = np.full(np.shape(x), np.inf)
    for (ax, ay), (bx, by) in zip(river[:-1], river[1:]):
        t = np.clip(((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2), 0, 1)
        best = np.minimum(best, np.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay))))
    return best


def river_x_at(y):
    return np.interp(y, river[:, 1], river[:, 0])


# --- true land class: Voronoi patches, forest west of the river, degraded/plantation east --
n_seeds = 180
sx, sy = rng.uniform(0, COLS * CELL_KM, n_seeds), rng.uniform(0, ROWS * CELL_KM, n_seeds)
east = sx > river_x_at(sy)
seed_cls = np.where(east,
                    rng.choice(3, n_seeds, p=[0.15, 0.50, 0.35]),
                    rng.choice(3, n_seeds, p=[0.65, 0.20, 0.15]))
nearest = np.argmin((X[..., None] - sx) ** 2 + (Y[..., None] - sy) ** 2, axis=-1)
truth = seed_cls[nearest]
tx, ty = km(113.915, -2.205)  # town on the river
villages = [(river_x_at(v), v) for v in rng.uniform(3, 52, 6)]
built = np.hypot(X - tx, Y - ty) < 2.5
for vx, vy in villages:
    built |= np.hypot(X - vx, Y - vy) < 0.75
truth[built] = 3
DIST_RIVER_M = dist_to_river(X, Y) * 1000

pad = np.pad(truth, 1, mode="edge")
boundary = np.zeros_like(truth, dtype=bool)
for dr in (-1, 0, 1):
    for dc in (-1, 0, 1):
        boundary |= pad[1 + dr:1 + dr + ROWS, 1 + dc:1 + dc + COLS] != truth

# --- weak label from the older maps: patch-level out-of-date plus per-cell confusion -------
label = truth.copy()
cleared_seed = (seed_cls == 1) & (rng.random(n_seeds) < 0.10)   # cleared after the 2021 maps
planted_seed = (seed_cls == 2) & (rng.random(n_seeds) < 0.12)   # planted after the 2019 palm map
out_of_date = ~built & (cleared_seed[nearest] | planted_seed[nearest])
label[out_of_date & (truth == 1)] = 0
label[out_of_date & (truth == 2)] = 1
confused = ~built & ~out_of_date & (rng.random(truth.shape) < 0.04)
for k, v in {0: 2, 1: 2, 2: 0}.items():   # the usual radar/optical confusions
    label[confused & (truth == k)] = v

# --- canals and drying sensitivity ----------------------------------------------------------
canal = np.select([truth == 0, truth == 1, truth == 2, truth == 3],
                  [rng.gamma(1.2, 0.12, truth.shape), rng.gamma(4, 0.45, truth.shape),
                   rng.gamma(6, 0.45, truth.shape), rng.gamma(3, 0.3, truth.shape)])
sens = np.select([truth == 0, truth == 1, truth == 2, truth == 3],
                 [rng.gamma(2, 0.18, truth.shape), 1.8 + 0.35 * canal + rng.normal(0, 0.4, truth.shape),
                  0.7 + 0.2 * canal + rng.normal(0, 0.4, truth.shape), np.full(truth.shape, 0.05)]).clip(0.02)
hv_ratio = np.where(truth == 0, 0.3, 0.55)

deficit = [0.0]
for i in range(1, T):
    deficit.append(max(0.0, deficit[-1] + ET_MM_DAY * DAYS[i] - RAIN[i]))
dry = np.array(deficit) / max(deficit)

tile_rain = 1 + rng.uniform(-0.15, 0.15, (2, 2))   # ERA5-scale tiles over the box
rain_cell = np.array(RAIN)[:, None, None] * tile_rain[(r_idx * 2) // ROWS, (c_idx * 2) // COLS][None]

# --- fire: hazard from latent dryness, canals, class, nearby fires last interval -----------
class_off = np.array([-0.5, 0.0, 0.9, -3.0])[truth]
cell_re = rng.normal(0, 0.5, truth.shape)
fire = np.zeros((T, ROWS, COLS), dtype=bool)   # fire[i]: detection in the interval ending at pass i
burned = np.zeros((ROWS, COLS), dtype=bool)
K = np.ones((9, 9)); K[4, 4] = 0                 # neighbours within ~2 km


def neighbour_count(m):
    p = np.pad(m.astype(float), 4)
    out = np.zeros(m.shape)
    for dr in range(9):
        for dc in range(9):
            if K[dr, dc]:
                out += p[dr:dr + ROWS, dc:dc + COLS]
    return out


for i in range(1, T):
    dry_mid = (dry[i - 1] + dry[i]) / 2
    nb = 1 - np.exp(-neighbour_count(fire[i - 1]) / 3)
    logit = (-9.5 + 4.5 * dry_mid * np.minimum(sens / 2, 1.5) + class_off + 0.35 * canal
             + 1.6 * nb + math.log(DAYS[i] / 12) + cell_re)
    fire[i] = ~burned & (rng.random(truth.shape) < 1 / (1 + np.exp(-logit)))
    burned |= fire[i]

# --- radar series per pass (dB) -------------------------------------------------------------
base_hh = np.select([truth == k for k in range(4)],
                    [rng.normal(m, s, truth.shape) for m, s in [(-8.0, 0.8), (-9.8, 1.4), (-7.2, 1.0), (-3.5, 2.0)]])
base_hv = np.select([truth == k for k in range(4)],
                    [rng.normal(m, s, truth.shape) for m, s in [(-15.0, 0.8), (-18.5, 1.8), (-16.0, 1.2), (-15.5, 1.5)]])
burn_hh, burn_hv = rng.uniform(1, 4, truth.shape), rng.normal(-2.0, 0.6, truth.shape)
first_fire = np.where(fire.any(0), fire.argmax(0), T)
HH = np.empty((T, ROWS, COLS)); HV = np.empty((T, ROWS, COLS))
for t in range(T):
    after = first_fire <= t
    HH[t] = base_hh - sens * dry[t] + after * burn_hh + rng.normal(0, SIGMA, truth.shape)
    HV[t] = base_hv - hv_ratio * sens * dry[t] + after * burn_hv + rng.normal(0, SIGMA, truth.shape)
D = HV - HV[0]   # HV drying index vs the baseline pass; the reference forest stays flat

# --- sample 1000 cells: all-landscape random, built over-sampled to N_BUILT ------------------
flat = np.arange(ROWS * COLS)
built_ids = flat[label.ravel() == 3]
pick_b = rng.choice(built_ids, min(N_BUILT, len(built_ids)), replace=False)
pick_o = rng.choice(np.setdiff1d(flat, built_ids), N_SAMPLE - len(pick_b), replace=False)
sample = np.sort(np.concatenate([pick_b, pick_o]))
hand = set(rng.choice(sample, N_HAND, replace=False).tolist())


def cid(r, c):
    return f"r{r:03d}c{c:03d}"


def block(r, c):
    return f"b{r // 10:02d}{c // 10:02d}"   # 5 km spatial block for GroupKFold


# --- table 1: land class -------------------------------------------------------------------
sstd_mu = np.array([1.0, 1.8, 1.3, 2.6])
lc_rows = []
for f in sample:
    r, c = divmod(int(f), COLS)
    t_cls, l_cls = int(truth[r, c]), int(label[r, c])
    hv_lin = 10 ** (HV[:, r, c] / 10)
    sstd = max(0.3, rng.normal(sstd_mu[t_cls], 0.3 * sstd_mu[t_cls]))
    contrast = 0.9 * sstd ** 2 * (1 + rng.normal(0, 0.15))
    if confused[r, c]:
        purity, agree = rng.beta(5, 5), rng.choice([1, 2])
    elif out_of_date[r, c]:
        purity, agree = rng.beta(16, 3), rng.choice([2, 3])
    elif boundary[r, c]:
        purity, agree = rng.beta(8, 3), rng.choice([2, 3, 4], p=[0.2, 0.4, 0.4])
    else:
        purity, agree = rng.beta(18, 2), rng.choice([3, 4], p=[0.3, 0.7])
    lc_rows.append({
        "cell_id": cid(r, c), "block_id": block(r, c),
        "lon": round(float(LON[r, c]), 5), "lat": round(float(LAT[r, c]), 5),
        "median_hh_db": round(float(np.median(HH[:, r, c])), 2),
        "median_hv_db": round(float(np.median(HV[:, r, c])), 2),
        "hh_minus_hv_db": round(float(np.median(HH[:, r, c]) - np.median(HV[:, r, c])), 2),
        "hv_temporal_cv": round(float(hv_lin.std() / hv_lin.mean()), 4),
        "hv_spatial_std_db": round(sstd, 2),
        "glcm_contrast": round(max(0.05, contrast), 3),
        "glcm_homogeneity": round(float(np.clip(1 / (1 + 0.35 * contrast) + rng.normal(0, 0.03), 0.05, 0.98)), 3),
        "glcm_entropy": round(float(np.clip(2.8 + 0.9 * sstd + rng.normal(0, 0.15), 1.0, math.log(256))), 3),
        "dist_river_m": int(round(float(DIST_RIVER_M[r, c]), -1)),
        "label_map": CLASSES[l_cls],
        "label_purity": round(float(purity), 3),
        "n_maps_agree": int(agree),
        "hand_label": CLASSES[t_cls] if int(f) in hand else "",
        "true_class_mock": CLASSES[t_cls],
        "label_is_wrong_mock": int(l_cls != t_cls),
        "map_out_of_date_mock": int(bool(out_of_date[r, c]) and l_cls != t_cls),
    })

# --- table 2: fire risk (features at pass t, target = detection in (t, t+1]) ---------------
fr_rows = []
prior = np.zeros((ROWS, COLS), dtype=bool)
for t in range(1, T - 1):
    prior |= fire[t]
    py_, px_ = np.nonzero(prior)
    near_now = neighbour_count(fire[t]) > 0
    for f in sample:
        r, c = divmod(int(f), COLS)
        if first_fire[r, c] <= t:
            continue   # cells already burned are dropped
        dist = float(np.hypot(px_ - c, py_ - r).min() * CELL_KM) if len(px_) else NO_FIRE_KM
        fr_rows.append({
            "cell_id": cid(r, c), "block_id": block(r, c),
            "pass_date": PASSES[t], "target_interval_end": PASSES[t + 1],
            "target_interval_days": DAYS[t + 1],
            "land_class": CLASSES[int(label[r, c])],
            "canal_density_km_per_km2": round(float(canal[r, c]), 3),
            "hv_index_db": round(float(D[t, r, c]), 2),
            "hv_index_change_db": round(float(D[t, r, c] - D[t - 1, r, c]), 2),
            "dist_prior_fire_km": round(min(dist, NO_FIRE_KM), 2),
            "rain_interval_mm": round(float(rain_cell[t, r, c]), 1),
            "fire_within_2km_interval": int(bool(near_now[r, c] or fire[t, r, c])),
            "fire_next_interval": int(fire[t + 1, r, c]),
        })


def write(name, rows):
    with open(OUT / name, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


write("landclass_cells_mock.csv", lc_rows)
write("fire_risk_mock.csv", fr_rows)

# --- self-check: shape, realism ranges, no leakage --------------------------------------------
assert len(lc_rows) == N_SAMPLE and len({r["cell_id"] for r in lc_rows}) == N_SAMPLE
shares = {k: float(np.mean([r["true_class_mock"] == k for r in lc_rows])) for k in CLASSES}
assert all(s >= 0.04 for s in shares.values()), shares
wrong = np.mean([r["label_is_wrong_mock"] for r in lc_rows])
assert 0.04 <= wrong <= 0.15, wrong
season = {k: float(fire.any(0)[truth == i].mean()) for i, k in enumerate(CLASSES)}
assert 0.08 <= season["degraded"] <= 0.25 and 0.03 <= season["plantation"] <= 0.18, season
assert season["forest"] < 0.03 and season["built"] < 0.02, season
pos = np.mean([r["fire_next_interval"] for r in fr_rows])
assert 0.01 <= pos <= 0.08, pos
by_cell = {}
for r in fr_rows:
    by_cell.setdefault(r["cell_id"], []).append(r)
for rows in by_cell.values():
    tgt = [r["fire_next_interval"] for r in rows]
    assert sum(tgt) <= 1 and (sum(tgt) == 0 or tgt[-1] == 1)   # nothing kept after a fire
    assert all(r["pass_date"] < r["target_interval_end"] for r in rows)
print(f"landclass: {len(lc_rows)} rows, true shares {({k: round(v, 3) for k, v in shares.items()})}, "
      f"wrong labels {wrong:.3f}")
print(f"fire_risk: {len(fr_rows)} rows, positive rate {pos:.3f}, "
      f"season burned share {({k: round(v, 3) for k, v in season.items()})}")
