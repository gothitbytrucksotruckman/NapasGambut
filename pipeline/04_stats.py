"""Stage 4: Cell aggregation, double-difference drying index, and MAD noise floor.

Implements Steps 2-5 of the Napas Gambut scientific method:
1. Block-average HHHH, HVHV, and numberOfLooks into grid cells in LINEAR POWER first.
2. Convert cell means to decibels (10 * log10), compute HH - HV, and compute
   theoretical speckle grain (4.34 / sqrt(N_c * L)).
3. Identify dense/reference forest cells and compute per-date reference median
   change relative to the first valid baseline date t_0.
4. Compute the double-difference drying index D_ct for HH and HV (plus integer
   tenths of a dB for series.json and raw delta for Hypothesis Test 4).
5. Compute the empirical MAD noise floor sigma_t, run QA Checks 3 and 4
   (steady reference & split-half null test), warn if any date exceeds 0.5 dB,
   and save outputs to data/cell_stats.parquet and data/noise_floor.json.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

DEFAULT_CONFIG: dict[str, Any] = {
    "cell_size_m": 500,
    "min_valid_fraction": 0.5,
    "reference_min_cells": 200,
    "sigma_threshold": 2.0,
    "headline_sigma": 3.0,
    "deep_sigma": 4.0,
    "max_noise_floor_db": 0.5,
}

PRIMARY_REF_CLASSES = ("reference_forest", "dense_forest")
FALLBACK_REF_CLASS = "intact_forest"
ROW_COL_RE = re.compile(r"^r(\d+)c(\d+)$", re.IGNORECASE)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_path(path: Path) -> Path:
    """Resolve relative paths against PROJECT_ROOT if not already existing from cwd."""
    if path.is_absolute() or path.exists():
        return path
    return PROJECT_ROOT / path


def load_config(config_path: Path | None) -> dict[str, Any]:
    """Load pipeline config.yaml with safe defaults for missing keys or file."""
    cfg = dict(DEFAULT_CONFIG)
    if config_path is None or not config_path.exists():
        return cfg

    try:
        import yaml
    except ImportError:
        return cfg

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return cfg

    for key in DEFAULT_CONFIG:
        if key in raw and raw[key] is not None:
            cfg[key] = raw[key]
    if "change_k" in raw and "sigma_threshold" not in raw:
        cfg["sigma_threshold"] = raw["change_k"]
    if "headline_k" in raw and "headline_sigma" not in raw:
        cfg["headline_sigma"] = raw["headline_k"]
    if "deep_drying_sigma" in raw and raw["deep_drying_sigma"] is not None:
        cfg["deep_sigma"] = raw["deep_drying_sigma"]
    elif "deep_k" in raw and "deep_sigma" not in raw:
        cfg["deep_sigma"] = raw["deep_k"]
    if "merged_cube_zarr" in raw and raw["merged_cube_zarr"]:
        cfg["merged_cube_zarr"] = raw["merged_cube_zarr"]
    return cfg


def load_quality_report(quality_path: Path | None) -> tuple[list[str] | None, set[str]]:
    """Read kept_dates and dropped_dates from data/quality_report.json if present."""
    if quality_path is None or not quality_path.exists():
        return None, set()

    payload = json.loads(quality_path.read_text(encoding="utf-8"))
    kept_raw = payload.get("kept_dates")
    kept_dates = [str(d)[:10] for d in kept_raw] if isinstance(kept_raw, list) else None

    dropped: set[str] = set()
    for item in payload.get("dropped_dates", []):
        if isinstance(item, str):
            dropped.add(item[:10])
        elif isinstance(item, dict) and item.get("date"):
            dropped.add(str(item["date"])[:10])
    return kept_dates, dropped


def _parse_wkb_bbox(wkb: bytes) -> tuple[float, float, float, float] | None:
    """Extract (minx, miny, maxx, maxy) from a standard WKB/EWKB 2D polygon."""
    if not isinstance(wkb, (bytes, bytearray, memoryview)) or len(wkb) < 9:
        return None
    buf = bytes(wkb)
    endian = "<" if buf[0] == 1 else ">"
    geom_type = struct.unpack(f"{endian}I", buf[1:5])[0]
    offset = 5
    if geom_type & 0x20000000:  # EWKB SRID flag
        offset += 4
    base_type = geom_type & 0xFF
    if base_type != 3 or len(buf) < offset + 4:  # Polygon
        return None

    num_rings = struct.unpack(f"{endian}I", buf[offset : offset + 4])[0]
    offset += 4
    xs: list[float] = []
    ys: list[float] = []
    for _ in range(num_rings):
        if len(buf) < offset + 4:
            return None
        num_pts = struct.unpack(f"{endian}I", buf[offset : offset + 4])[0]
        offset += 4
        needed = num_pts * 16
        if len(buf) < offset + needed:
            return None
        coords = struct.unpack(f"{endian}{num_pts * 2}d", buf[offset : offset + needed])
        xs.extend(coords[0::2])
        ys.extend(coords[1::2])
        offset += needed
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _extract_cell_bounds(
    df: pd.DataFrame, target_crs: Any | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """Extract per-cell [minx, miny, maxx, maxy] arrays in target_crs if possible."""
    for bound_cols in (
        ("minx", "miny", "maxx", "maxy"),
        ("x_min", "y_min", "x_max", "y_max"),
    ):
        if all(col in df.columns for col in bound_cols):
            return (
                df[bound_cols[0]].to_numpy(dtype=np.float64),
                df[bound_cols[1]].to_numpy(dtype=np.float64),
                df[bound_cols[2]].to_numpy(dtype=np.float64),
                df[bound_cols[3]].to_numpy(dtype=np.float64),
            )

    if "geometry" not in df.columns:
        return None

    if hasattr(df, "geometry") and hasattr(df, "bounds"):
        gdf = df
        if target_crs is not None and getattr(gdf, "crs", None) is not None:
            if str(gdf.crs) != str(target_crs):
                gdf = gdf.to_crs(target_crs)
        bounds = gdf.bounds
        return (
            bounds["minx"].to_numpy(dtype=np.float64),
            bounds["miny"].to_numpy(dtype=np.float64),
            bounds["maxx"].to_numpy(dtype=np.float64),
            bounds["maxy"].to_numpy(dtype=np.float64),
        )

    # Pure-Python WKB fallback when geopandas/shapely are not installed
    bboxes = [_parse_wkb_bbox(val) for val in df["geometry"]]
    if all(box is not None for box in bboxes):
        arr = np.asarray(bboxes, dtype=np.float64)
        return arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    return None


def _reproject_lonlat_bounds_if_needed(
    bounds: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    target_crs: Any | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Reproject degree bounds to projected cube CRS when GeoJSON is in EPSG:4326."""
    minx, miny, maxx, maxy = bounds
    looks_geographic = (
        np.nanmax(np.abs(minx)) <= 180.0
        and np.nanmax(np.abs(maxx)) <= 180.0
        and np.nanmax(np.abs(miny)) <= 90.0
        and np.nanmax(np.abs(maxy)) <= 90.0
    )
    if not looks_geographic or target_crs is None:
        return bounds

    try:
        from pyproj import Transformer
    except ImportError:
        return bounds

    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    tx1, ty1 = transformer.transform(minx, miny)
    tx2, ty2 = transformer.transform(maxx, maxy)
    return (
        np.minimum(tx1, tx2),
        np.minimum(ty1, ty2),
        np.maximum(tx1, tx2),
        np.maximum(ty1, ty2),
    )


def load_grid_cells(
    grid_path: Path, target_crs: Any | None = None
) -> tuple[pd.DataFrame, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None]:
    """Load grid cell metadata and bounding boxes from Parquet or GeoJSON."""
    if not grid_path.exists():
        raise FileNotFoundError(f"Grid file not found: {grid_path}")

    suffix = grid_path.suffix.lower()
    if suffix == ".geojson" or suffix == ".json":
        raw = json.loads(grid_path.read_text(encoding="utf-8"))
        rows: list[dict[str, Any]] = []
        bboxes: list[tuple[float, float, float, float]] = []
        for feat in raw.get("features", []):
            props = dict(feat.get("properties") or {})
            if "id" not in props and "id" in feat:
                props["id"] = feat["id"]
            coords = feat.get("geometry", {}).get("coordinates", [[]])[0]
            xs = [pt[0] for pt in coords]
            ys = [pt[1] for pt in coords]
            bboxes.append((min(xs), min(ys), max(xs), max(ys)))
            rows.append(props)
        df = pd.DataFrame(rows)
        arr = np.asarray(bboxes, dtype=np.float64)
        bounds = _reproject_lonlat_bounds_if_needed(
            (arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]), target_crs
        )
        return _normalize_grid_columns(df), bounds

    # Parquet (try GeoPandas first so CRS transforms work seamlessly)
    df: pd.DataFrame
    try:
        import geopandas as gpd

        df = gpd.read_parquet(grid_path)
    except Exception:
        df = pd.read_parquet(grid_path)

    bounds = _extract_cell_bounds(df, target_crs)
    if bounds is not None and not hasattr(df, "bounds"):
        bounds = _reproject_lonlat_bounds_if_needed(bounds, target_crs)
    return _normalize_grid_columns(pd.DataFrame(df.drop(columns=["geometry"], errors="ignore"))), bounds


def _normalize_grid_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize cell_id and class column names across upstream variants."""
    out = df.copy()
    if "cell_id" not in out.columns:
        if "id" in out.columns:
            out["cell_id"] = out["id"].astype(str)
        elif "row" in out.columns and "col" in out.columns:
            out["cell_id"] = [
                f"r{int(r):03d}c{int(c):03d}" for r, c in zip(out["row"], out["col"])
            ]
        else:
            raise ValueError("Grid table must include 'cell_id', 'id', or ('row', 'col').")
    else:
        out["cell_id"] = out["cell_id"].astype(str)

    if "class" not in out.columns:
        if "land_cover" in out.columns:
            out["class"] = out["land_cover"].astype(str)
        else:
            raise ValueError("Grid table must include a 'class' or 'land_cover' column.")
    else:
        out["class"] = out["class"].astype(str)

    if "row" not in out.columns or "col" not in out.columns:
        parsed_rows: list[int] = []
        parsed_cols: list[int] = []
        valid_ids = True
        for cid in out["cell_id"]:
            m = ROW_COL_RE.match(cid)
            if not m:
                valid_ids = False
                break
            parsed_rows.append(int(m.group(1)))
            parsed_cols.append(int(m.group(2)))
        if valid_ids and len(parsed_rows) == len(out):
            out["row"] = parsed_rows
            out["col"] = parsed_cols

    return out.reset_index(drop=True)


def build_pixel_to_cell_map(
    y_coords: np.ndarray,
    x_coords: np.ndarray,
    grid_df: pd.DataFrame,
    bounds: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None,
    cell_size_m: float,
) -> np.ndarray:
    """Map every (y, x) pixel coordinate to its 0-based grid cell index (-1 if outside)."""
    ny = len(y_coords)
    nx = len(x_coords)
    n_cells = len(grid_df)

    # Prefer exact pixel slice indices from 03_grid.py when present and within cube shape
    slice_cols = ("y_start", "y_stop", "x_start", "x_stop")
    if all(col in grid_df.columns for col in slice_cols):
        ys = grid_df["y_start"].to_numpy(dtype=np.int64)
        ye = grid_df["y_stop"].to_numpy(dtype=np.int64)
        xs = grid_df["x_start"].to_numpy(dtype=np.int64)
        xe = grid_df["x_stop"].to_numpy(dtype=np.int64)
        if (
            np.all((ys >= 0) & (ys <= ye) & (ye <= ny))
            and np.all((xs >= 0) & (xs <= xe) & (xe <= nx))
        ):
            cell_map = np.full((ny, nx), -1, dtype=np.int32)
            for c_idx in range(n_cells):
                cell_map[ys[c_idx] : ye[c_idx], xs[c_idx] : xe[c_idx]] = c_idx
            return cell_map

    if bounds is not None:
        minx, miny, maxx, maxy = bounds
        dx = float(np.median(maxx - minx))
        dy = float(np.median(maxy - miny))
        x0 = float(np.min(minx))
        y0 = float(np.min(miny))

        col_idx = np.rint((minx - x0) / dx).astype(np.int64)
        row_idx = np.rint((miny - y0) / dy).astype(np.int64)
        regular_x = np.allclose(minx, x0 + col_idx * dx, atol=1e-2)
        regular_y = np.allclose(miny, y0 + row_idx * dy, atol=1e-2)

        if regular_x and regular_y and dx > 0 and dy > 0:
            n_grid_rows = int(row_idx.max()) + 1
            n_grid_cols = int(col_idx.max()) + 1
            lookup = np.full((n_grid_rows, n_grid_cols), -1, dtype=np.int32)
            lookup[row_idx, col_idx] = np.arange(n_cells, dtype=np.int32)

            px_col = np.floor((x_coords - x0) / dx).astype(np.int64)
            px_row = np.floor((y_coords - y0) / dy).astype(np.int64)
            valid_x = (px_col >= 0) & (px_col < n_grid_cols)
            valid_y = (px_row >= 0) & (px_row < n_grid_rows)

            cell_map = np.full((ny, nx), -1, dtype=np.int32)
            yy = np.where(valid_y)[0]
            xx = np.where(valid_x)[0]
            if len(yy) > 0 and len(xx) > 0:
                sub = lookup[np.ix_(px_row[yy], px_col[xx])]
                cell_map[np.ix_(yy, xx)] = sub
            return cell_map

        # General bounding-box fallback for non-uniform or clipped polygons
        cell_map = np.full((ny, nx), -1, dtype=np.int32)
        for c_idx in range(n_cells):
            y_mask = (y_coords >= miny[c_idx]) & (y_coords < maxy[c_idx])
            if not np.any(y_mask):
                continue
            x_mask = (x_coords >= minx[c_idx]) & (x_coords < maxx[c_idx])
            if not np.any(x_mask):
                continue
            cell_map[np.ix_(y_mask, x_mask)] = c_idx
        return cell_map

    # Fallback when no geometry/bounds exist: bin by row/col from pixel origin
    if "row" not in grid_df.columns or "col" not in grid_df.columns:
        raise ValueError("Cannot align pixels to cells without geometry bounds or row/col.")
    row_vals = grid_df["row"].to_numpy(dtype=np.int64)
    col_vals = grid_df["col"].to_numpy(dtype=np.int64)
    lookup = np.full((int(row_vals.max()) + 1, int(col_vals.max()) + 1), -1, dtype=np.int32)
    lookup[row_vals, col_vals] = np.arange(n_cells, dtype=np.int32)

    px_step_x = abs(float(np.median(np.diff(x_coords)))) if nx > 1 else 20.0
    px_step_y = abs(float(np.median(np.diff(y_coords)))) if ny > 1 else 20.0
    x_origin = float(np.min(x_coords)) - 0.5 * px_step_x
    y_top = float(np.max(y_coords)) + 0.5 * px_step_y

    px_col = np.floor((x_coords - x_origin) / cell_size_m).astype(np.int64)
    px_row = np.floor((y_top - y_coords) / cell_size_m).astype(np.int64)
    valid_x = (px_col >= 0) & (px_col < lookup.shape[1])
    valid_y = (px_row >= 0) & (px_row < lookup.shape[0])

    cell_map = np.full((ny, nx), -1, dtype=np.int32)
    yy = np.where(valid_y)[0]
    xx = np.where(valid_x)[0]
    if len(yy) > 0 and len(xx) > 0:
        cell_map[np.ix_(yy, xx)] = lookup[np.ix_(px_row[yy], px_col[xx])]
    return cell_map


def select_reference_cells(
    classes: pd.Series, min_ref_cells: int
) -> tuple[np.ndarray, list[str], bool]:
    """Identify reference forest cells with automatic fallback to intact_forest."""
    cls_lower = classes.str.strip().str.lower()
    primary_mask = cls_lower.isin(PRIMARY_REF_CLASSES).to_numpy()
    used_classes = [c for c in PRIMARY_REF_CLASSES if bool((cls_lower == c).any())]

    if int(primary_mask.sum()) >= min_ref_cells:
        return primary_mask, used_classes, False

    intact_mask = (cls_lower == FALLBACK_REF_CLASS).to_numpy()
    if int(intact_mask.sum()) > 0:
        combined_mask = primary_mask | intact_mask
        used_classes.append(FALLBACK_REF_CLASS)
        print(
            f"[WARN] Found only {int(primary_mask.sum())} {PRIMARY_REF_CLASSES} cells "
            f"(< {min_ref_cells}). Falling back to include '{FALLBACK_REF_CLASS}' "
            f"(total reference cells: {int(combined_mask.sum())}).",
            file=sys.stderr,
        )
        return combined_mask, used_classes, True

    if int(primary_mask.sum()) > 0:
        print(
            f"[WARN] Found only {int(primary_mask.sum())} reference cells (< {min_ref_cells}) "
            f"and no '{FALLBACK_REF_CLASS}' fallback cells.",
            file=sys.stderr,
        )
        return primary_mask, used_classes, False

    available = sorted(cls_lower.unique().tolist())
    raise ValueError(
        f"No reference forest cells found in grid. Expected {PRIMARY_REF_CLASSES} "
        f"or '{FALLBACK_REF_CLASS}', got classes: {available}"
    )


def _normalize_date_str(val: Any) -> str:
    """Convert numpy.datetime64, pandas Timestamp, or string to YYYY-MM-DD."""
    if isinstance(val, (str, np.str_, bytes)):
        text = val.decode("utf-8") if isinstance(val, bytes) else str(val)
        return str(pd.Timestamp(text).strftime("%Y-%m-%d"))
    return str(pd.Timestamp(val).strftime("%Y-%m-%d"))


def _to_nullable_tenths(values: np.ndarray) -> pd.Series:
    """Convert float dB array to pandas nullable Int64 tenths of a decibel."""
    out = pd.Series(pd.NA, index=range(len(values)), dtype="Int64")
    finite = np.isfinite(values)
    if np.any(finite):
        out.iloc[finite] = np.rint(values[finite] * 10.0).astype(np.int64)
    return out


def _compute_mad(values: np.ndarray) -> float:
    """Compute scaled Median Absolute Deviation: 1.4826 * median(|x - median(x)|)."""
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return float("nan")
    med = float(np.median(finite))
    return float(1.4826 * np.median(np.abs(finite - med)))


def compute_cell_statistics(
    cube: Any,
    grid_df: pd.DataFrame,
    bounds: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None,
    cfg: dict[str, Any],
    kept_dates: list[str] | None = None,
    dropped_dates: set[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run Steps 2-5 on an xarray Dataset-like cube and cell grid."""
    dropped_set = set(dropped_dates or set())
    cube_time_raw = np.asarray(cube.coords["time"].values)
    cube_dates = [_normalize_date_str(t) for t in cube_time_raw]
    cube_date_to_idx = {d: i for i, d in enumerate(cube_dates)}

    all_dates_set = set(cube_dates) | set(kept_dates or []) | dropped_set
    dates = sorted(all_dates_set)
    n_dates = len(dates)
    n_cells = len(grid_df)
    if n_dates == 0 or n_cells == 0:
        raise ValueError(f"Empty input: n_dates={n_dates}, n_cells={n_cells}")

    y_coords = np.asarray(cube.coords["y"].values, dtype=np.float64)
    x_coords = np.asarray(cube.coords["x"].values, dtype=np.float64)
    cell_map = build_pixel_to_cell_map(
        y_coords=y_coords,
        x_coords=x_coords,
        grid_df=grid_df,
        bounds=bounds,
        cell_size_m=float(cfg["cell_size_m"]),
    )

    in_grid_mask = cell_map >= 0
    flat_cell_idx = cell_map[in_grid_mask]
    total_pixels_per_cell = np.bincount(flat_cell_idx, minlength=n_cells).astype(np.int32)
    min_valid_fraction = float(cfg["min_valid_fraction"])

    # Allocate [n_cells, n_dates] matrices
    n_valid = np.zeros((n_cells, n_dates), dtype=np.int32)
    valid_frac = np.zeros((n_cells, n_dates), dtype=np.float32)
    looks_mean = np.full((n_cells, n_dates), np.nan, dtype=np.float32)
    gamma_bar_hh = np.full((n_cells, n_dates), np.nan, dtype=np.float64)
    gamma_bar_hv = np.full((n_cells, n_dates), np.nan, dtype=np.float64)
    g_hh = np.full((n_cells, n_dates), np.nan, dtype=np.float64)
    g_hv = np.full((n_cells, n_dates), np.nan, dtype=np.float64)
    hh_minus_hv = np.full((n_cells, n_dates), np.nan, dtype=np.float64)
    sigma_speckle = np.full((n_cells, n_dates), np.nan, dtype=np.float64)

    has_looks = "numberOfLooks" in cube.data_vars
    has_mask = "mask" in cube.data_vars
    if not has_looks:
        print("[WARN] 'numberOfLooks' variable missing in cube; defaulting L=1.0.", file=sys.stderr)

    # Step 2 & Step 3: Block-average in linear power first, then convert to dB
    for t_out, date_str in enumerate(dates):
        if date_str in dropped_set or date_str not in cube_date_to_idx:
            if date_str not in cube_date_to_idx:
                dropped_set.add(date_str)
            continue

        t_cube = cube_date_to_idx[date_str]
        slice_ds = cube.isel(time=t_cube)
        hh_arr = np.asarray(slice_ds["HHHH"].transpose("y", "x").values, dtype=np.float64)
        hv_arr = np.asarray(slice_ds["HVHV"].transpose("y", "x").values, dtype=np.float64)
        if has_mask:
            mask_arr = np.asarray(slice_ds["mask"].transpose("y", "x").values)
            mask_ok = (mask_arr > 0) & (mask_arr < 10)
        else:
            mask_ok = np.ones_like(hh_arr, dtype=bool)

        if has_looks:
            looks_arr = np.asarray(
                slice_ds["numberOfLooks"].transpose("y", "x").values, dtype=np.float64
            )
            looks_ok = np.isfinite(looks_arr) & (looks_arr > 0.0)
        else:
            looks_arr = np.ones_like(hh_arr, dtype=np.float64)
            looks_ok = np.ones_like(hh_arr, dtype=bool)

        px_valid = (
            in_grid_mask
            & mask_ok
            & looks_ok
            & np.isfinite(hh_arr)
            & (hh_arr > 0.0)
            & np.isfinite(hv_arr)
            & (hv_arr > 0.0)
        )

        idx_valid = cell_map[px_valid]
        counts = np.bincount(idx_valid, minlength=n_cells).astype(np.int32)
        n_valid[:, t_out] = counts
        frac = np.where(
            total_pixels_per_cell > 0,
            counts / np.maximum(total_pixels_per_cell, 1),
            0.0,
        )
        valid_frac[:, t_out] = frac.astype(np.float32)

        sum_hh = np.bincount(idx_valid, weights=hh_arr[px_valid], minlength=n_cells)
        sum_hv = np.bincount(idx_valid, weights=hv_arr[px_valid], minlength=n_cells)
        sum_looks = np.bincount(idx_valid, weights=looks_arr[px_valid], minlength=n_cells)

        cell_ok = (counts > 0) & (frac >= min_valid_fraction)
        denom = np.maximum(counts, 1)

        mean_hh = np.where(cell_ok, sum_hh / denom, np.nan)
        mean_hv = np.where(cell_ok, sum_hv / denom, np.nan)
        mean_l = np.where(cell_ok, sum_looks / denom, np.nan)

        gamma_bar_hh[:, t_out] = mean_hh
        gamma_bar_hv[:, t_out] = mean_hv
        looks_mean[:, t_out] = mean_l.astype(np.float32)

        db_hh = np.where(cell_ok & (mean_hh > 0.0), 10.0 * np.log10(mean_hh), np.nan)
        db_hv = np.where(cell_ok & (mean_hv > 0.0), 10.0 * np.log10(mean_hv), np.nan)
        g_hh[:, t_out] = db_hh
        g_hv[:, t_out] = db_hv
        hh_minus_hv[:, t_out] = db_hh - db_hv

        nl = counts * mean_l
        sigma_speckle[:, t_out] = np.where(cell_ok & (nl > 0.0), 4.34 / np.sqrt(nl), np.nan)

    # Step 4: Reference cells & baseline t_0
    ref_mask, ref_classes_used, ref_fallback = select_reference_cells(
        grid_df["class"], int(cfg["reference_min_cells"])
    )
    t0_idx: int | None = None
    for t_idx, date_str in enumerate(dates):
        if date_str in dropped_set:
            continue
        if np.any(ref_mask & np.isfinite(g_hh[:, t_idx]) & np.isfinite(g_hv[:, t_idx])):
            t0_idx = t_idx
            break

    if t0_idx is None:
        raise ValueError("No valid baseline date found with valid reference forest cells.")
    if t0_idx > 0:
        print(
            f"[INFO] First date {dates[0]} is dropped/invalid; using {dates[t0_idx]} as baseline t_0.",
            file=sys.stderr,
        )

    raw_delta_hh = g_hh - g_hh[:, [t0_idx]]
    raw_delta_hv = g_hv - g_hv[:, [t0_idx]]

    d_hh = np.full((n_cells, n_dates), np.nan, dtype=np.float64)
    d_hv = np.full((n_cells, n_dates), np.nan, dtype=np.float64)

    max_noise_limit = float(cfg["max_noise_floor_db"])
    change_k = float(cfg["sigma_threshold"])

    # Deterministic 50/50 split of reference cells for QA Check 4
    ref_indices = np.where(ref_mask)[0]
    rng = np.random.default_rng(20261114)
    shuffled_ref = rng.permutation(ref_indices)
    half_n = len(shuffled_ref) // 2
    half_a_mask = np.zeros(n_cells, dtype=bool)
    half_b_mask = np.zeros(n_cells, dtype=bool)
    half_a_mask[shuffled_ref[:half_n]] = True
    half_b_mask[shuffled_ref[half_n:]] = True

    per_date_records: list[dict[str, Any]] = []
    sigma_manifest_list: list[float | None] = []
    split_half_all_d_b: list[np.ndarray] = []

    # Step 4 (ref median + double difference) & Step 5 (MAD noise floor)
    for t_idx, date_str in enumerate(dates):
        is_dropped = date_str in dropped_set
        is_baseline = t_idx == t0_idx

        if is_dropped:
            sigma_manifest_list.append(None)
            per_date_records.append(
                {
                    "date": date_str,
                    "is_baseline": False,
                    "is_dropped": True,
                    "n_ref_valid": 0,
                    "ref_median_g_hh_db": None,
                    "ref_median_g_hv_db": None,
                    "ref_delta_hh_db": None,
                    "ref_delta_hv_db": None,
                    "sigma_hh_db": None,
                    "sigma_hv_db": None,
                    "sigma_manifest_db": None,
                    "mean_speckle_db": None,
                    "split_half_within_2sigma_pct": None,
                    "exceeds_limit": False,
                }
            )
            continue

        ref_valid_hh = ref_mask & np.isfinite(raw_delta_hh[:, t_idx])
        ref_valid_hv = ref_mask & np.isfinite(raw_delta_hv[:, t_idx])
        n_ref_valid = int(np.sum(ref_valid_hh & ref_valid_hv))

        ref_med_g_hh = (
            float(np.median(g_hh[ref_valid_hh, t_idx])) if np.any(ref_valid_hh) else float("nan")
        )
        ref_med_g_hv = (
            float(np.median(g_hv[ref_valid_hv, t_idx])) if np.any(ref_valid_hv) else float("nan")
        )

        ref_delta_hh = 0.0 if is_baseline else float(np.median(raw_delta_hh[ref_valid_hh, t_idx]))
        ref_delta_hv = 0.0 if is_baseline else float(np.median(raw_delta_hv[ref_valid_hv, t_idx]))

        d_hh[:, t_idx] = raw_delta_hh[:, t_idx] - ref_delta_hh
        d_hv[:, t_idx] = raw_delta_hv[:, t_idx] - ref_delta_hv

        if is_baseline:
            # Ensure exact 0 at baseline for all valid cells
            d_hh[np.isfinite(g_hh[:, t_idx]), t_idx] = 0.0
            d_hv[np.isfinite(g_hv[:, t_idx]), t_idx] = 0.0
            sigma_hh_t = 0.0
            sigma_hv_t = 0.0
            sigma_manifest_list.append(None)
            split_pct = None
        else:
            sigma_hh_t = _compute_mad(d_hh[ref_valid_hh, t_idx])
            sigma_hv_t = _compute_mad(d_hv[ref_valid_hv, t_idx])
            sigma_rounded = (
                round(sigma_hh_t, 4) if math.isfinite(sigma_hh_t) else None
            )
            sigma_manifest_list.append(sigma_rounded)

            # QA Check 4: Split-half null check
            a_valid = half_a_mask & np.isfinite(raw_delta_hh[:, t_idx])
            b_valid = half_b_mask & np.isfinite(raw_delta_hh[:, t_idx])
            split_pct = None
            if np.any(a_valid) and np.any(b_valid):
                ref_a = float(np.median(raw_delta_hh[a_valid, t_idx]))
                d_a = raw_delta_hh[a_valid, t_idx] - ref_a
                sig_a = _compute_mad(d_a)
                d_b = raw_delta_hh[b_valid, t_idx] - ref_a
                if math.isfinite(sig_a) and sig_a >= 0.0:
                    lim = max(change_k * sig_a, 1e-6)
                    split_pct = round(float(100.0 * np.mean(np.abs(d_b) <= lim)), 2)
                    split_half_all_d_b.append(np.abs(d_b) <= lim)

        mean_sp = (
            float(np.nanmean(sigma_speckle[:, t_idx]))
            if np.any(np.isfinite(sigma_speckle[:, t_idx]))
            else float("nan")
        )
        exceeds = bool(not is_baseline and math.isfinite(sigma_hh_t) and sigma_hh_t > max_noise_limit)

        per_date_records.append(
            {
                "date": date_str,
                "is_baseline": is_baseline,
                "is_dropped": False,
                "n_ref_valid": n_ref_valid,
                "ref_median_g_hh_db": round(ref_med_g_hh, 4) if math.isfinite(ref_med_g_hh) else None,
                "ref_median_g_hv_db": round(ref_med_g_hv, 4) if math.isfinite(ref_med_g_hv) else None,
                "ref_delta_hh_db": round(ref_delta_hh, 4) if math.isfinite(ref_delta_hh) else None,
                "ref_delta_hv_db": round(ref_delta_hv, 4) if math.isfinite(ref_delta_hv) else None,
                "sigma_hh_db": round(sigma_hh_t, 4) if math.isfinite(sigma_hh_t) else None,
                "sigma_hv_db": round(sigma_hv_t, 4) if math.isfinite(sigma_hv_t) else None,
                "sigma_manifest_db": sigma_manifest_list[-1],
                "mean_speckle_db": round(mean_sp, 4) if math.isfinite(mean_sp) else None,
                "split_half_within_2sigma_pct": split_pct,
                "exceeds_limit": exceeds,
            }
        )

    # Assemble long-format cell_stats DataFrame sorted by (cell_id, date)
    cell_ids = grid_df["cell_id"].to_numpy()
    cell_classes = grid_df["class"].to_numpy()
    total_px_flat = np.repeat(total_pixels_per_cell, n_dates)
    dropped_col = np.tile(np.array([d in dropped_set for d in dates], dtype=bool), n_cells)

    d_hh_flat = d_hh.ravel()
    d_hv_flat = d_hv.ravel()
    hh_tenths = _to_nullable_tenths(d_hh_flat)
    hv_tenths = _to_nullable_tenths(d_hv_flat)

    stats_df = pd.DataFrame(
        {
            "cell_id": np.repeat(cell_ids, n_dates),
            "date": np.tile(np.array(dates, dtype=object), n_cells),
            "class": np.repeat(cell_classes, n_dates),
            "is_reference": np.repeat(ref_mask, n_dates),
            "is_dropped_date": dropped_col,
            "total_pixels": total_px_flat,
            "n_valid_pixels": n_valid.ravel(),
            "valid_fraction": valid_frac.ravel(),
            "looks_mean": looks_mean.ravel(),
            "gamma_bar_hh": gamma_bar_hh.ravel(),
            "gamma_bar_hv": gamma_bar_hv.ravel(),
            "g_hh": g_hh.ravel().astype(np.float32),
            "g_hv": g_hv.ravel().astype(np.float32),
            "hh_minus_hv": hh_minus_hv.ravel().astype(np.float32),
            "sigma_speckle_db": sigma_speckle.ravel().astype(np.float32),
            "raw_delta_hh": raw_delta_hh.ravel().astype(np.float32),
            "raw_delta_hv": raw_delta_hv.ravel().astype(np.float32),
            "D_hh": d_hh_flat.astype(np.float32),
            "D_hv": d_hv_flat.astype(np.float32),
            "hh_tenths": hh_tenths,
            "hv_tenths": hv_tenths,
        }
    )
    stats_df.sort_values(["cell_id", "date"], kind="mergesort", inplace=True)
    stats_df.reset_index(drop=True, inplace=True)

    # Compute QA summary metrics (Checks 3 and 4)
    non_baseline_sigmas_hh = [
        r["sigma_hh_db"]
        for r in per_date_records
        if not r["is_dropped"] and not r["is_baseline"] and r["sigma_hh_db"] is not None
    ]
    non_baseline_sigmas_hv = [
        r["sigma_hv_db"]
        for r in per_date_records
        if not r["is_dropped"] and not r["is_baseline"] and r["sigma_hv_db"] is not None
    ]
    dates_exceeding = [r["date"] for r in per_date_records if r["exceeds_limit"]]

    overall_split_pct = None
    if split_half_all_d_b:
        concat_bool = np.concatenate(split_half_all_d_b)
        overall_split_pct = round(float(100.0 * np.mean(concat_bool)), 2)

    ref_raw_series = [
        r["ref_median_g_hh_db"]
        for r in per_date_records
        if not r["is_dropped"] and r["ref_median_g_hh_db"] is not None
    ]
    max_step = (
        round(float(np.max(np.abs(np.diff(ref_raw_series)))), 4)
        if len(ref_raw_series) >= 2
        else 0.0
    )
    ref_iqr = float(stats.iqr(d_hh[ref_mask, :], nan_policy="omit")) if np.any(ref_mask) else 0.0

    valid_date_cols = np.array([d not in dropped_set for d in dates], dtype=bool)
    median_cell_n_pixels = (
        int(np.median(np.median(n_valid[:, valid_date_cols], axis=1)))
        if np.any(valid_date_cols)
        else 0
    )

    noise_report: dict[str, Any] = {
        "schema_version": "0.1",
        "cell_size_m": int(cfg["cell_size_m"]),
        "min_valid_fraction": float(cfg["min_valid_fraction"]),
        "baseline_date": dates[t0_idx],
        "reference_classes_used": ref_classes_used,
        "reference_fallback_used": ref_fallback,
        "reference_cell_count": int(np.sum(ref_mask)),
        "dates": dates,
        "dropped_dates": sorted(dropped_set),
        "thresholds": {
            "sigma_db": sigma_manifest_list,
            "change_k": float(cfg["sigma_threshold"]),
            "headline_k": float(cfg["headline_sigma"]),
            "deep_k": float(cfg["deep_sigma"]),
            "max_noise_floor_db": max_noise_limit,
        },
        "per_date": per_date_records,
        "qa_summary": {
            "max_sigma_hh_db": max(non_baseline_sigmas_hh) if non_baseline_sigmas_hh else None,
            "max_sigma_hv_db": max(non_baseline_sigmas_hv) if non_baseline_sigmas_hv else None,
            "reference_global_iqr_db": round(ref_iqr, 4),
            "any_exceeds_limit": len(dates_exceeding) > 0,
            "dates_exceeding_limit": dates_exceeding,
            "split_half_overall_within_2sigma_pct": overall_split_pct,
            "split_half_pass": bool(overall_split_pct is not None and overall_split_pct >= 90.0),
            "steady_reference_max_step_db": max_step,
            "steady_reference_pass": bool(max_step <= max_noise_limit),
            "cell_static_n_pixels_median": median_cell_n_pixels,
        },
    }
    return stats_df, noise_report


def print_noise_floor_summary(noise_report: dict[str, Any]) -> None:
    """Print per-date sigma_t table and warn prominently if any date exceeds 0.5 dB."""
    limit = float(noise_report["thresholds"]["max_noise_floor_db"])
    print("\n=== Napas Gambut Stage 4: Empirical Noise Floor (sigma_t) ===")
    print(
        f"Baseline (t_0): {noise_report['baseline_date']} | "
        f"Reference: {noise_report['reference_classes_used']} "
        f"({noise_report['reference_cell_count']} cells) | "
        f"Cell size: {noise_report['cell_size_m']} m"
    )
    header = (
        f"{'Date':<12} {'N_ref':>6} {'Ref dHH':>8} {'sigma_HH':>9} "
        f"{'sigma_HV':>9} {'SplitHalf':>10} {'Status':<14}"
    )
    print(header)
    print("-" * len(header))

    for rec in noise_report["per_date"]:
        if rec["is_dropped"]:
            print(
                f"{rec['date']:<12} {'-':>6} {'null':>8} {'null':>9} "
                f"{'null':>9} {'-':>10} {'DROPPED':<14}"
            )
            continue

        s_hh = f"{rec['sigma_hh_db']:.4f}" if rec["sigma_hh_db"] is not None else "null"
        s_hv = f"{rec['sigma_hv_db']:.4f}" if rec["sigma_hv_db"] is not None else "null"
        d_ref = f"{rec['ref_delta_hh_db']:+.4f}" if rec["ref_delta_hh_db"] is not None else "null"
        split = (
            f"{rec['split_half_within_2sigma_pct']:.1f}%"
            if rec["split_half_within_2sigma_pct"] is not None
            else "-"
        )
        if rec["is_baseline"]:
            status = "BASELINE (t0)"
        elif rec["exceeds_limit"]:
            status = f"WARN > {limit:.2f} dB"
        else:
            status = "OK"
        print(
            f"{rec['date']:<12} {rec['n_ref_valid']:>6} {d_ref:>8} "
            f"{s_hh:>9} {s_hv:>9} {split:>10} {status:<14}"
        )

    qa = noise_report["qa_summary"]
    print(
        f"\nQA Check 3 (Steady Reference max step): {qa['steady_reference_max_step_db']} dB "
        f"({'PASS' if qa['steady_reference_pass'] else 'CHECK'})"
    )
    print(
        f"QA Check 4 (Split-Half Null within +-2*sigma): "
        f"{qa['split_half_overall_within_2sigma_pct']}% "
        f"({'PASS' if qa['split_half_pass'] else 'FAIL'})"
    )
    if qa["any_exceeds_limit"]:
        print(
            f"\n[WARNING] Noise floor sigma_t exceeded {limit:.2f} dB on dates: "
            f"{qa['dates_exceeding_limit']}.\n"
            "  Recommended Hour 3 action: check whether those dates belong in dropped_dates, "
            "refine reference forest mask, or increase cell_size_m from 500 to 1000 in config.yaml.",
            file=sys.stderr,
        )


def _read_zarr_v2_array(var_dir: Path, zarray: dict[str, Any]) -> np.ndarray:
    """Read a Zarr v2 array directory using numcodecs (avoids zarr v3 Windows asyncio hang)."""
    import itertools
    import numcodecs

    shape = tuple(int(s) for s in zarray["shape"])
    chunks = tuple(int(c) for c in zarray["chunks"])
    dtype = np.dtype(zarray["dtype"])
    order = zarray.get("order", "C")
    sep = zarray.get("dimension_separator", ".")
    fill_raw = zarray.get("fill_value")

    if fill_raw is None:
        fill_val: Any = "" if dtype.kind in ("U", "S") else 0
    elif isinstance(fill_raw, str) and fill_raw.lower() == "nan":
        fill_val = np.nan
    else:
        fill_val = fill_raw

    out = np.full(shape, fill_val, dtype=dtype)
    codec = numcodecs.get_codec(zarray["compressor"]) if zarray.get("compressor") else None
    filters = [numcodecs.get_codec(f) for f in (zarray.get("filters") or [])]

    grid_counts = [math.ceil(s / c) for s, c in zip(shape, chunks)]
    for chunk_idx in itertools.product(*(range(n) for n in grid_counts)):
        chunk_file = var_dir / sep.join(str(i) for i in chunk_idx)
        if not chunk_file.exists():
            continue
        raw = chunk_file.read_bytes()
        if codec is not None:
            raw = codec.decode(raw)
        for flt in reversed(filters):
            raw = flt.decode(raw)
        arr = np.frombuffer(raw, dtype=dtype).reshape(chunks, order=order)
        slices = tuple(
            slice(idx * ch, min((idx + 1) * ch, dim_len))
            for idx, ch, dim_len in zip(chunk_idx, chunks, shape)
        )
        valid_sub = tuple(slice(0, sl.stop - sl.start) for sl in slices)
        out[slices] = arr[valid_sub]
    return out


def _load_zarr_v2_dataset(cube_path: Path) -> tuple[Any, Any | None]:
    """Load a Zarr v2 store directly into an xarray.Dataset via numcodecs."""
    import xarray as xr

    zmeta_path = cube_path / ".zmetadata"
    if zmeta_path.exists():
        meta = json.loads(zmeta_path.read_text(encoding="utf-8")).get("metadata", {})
    else:
        meta = {}

    root_attrs = meta.get(".zattrs")
    if root_attrs is None and (cube_path / ".zattrs").exists():
        root_attrs = json.loads((cube_path / ".zattrs").read_text(encoding="utf-8"))
    root_attrs = root_attrs or {}

    coord_names = {"time", "y", "x", "spatial_ref"}
    coords: dict[str, Any] = {}
    data_vars: dict[str, tuple[tuple[str, ...], np.ndarray]] = {}

    for entry in sorted(cube_path.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        name = entry.name
        zarray = meta.get(f"{name}/.zarray")
        if zarray is None:
            za_file = entry / ".zarray"
            if not za_file.exists():
                continue
            zarray = json.loads(za_file.read_text(encoding="utf-8"))

        zattrs = meta.get(f"{name}/.zattrs")
        if zattrs is None and (entry / ".zattrs").exists():
            zattrs = json.loads((entry / ".zattrs").read_text(encoding="utf-8"))
        zattrs = zattrs or {}

        dims = tuple(zattrs.get("_ARRAY_DIMENSIONS", (name,)))
        arr = _read_zarr_v2_array(entry, zarray)
        if name in coord_names or dims == (name,):
            coords[name] = (dims, arr, zattrs)
        else:
            data_vars[name] = (dims, arr)

    ds = xr.Dataset(data_vars=data_vars, coords=coords, attrs=root_attrs)
    crs = root_attrs.get("crs") or (
        f"EPSG:{int(root_attrs['epsg'])}" if "epsg" in root_attrs else None
    )
    if crs is None and "spatial_ref" in coords and "crs_wkt" in coords["spatial_ref"][2]:
        crs = coords["spatial_ref"][2]["crs_wkt"]
    return ds, crs


def _open_zarr_cube(cube_path: Path) -> tuple[Any, Any | None]:
    """Open Zarr cube (fast Zarr v2 numcodecs reader, with xr.open_zarr fallback)."""
    if not cube_path.exists():
        raise FileNotFoundError(f"GCOV Zarr cube not found: {cube_path}")
    try:
        import xarray as xr
    except ImportError as exc:
        raise ImportError(
            "xarray is required to read Zarr cubes. Install with: pip install xarray zarr pyarrow"
        ) from exc

    if (cube_path / ".zmetadata").exists() or (cube_path / ".zgroup").exists():
        return _load_zarr_v2_dataset(cube_path)

    cube = xr.open_zarr(cube_path)
    crs = None
    if hasattr(cube, "rio") and getattr(cube.rio, "crs", None) is not None:
        crs = cube.rio.crs
    elif "spatial_ref" in cube.coords and "crs_wkt" in cube.coords["spatial_ref"].attrs:
        crs = cube.coords["spatial_ref"].attrs["crs_wkt"]
    return cube, crs


class _MockDataArray:
    """Minimal xarray.DataArray stand-in for dependency-light --self-test."""

    def __init__(self, values: np.ndarray, dims: tuple[str, ...]) -> None:
        self.values = values
        self.dims = dims

    def transpose(self, *target_dims: str) -> "_MockDataArray":
        if target_dims == self.dims:
            return self
        axes = [self.dims.index(d) for d in target_dims]
        return _MockDataArray(np.transpose(self.values, axes), target_dims)


class _MockCoord:
    """Minimal xarray coordinate wrapper for --self-test."""

    def __init__(self, values: np.ndarray) -> None:
        self.values = values
        self.attrs: dict[str, Any] = {}


class _MockDataset:
    """Minimal xarray.Dataset stand-in for --self-test when xarray is absent."""

    def __init__(
        self,
        data_vars: dict[str, _MockDataArray],
        coords: dict[str, _MockCoord],
    ) -> None:
        self.data_vars = data_vars
        self.coords = coords

    def __getitem__(self, key: str) -> _MockDataArray:
        return self.data_vars[key]

    def isel(self, time: int) -> "_MockDataset":
        sliced = {
            k: _MockDataArray(v.values[time], v.dims[1:])
            for k, v in self.data_vars.items()
        }
        return _MockDataset(sliced, self.coords)


def run_self_test() -> int:
    """Verify linear-power averaging, double difference, MAD sigma_t, and QA checks."""
    print("Running pipeline/04_stats.py --self-test ...")
    rng = np.random.default_rng(42)

    # Build a synthetic 20 m pixel grid covering 20 x 20 cells of 500 m (400 cells)
    n_cell_rows, n_cell_cols = 20, 20
    px_per_cell = 25  # 25 * 20 m = 500 m
    ny = n_cell_rows * px_per_cell
    nx = n_cell_cols * px_per_cell
    x0, y0 = 500000.0, 9700000.0
    x_coords = x0 + 10.0 + np.arange(nx) * 20.0
    y_coords = y0 + 10.0 + np.arange(ny) * 20.0

    rows_list = []
    for r in range(n_cell_rows):
        for c in range(n_cell_cols):
            # 220 reference_forest cells (>= 200), 180 drained cells
            idx = r * n_cell_cols + c
            cls = "reference_forest" if idx < 220 else "drained"
            minx = x0 + c * 500.0
            miny = y0 + r * 500.0
            rows_list.append(
                {
                    "cell_id": f"r{r:03d}c{c:03d}",
                    "row": r,
                    "col": c,
                    "class": cls,
                    "minx": minx,
                    "miny": miny,
                    "maxx": minx + 500.0,
                    "maxy": miny + 500.0,
                }
            )
    grid_df = pd.DataFrame(rows_list)
    bounds = (
        grid_df["minx"].to_numpy(),
        grid_df["miny"].to_numpy(),
        grid_df["maxx"].to_numpy(),
        grid_df["maxy"].to_numpy(),
    )

    dates = ["2026-06-20", "2026-07-02", "2026-07-14", "2026-07-26", "2026-08-07"]
    dropped_dates = {"2026-07-26"}
    # Simulate +0.6 dB global calibration drift on 2026-07-14 and -2.0 dB drying on drained cells
    hh_cube = np.zeros((len(dates), ny, nx), dtype=np.float32)
    hv_cube = np.zeros((len(dates), ny, nx), dtype=np.float32)
    mask_cube = np.ones((len(dates), ny, nx), dtype=np.uint8)
    looks_cube = np.full((len(dates), ny, nx), 4.0, dtype=np.float32)

    cell_row_of_px = np.arange(ny) // px_per_cell
    cell_col_of_px = np.arange(nx) // px_per_cell
    cell_idx_px = cell_row_of_px[:, None] * n_cell_cols + cell_col_of_px[None, :]
    is_drained_px = cell_idx_px >= 220

    drift_db = [0.0, 0.2, 0.6, 0.0, -0.3]
    dry_db = [0.0, -0.8, -1.6, 0.0, -2.4]

    for t in range(len(dates)):
        base_hh_db = np.full((ny, nx), -8.0 + drift_db[t], dtype=np.float64)
        base_hv_db = np.full((ny, nx), -14.0 + drift_db[t], dtype=np.float64)
        base_hh_db[is_drained_px] += dry_db[t]
        base_hv_db[is_drained_px] += 0.4 * dry_db[t]
        # Add realistic multi-look gamma speckle multiplicative noise
        hh_lin = (10.0 ** (base_hh_db / 10.0)) * rng.gamma(shape=4.0, scale=0.25, size=(ny, nx))
        hv_lin = (10.0 ** (base_hv_db / 10.0)) * rng.gamma(shape=4.0, scale=0.25, size=(ny, nx))
        hh_cube[t] = hh_lin.astype(np.float32)
        hv_cube[t] = hv_lin.astype(np.float32)

    # Inject NISAR _FillValue=255 into 10% of pixels on valid dates (still >= 0.5 valid)
    mask_cube[:, :50, :50] = 255

    cube = _MockDataset(
        data_vars={
            "HHHH": _MockDataArray(hh_cube, ("time", "y", "x")),
            "HVHV": _MockDataArray(hv_cube, ("time", "y", "x")),
            "mask": _MockDataArray(mask_cube, ("time", "y", "x")),
            "numberOfLooks": _MockDataArray(looks_cube, ("time", "y", "x")),
        },
        coords={
            "time": _MockCoord(np.array(dates, dtype="datetime64[D]")),
            "y": _MockCoord(y_coords),
            "x": _MockCoord(x_coords),
        },
    )

    stats_df, noise_report = compute_cell_statistics(
        cube=cube,
        grid_df=grid_df,
        bounds=bounds,
        cfg=DEFAULT_CONFIG,
        kept_dates=[d for d in dates if d not in dropped_dates],
        dropped_dates=dropped_dates,
    )
    print_noise_floor_summary(noise_report)

    # Assertions verifying scientific correctness
    assert len(stats_df) == len(grid_df) * len(dates)
    assert noise_report["thresholds"]["sigma_db"][0] is None  # baseline date
    assert noise_report["thresholds"]["sigma_db"][3] is None  # dropped date 2026-07-26

    # Check calibration drift cancellation on 2026-08-07 (drained cells should be near -2.4 dB)
    aug = stats_df[(stats_df["date"] == "2026-08-07") & (stats_df["class"] == "drained")]
    median_dry = float(aug["D_hh"].median())
    assert abs(median_dry - (-2.4)) < 0.15, f"Expected D_hh ~ -2.4 dB, got {median_dry:.3f}"

    # Check reference cells center on 0 and noise floor < 0.5 dB
    ref_aug = stats_df[(stats_df["date"] == "2026-08-07") & (stats_df["is_reference"])]
    assert abs(float(ref_aug["D_hh"].median())) < 1e-4
    assert not noise_report["qa_summary"]["any_exceeds_limit"]
    assert noise_report["qa_summary"]["split_half_pass"]

    # Check dropped date rows have NaN/NA
    dropped_rows = stats_df[stats_df["date"] == "2026-07-26"]
    assert dropped_rows["D_hh"].isna().all()
    assert dropped_rows["hh_tenths"].isna().all()

    print("\n[PASS] --self-test verified all mathematical invariants and QA checks.")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for Stage 4 statistics."""
    parser = argparse.ArgumentParser(
        description="Compute 500 m cell linear-power averages, double-difference indices, and MAD noise floor."
    )
    parser.add_argument("--cube", type=Path, default=None)
    parser.add_argument("--grid", type=Path, default=PROJECT_ROOT / "data/grid_cells.parquet")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.yaml")
    parser.add_argument("--quality", type=Path, default=PROJECT_ROOT / "data/quality_report.json")
    parser.add_argument("--out-stats", type=Path, default=PROJECT_ROOT / "data/cell_stats.parquet")
    parser.add_argument("--out-noise", type=Path, default=PROJECT_ROOT / "data/noise_floor.json")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in synthetic verification without requiring external Zarr/Parquet files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for pipeline/04_stats.py."""
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()

    config_path = _resolve_path(args.config)
    cfg = load_config(config_path)
    cube_path = _resolve_path(
        args.cube if args.cube is not None else Path(cfg.get("merged_cube_zarr", "data/gcov_cube.zarr"))
    )
    quality_path = _resolve_path(args.quality)
    kept_dates, dropped_dates = load_quality_report(quality_path)
    cube, cube_crs = _open_zarr_cube(cube_path)

    grid_path = _resolve_path(args.grid)
    if not grid_path.exists():
        for fallback in (
            PROJECT_ROOT / "bundle/cells.geojson",
            PROJECT_ROOT / "public/bundle/cells.geojson",
        ):
            if fallback.exists():
                print(
                    f"[INFO] {grid_path} missing; falling back to {fallback}.",
                    file=sys.stderr,
                )
                grid_path = fallback
                break

    grid_df, bounds = load_grid_cells(grid_path, target_crs=cube_crs)
    stats_df, noise_report = compute_cell_statistics(
        cube=cube,
        grid_df=grid_df,
        bounds=bounds,
        cfg=cfg,
        kept_dates=kept_dates,
        dropped_dates=dropped_dates,
    )

    out_stats = _resolve_path(args.out_stats)
    out_noise = _resolve_path(args.out_noise)
    out_stats.parent.mkdir(parents=True, exist_ok=True)
    out_noise.parent.mkdir(parents=True, exist_ok=True)
    stats_df.to_parquet(out_stats, index=False)
    out_noise.write_text(json.dumps(noise_report, indent=2), encoding="utf-8")

    print_noise_floor_summary(noise_report)
    print(f"\nSaved cell statistics -> {out_stats} ({len(stats_df)} rows)")
    print(f"Saved noise floor     -> {out_noise}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
