"""Canal ranking helper (Contract 0.2 / Track D1): "Block this canal first".

Buffers each OSM canal way by 1 km (EPSG:32749), spatially joins peatland cells
(drained, rewetted, plantation), computes season-minimum drying and burned-cell
counts per canal, and returns the top 20 canals sorted by lowest median_min_hh_db.

Works with GeoPandas/Shapely when installed and falls back cleanly to an exact
pure-NumPy UTM 49S segment-to-cell-box distance check (<= 1000 m) when running
in lightweight Python environments.

Run: py pipeline/canal_ranking.py [--self-test] [--out data/canal_rankings.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString, Polygon, box, shape
    HAS_GEO = True
except ImportError:
    HAS_GEO = False

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
BUNDLE_DIR = PROJECT_ROOT / "bundle"

PEAT_CLASSES = {"drained", "rewetted", "plantation"}
BURNED_STATES = {2, 3, 4}
NO_DATA_STATE = 1


def round_half_up(v: float, d: int = 1) -> float:
    """JavaScript Math.round semantics, matching scripts/mock/scorecard.ts."""
    f = 10 ** d
    return math.floor(float(v) * f + 0.5) / f


def wgs84_to_utm(lon: np.ndarray, lat: np.ndarray, epsg: int = 32749) -> tuple[np.ndarray, np.ndarray]:
    """Convert WGS84 lon/lat arrays to UTM (default EPSG:32749, UTM Zone 49S)."""
    epsg_int = int(epsg)
    south = 32701 <= epsg_int <= 32760
    zone = (epsg_int - 32700) if south else (epsg_int - 32600)
    a = 6378137.0
    f = 1.0 / 298.257223563
    k0 = 0.9996
    e2 = f * (2.0 - f)
    ep2 = e2 / (1.0 - e2)
    lon0 = np.radians((zone - 1) * 6.0 - 180.0 + 3.0)
    phi = np.radians(np.asarray(lat, dtype=np.float64))
    lam = np.radians(np.asarray(lon, dtype=np.float64))

    sin_phi = np.sin(phi)
    cos_phi = np.cos(phi)
    tan_phi = np.tan(phi)

    N = a / np.sqrt(1.0 - e2 * sin_phi ** 2)
    T = tan_phi ** 2
    C = ep2 * cos_phi ** 2
    A = cos_phi * (lam - lon0)
    M = a * (
        (1.0 - e2 / 4.0 - 3.0 * e2 ** 2 / 64.0 - 5.0 * e2 ** 3 / 256.0) * phi
        - (3.0 * e2 / 8.0 + 3.0 * e2 ** 2 / 32.0 + 45.0 * e2 ** 3 / 1024.0) * np.sin(2.0 * phi)
        + (15.0 * e2 ** 2 / 256.0 + 45.0 * e2 ** 3 / 1024.0) * np.sin(4.0 * phi)
        - (35.0 * e2 ** 3 / 3072.0) * np.sin(6.0 * phi)
    )
    x = 500000.0 + k0 * N * (
        A
        + (1.0 - T + C) * A ** 3 / 6.0
        + (5.0 - 18.0 * T + T ** 2 + 72.0 * C - 58.0 * ep2) * A ** 5 / 120.0
    )
    y = (10000000.0 if south else 0.0) + k0 * (
        M
        + N
        * tan_phi
        * (
            A ** 2 / 2.0
            + (5.0 - T + 9.0 * C + 4.0 * C ** 2) * A ** 4 / 24.0
            + (61.0 - 58.0 * T + T ** 2 + 600.0 * C - 330.0 * ep2) * A ** 6 / 720.0
        )
    )
    return x, y


def stable_canal_id(props: dict[str, Any], coords: list[list[float]], fallback_index: int) -> str:
    """Return an existing id, osm_id, or deterministic geometry-derived 'osm:<hash>' id."""
    if props.get("id"):
        return str(props["id"])
    if props.get("osm_id"):
        raw = str(props["osm_id"])
        return raw if raw.startswith("osm:") else f"osm:{raw}"
    if coords:
        rounded = [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in coords]
        digest = hashlib.sha1(json.dumps(rounded, separators=(",", ":")).encode("utf-8")).hexdigest()[:10]
        return f"osm:{digest}"
    return f"osm:canal-{fallback_index:04d}"


def assign_canal_ids(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return shallow-copied context features with deterministic `properties.id` on canals."""
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    canal_seq = 0
    for feat in features:
        props = dict(feat.get("properties") or {})
        geom = feat.get("geometry") or {}
        if props.get("kind") == "canal":
            canal_seq += 1
            coords = geom.get("coordinates") or []
            if geom.get("type") == "MultiLineString" and coords:
                coords = coords[0]
            cid = stable_canal_id(props, coords if isinstance(coords, list) else [], canal_seq)
            if cid in seen_ids:
                cid = f"{cid}-{canal_seq}"
            seen_ids.add(cid)
            props["id"] = cid
        out.append({**feat, "properties": props})
    return out


def _normalize_geojson_canals(canals_input: Any) -> list[dict[str, Any]]:
    """Convert GeoDataFrame, FeatureCollection, list of features, or path to canal GeoJSON features."""
    if isinstance(canals_input, (str, Path)):
        canals_input = json.loads(Path(canals_input).read_text(encoding="utf-8"))

    if HAS_GEO and isinstance(canals_input, gpd.GeoDataFrame):
        gdf = canals_input
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
        feats = []
        for idx, row in gdf.iterrows():
            props = {k: (None if pd.isna(v) else v) for k, v in row.drop(labels=["geometry"]).to_dict().items()}
            if props.get("kind", "canal") != "canal":
                continue
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            feats.append({"type": "Feature", "geometry": geom.__geo_interface__, "properties": props})
        return assign_canal_ids(feats)

    raw_features = canals_input.get("features", []) if isinstance(canals_input, dict) else list(canals_input)
    canal_feats = []
    for feat in raw_features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        if props.get("kind", "canal") != "canal":
            continue
        if geom.get("type") not in ("LineString", "MultiLineString"):
            continue
        canal_feats.append(feat)
    return assign_canal_ids(canal_feats)


def _normalize_cells(cells_input: Any, epsg: int) -> pd.DataFrame:
    """Return DataFrame of peat cells with cell_id, class, x_min, y_min, x_max, y_max in UTM."""
    if isinstance(cells_input, (str, Path)):
        p = Path(cells_input)
        if p.suffix == ".parquet":
            cells_input = pd.read_parquet(p)
        else:
            cells_input = json.loads(p.read_text(encoding="utf-8"))

    if HAS_GEO and isinstance(cells_input, gpd.GeoDataFrame):
        gdf = cells_input.copy()
        if "cell_id" not in gdf.columns and "id" in gdf.columns:
            gdf["cell_id"] = gdf["id"]
        if "class" not in gdf.columns and "class_id" in gdf.columns:
            gdf["class"] = gdf["class_id"]
        gdf = gdf[gdf["class"].isin(PEAT_CLASSES)].copy()
        if gdf.empty:
            return pd.DataFrame(columns=["cell_id", "class", "x_min", "y_min", "x_max", "y_max", "geometry"])
        if gdf.crs is not None and gdf.crs.to_epsg() != epsg:
            gdf = gdf.to_crs(epsg)
        bounds = gdf.geometry.bounds
        gdf["x_min"] = bounds["minx"]
        gdf["y_min"] = bounds["miny"]
        gdf["x_max"] = bounds["maxx"]
        gdf["y_max"] = bounds["maxy"]
        return gdf

    if isinstance(cells_input, dict) and cells_input.get("type") == "FeatureCollection":
        rows = []
        for feat in cells_input.get("features", []):
            pr = feat.get("properties") or {}
            cls = pr.get("class") or pr.get("class_id")
            if cls not in PEAT_CLASSES:
                continue
            cid = pr.get("id") or pr.get("cell_id")
            ring = (feat.get("geometry") or {}).get("coordinates", [[]])[0]
            if not ring:
                lon, lat = pr["centroid"]
                xs, ys = wgs84_to_utm(np.array([lon]), np.array([lat]), epsg=epsg)
                rows.append({"cell_id": cid, "class": cls, "x_min": xs[0] - 250.0, "y_min": ys[0] - 250.0, "x_max": xs[0] + 250.0, "y_max": ys[0] + 250.0})
            else:
                lons = np.array([pt[0] for pt in ring], dtype=np.float64)
                lats = np.array([pt[1] for pt in ring], dtype=np.float64)
                xs, ys = wgs84_to_utm(lons, lats, epsg=epsg)
                rows.append({"cell_id": cid, "class": cls, "x_min": float(xs.min()), "y_min": float(ys.min()), "x_max": float(xs.max()), "y_max": float(ys.max())})
        return pd.DataFrame(rows)

    df = cells_input.copy()
    if "cell_id" not in df.columns and "id" in df.columns:
        df["cell_id"] = df["id"]
    if "class" not in df.columns and "class_id" in df.columns:
        df["class"] = df["class_id"]
    df = df[df["class"].isin(PEAT_CLASSES)].copy()
    if df.empty:
        return pd.DataFrame(columns=["cell_id", "class", "x_min", "y_min", "x_max", "y_max"])
    if not {"x_min", "y_min", "x_max", "y_max"}.issubset(df.columns):
        lon_col = "centroid_lon" if "centroid_lon" in df.columns else "lon"
        lat_col = "centroid_lat" if "centroid_lat" in df.columns else "lat"
        xs, ys = wgs84_to_utm(df[lon_col].to_numpy(), df[lat_col].to_numpy(), epsg=epsg)
        df["x_min"] = xs - 250.0
        df["x_max"] = xs + 250.0
        df["y_min"] = ys - 250.0
        df["y_max"] = ys + 250.0
    return df[["cell_id", "class", "x_min", "y_min", "x_max", "y_max"]].reset_index(drop=True)


def _cell_drying_and_burns(cell_stats_df: pd.DataFrame, states_df: pd.DataFrame | None) -> tuple[dict[str, float], set[str]]:
    """Compute {cell_id: min_hh_db} across valid passes and set of burned cell_ids."""
    stats = cell_stats_df.copy()
    if "cell_id" not in stats.columns and "id" in stats.columns:
        stats["cell_id"] = stats["id"]

    if "D_hh" in stats.columns:
        stats["_hh_db"] = pd.to_numeric(stats["D_hh"], errors="coerce")
    elif "hh_tenths" in stats.columns:
        stats["_hh_db"] = pd.to_numeric(stats["hh_tenths"], errors="coerce") / 10.0
    else:
        raise ValueError("cell_stats_df must contain 'D_hh' or 'hh_tenths'")

    if "is_dropped_date" in stats.columns:
        stats = stats[~stats["is_dropped_date"].astype(bool)]

    burned_cells: set[str] = set()
    if states_df is not None and not states_df.empty:
        st = states_df.copy()
        if "cell_id" not in st.columns and "id" in st.columns:
            st["cell_id"] = st["id"]
        st["state"] = pd.to_numeric(st["state"], errors="coerce")
        burned_cells = set(st.loc[st["state"].isin(BURNED_STATES), "cell_id"].astype(str))
        if {"cell_id", "date"}.issubset(stats.columns) and {"cell_id", "date"}.issubset(st.columns):
            merged = stats.merge(st[["cell_id", "date", "state"]], on=["cell_id", "date"], how="left")
            stats = merged[merged["state"].isna() | (merged["state"] != NO_DATA_STATE)]

    stats = stats.dropna(subset=["_hh_db"])
    min_hh = stats.groupby("cell_id")["_hh_db"].min().to_dict()
    return {str(k): float(v) for k, v in min_hh.items()}, burned_cells


def _min_dist_sq_segments_to_boxes(
    seg_ax: np.ndarray,
    seg_ay: np.ndarray,
    seg_bx: np.ndarray,
    seg_by: np.ndarray,
    box_xmin: np.ndarray,
    box_ymin: np.ndarray,
    box_xmax: np.ndarray,
    box_ymax: np.ndarray,
    max_dist: float,
) -> np.ndarray:
    """Return boolean mask (len boxes) for whether any segment is within max_dist of each axis-aligned box."""
    matched = np.zeros(len(box_xmin), dtype=bool)
    max_dist_sq = max_dist * max_dist
    n_seg = len(seg_ax)
    if n_seg == 0 or len(box_xmin) == 0:
        return matched

    # Fast canal-level AABB reject before checking per-segment proximity.
    cx0 = min(float(seg_ax.min()), float(seg_bx.min())) - max_dist
    cx1 = max(float(seg_ax.max()), float(seg_bx.max())) + max_dist
    cy0 = min(float(seg_ay.min()), float(seg_by.min())) - max_dist
    cy1 = max(float(seg_ay.max()), float(seg_by.max())) + max_dist
    cand_idx = np.flatnonzero((box_xmax >= cx0) & (box_xmin <= cx1) & (box_ymax >= cy0) & (box_ymin <= cy1))
    if len(cand_idx) == 0:
        return matched

    bx0 = box_xmin[cand_idx]
    bx1 = box_xmax[cand_idx]
    by0 = box_ymin[cand_idx]
    by1 = box_ymax[cand_idx]

    # Exact Euclidean distance from segment AB to axis-aligned box B is min over u in [0, 1] of dist(A + u*(B-A), B).
    # Sample adaptive dense substeps (at most 100 m spacing) plus segment endpoints, guaranteeing <=50 m bound error;
    # for boundary accuracy within 1000 m, evaluate exact box distance at critical points along each segment.
    hit = np.zeros(len(cand_idx), dtype=bool)
    for ax, ay, dx, dy in zip(seg_ax, seg_ay, seg_bx - seg_ax, seg_by - seg_ay):
        seg_len = math.hypot(dx, dy)
        smin_x = min(ax, ax + dx) - max_dist
        smax_x = max(ax, ax + dx) + max_dist
        smin_y = min(ay, ay + dy) - max_dist
        smax_y = max(ay, ay + dy) + max_dist
        local = (~hit) & (bx1 >= smin_x) & (bx0 <= smax_x) & (by1 >= smin_y) & (by0 <= smax_y)
        if not np.any(local):
            continue
        li = np.flatnonzero(local)
        lx0, lx1, ly0, ly1 = bx0[li], bx1[li], by0[li], by1[li]

        # Closed-form piecewise-quadratic minimization of ||clamp(A + u*D, box) - (A + u*D)||^2:
        # collect breakpoints u in [0, 1] where A_x + u*dx crosses lx0/lx1 or A_y + u*dy crosses ly0/ly1,
        # plus projection optima inside the intervals. Evaluating exact dist-to-box at 0, 1, all crossings,
        # and exact interior projection u* solves the convex 1D piecewise-quadratic minimum exactly.
        us = [np.zeros(len(li)), np.ones(len(li))]
        if abs(dx) > 1e-12:
            for edge in (lx0, lx1):
                u = (edge - ax) / dx
                us.append(np.clip(u, 0.0, 1.0))
        if abs(dy) > 1e-12:
            for edge in (ly0, ly1):
                u = (edge - ay) / dy
                us.append(np.clip(u, 0.0, 1.0))
        # Midpoints cover the interior sub-intervals; where active face has fixed clamp (cx, cy), minimize along u:
        u_stack = np.sort(np.vstack(us), axis=0)  # (k, m)
        mids = 0.5 * (u_stack[:-1] + u_stack[1:])
        candidates = [u_stack]
        # Inside each interval defined by midpoints, clamp target is constant per box, so optimal u on the segment
        # is (dx*(cx - ax) + dy*(cy - ay)) / (dx^2 + dy^2).
        denom = dx * dx + dy * dy
        if denom > 1e-12:
            for row in range(mids.shape[0]):
                um = mids[row]
                pxm = ax + um * dx
                pym = ay + um * dy
                cxm = np.where(pxm < lx0, lx0, np.where(pxm > lx1, lx1, pxm))
                cym = np.where(pym < ly0, ly0, np.where(pym > ly1, ly1, pym))
                # For coordinates inside the box on that interval, that component's error is 0 regardless of u;
                # optimize over whichever component(s) are clamped.
                x_out = (pxm < lx0) | (pxm > lx1)
                y_out = (pym < ly0) | (pym > ly1)
                d_num = np.where(x_out, dx * (cxm - ax), 0.0) + np.where(y_out, dy * (cym - ay), 0.0)
                d_den = np.where(x_out, dx * dx, 0.0) + np.where(y_out, dy * dy, 0.0)
                safe_den = np.where(d_den > 1e-12, d_den, 1.0)
                u_opt = np.where(d_den > 1e-12, np.clip(d_num / safe_den, u_stack[row], u_stack[row + 1]), um)
                candidates.append(u_opt[None, :])

        all_u = np.vstack(candidates)
        px = ax + all_u * dx
        py = ay + all_u * dy
        ex = np.maximum(0.0, np.maximum(lx0[None, :] - px, px - lx1[None, :]))
        ey = np.maximum(0.0, np.maximum(ly0[None, :] - py, py - ly1[None, :]))
        min_d2 = (ex * ex + ey * ey).min(axis=0)
        hit[li[min_d2 <= max_dist_sq + 1e-9]] = True

    matched[cand_idx[hit]] = True
    return matched


def _extract_segments_utm(geometry: dict[str, Any], epsg: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Return segment endpoint arrays (ax, ay, bx, by) in UTM meters and total length in km."""
    gtype = geometry.get("type")
    lines = [geometry.get("coordinates", [])] if gtype == "LineString" else list(geometry.get("coordinates", []))
    ax_list, ay_list, bx_list, by_list = [], [], [], []
    length_m = 0.0
    for line in lines:
        if len(line) < 2:
            continue
        arr = np.asarray(line, dtype=np.float64)
        xs, ys = wgs84_to_utm(arr[:, 0], arr[:, 1], epsg=epsg)
        dx = np.diff(xs)
        dy = np.diff(ys)
        length_m += float(np.hypot(dx, dy).sum())
        ax_list.append(xs[:-1])
        ay_list.append(ys[:-1])
        bx_list.append(xs[1:])
        by_list.append(ys[1:])
    if not ax_list:
        empty = np.array([], dtype=np.float64)
        return empty, empty, empty, empty, 0.0
    return (
        np.concatenate(ax_list),
        np.concatenate(ay_list),
        np.concatenate(bx_list),
        np.concatenate(by_list),
        length_m / 1000.0,
    )


def rank_canals(
    cells_gdf: Any,
    cell_stats_df: pd.DataFrame,
    states_df: pd.DataFrame | None,
    canals_gdf: Any,
    *,
    epsg: int = 32749,
    buffer_m: float = 1000.0,
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Rank up to top_n canals by lowest median minimum HH drying within a 1 km buffer.

    Returns a list of dicts matching Contract 0.2 `scorecard.rankings.canals`:
    `canal`, `name_en`, `name_id`, `length_km`, `n_cells`, `median_min_hh_db`, `n_burned_cells`.
    """
    canal_feats = _normalize_geojson_canals(canals_gdf)
    if not canal_feats:
        return []

    peat_df = _normalize_cells(cells_gdf, epsg=epsg)
    if peat_df.empty:
        return []

    min_hh_map, burned_cells = _cell_drying_and_burns(cell_stats_df, states_df)
    peat_df = peat_df[peat_df["cell_id"].astype(str).isin(min_hh_map)].copy().reset_index(drop=True)
    if peat_df.empty:
        return []

    peat_ids = peat_df["cell_id"].astype(str).tolist()
    peat_mins = np.array([min_hh_map[cid] for cid in peat_ids], dtype=np.float64)
    peat_burned = np.array([1 if cid in burned_cells else 0 for cid in peat_ids], dtype=np.int64)

    # Prefer geopandas spatial join when both inputs can cleanly use GeoPandas, else exact UTM box-segment distance.
    canals_matched: dict[int, list[int]] = {}
    canal_lengths_km: dict[int, float] = {}

    if HAS_GEO and isinstance(cells_gdf, gpd.GeoDataFrame) and isinstance(canals_gdf, gpd.GeoDataFrame):
        cells_utm = peat_df if isinstance(peat_df, gpd.GeoDataFrame) else gpd.GeoDataFrame(
            peat_df, geometry=[box(r.x_min, r.y_min, r.x_max, r.y_max) for r in peat_df.itertuples()], crs=f"EPSG:{epsg}"
        )
        canal_geoms = [shape(f["geometry"]) for f in canal_feats]
        canals_utm = gpd.GeoDataFrame(
            {"canal_idx": list(range(len(canal_feats)))},
            geometry=canal_geoms,
            crs="EPSG:4326",
        ).to_crs(epsg)
        for ci, geom in enumerate(canals_utm.geometry):
            canal_lengths_km[ci] = float(geom.length) / 1000.0
        buffered = gpd.GeoDataFrame(
            {"canal_idx": canals_utm["canal_idx"]},
            geometry=canals_utm.geometry.buffer(buffer_m),
            crs=f"EPSG:{epsg}",
        )
        joined = gpd.sjoin(cells_utm[["cell_id", "geometry"]].reset_index(), buffered, how="inner", predicate="intersects")
        for ci, grp in joined.groupby("canal_idx"):
            canals_matched[int(ci)] = sorted(set(int(x) for x in grp["index"]))
    else:
        bx0 = peat_df["x_min"].to_numpy(dtype=np.float64)
        by0 = peat_df["y_min"].to_numpy(dtype=np.float64)
        bx1 = peat_df["x_max"].to_numpy(dtype=np.float64)
        by1 = peat_df["y_max"].to_numpy(dtype=np.float64)
        for ci, feat in enumerate(canal_feats):
            ax, ay, bx, by, len_km = _extract_segments_utm(feat["geometry"], epsg=epsg)
            canal_lengths_km[ci] = len_km
            if len_km <= 0.0:
                continue
            mask = _min_dist_sq_segments_to_boxes(ax, ay, bx, by, bx0, by0, bx1, by1, buffer_m)
            idxs = np.flatnonzero(mask)
            if len(idxs) > 0:
                canals_matched[ci] = idxs.tolist()

    unnamed_counter = 0
    records: list[dict[str, Any]] = []
    for ci, feat in enumerate(canal_feats):
        props = feat.get("properties") or {}
        has_name = bool(props.get("name_en") or props.get("name_id") or props.get("name"))
        if not has_name:
            unnamed_counter += 1
        cell_idxs = canals_matched.get(ci)
        if not cell_idxs:
            continue
        vals = peat_mins[cell_idxs]
        med = float(np.median(vals))
        n_burned = int(peat_burned[cell_idxs].sum())
        raw_en = props.get("name_en") or props.get("name")
        raw_id = props.get("name_id") or props.get("name")
        name_en = str(raw_en) if raw_en else f"Unnamed canal #{unnamed_counter}"
        name_id = str(raw_id) if raw_id else f"Kanal tanpa nama #{unnamed_counter}"
        records.append({
            "canal": str(props["id"]),
            "name_en": name_en,
            "name_id": name_id,
            "length_km": round_half_up(canal_lengths_km.get(ci, 0.0), 2),
            "n_cells": int(len(cell_idxs)),
            "median_min_hh_db": round_half_up(med, 1),
            "n_burned_cells": n_burned,
        })

    records.sort(key=lambda r: (r["median_min_hh_db"], -r["n_burned_cells"], -r["n_cells"], r["canal"]))
    return records[:top_n]


def run_self_test() -> int:
    """Verify buffer matching, class filtering, sorting, rounding, and Contract 0.2 schema."""
    # Construct 3 UTM cells near 114.0E, -2.0S and 2 canals:
    # Canal A passes right through drained cell r000c000 (-3.14 dB, burned) and rewetted r000c001 (-1.86 dB).
    # Intact forest r000c002 (-0.2 dB) is adjacent to Canal A but must be excluded from peat aggregation.
    # Canal B sits 3 km east near drained r000c005 (-0.9 dB, unburned).
    xs, ys = wgs84_to_utm(np.array([114.0, 114.0045, 114.0, 114.035]), np.array([-2.0, -2.0, -2.0045, -2.0]))
    cells_df = pd.DataFrame([
        {"cell_id": "r000c000", "class": "drained", "x_min": xs[0] - 250, "x_max": xs[0] + 250, "y_min": ys[0] - 250, "y_max": ys[0] + 250},
        {"cell_id": "r000c001", "class": "rewetted", "x_min": xs[1] - 250, "x_max": xs[1] + 250, "y_min": ys[1] - 250, "y_max": ys[1] + 250},
        {"cell_id": "r000c002", "class": "intact_forest", "x_min": xs[2] - 250, "x_max": xs[2] + 250, "y_min": ys[2] - 250, "y_max": ys[2] + 250},
        {"cell_id": "r000c005", "class": "drained", "x_min": xs[3] - 250, "x_max": xs[3] + 250, "y_min": ys[3] - 250, "y_max": ys[3] + 250},
    ])
    stats_df = pd.DataFrame([
        {"cell_id": "r000c000", "date": "2026-07-04", "D_hh": 0.0},
        {"cell_id": "r000c000", "date": "2026-08-21", "D_hh": -3.14},
        {"cell_id": "r000c001", "date": "2026-08-21", "D_hh": -1.86},
        {"cell_id": "r000c002", "date": "2026-08-21", "D_hh": -0.20},
        {"cell_id": "r000c005", "date": "2026-08-21", "D_hh": -0.90},
    ])
    states_df = pd.DataFrame([
        {"cell_id": "r000c000", "date": "2026-08-21", "state": 2},
        {"cell_id": "r000c001", "date": "2026-08-21", "state": 7},
        {"cell_id": "r000c002", "date": "2026-08-21", "state": 8},
        {"cell_id": "r000c005", "date": "2026-08-21", "state": 8},
    ])
    canals_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[113.998, -2.0], [114.006, -2.0]]},
                "properties": {"id": "osm:101", "kind": "canal", "name_en": "Canal West", "name_id": "Kanal Barat"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[114.033, -2.0], [114.040, -2.0]]},
                "properties": {"id": "osm:202", "kind": "canal", "name_en": None, "name_id": None},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[114.033, -2.0], [114.040, -2.0]]},
                "properties": {"kind": "river", "name_en": "Ignore River", "name_id": "Sungai"},
            },
        ],
    }

    ranked = rank_canals(cells_df, stats_df, states_df, canals_fc)
    assert len(ranked) == 2, f"expected 2 canals, got {len(ranked)}"
    assert ranked[0]["canal"] == "osm:101", ranked[0]
    assert ranked[0]["n_cells"] == 2, ranked[0]
    assert ranked[0]["n_burned_cells"] == 1, ranked[0]
    assert ranked[0]["median_min_hh_db"] == -2.5, ranked[0]
    assert ranked[0]["length_km"] > 0.5, ranked[0]
    assert ranked[1]["canal"] == "osm:202" and ranked[1]["name_en"] == "Unnamed canal #1", ranked[1]
    assert ranked[1]["median_min_hh_db"] == -0.9, ranked[1]
    print("canal_ranking self-test: passed (buffer join, peat filter, sorting, schema)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rank peatland drainage canals for Contract 0.2 scorecard.")
    ap.add_argument("--cells", type=Path, default=DATA_DIR / "grid_cells.parquet")
    ap.add_argument("--stats", type=Path, default=DATA_DIR / "cell_stats.parquet")
    ap.add_argument("--states", type=Path, default=DATA_DIR / "states.parquet")
    ap.add_argument("--canals", type=Path, default=BUNDLE_DIR / "context_features.geojson")
    ap.add_argument("--out", type=Path, default=DATA_DIR / "canal_rankings.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return run_self_test()

    cells = pd.read_parquet(args.cells) if args.cells.suffix == ".parquet" else args.cells
    stats = pd.read_parquet(args.stats)
    states = pd.read_parquet(args.states) if args.states.exists() else None
    canals_path = args.canals if args.canals.exists() else (DATA_DIR / "osm_canals.geojson")
    ranked = rank_canals(cells, stats, states, canals_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(ranked, indent=2), encoding="utf-8")
    print(f"[SAVED] {args.out} ({len(ranked)} ranked canals)")
    if ranked:
        print(f"  top canal: {ranked[0]['canal']} ({ranked[0]['name_en']}), median_min_hh_db={ranked[0]['median_min_hh_db']} dB, cells={ranked[0]['n_cells']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
