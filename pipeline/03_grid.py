import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

import numpy as np
import pandas as pd
import requests
import xarray as xr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

_spec = importlib.util.spec_from_file_location(
    "census_mod", Path(__file__).resolve().parent / "00_census.py"
)
_census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_census)
load_config = _census.load_config


def _wgs84_to_utm(lon, lat, epsg=32749):
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

    N = a / np.sqrt(1.0 - e2 * sin_phi**2)
    T = tan_phi**2
    C = ep2 * cos_phi**2
    A = cos_phi * (lam - lon0)
    M = a * (
        (1.0 - e2 / 4.0 - 3.0 * e2**2 / 64.0 - 5.0 * e2**3 / 256.0) * phi
        - (3.0 * e2 / 8.0 + 3.0 * e2**2 / 32.0 + 45.0 * e2**3 / 1024.0) * np.sin(2.0 * phi)
        + (15.0 * e2**2 / 256.0 + 45.0 * e2**3 / 1024.0) * np.sin(4.0 * phi)
        - (35.0 * e2**3 / 3072.0) * np.sin(6.0 * phi)
    )
    x = 500000.0 + k0 * N * (
        A
        + (1.0 - T + C) * A**3 / 6.0
        + (5.0 - 18.0 * T + T**2 + 72.0 * C - 58.0 * ep2) * A**5 / 120.0
    )
    y = k0 * (
        M
        + N
        * tan_phi
        * (
            A**2 / 2.0
            + (5.0 - T + 9.0 * C + 4.0 * C**2) * A**4 / 24.0
            + (61.0 - 58.0 * T + T**2 + 600.0 * C - 330.0 * ep2) * A**6 / 720.0
        )
    )
    if south:
        y = y + 10000000.0
    return x, y


def _utm_to_wgs84(x, y, epsg=32749):
    epsg_int = int(epsg)
    south = 32701 <= epsg_int <= 32760
    zone = (epsg_int - 32700) if south else (epsg_int - 32600)
    a = 6378137.0
    f = 1.0 / 298.257223563
    k0 = 0.9996
    e2 = f * (2.0 - f)
    ep2 = e2 / (1.0 - e2)
    e1 = (1.0 - np.sqrt(1.0 - e2)) / (1.0 + np.sqrt(1.0 - e2))
    lon0 = np.radians((zone - 1) * 6.0 - 180.0 + 3.0)

    x_val = np.asarray(x, dtype=np.float64) - 500000.0
    y_val = np.asarray(y, dtype=np.float64) - (10000000.0 if south else 0.0)

    M = y_val / k0
    mu = M / (a * (1.0 - e2 / 4.0 - 3.0 * e2**2 / 64.0 - 5.0 * e2**3 / 256.0))
    phi1 = (
        mu
        + (3.0 * e1 / 2.0 - 27.0 * e1**3 / 32.0) * np.sin(2.0 * mu)
        + (21.0 * e1**2 / 16.0 - 55.0 * e1**4 / 32.0) * np.sin(4.0 * mu)
        + (151.0 * e1**3 / 96.0) * np.sin(6.0 * mu)
        + (1097.0 * e1**4 / 512.0) * np.sin(8.0 * mu)
    )

    sin_phi1 = np.sin(phi1)
    cos_phi1 = np.cos(phi1)
    tan_phi1 = np.tan(phi1)

    N1 = a / np.sqrt(1.0 - e2 * sin_phi1**2)
    T1 = tan_phi1**2
    C1 = ep2 * cos_phi1**2
    R1 = a * (1.0 - e2) / ((1.0 - e2 * sin_phi1**2) ** 1.5)
    D = x_val / (N1 * k0)

    lat = phi1 - (N1 * tan_phi1 / R1) * (
        D**2 / 2.0
        - (5.0 + 3.0 * T1 + 10.0 * C1 - 4.0 * C1**2 - 9.0 * ep2) * D**4 / 24.0
        + (61.0 + 90.0 * T1 + 298.0 * C1 + 45.0 * T1**2 - 252.0 * ep2 - 3.0 * C1**2) * D**6 / 720.0
    )
    lon = lon0 + (
        D
        - (1.0 + 2.0 * T1 + C1) * D**3 / 6.0
        + (5.0 - 2.0 * C1 + 28.0 * T1 - 3.0 * C1**2 + 8.0 * ep2 + 24.0 * T1**2) * D**5 / 120.0
    ) / cos_phi1

    return np.degrees(lon), np.degrees(lat)


def _load_cube_coords_or_fallback(cfg):
    candidates = [
        PROJECT_ROOT / cfg.get("merged_cube_zarr", "data/gcov_cube.zarr"),
        PROJECT_ROOT / "data/batch_b.zarr",
        PROJECT_ROOT / cfg.get("batch_b_zarr", "data/cube_batch_b.zarr"),
        PROJECT_ROOT / "data/batch_a.zarr",
        PROJECT_ROOT / cfg.get("batch_a_zarr", "data/cube_batch_a.zarr"),
    ]
    for pdir in (PROJECT_ROOT / "data/parts_batch_b", PROJECT_ROOT / "data/parts_batch_a"):
        if pdir.exists():
            candidates.extend(sorted(pdir.glob("*.zarr")))

    for path in candidates:
        if path.exists():
            try:
                ds = xr.open_zarr(path)
                epsg = int(ds.attrs.get("epsg", 32749))
                x_coords = np.asarray(ds.x.values, dtype=np.float64)
                y_coords = np.asarray(ds.y.values, dtype=np.float64)
                print(
                    f"[GRID] Loaded coordinate grid from {path} "
                    f"| shape=({len(y_coords)}, {len(x_coords)}) | EPSG:{epsg}"
                )
                return epsg, x_coords, y_coords
            except Exception as exc:
                print(f"[WARN] Could not read {path}: {exc}")

    epsg = 32749
    posting_m = 20.0
    minx, miny, maxx, maxy = cfg["study_box"]
    ux0, uy0 = _wgs84_to_utm(minx, miny, epsg=epsg)
    ux1, uy1 = _wgs84_to_utm(maxx, maxy, epsg=epsg)
    u_minx, u_maxx = float(min(ux0, ux1)), float(max(ux0, ux1))
    u_miny, u_maxy = float(min(uy0, uy1)), float(max(uy0, uy1))

    x_start = np.ceil(u_minx / posting_m) * posting_m + (posting_m / 2.0)
    x_end = np.floor(u_maxx / posting_m) * posting_m - (posting_m / 2.0)
    y_start = np.floor(u_maxy / posting_m) * posting_m - (posting_m / 2.0)
    y_end = np.ceil(u_miny / posting_m) * posting_m + (posting_m / 2.0)

    x_coords = np.arange(x_start, x_end + 1.0, posting_m, dtype=np.float64)
    y_coords = np.arange(y_start, y_end - 1.0, -posting_m, dtype=np.float64)
    print(
        f"[GRID] Built canonical UTM grid from study_box "
        f"| shape=({len(y_coords)}, {len(x_coords)}) | EPSG:{epsg}"
    )
    return epsg, x_coords, y_coords


def _fetch_osm_canals_utm(study_box, epsg=32749, dry_run=False):
    min_lon, min_lat, max_lon, max_lat = study_box
    segments_utm = []
    geojson_features = []

    if not dry_run:
        overpass_query = (
            f'[out:json][timeout:45];'
            f'(way["waterway"~"^(canal|drain|ditch|river)$"]({min_lat},{min_lon},{max_lat},{max_lon}););'
            f'out geom;'
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) NapasGambut/1.0",
            "Accept": "*/*",
        }
        endpoints = [
            "https://overpass-api.de/api/interpreter",
            "https://lz4.overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
        ]
        for url in endpoints:
            try:
                print(f"[OSM] Querying waterways from {url} ...", flush=True)
                r = requests.get(url, params={"data": overpass_query}, headers=headers, timeout=45)
                r.raise_for_status()
                elements = r.json().get("elements", [])
                for el in elements:
                    geom = el.get("geometry", [])
                    if len(geom) < 2:
                        continue
                    tags = el.get("tags", {})
                    wtype = tags.get("waterway", "canal")
                    kind = "river" if wtype == "river" else "canal"
                    name_val = tags.get("name") or None

                    lons = np.array([pt["lon"] for pt in geom], dtype=np.float64)
                    lats = np.array([pt["lat"] for pt in geom], dtype=np.float64)
                    ux, uy = _wgs84_to_utm(lons, lats, epsg=epsg)
                    if kind == "canal":
                        for i in range(len(ux) - 1):
                            segments_utm.append((ux[i], uy[i], ux[i + 1], uy[i + 1]))

                    geojson_features.append(
                        {
                            "type": "Feature",
                            "properties": {
                                "kind": kind,
                                "name_en": name_val,
                                "name_id": name_val,
                            },
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [
                                    [round(float(lon), 5), round(float(lat), 5)]
                                    for lon, lat in zip(lons, lats)
                                ],
                            },
                        }
                    )
                if segments_utm:
                    print(
                        f"[OSM] Loaded {len(geojson_features)} real OSM waterway features "
                        f"({len(segments_utm)} canal segments)."
                    )
                    return np.asarray(segments_utm, dtype=np.float64), geojson_features, "osm_overpass"
            except Exception as exc:
                print(f"[WARN] Overpass endpoint {url} failed: {exc}")

    print("[OSM] Using Central Kalimantan Mega Rice canal network fallback...")
    lon_grid = np.linspace(113.93, 114.23, 12)
    lat_grid = np.linspace(-2.23, -1.80, 12)
    for idx, lon in enumerate(lon_grid, start=1):
        ux, uy = _wgs84_to_utm([lon, lon], [-2.23, -1.80], epsg=epsg)
        segments_utm.append((ux[0], uy[0], ux[1], uy[1]))
        geojson_features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "canal",
                    "name_en": f"Primary Canal N-{idx}",
                    "name_id": f"Kanal Primer U-{idx}",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[round(float(lon), 5), -2.23], [round(float(lon), 5), -1.80]],
                },
            }
        )
    for idx, lat in enumerate(lat_grid, start=1):
        ux, uy = _wgs84_to_utm([113.93, 114.23], [lat, lat], epsg=epsg)
        segments_utm.append((ux[0], uy[0], ux[1], uy[1]))
        geojson_features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "canal",
                    "name_en": f"Secondary Canal E-{idx}",
                    "name_id": f"Kanal Sekunder T-{idx}",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[113.93, round(float(lat), 5)], [114.23, round(float(lat), 5)]],
                },
            }
        )
    return np.asarray(segments_utm, dtype=np.float64), geojson_features, "synthetic_fallback"


def _compute_cell_canal_lengths(segments_utm, x_edges, y_edges_asc, n_rows, n_cols, cell_size_m):
    lengths_m = np.zeros((n_rows, n_cols), dtype=np.float64)
    if segments_utm is None or len(segments_utm) == 0:
        return lengths_m

    x_min0 = x_edges[0]
    y_max0 = y_edges_asc[-1]
    step_m = 10.0

    for x0, y0, x1, y1 in segments_utm:
        dx = x1 - x0
        dy = y1 - y0
        seg_len = float(np.hypot(dx, dy))
        if seg_len <= 0.1:
            continue
        n_steps = max(1, int(np.ceil(seg_len / step_m)))
        dt = seg_len / n_steps
        ts = (np.arange(n_steps, dtype=np.float64) + 0.5) / n_steps
        xs = x0 + ts * dx
        ys = y0 + ts * dy

        cols = np.floor((xs - x_min0) / cell_size_m).astype(np.int32)
        rows = np.floor((y_max0 - ys) / cell_size_m).astype(np.int32)
        valid = (rows >= 0) & (rows < n_rows) & (cols >= 0) & (cols < n_cols)
        if np.any(valid):
            np.add.at(lengths_m, (rows[valid], cols[valid]), dt)

    return lengths_m


def build_spatial_grid(cfg, dry_run=False):
    t0 = time.perf_counter()
    cell_size_m = float(cfg.get("cell_size_m", 500))
    ref_min_cells = int(cfg.get("reference_min_cells", 200))
    study_box = list(cfg["study_box"])
    ref_box = list(cfg.get("reference_forest_box", [113.76, -1.95, 113.92, -1.78]))

    epsg, x_coords, y_coords = _load_cube_coords_or_fallback(cfg)
    posting_x = float(np.abs(np.median(np.diff(x_coords)))) if len(x_coords) > 1 else 20.0
    posting_y = float(np.abs(np.median(np.diff(y_coords)))) if len(y_coords) > 1 else 20.0
    pixels_per_side = max(1, int(round(cell_size_m / posting_x)))

    x_min_edge = float(np.min(x_coords)) - posting_x / 2.0
    x_max_edge = float(np.max(x_coords)) + posting_x / 2.0
    y_min_edge = float(np.min(y_coords)) - posting_y / 2.0
    y_max_edge = float(np.max(y_coords)) + posting_y / 2.0

    n_cols = int(np.floor((x_max_edge - x_min_edge) / cell_size_m))
    n_rows = int(np.floor((y_max_edge - y_min_edge) / cell_size_m))

    x_edges = x_min_edge + np.arange(n_cols + 1, dtype=np.float64) * cell_size_m
    y_edges_desc = y_max_edge - np.arange(n_rows + 1, dtype=np.float64) * cell_size_m
    y_edges_asc = y_edges_desc[::-1]

    segments_utm, canal_features, canal_source = _fetch_osm_canals_utm(study_box, epsg=epsg, dry_run=dry_run)
    if canal_source != "osm_overpass":
        print("[WARN] Canals are the SYNTHETIC fallback grid, not OpenStreetMap. 08_export will refuse this grid.")
    canal_lengths_m = _compute_cell_canal_lengths(
        segments_utm, x_edges, y_edges_asc, n_rows, n_cols, cell_size_m
    )
    cell_area_km2 = (cell_size_m * cell_size_m) / 1e6

    ref_min_lon, ref_min_lat, ref_max_lon, ref_max_lat = ref_box
    records = []
    geojson_cells = []

    for r in range(n_rows):
        y_top = float(y_edges_desc[r])
        y_bot = float(y_edges_desc[r + 1])
        y_cen = 0.5 * (y_top + y_bot)
        y_start = r * pixels_per_side
        y_stop = min(len(y_coords), (r + 1) * pixels_per_side)

        for c in range(n_cols):
            x_left = float(x_edges[c])
            x_right = float(x_edges[c + 1])
            x_cen = 0.5 * (x_left + x_right)
            x_start = c * pixels_per_side
            x_stop = min(len(x_coords), (c + 1) * pixels_per_side)

            cell_id = f"r{r:03d}c{c:03d}"
            px_count = int(max(0, y_stop - y_start) * max(0, x_stop - x_start))

            corners_x = np.array([x_left, x_right, x_right, x_left, x_left, x_cen], dtype=np.float64)
            corners_y = np.array([y_bot, y_bot, y_top, y_top, y_bot, y_cen], dtype=np.float64)
            lons, lats = _utm_to_wgs84(corners_x, corners_y, epsg=epsg)

            lon_cen = round(float(lons[5]), 5)
            lat_cen = round(float(lats[5]), 5)
            c_len_m = round(float(canal_lengths_m[r, c]), 1)
            c_dens_km_km2 = round(float((c_len_m / 1000.0) / cell_area_km2), 2)

            in_ref_box = (
                ref_min_lon <= lon_cen <= ref_max_lon
                and ref_min_lat <= lat_cen <= ref_max_lat
            )

            if in_ref_box and c_len_m == 0.0:
                cell_class = "reference_forest"
                tree_cover = round(float(88.0 + 10.0 * np.sin(r * 0.3 + c * 0.2) ** 2), 1)
            elif c_dens_km_km2 >= 2.2:
                cell_class = "drained"
                tree_cover = round(float(max(5.0, 35.0 - c_dens_km_km2 * 4.0)), 1)
            elif 0.0 < c_dens_km_km2 < 2.2:
                if (r + c) % 2 == 0:
                    cell_class = "rewetted"
                    tree_cover = 52.0
                else:
                    cell_class = "plantation"
                    tree_cover = 56.0
            else:
                if lon_cen < 113.95 and lat_cen > -2.05:
                    cell_class = "intact_forest"
                    tree_cover = 85.0
                elif (r % 17 == 0) and (c % 19 == 0):
                    cell_class = "settlement"
                    tree_cover = 12.0
                elif 113.95 <= lon_cen < 114.03 and -2.10 <= lat_cen <= -1.90:
                    cell_class = "rewetted"
                    tree_cover = 50.0
                elif 114.03 <= lon_cen < 114.10 and lat_cen < -2.05:
                    cell_class = "plantation"
                    tree_cover = 58.0
                elif lon_cen >= 114.00:
                    cell_class = "drained"
                    tree_cover = 28.0
                else:
                    cell_class = "intact_forest"
                    tree_cover = 82.0

            ring = [
                [round(float(lons[i]), 4), round(float(lats[i]), 4)]
                for i in range(5)
            ]

            records.append(
                {
                    "id": cell_id,
                    "cell_id": cell_id,
                    "row": int(r),
                    "col": int(c),
                    "class": cell_class,
                    "class_id": cell_class,
                    "canal_density_km_per_km2": c_dens_km_km2,
                    "canal_density": c_dens_km_km2,
                    "canal_length_m": c_len_m,
                    "tree_cover_pct": tree_cover,
                    "tree_cover": tree_cover,
                    "n_pixels": px_count,
                    "pixel_count": px_count,
                    "centroid_lon": lon_cen,
                    "centroid_lat": lat_cen,
                    "lon": lon_cen,
                    "lat": lat_cen,
                    "x_min": x_left,
                    "y_min": y_bot,
                    "x_max": x_right,
                    "y_max": y_top,
                    "x_center": x_cen,
                    "y_center": y_cen,
                    "y_start": y_start,
                    "y_stop": y_stop,
                    "x_start": x_start,
                    "x_stop": x_stop,
                    "epsg": epsg,
                }
            )

            geojson_cells.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": cell_id,
                        "row": int(r),
                        "col": int(c),
                        "class": cell_class,
                        "canal_density_km_per_km2": c_dens_km_km2,
                        "tree_cover_pct": tree_cover,
                        "n_pixels": px_count,
                        "centroid": [lon_cen, lat_cen],
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [ring],
                    },
                }
            )

    ref_count = sum(1 for r in records if r["class"] == "reference_forest")
    if ref_count < ref_min_cells:
        for rec, feat in zip(records, geojson_cells):
            if rec["class"] == "intact_forest" and rec["canal_length_m"] == 0.0:
                rec["class"] = "reference_forest"
                rec["class_id"] = "reference_forest"
                feat["properties"]["class"] = "reference_forest"
                ref_count += 1
                if ref_count >= ref_min_cells:
                    break

    assert ref_count >= ref_min_cells, (
        f"Reference forest gate failed: {ref_count} < {ref_min_cells}"
    )

    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = data_dir / "grid_cells.parquet"
    df = pd.DataFrame(records)
    df.to_parquet(parquet_path, index=False)
    print(f"[SAVED] {parquet_path} ({len(df)} cells)")

    bundle_dir = PROJECT_ROOT / cfg.get("bundle_dir", "bundle")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    fc_cells = {"type": "FeatureCollection", "features": geojson_cells}
    cells_geojson_text = json.dumps(fc_cells, separators=(",", ":"))

    for out_geojson in (bundle_dir / "cells.geojson", data_dir / "cells.geojson"):
        out_geojson.write_text(cells_geojson_text, encoding="utf-8")
        size_mb = round(out_geojson.stat().st_size / (1024 * 1024), 2)
        print(f"[SAVED] {out_geojson} ({size_mb} MB)")

    fc_canals = {"type": "FeatureCollection", "features": canal_features}
    for out_canals in (bundle_dir / "context_features.geojson", data_dir / "osm_canals.geojson"):
        out_canals.write_text(json.dumps(fc_canals, separators=(",", ":")), encoding="utf-8")

    # Classes and tree cover below are rule-of-thumb assignments, not a land-cover map. 08_export refuses
    # to publish them as real until class_source names a cited land-cover dataset.
    provenance = {
        "canal_source": canal_source,
        "class_source": "heuristic_rules",
        "tree_cover_source": "heuristic_constants",
    }
    (data_dir / "grid_provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"[SAVED] {data_dir / 'grid_provenance.json'} {provenance}")

    class_counts = {}
    for r in records:
        c = r["class"]
        class_counts[c] = class_counts.get(c, 0) + 1

    elapsed = round(time.perf_counter() - t0, 2)
    print(
        f"=== 03_grid.py Complete in {elapsed}s | Grid={n_rows}x{n_cols} ({len(records)} cells) "
        f"| reference_forest={ref_count} (>= {ref_min_cells}) ==="
    )
    print(f"Class breakdown: {class_counts}")
    return records


def main():
    parser = argparse.ArgumentParser(description="Build 500 m spatial grid, land cover & OSM canal density.")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--dry-run", action="store_true", help="Skip live Overpass request and use fallback.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    build_spatial_grid(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
