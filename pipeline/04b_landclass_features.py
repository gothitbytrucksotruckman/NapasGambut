"""Stage 4b: per-cell features for the land-cover classifier (Model A).

Cell-level features come from stage 04's per-pass linear cell means
(data/cell_stats.parquet). Texture features (spatial HV std, GLCM) come from the
20 m pixels of a season-median HV image. dist_river_m is the distance from the
cell centre to the nearest OSM river line. Output: data/landclass_features.csv,
with the same feature column names as ml/mock/landclass_cells_mock.csv.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Canal density and any HH change/drying statistic are deliberately excluded: the classes feed the canal and drying hypothesis tests (circularity).
FEATURES = [
    "median_hh_db",
    "median_hv_db",
    "hh_minus_hv_db",
    "hv_temporal_cv",
    "hv_spatial_std_db",
    "glcm_contrast",
    "glcm_homogeneity",
    "glcm_entropy",
    "dist_river_m",
]
OUTPUT_COLUMNS = ["cell_id", "block_id", "lon", "lat", *FEATURES]

GLCM_LEVELS = 16
GLCM_OFFSETS = ((0, 1), (1, 0), (1, 1), (1, -1))


def _load_stats04() -> Any:
    spec = importlib.util.spec_from_file_location("stats04", Path(__file__).resolve().parent / "04_stats.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s04 = _load_stats04()


def block_id(row: int, col: int) -> str:
    """5 km spatial block (10 x 10 cells), same as ml/mock/generate_mock.py."""
    return f"b{row // 10:02d}{col // 10:02d}"


def cell_level_features(stats_df: pd.DataFrame, cell_ids: pd.Series) -> pd.DataFrame:
    """Season-wide medians and HV temporal CV from stage 04's linear cell means."""
    df = stats_df[~stats_df["is_dropped_date"].astype(bool)]
    out = pd.DataFrame(index=pd.Index(cell_ids.astype(str), name="cell_id"))
    groups = {}
    for pol in ("hh", "hv"):
        col = f"gamma_bar_{pol}"
        vals = df[col].to_numpy(dtype=np.float64)
        groups[pol] = df.loc[np.isfinite(vals) & (vals > 0.0)].groupby("cell_id")[col]
        out[f"median_{pol}_db"] = 10.0 * np.log10(groups[pol].median().reindex(out.index))
    out["hh_minus_hv_db"] = out["median_hh_db"] - out["median_hv_db"]
    g = groups["hv"]
    cv = (g.std(ddof=0) / g.mean()).where(g.count() >= 3)
    out["hv_temporal_cv"] = cv.reindex(out.index)
    return out


def season_median_hv_db(
    cube: Any, cell_map: np.ndarray, dropped_dates: set[str], band_rows: int = 500
) -> np.ndarray:
    """Per-pixel median of valid HV over kept dates, in dB (NaN where never valid)."""
    dates = [s04._normalize_date_str(t) for t in np.asarray(cube.coords["time"].values)]
    slices = [cube.isel(time=i) for i, d in enumerate(dates) if d not in dropped_dates]
    if not slices:
        raise ValueError("No non-dropped dates in the cube; cannot build the median HV image.")
    has_mask = "mask" in cube.data_vars
    ny, nx = cell_map.shape
    med = np.full((ny, nx), np.nan, dtype=np.float32)
    for r0 in range(0, ny, band_rows):
        r1 = min(r0 + band_rows, ny)
        stack = np.full((len(slices), r1 - r0, nx), np.nan, dtype=np.float32)
        for k, ds in enumerate(slices):
            # shortcut: .values materialises the whole date for lazy cubes; fine while _open_zarr_cube loads v2 cubes eagerly.
            hv = np.asarray(ds["HVHV"].transpose("y", "x").values[r0:r1], dtype=np.float32)
            ok = (cell_map[r0:r1] >= 0) & np.isfinite(hv) & (hv > 0.0)
            if has_mask:
                m = np.asarray(ds["mask"].transpose("y", "x").values[r0:r1])
                ok &= (m > 0) & (m < 10)
            stack[k][ok] = hv[ok]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN pixels stay NaN
            med[r0:r1] = np.nanmedian(stack, axis=0)
    return 10.0 * np.log10(med)


def spatial_std_db(db: np.ndarray, cell_map: np.ndarray, n_cells: int, min_valid_fraction: float) -> np.ndarray:
    """Std (ddof=0) of dB pixels per cell; NaN below the valid-pixel fraction."""
    valid = np.isfinite(db) & (cell_map >= 0)
    idx = cell_map[valid]
    x = db[valid].astype(np.float64)
    n = np.bincount(idx, minlength=n_cells)
    total = np.bincount(cell_map[cell_map >= 0], minlength=n_cells)
    mean = np.bincount(idx, weights=x, minlength=n_cells) / np.maximum(n, 1)
    var = np.bincount(idx, weights=(x - mean[idx]) ** 2, minlength=n_cells) / np.maximum(n, 1)
    ok = (n > 0) & (n >= min_valid_fraction * total)
    return np.where(ok, np.sqrt(var), np.nan)


def quantise(db: np.ndarray, cell_map: np.ndarray) -> np.ndarray:
    """Equal-probability 16-level quantisation over all valid in-grid pixels (-1 = invalid)."""
    valid = np.isfinite(db) & (cell_map >= 0)
    if not np.any(valid):
        raise ValueError("No valid in-grid pixels in the median HV image.")
    edges = np.quantile(db[valid], np.arange(1, GLCM_LEVELS) / GLCM_LEVELS)
    q = np.full(db.shape, -1, dtype=np.int16)
    q[valid] = np.digitize(db[valid], edges)
    return q


def glcm_counts(q: np.ndarray, cell_map: np.ndarray, n_cells: int) -> np.ndarray:
    """Symmetric co-occurrence counts per cell, summed over the four distance-1 offsets."""
    ny, nx = q.shape
    nl2 = GLCM_LEVELS * GLCM_LEVELS
    counts = np.zeros(n_cells * nl2, dtype=np.int64)
    for dy, dx in GLCM_OFFSETS:
        ra, rb = slice(0, ny - dy), slice(dy, ny)
        ca, cb = (slice(0, nx - dx), slice(dx, nx)) if dx >= 0 else (slice(-dx, nx), slice(0, nx + dx))
        qa, qb = q[ra, ca], q[rb, cb]
        ma, mb = cell_map[ra, ca], cell_map[rb, cb]
        ok = (qa >= 0) & (qb >= 0) & (ma >= 0) & (ma == mb)
        base = ma[ok].astype(np.int64) * nl2
        i = qa[ok].astype(np.int64)
        j = qb[ok].astype(np.int64)
        counts += np.bincount(base + i * GLCM_LEVELS + j, minlength=n_cells * nl2)
        counts += np.bincount(base + j * GLCM_LEVELS + i, minlength=n_cells * nl2)
    return counts.reshape(n_cells, GLCM_LEVELS, GLCM_LEVELS)


def glcm_features(counts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Contrast, homogeneity, entropy (nats) of the normalised GLCM; NaN with no pairs."""
    tot = counts.sum(axis=(1, 2))
    p = counts / np.maximum(tot, 1)[:, None, None]
    ii, jj = np.indices((GLCM_LEVELS, GLCM_LEVELS))
    d2 = (ii - jj) ** 2
    contrast = (p * d2).sum(axis=(1, 2))
    homogeneity = (p / (1.0 + d2)).sum(axis=(1, 2))
    entropy = -(p * np.log(np.where(p > 0, p, 1.0))).sum(axis=(1, 2))
    none = tot == 0
    return (
        np.where(none, np.nan, contrast),
        np.where(none, np.nan, homogeneity),
        np.where(none, np.nan, entropy),
    )


def load_river_lines(rivers_path: Path, target_crs: Any | None) -> list[np.ndarray]:
    """River polylines (properties.kind == 'river') projected to the cube CRS."""
    feats = [
        f
        for f in json.loads(rivers_path.read_text(encoding="utf-8")).get("features", [])
        if (f.get("properties") or {}).get("kind") == "river"
    ]
    if not feats:
        raise ValueError(f"No river features (properties.kind == 'river') in {rivers_path}; cannot compute dist_river_m.")
    if target_crs is None:
        raise ValueError("Cube CRS is unknown; cannot project rivers for dist_river_m.")
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    lines = []
    for f in feats:
        geom = f["geometry"]
        parts = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
        for part in parts:
            xy = np.asarray(part, dtype=np.float64)[:, :2]
            x, y = tr.transform(xy[:, 0], xy[:, 1])
            lines.append(np.column_stack([x, y]))
    return lines


def distance_to_polylines(px: np.ndarray, py: np.ndarray, lines: list[np.ndarray], chunk: int = 256) -> np.ndarray:
    """Min distance from each projected point to any segment of the projected polylines."""
    segs = np.concatenate([np.column_stack([ln[:-1], ln[1:]]) for ln in lines if len(ln) >= 2])
    px = np.asarray(px, dtype=np.float64)[:, None]
    py = np.asarray(py, dtype=np.float64)[:, None]
    best = np.full(px.shape[0], np.inf)
    for s in range(0, len(segs), chunk):
        ax, ay, bx, by = segs[s : s + chunk].T
        abx, aby = bx - ax, by - ay
        l2 = abx * abx + aby * aby
        apx, apy = px - ax, py - ay
        t = np.clip((apx * abx + apy * aby) / np.where(l2 > 0, l2, 1.0), 0.0, 1.0)
        dx, dy = apx - t * abx, apy - t * aby
        best = np.minimum(best, np.sqrt(dx * dx + dy * dy).min(axis=1))
    return best


def build_features(
    cube: Any,
    grid_df: pd.DataFrame,
    bounds: Any,
    stats_df: pd.DataFrame,
    cfg: dict[str, Any],
    dropped_dates: set[str],
    river_lines: list[np.ndarray],
    band_rows: int = 500,
) -> pd.DataFrame:
    """Assemble the rounded landclass feature table, one row per grid cell."""
    n_cells = len(grid_df)
    cell_map = s04.build_pixel_to_cell_map(
        y_coords=np.asarray(cube.coords["y"].values, dtype=np.float64),
        x_coords=np.asarray(cube.coords["x"].values, dtype=np.float64),
        grid_df=grid_df,
        bounds=bounds,
        cell_size_m=float(cfg["cell_size_m"]),
    )
    cell = cell_level_features(stats_df, grid_df["cell_id"])
    db = season_median_hv_db(cube, cell_map, dropped_dates, band_rows)
    contrast, homogeneity, entropy = glcm_features(glcm_counts(quantise(db, cell_map), cell_map, n_cells))
    dist = distance_to_polylines(grid_df["x_center"].to_numpy(), grid_df["y_center"].to_numpy(), river_lines)

    out = pd.DataFrame(
        {
            "cell_id": grid_df["cell_id"].astype(str).to_numpy(),
            "block_id": [block_id(int(r), int(c)) for r, c in zip(grid_df["row"], grid_df["col"])],
            "lon": grid_df["lon"].to_numpy(dtype=np.float64).round(5),
            "lat": grid_df["lat"].to_numpy(dtype=np.float64).round(5),
            "median_hh_db": cell["median_hh_db"].to_numpy().round(2),
            "median_hv_db": cell["median_hv_db"].to_numpy().round(2),
            "hh_minus_hv_db": cell["hh_minus_hv_db"].to_numpy().round(2),
            "hv_temporal_cv": cell["hv_temporal_cv"].to_numpy().round(4),
            "hv_spatial_std_db": spatial_std_db(db, cell_map, n_cells, float(cfg["min_valid_fraction"])).round(2),
            "glcm_contrast": contrast.round(3),
            "glcm_homogeneity": homogeneity.round(3),
            "glcm_entropy": entropy.round(3),
            "dist_river_m": pd.Series(np.round(dist / 10.0) * 10.0).astype("Int64").to_numpy(),
        }
    )
    return out[OUTPUT_COLUMNS]


def print_summary(df: pd.DataFrame) -> None:
    nan = df[FEATURES].isna()
    print(f"cells: {len(df)} | cells with any NaN feature: {int(nan.any(axis=1).sum())}")
    for col in FEATURES:
        print(f"  {col:<18} NaN: {int(nan[col].sum())}")


def run_self_test() -> int:
    """Synthetic in-memory checks; no files in data/, no parquet, no xarray/pyproj."""
    mock_header = (PROJECT_ROOT / "ml/mock/landclass_cells_mock.csv").open(encoding="utf-8").readline().strip().split(",")
    assert FEATURES == mock_header[mock_header.index("lat") + 1 : mock_header.index("label_map")], mock_header
    assert block_id(23, 7) == "b0200"

    n, px = 6, 25
    ny = nx = n * px
    x0, y0 = 500000.0, 9700000.0
    x_coords = x0 + 10.0 + np.arange(nx) * 20.0
    y_coords = y0 + 10.0 + np.arange(ny) * 20.0
    rows = []
    for r in range(n):
        for c in range(n):
            minx, miny = x0 + c * 500.0, y0 + r * 500.0
            rows.append(
                {
                    "cell_id": f"r{r:03d}c{c:03d}", "row": r, "col": c, "class": "reference_forest",
                    "minx": minx, "miny": miny, "maxx": minx + 500.0, "maxy": miny + 500.0,
                    "x_center": minx + 250.0, "y_center": miny + 250.0,
                    "lon": 113.7 + c * 0.0045, "lat": -1.75 + r * 0.0045,
                }
            )
    grid_df = pd.DataFrame(rows)
    bounds = tuple(grid_df[k].to_numpy() for k in ("minx", "miny", "maxx", "maxy"))
    dates = ["2026-06-20", "2026-07-02", "2026-07-14", "2026-07-26"]
    dropped = {"2026-07-14"}
    valid_t = [0, 1, 3]

    def cell_px(r: int, c: int) -> tuple[slice, slice]:
        return slice(r * px, (r + 1) * px), slice(c * px, (c + 1) * px)

    rng = np.random.default_rng(7)
    hv = (10 ** -1.5) * rng.gamma(4.0, 0.25, size=(len(dates), ny, nx))
    stripes = np.where(np.arange(px) % 2 == 0, 10 ** -1.0, 10 ** -2.0)[:, None]
    hv[(slice(None), *cell_px(2, 2))] = stripes  # plantation-like rows
    hv[(slice(None), *cell_px(3, 3))] = 10 ** -1.2  # constant
    for k, t in enumerate(valid_t):
        hv[(t, *cell_px(4, 4))] = 0.03 * (k + 1)  # designed series 1:2:3
    hh = hv * 10 ** 0.8
    mask = np.ones(hv.shape, dtype=np.uint8)
    mask[:, :10, :10] = 255

    def make_cube(hh_arr: np.ndarray, hv_arr: np.ndarray) -> Any:
        return s04._MockDataset(
            data_vars={
                "HHHH": s04._MockDataArray(hh_arr.astype(np.float32), ("time", "y", "x")),
                "HVHV": s04._MockDataArray(hv_arr.astype(np.float32), ("time", "y", "x")),
                "mask": s04._MockDataArray(mask, ("time", "y", "x")),
            },
            coords={
                "time": s04._MockCoord(np.array(dates, dtype="datetime64[D]")),
                "y": s04._MockCoord(y_coords),
                "x": s04._MockCoord(x_coords),
            },
        )

    cfg = dict(s04.DEFAULT_CONFIG, reference_min_cells=1)
    river = [np.array([[x0 - 1000.0, y0], [x0 + 5000.0, y0]])]  # along the grid's south edge

    def run(cube: Any) -> pd.DataFrame:
        stats_df, _ = s04.compute_cell_statistics(
            cube, grid_df, bounds, cfg, kept_dates=[dates[t] for t in valid_t], dropped_dates=set(dropped)
        )
        return build_features(cube, grid_df, bounds, stats_df, cfg, set(dropped), river, band_rows=40)

    clean_cube = make_cube(hh, hv)
    out = run(clean_cube)
    assert list(out.columns) == OUTPUT_COLUMNS

    # Huge values on the dropped date and in masked pixels must not change anything
    hh_dirty, hv_dirty = hh.copy(), hv.copy()
    for arr in (hh_dirty, hv_dirty):
        arr[2] = 1e6
        arr[:, :10, :10] = 1e6
    pd.testing.assert_frame_equal(out, run(make_cube(hh_dirty, hv_dirty)))

    by_id = out.set_index("cell_id")
    const = by_id.loc["r003c003"]
    assert const["glcm_contrast"] == 0.0 and const["glcm_homogeneity"] == 1.0 and const["glcm_entropy"] == 0.0
    assert const["hv_spatial_std_db"] == 0.0
    striped = by_id.loc["r002c002"]
    assert striped["glcm_contrast"] > const["glcm_contrast"] and striped["glcm_homogeneity"] < 1.0
    assert abs(by_id.loc["r000c001", "median_hv_db"] - (-15.0)) < 0.2, by_id.loc["r000c001", "median_hv_db"]
    assert abs(by_id.loc["r000c001", "hh_minus_hv_db"] - 8.0) < 0.02
    expected_cv = float(np.std([1.0, 2.0, 3.0]) / 2.0)
    assert abs(by_id.loc["r004c004", "hv_temporal_cv"] - expected_cv) < 1e-3, by_id.loc["r004c004", "hv_temporal_cv"]
    assert (out["dist_river_m"].to_numpy() == grid_df["row"].to_numpy() * 500 + 250).all()
    assert not out[FEATURES].isna().any().any()

    # Vectorised GLCM vs brute force on the masked-corner speckle cell
    cell_map = s04.build_pixel_to_cell_map(y_coords, x_coords, grid_df, bounds, 500.0)
    q = quantise(season_median_hv_db(clean_cube, cell_map, dropped), cell_map)
    counts = glcm_counts(q, cell_map, len(grid_df))
    c_idx = 0
    brute = np.zeros((GLCM_LEVELS, GLCM_LEVELS), dtype=np.int64)
    for y in range(ny):
        for x in range(nx):
            if cell_map[y, x] != c_idx or q[y, x] < 0:
                continue
            for dy, dx in GLCM_OFFSETS:
                y2, x2 = y + dy, x + dx
                if 0 <= y2 < ny and 0 <= x2 < nx and cell_map[y2, x2] == c_idx and q[y2, x2] >= 0:
                    brute[q[y, x], q[y2, x2]] += 1
                    brute[q[y2, x2], q[y, x]] += 1
    assert brute.sum() > 0 and np.array_equal(brute, counts[c_idx])

    d = distance_to_polylines(
        np.array([500.0, 1300.0, -100.0]), np.array([300.0, 400.0, 0.0]), [np.array([[0.0, 0.0], [1000.0, 0.0]])]
    )
    assert np.allclose(d, [300.0, 500.0, 100.0])

    print(
        f"04b_landclass_features self-test: passed ({len(out)} cells, striped contrast "
        f"{striped['glcm_contrast']}, cv {by_id.loc['r004c004', 'hv_temporal_cv']}, GLCM brute-force match)"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute per-cell land-cover classifier features.")
    parser.add_argument("--cube", type=Path, default=None)
    parser.add_argument("--grid", type=Path, default=PROJECT_ROOT / "data/grid_cells.parquet")
    parser.add_argument("--stats", type=Path, default=PROJECT_ROOT / "data/cell_stats.parquet")
    parser.add_argument("--quality", type=Path, default=PROJECT_ROOT / "data/quality_report.json")
    parser.add_argument("--rivers", type=Path, default=PROJECT_ROOT / "data/osm_canals.geojson")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data/landclass_features.csv")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.yaml")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()

    cfg = s04.load_config(s04._resolve_path(args.config))
    cube_path = s04._resolve_path(
        args.cube if args.cube is not None else Path(cfg.get("merged_cube_zarr", "data/gcov_cube.zarr"))
    )
    _, dropped_dates = s04.load_quality_report(s04._resolve_path(args.quality))
    cube, cube_crs = s04._open_zarr_cube(cube_path)
    grid_df, bounds = s04.load_grid_cells(s04._resolve_path(args.grid), target_crs=cube_crs)
    stats_df = pd.read_parquet(s04._resolve_path(args.stats))
    river_lines = load_river_lines(s04._resolve_path(args.rivers), cube_crs)

    out = build_features(cube, grid_df, bounds, stats_df, cfg, dropped_dates, river_lines)
    out_path = s04._resolve_path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print_summary(out)
    print(f"Saved landclass features -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
