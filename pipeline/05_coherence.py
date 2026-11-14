"""Stage 5: NISAR GUNW 12-day interferometric coherence per 500 m cell.

Queries NASA ASF for NISAR L2 GUNW interferograms matching the locked GCOV
geometry (track, frame, flightDirection), inspects HDF5 groups to locate the
80 m coherence layer, clips to study_box while streaming, and averages into the
500 m grid cells in data/grid_cells.parquet.

Scales coherence to integers [0, 100] (nullable Int64) with exact length
len(dates) - 1 per cell for bundle/series.json. Intervals touching a dropped
date are set to null. When EARTHDATA_TOKEN is absent or a GUNW pair is missing
for an interval (e.g., provisional backlog or 36-day gap), falls back to a
cell-level spatial/radiometric stability coherence proxy from gcov_cube.zarr
and records the exact source per interval in coherence_report.json.

Explicitly excludes phase unwrapping and LOS ground-motion displacement.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import os
import re
import sys
from datetime import date as dt_date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DATE_PAIR_RE = re.compile(r"(\d{8})T\d{6}.*?(\d{8})T\d{6}")


def _resolve_path(path: Path) -> Path:
    """Resolve relative paths against PROJECT_ROOT if not already existing from cwd."""
    if path.is_absolute() or path.exists():
        return path
    return PROJECT_ROOT / path


def _load_stats_helpers():
    """Import shared Zarr v2, config, quality, and grid loaders from 04_stats.py."""
    stats_path = Path(__file__).resolve().parent / "04_stats.py"
    spec = importlib.util.spec_from_file_location("stats_mod", stats_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load helper module: {stats_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get_earthdata_token() -> str:
    """Read Earthdata bearer token from env or .env file."""
    token = os.environ.get("EARTHDATA_TOKEN") or os.environ.get("EDL_TOKEN")
    if token:
        return token.strip()
    for env_path in (PROJECT_ROOT / ".env", Path.home() / ".env"):
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("EARTHDATA_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def load_locked_geometry(
    cfg: dict[str, Any],
    selected_scenes_path: Path,
    cube_path: Path,
) -> dict[str, str | None]:
    """Resolve locked (track, frame, flightDirection) from selected_scenes, cube, or config."""
    geom: dict[str, str | None] = {
        "track": str(cfg["track"]) if cfg.get("track") is not None else None,
        "frame": str(cfg["frame"]) if cfg.get("frame") is not None else None,
        "flightDirection": (
            str(cfg["flightDirection"]) if cfg.get("flightDirection") is not None else None
        ),
    }
    if selected_scenes_path.exists():
        payload = json.loads(selected_scenes_path.read_text(encoding="utf-8"))
        sel = payload.get("selected_geometry") or {}
        geom["track"] = geom["track"] or (str(sel["track"]) if sel.get("track") else None)
        geom["frame"] = geom["frame"] or (str(sel["frame"]) if sel.get("frame") else None)
        geom["flightDirection"] = geom["flightDirection"] or (
            str(sel["flightDirection"]) if sel.get("flightDirection") else None
        )

    zattrs_path = cube_path / ".zattrs"
    if zattrs_path.exists():
        zattrs = json.loads(zattrs_path.read_text(encoding="utf-8"))
        geom["track"] = geom["track"] or (str(zattrs["track"]) if zattrs.get("track") else None)
        geom["frame"] = geom["frame"] or (str(zattrs["frame"]) if zattrs.get("frame") else None)
        geom["flightDirection"] = geom["flightDirection"] or (
            str(zattrs["flightDirection"]) if zattrs.get("flightDirection") else None
        )
    return geom


def parse_gunw_filename(filename: str, url: str = "") -> dict[str, Any] | None:
    """Parse NISAR L2 GUNW filename metadata (geometry, pair dates, CRID/counter)."""
    name = Path(filename).name
    if name.endswith("_QA_STATS.h5") or not name.endswith(".h5"):
        return None
    parts = name[:-3].split("_")
    if len(parts) < 15 or parts[0] != "NISAR" or parts[3] != "GUNW":
        return None

    m = DATE_PAIR_RE.search(name)
    if not m:
        return None
    d1_raw, d2_raw = m.group(1), m.group(2)
    d1 = f"{d1_raw[:4]}-{d1_raw[4:6]}-{d1_raw[6:8]}"
    d2 = f"{d2_raw[:4]}-{d2_raw[4:6]}-{d2_raw[6:8]}"
    ref_date, sec_date = (d1, d2) if d1 <= d2 else (d2, d1)

    try:
        counter = int(parts[-1])
    except ValueError:
        counter = 0

    crid = next((p for p in parts if len(p) == 6 and p[0] in ("P", "R") and p[1:].isdigit()), "P00000")
    return {
        "scene_name": name,
        "track": parts[5].zfill(3),
        "flightDirection": parts[6],
        "frame": parts[7].zfill(3),
        "mode": parts[8],
        "ref_date": ref_date,
        "sec_date": sec_date,
        "crid": crid,
        "counter": counter,
        "url": url,
    }


def search_asf_gunw_pairs(
    study_box: list[float],
    dates: list[str],
    geometry: dict[str, str | None],
) -> list[dict[str, Any]]:
    """Query NASA ASF catalog for NISAR GUNW pairs matching the locked GCOV geometry."""
    try:
        import asf_search as asf
    except ImportError:
        print("[WARN] asf_search not installed; skipping live GUNW catalog query.", file=sys.stderr)
        return []

    minx, miny, maxx, maxy = study_box
    wkt = f"POLYGON(({minx} {miny}, {maxx} {miny}, {maxx} {maxy}, {minx} {maxy}, {minx} {miny}))"
    params: dict[str, Any] = {
        "dataset": getattr(asf.DATASET, "NISAR", "NISAR"),
        "processingLevel": getattr(asf.PRODUCT_TYPE, "GUNW", "GUNW"),
        "intersectsWith": wkt,
        "start": f"{dates[0]}T00:00:00Z",
        "end": f"{dates[-1]}T23:59:59Z",
    }
    if geometry.get("flightDirection"):
        params["flightDirection"] = geometry["flightDirection"]

    try:
        response = asf.search(opts=asf.ASFSearchOptions(**params))
        urls = response.find_urls(extension=".h5", directAccess=False)
    except Exception as exc:
        print(f"[WARN] ASF GUNW catalog query failed: {exc}", file=sys.stderr)
        return []

    latest: dict[tuple[str, str], dict[str, Any]] = {}
    target_track = str(geometry.get("track") or "").zfill(3) if geometry.get("track") else None
    target_frame = str(geometry.get("frame") or "").zfill(3) if geometry.get("frame") else None
    target_dir = geometry.get("flightDirection")

    for url in urls:
        parsed = parse_gunw_filename(Path(url).name, url=url)
        if not parsed:
            continue
        if target_track and parsed["track"] != target_track:
            continue
        if target_frame and parsed["frame"] != target_frame:
            continue
        if target_dir and parsed["flightDirection"] != target_dir:
            continue

        pair_key = (parsed["ref_date"], parsed["sec_date"])
        prev = latest.get(pair_key)
        if prev is None or (parsed["crid"], parsed["counter"]) > (prev["crid"], prev["counter"]):
            latest[pair_key] = parsed

    return sorted(latest.values(), key=lambda r: (r["ref_date"], r["sec_date"]))


def _locate_gunw_coherence_dataset(h5_file: Any) -> tuple[str, Any, Any] | None:
    """Inspect GUNW HDF5 groups to find the 80 m coherence layer and its grid group."""
    preferred_bases = (
        "/science/LSAR/GUNW/grids/frequencyA/interferogram",
        "/science/LSAR/GUNW/grids/frequencyA",
        "/science/LSAR/GUNW/grids/frequencyB",
    )
    candidates: list[tuple[int, str, Any]] = []

    def _visit(prefix: str, grp: Any) -> None:
        for key in grp.keys():
            obj = grp[key]
            path = f"{prefix}/{key}"
            if hasattr(obj, "keys"):
                _visit(path, obj)
            else:
                low = key.lower()
                if "coherence" in low and "unwrapped" not in low:
                    score = 0
                    if "hhhh" in path.lower():
                        score += 10
                    if key == "coherenceMagnitude":
                        score += 5
                    if "frequencya" in path.lower():
                        score += 3
                    candidates.append((score, path, obj))

    for base in preferred_bases:
        if base in h5_file:
            _visit(base, h5_file[base])
            if candidates:
                break

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, best_path, dataset = candidates[0]
    parent_group = dataset.parent
    return best_path, dataset, parent_group


def _find_coord_group(h5_file: Any, coh_parent: Any) -> tuple[np.ndarray, np.ndarray, int]:
    """Resolve xCoordinates, yCoordinates, and projection EPSG near a GUNW coherence dataset."""
    grp = coh_parent
    while grp is not None and grp.name != "/":
        if "xCoordinates" in grp and "yCoordinates" in grp:
            epsg = int(grp["projection"][()]) if "projection" in grp else 32749
            return (
                np.asarray(grp["xCoordinates"][:], dtype=np.float64),
                np.asarray(grp["yCoordinates"][:], dtype=np.float64),
                epsg,
            )
        grp = grp.parent
    raise KeyError("Could not locate xCoordinates/yCoordinates/projection in GUNW HDF5 file.")


def stream_gunw_coherence_slice(
    url: str,
    study_box: list[float],
    token: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, str]:
    """Stream clipped 80 m coherence raster from a remote NISAR GUNW HDF5 file."""
    import h5py
    from pyproj import Transformer

    fetch_path = Path(__file__).resolve().parent / "01_fetch.py"
    spec = importlib.util.spec_from_file_location("fetch_mod", fetch_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not import AutoRefreshRangeFile from {fetch_path}")
    fetch_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch_mod)

    minx, miny, maxx, maxy = study_box
    with fetch_mod.AutoRefreshRangeFile(url, token, block_size=64 * 1024) as fobj:
        with h5py.File(fobj, "r", rdcc_nbytes=32 * 1024 * 1024, rdcc_nslots=10007) as h5:
            found = _locate_gunw_coherence_dataset(h5)
            if found is None:
                raise KeyError("No coherence dataset found under /science/LSAR/GUNW/grids")
            coh_path, coh_ds, coh_parent = found
            x_full, y_full, epsg = _find_coord_group(h5, coh_parent)

            transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
            ux0, uy0 = transformer.transform(minx, miny)
            ux1, uy1 = transformer.transform(maxx, maxy)
            u_minx, u_maxx = min(ux0, ux1), max(ux0, ux1)
            u_miny, u_maxy = min(uy0, uy1), max(uy0, uy1)

            x_idx = np.where((x_full >= u_minx) & (x_full <= u_maxx))[0]
            y_idx = np.where((y_full >= u_miny) & (y_full <= u_maxy))[0]
            if len(x_idx) == 0 or len(y_idx) == 0:
                raise ValueError("GUNW spatial intersection with study_box is empty.")

            x_sl = slice(int(x_idx[0]), int(x_idx[-1]) + 1)
            y_sl = slice(int(y_idx[0]), int(y_idx[-1]) + 1)
            arr = np.asarray(coh_ds[y_sl, x_sl], dtype=np.float32)
            return arr, y_full[y_sl], x_full[x_sl], epsg, coh_path


def aggregate_coherence_to_cells(
    coh_arr: np.ndarray,
    y_coords: np.ndarray,
    x_coords: np.ndarray,
    grid_df: pd.DataFrame,
    bounds: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None,
    cell_size_m: float,
    stats_mod: Any,
) -> tuple[np.ndarray, np.ndarray]:
    """Average 80 m coherence raster pixels into 500 m grid cells."""
    cell_map = stats_mod.build_pixel_to_cell_map(
        y_coords=y_coords,
        x_coords=x_coords,
        grid_df=grid_df,
        bounds=bounds,
        cell_size_m=cell_size_m,
    )
    n_cells = len(grid_df)
    valid = (
        (cell_map >= 0)
        & np.isfinite(coh_arr)
        & (coh_arr >= 0.0)
        & (coh_arr <= 1.0)
    )
    idx_valid = cell_map[valid]
    counts = np.bincount(idx_valid, minlength=n_cells).astype(np.int32)
    sums = np.bincount(idx_valid, weights=coh_arr[valid].astype(np.float64), minlength=n_cells)
    coh_mean = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
    return coh_mean, counts


def _estimate_pair_coherence_from_gcov(
    cube: Any,
    t0_idx: int,
    t1_idx: int,
    gap_days: int,
    cell_map: np.ndarray,
    n_cells: int,
    min_valid_fraction: float,
    total_pixels_per_cell: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute a physics-consistent radiometric/spatial coherence proxy from GCOV endpoints.

    Uses per-cell linear-power temporal stability exp(-|Delta_log|) combined with
    within-cell spatial backscatter correlation between dates t0 and t1, modulated
    by baseline decorrelation over >12-day gaps. Used strictly as a fallback when
    live GUNW granules are unavailable.
    """
    s0 = cube.isel(time=t0_idx)
    s1 = cube.isel(time=t1_idx)

    hh0 = np.asarray(s0["HHHH"].transpose("y", "x").values, dtype=np.float64)
    hh1 = np.asarray(s1["HHHH"].transpose("y", "x").values, dtype=np.float64)
    hv0 = np.asarray(s0["HVHV"].transpose("y", "x").values, dtype=np.float64)
    hv1 = np.asarray(s1["HVHV"].transpose("y", "x").values, dtype=np.float64)

    has_mask = "mask" in cube.data_vars
    if has_mask:
        m0 = np.asarray(s0["mask"].transpose("y", "x").values)
        m1 = np.asarray(s1["mask"].transpose("y", "x").values)
        mask_ok = (m0 > 0) & (m0 < 10) & (m1 > 0) & (m1 < 10)
    else:
        mask_ok = np.ones_like(hh0, dtype=bool)

    valid = (
        (cell_map >= 0)
        & mask_ok
        & np.isfinite(hh0)
        & (hh0 > 0.0)
        & np.isfinite(hh1)
        & (hh1 > 0.0)
        & np.isfinite(hv0)
        & (hv0 > 0.0)
        & np.isfinite(hv1)
        & (hv1 > 0.0)
    )
    idx = cell_map[valid]
    counts = np.bincount(idx, minlength=n_cells).astype(np.int32)
    frac = counts / np.maximum(total_pixels_per_cell, 1)
    cell_ok = (counts > 0) & (frac >= min_valid_fraction)

    x_hh = 10.0 * np.log10(hh0[valid])
    y_hh = 10.0 * np.log10(hh1[valid])
    x_hv = 10.0 * np.log10(hv0[valid])
    y_hv = 10.0 * np.log10(hv1[valid])

    denom = np.maximum(counts, 1)
    mx0 = np.bincount(idx, weights=x_hh, minlength=n_cells) / denom
    my0 = np.bincount(idx, weights=y_hh, minlength=n_cells) / denom
    mx1 = np.bincount(idx, weights=x_hv, minlength=n_cells) / denom
    my1 = np.bincount(idx, weights=y_hv, minlength=n_cells) / denom

    sxx = np.bincount(idx, weights=x_hh * x_hh, minlength=n_cells) / denom - mx0 * mx0
    syy = np.bincount(idx, weights=y_hh * y_hh, minlength=n_cells) / denom - my0 * my0
    sxy = np.bincount(idx, weights=x_hh * y_hh, minlength=n_cells) / denom - mx0 * my0

    r_hh = np.clip(sxy / np.sqrt(np.maximum(sxx * syy, 1e-9)), 0.0, 1.0)
    amp_stab = np.exp(-0.35 * (np.abs(my0 - mx0) + 1.5 * np.abs(my1 - mx1)))
    gap_decay = math.exp(-0.012 * max(0, gap_days - 12))

    # Blend spatial correlation and radiometric stability into realistic [0.05, 0.95] range
    coh_est = np.clip((0.55 * r_hh + 0.45 * amp_stab) * gap_decay, 0.05, 0.95)
    coh_mean = np.where(cell_ok, coh_est, np.nan)
    return coh_mean, counts


def compute_coherence_table(
    dates: list[str],
    dropped_dates: set[str],
    grid_df: pd.DataFrame,
    bounds: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None,
    cell_size_m: float,
    min_valid_fraction: float,
    stats_mod: Any,
    cube: Any | None = None,
    gunw_scenes: list[dict[str, Any]] | None = None,
    study_box: list[float] | None = None,
    token: str = "",
    offline: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute per-cell, per-interval coherence (length len(dates) - 1) and report."""
    n_cells = len(grid_df)
    n_intervals = max(0, len(dates) - 1)
    if n_intervals == 0 or n_cells == 0:
        raise ValueError(f"Need >= 2 dates and >= 1 cell; got dates={len(dates)}, cells={n_cells}")

    gunw_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for sc in gunw_scenes or []:
        gunw_lookup[(sc["ref_date"], sc["sec_date"])] = sc

    cube_dates: dict[str, int] = {}
    cell_map_gcov: np.ndarray | None = None
    total_px_gcov: np.ndarray | None = None
    if cube is not None:
        cube_dates = {
            stats_mod._normalize_date_str(t): i for i, t in enumerate(cube.coords["time"].values)
        }
        y_coords = np.asarray(cube.coords["y"].values, dtype=np.float64)
        x_coords = np.asarray(cube.coords["x"].values, dtype=np.float64)
        cell_map_gcov = stats_mod.build_pixel_to_cell_map(
            y_coords=y_coords,
            x_coords=x_coords,
            grid_df=grid_df,
            bounds=bounds,
            cell_size_m=cell_size_m,
        )
        total_px_gcov = np.bincount(
            cell_map_gcov[cell_map_gcov >= 0], minlength=n_cells
        ).astype(np.int32)

    coh_mat = np.full((n_cells, n_intervals), np.nan, dtype=np.float64)
    counts_mat = np.zeros((n_cells, n_intervals), dtype=np.int32)
    sources_per_interval: list[str] = []
    per_interval_reports: list[dict[str, Any]] = []
    inspected_layers: list[str] = []

    for k in range(n_intervals):
        d0, d1 = dates[k], dates[k + 1]
        gap_days = (dt_date.fromisoformat(d1) - dt_date.fromisoformat(d0)).days
        if d0 in dropped_dates or d1 in dropped_dates:
            src = "dropped_endpoint"
            sources_per_interval.append(src)
            per_interval_reports.append(
                {
                    "interval_idx": k,
                    "date_start": d0,
                    "date_end": d1,
                    "gap_days": gap_days,
                    "source": src,
                    "scene_name": None,
                    "valid_cells": 0,
                    "mean_coh": None,
                    "median_coh": None,
                    "dropped": True,
                }
            )
            continue

        matched_scene = gunw_lookup.get((d0, d1))
        used_gunw = False
        scene_name = None

        if matched_scene is not None and token and not offline and study_box is not None:
            try:
                coh_arr, gy, gx, _, layer_path = stream_gunw_coherence_slice(
                    url=matched_scene["url"],
                    study_box=study_box,
                    token=token,
                )
                if layer_path not in inspected_layers:
                    inspected_layers.append(layer_path)
                coh_mean, px_counts = aggregate_coherence_to_cells(
                    coh_arr=coh_arr,
                    y_coords=gy,
                    x_coords=gx,
                    grid_df=grid_df,
                    bounds=bounds,
                    cell_size_m=cell_size_m,
                    stats_mod=stats_mod,
                )
                coh_mat[:, k] = coh_mean
                counts_mat[:, k] = px_counts
                used_gunw = True
                src = "nisar_gunw"
                scene_name = matched_scene["scene_name"]
            except Exception as exc:
                print(
                    f"[WARN] GUNW stream failed for ({d0}, {d1}): {exc}; using GCOV fallback.",
                    file=sys.stderr,
                )

        if not used_gunw:
            if (
                cube is not None
                and cell_map_gcov is not None
                and total_px_gcov is not None
                and d0 in cube_dates
                and d1 in cube_dates
            ):
                coh_mean, px_counts = _estimate_pair_coherence_from_gcov(
                    cube=cube,
                    t0_idx=cube_dates[d0],
                    t1_idx=cube_dates[d1],
                    gap_days=gap_days,
                    cell_map=cell_map_gcov,
                    n_cells=n_cells,
                    min_valid_fraction=min_valid_fraction,
                    total_pixels_per_cell=total_px_gcov,
                )
                coh_mat[:, k] = coh_mean
                counts_mat[:, k] = px_counts
                src = "gcov_radiometric_fallback"
            else:
                src = "missing_data"

        sources_per_interval.append(src)
        valid_vals = coh_mat[np.isfinite(coh_mat[:, k]), k]
        per_interval_reports.append(
            {
                "interval_idx": k,
                "date_start": d0,
                "date_end": d1,
                "gap_days": gap_days,
                "source": src,
                "scene_name": scene_name,
                "valid_cells": int(len(valid_vals)),
                "mean_coh": round(float(np.mean(valid_vals)), 4) if len(valid_vals) > 0 else None,
                "median_coh": round(float(np.median(valid_vals)), 4) if len(valid_vals) > 0 else None,
                "dropped": False,
            }
        )

    coh_flat = coh_mat.ravel()
    coh_int = pd.Series(pd.NA, index=range(len(coh_flat)), dtype="Int64")
    finite_mask = np.isfinite(coh_flat)
    if np.any(finite_mask):
        coh_int.iloc[finite_mask] = np.clip(
            np.rint(coh_flat[finite_mask] * 100.0).astype(np.int64), 0, 100
        )

    cell_ids = grid_df["cell_id"].to_numpy()
    date_starts = np.array([dates[k] for k in range(n_intervals)], dtype=object)
    date_ends = np.array([dates[k + 1] for k in range(n_intervals)], dtype=object)
    gap_days_arr = np.array(
        [(dt_date.fromisoformat(dates[k + 1]) - dt_date.fromisoformat(dates[k])).days for k in range(n_intervals)],
        dtype=np.int32,
    )

    coh_df = pd.DataFrame(
        {
            "cell_id": np.repeat(cell_ids, n_intervals),
            "interval_idx": np.tile(np.arange(n_intervals, dtype=np.int32), n_cells),
            "date_start": np.tile(date_starts, n_cells),
            "date_end": np.tile(date_ends, n_cells),
            "date": np.tile(date_ends, n_cells),
            "gap_days": np.tile(gap_days_arr, n_cells),
            "n_valid_pixels": counts_mat.ravel(),
            "coh_mean": coh_flat.astype(np.float32),
            "coh": coh_int,
            "coh_pct": coh_int,
            "source": np.tile(np.array(sources_per_interval, dtype=object), n_cells),
        }
    )
    coh_df.sort_values(["cell_id", "interval_idx"], kind="mergesort", inplace=True)
    coh_df.reset_index(drop=True, inplace=True)

    report = {
        "schema_version": "0.1",
        "dates": dates,
        "n_intervals": n_intervals,
        "n_cells": n_cells,
        "gunw_scenes_found": len(gunw_scenes or []),
        "gunw_layers_inspected": inspected_layers,
        "per_interval": per_interval_reports,
    }
    return coh_df, report


def print_coherence_summary(report: dict[str, Any]) -> None:
    """Print per-interval coherence summary table."""
    print("\n=== Napas Gambut Stage 5: 12-Day Interferometric Coherence ===")
    print(
        f"Cells: {report['n_cells']} | Intervals: {report['n_intervals']} (dates - 1) | "
        f"GUNW scenes found: {report['gunw_scenes_found']}"
    )
    header = (
        f"{'Idx':>3} {'Interval':<23} {'Gap':>4} {'Valid':>7} "
        f"{'MeanCoh':>8} {'MedCoh':>8} {'Source':<26}"
    )
    print(header)
    print("-" * len(header))
    for item in report["per_interval"]:
        span = f"{item['date_start']}->{item['date_end']}"
        mc = f"{item['mean_coh']:.3f}" if item["mean_coh"] is not None else "null"
        md = f"{item['median_coh']:.3f}" if item["median_coh"] is not None else "null"
        print(
            f"{item['interval_idx']:>3} {span:<23} {item['gap_days']:>3}d "
            f"{item['valid_cells']:>7} {mc:>8} {md:>8} {item['source']:<26}"
        )


def run_self_test() -> int:
    """Verify 80 m GUNW cell averaging, [0, 100] scaling, and dropped-date nulling."""
    print("Running pipeline/05_coherence.py --self-test ...")
    stats_mod = _load_stats_helpers()
    rng = np.random.default_rng(7)

    # 10x10 cells of 500 m (100 cells); 80 m GUNW grid covering 5 km x 5 km (~63x63 px)
    x0, y0 = 500000.0, 9700000.0
    rows_list = []
    for r in range(10):
        for c in range(10):
            minx = x0 + c * 500.0
            miny = y0 + r * 500.0
            rows_list.append(
                {
                    "cell_id": f"r{r:03d}c{c:03d}",
                    "row": r,
                    "col": c,
                    "class": "drained" if r < 6 else "reference_forest",
                    "x_min": minx,
                    "y_min": miny,
                    "x_max": minx + 500.0,
                    "y_max": miny + 500.0,
                }
            )
    grid_df = pd.DataFrame(rows_list)
    bounds = (
        grid_df["x_min"].to_numpy(),
        grid_df["y_min"].to_numpy(),
        grid_df["x_max"].to_numpy(),
        grid_df["y_max"].to_numpy(),
    )

    gx = x0 + 40.0 + np.arange(62) * 80.0
    gy = y0 + 40.0 + np.arange(62) * 80.0
    coh_80m = rng.uniform(0.50, 0.65, size=(len(gy), len(gx))).astype(np.float32)
    # Simulate sharp fire coherence collapse (< 0.15) in row 0..1, col 0..1
    coh_80m[:12, :12] = 0.11

    coh_mean, px_counts = aggregate_coherence_to_cells(
        coh_arr=coh_80m,
        y_coords=gy,
        x_coords=gx,
        grid_df=grid_df,
        bounds=bounds,
        cell_size_m=500.0,
        stats_mod=stats_mod,
    )
    assert len(coh_mean) == 100
    assert np.all(px_counts > 0)
    assert abs(float(coh_mean[0]) - 0.11) < 1e-4

    # Verify full interval table with 1 dropped date (4 dates -> 3 intervals; 2 touched by drop)
    dates = ["2026-06-22", "2026-07-04", "2026-07-16", "2026-07-28"]
    dropped = {"2026-07-16"}
    # Build tiny synthetic GCOV cube for fallback test on interval 0 (06-22 -> 07-04)
    px_x = x0 + 10.0 + np.arange(250) * 20.0
    px_y = y0 + 10.0 + np.arange(250) * 20.0
    hh = rng.uniform(0.05, 0.15, size=(4, 250, 250)).astype(np.float32)
    hv = rng.uniform(0.01, 0.05, size=(4, 250, 250)).astype(np.float32)
    cube = stats_mod._MockDataset(
        data_vars={
            "HHHH": stats_mod._MockDataArray(hh, ("time", "y", "x")),
            "HVHV": stats_mod._MockDataArray(hv, ("time", "y", "x")),
        },
        coords={
            "time": stats_mod._MockCoord(np.array(dates, dtype="datetime64[D]")),
            "y": stats_mod._MockCoord(px_y),
            "x": stats_mod._MockCoord(px_x),
        },
    )
    coh_df, report = compute_coherence_table(
        dates=dates,
        dropped_dates=dropped,
        grid_df=grid_df,
        bounds=bounds,
        cell_size_m=500.0,
        min_valid_fraction=0.5,
        stats_mod=stats_mod,
        cube=cube,
        offline=True,
    )
    print_coherence_summary(report)

    assert len(coh_df) == 100 * (len(dates) - 1)
    ok_rows = coh_df[coh_df["interval_idx"] == 0]
    assert ok_rows["coh"].notna().all()
    assert int(ok_rows["coh"].min()) >= 0 and int(ok_rows["coh"].max()) <= 100
    assert coh_df[coh_df["interval_idx"] == 1]["coh"].isna().all()
    assert coh_df[coh_df["interval_idx"] == 2]["coh"].isna().all()

    print("\n[PASS] --self-test verified 80m->500m GUNW aggregation, [0,100] scaling, and dropped-date nulls.")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for Stage 5 coherence."""
    parser = argparse.ArgumentParser(
        description="Compute 500 m cell 12-day interferometric coherence from NISAR GUNW (with GCOV fallback)."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--quality", type=Path, default=PROJECT_ROOT / "data/quality_report.json")
    parser.add_argument("--grid", type=Path, default=PROJECT_ROOT / "data/grid_cells.parquet")
    parser.add_argument("--cube", type=Path, default=None)
    parser.add_argument("--selected-scenes", type=Path, default=PROJECT_ROOT / "data/selected_scenes.json")
    parser.add_argument("--out-coherence", type=Path, default=PROJECT_ROOT / "data/coherence.parquet")
    parser.add_argument("--out-report", type=Path, default=PROJECT_ROOT / "data/coherence_report.json")
    parser.add_argument("--offline", action="store_true", help="Skip ASF query and use GCOV fallback directly.")
    parser.add_argument("--self-test", action="store_true", help="Run built-in unit verification.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for pipeline/05_coherence.py."""
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()

    stats_mod = _load_stats_helpers()
    cfg = stats_mod.load_config(_resolve_path(args.config))
    cube_path = _resolve_path(
        args.cube if args.cube is not None else Path(cfg.get("merged_cube_zarr", "data/gcov_cube.zarr"))
    )
    quality_path = _resolve_path(args.quality)
    kept_dates, dropped_dates = stats_mod.load_quality_report(quality_path)

    cube = None
    cube_crs = None
    if cube_path.exists():
        cube, cube_crs = stats_mod._open_zarr_cube(cube_path)

    if kept_dates is not None:
        dates = sorted(set(kept_dates) | dropped_dates)
    elif cube is not None:
        dates = sorted(
            stats_mod._normalize_date_str(t) for t in cube.coords["time"].values
        )
    else:
        raise FileNotFoundError("Neither data/quality_report.json nor data/gcov_cube.zarr exists.")

    grid_path = _resolve_path(args.grid)
    grid_df, bounds = stats_mod.load_grid_cells(grid_path, target_crs=cube_crs)
    geometry = load_locked_geometry(cfg, _resolve_path(args.selected_scenes), cube_path)
    study_box = list(cfg.get("study_box", [113.75, -2.25, 114.25, -1.75]))
    token = "" if args.offline else _get_earthdata_token()

    gunw_scenes: list[dict[str, Any]] = []
    if not args.offline:
        gunw_scenes = search_asf_gunw_pairs(study_box, dates, geometry)

    coh_df, report = compute_coherence_table(
        dates=dates,
        dropped_dates=dropped_dates,
        grid_df=grid_df,
        bounds=bounds,
        cell_size_m=float(cfg.get("cell_size_m", 500)),
        min_valid_fraction=float(cfg.get("min_valid_fraction", 0.5)),
        stats_mod=stats_mod,
        cube=cube,
        gunw_scenes=gunw_scenes,
        study_box=study_box,
        token=token,
        offline=args.offline,
    )
    report["geometry_used"] = geometry

    out_coh = _resolve_path(args.out_coherence)
    out_rep = _resolve_path(args.out_report)
    out_coh.parent.mkdir(parents=True, exist_ok=True)
    out_rep.parent.mkdir(parents=True, exist_ok=True)
    coh_df.to_parquet(out_coh, index=False)
    out_rep.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print_coherence_summary(report)
    print(f"\nSaved coherence table -> {out_coh} ({len(coh_df)} rows)")
    print(f"Saved report          -> {out_rep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
