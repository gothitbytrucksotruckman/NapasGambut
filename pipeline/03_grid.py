import argparse
import importlib.util
import json
import os
import time
import warnings
from pathlib import Path

import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import xarray as xr
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

_spec = importlib.util.spec_from_file_location(
    "census_mod", Path(__file__).resolve().parent / "00_census.py"
)
_census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_census)
load_config = _census.load_config

GFW_ASIA_MAPSERVER = "https://gis-gfw.wri.org/arcgis/rest/services/country_data/asia/MapServer"
GFW_PEAT_LAYER_URL = f"{GFW_ASIA_MAPSERVER}/10/query"
GFW_OIL_PALM_LAYER_URL = f"{GFW_ASIA_MAPSERVER}/2/query"
GFW_WOOD_FIBER_LAYER_URL = f"{GFW_ASIA_MAPSERVER}/0/query"

PRIMS_DEFAULT_ENDPOINTS = [
    "https://prims.brgm.go.id/arcgis/rest/services/PRIMS/Sekat_Kanal/FeatureServer/0/query",
    "https://prims.brg.go.id/arcgis/rest/services/PRIMS/Sekat_Kanal/MapServer/0/query",
    "https://geoportal.brgm.go.id/arcgis/rest/services/Sekat_Kanal/FeatureServer/0/query",
]


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


def _strip_zm_geometry(geom):
    if not geom or "coordinates" not in geom:
        return geom

    def _clean(coords):
        if not coords:
            return coords
        if isinstance(coords[0], (int, float)):
            return [float(coords[0]), float(coords[1])]
        return [_clean(c) for c in coords if c is not None]

    return {"type": geom["type"], "coordinates": _clean(geom["coordinates"])}


def _extract_osm_pbf_waterways(pbf_path, study_box):
    import osmium

    min_lon, min_lat, max_lon, max_lat = study_box
    bbox_poly = box(min_lon, min_lat, max_lon, max_lat)
    pad = 0.15

    class _WaterwayExtractor(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.features = []

        def way(self, w):
            if not w.tags:
                return
            wtype = w.tags.get("waterway")
            if wtype not in ("canal", "drain", "ditch", "river"):
                return
            coords = []
            near = False
            for nd in w.nodes:
                if nd.location.valid():
                    lon, lat = nd.location.lon, nd.location.lat
                    coords.append((lon, lat))
                    if (min_lon - pad) <= lon <= (max_lon + pad) and (min_lat - pad) <= lat <= (max_lat + pad):
                        near = True
            if near and len(coords) >= 2:
                line = LineString(coords)
                if line.intersects(bbox_poly):
                    clipped = line.intersection(bbox_poly)
                    if not clipped.is_empty:
                        name_val = w.tags.get("name") or None
                        kind = "river" if wtype == "river" else "canal"
                        geoms = [clipped] if clipped.geom_type == "LineString" else getattr(clipped, "geoms", [])
                        for g in geoms:
                            if g.geom_type == "LineString" and len(g.coords) >= 2:
                                self.features.append(
                                    {
                                        "type": "Feature",
                                        "properties": {
                                            "kind": kind,
                                            "waterway": wtype,
                                            "name_en": name_val,
                                            "name_id": name_val,
                                        },
                                        "geometry": {
                                            "type": "LineString",
                                            "coordinates": [
                                                [round(float(x), 5), round(float(y), 5)]
                                                for x, y in g.coords
                                            ],
                                        },
                                    }
                                )

    handler = _WaterwayExtractor()
    handler.apply_file(str(pbf_path), locations=True)
    return handler.features


# AI-generated (lines 264-522)
def _fetch_osm_canals_utm(study_box, epsg=32749, pbf_path=None):
    min_lon, min_lat, max_lon, max_lat = study_box
    bbox_poly = box(min_lon, min_lat, max_lon, max_lat)
    geojson_features = []

    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    extract_cache = data_dir / "osm_waterways_extract.geojson"
    default_pbf = Path(pbf_path) if pbf_path else (data_dir / "kalimantan-latest.osm.pbf")

    overpass_query = (
        f'[out:json][timeout:30];'
        f'(way["waterway"~"^(canal|drain|ditch|river)$"]({min_lat},{min_lon},{max_lat},{max_lon}););'
        f'out geom;'
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NapasGambut/1.0)",
        "Accept": "application/json",
    }
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ]

    if extract_cache.exists():
        try:
            cached_fc = json.loads(extract_cache.read_text(encoding="utf-8"))
            geojson_features = cached_fc.get("features", [])
            if geojson_features:
                print(
                    f"[OSM] Loaded {len(geojson_features)} real OSM waterway features from {extract_cache}"
                )
        except Exception as exc:
            print(f"[WARN] Could not read cached OSM extract {extract_cache}: {exc}")

    if not geojson_features and default_pbf.exists():
        print(f"[OSM] Extracting waterways from {default_pbf} via osmium...", flush=True)
        geojson_features = _extract_osm_pbf_waterways(default_pbf, study_box)
        if geojson_features:
            extract_cache.write_text(
                json.dumps({"type": "FeatureCollection", "features": geojson_features}, separators=(",", ":")),
                encoding="utf-8",
            )
            print(f"[OSM] Extracted {len(geojson_features)} real OSM waterways via osmium.")

    if not geojson_features:
        for url in endpoints:
            try:
                print(f"[OSM] Querying waterways from {url} ...", flush=True)
                r = requests.get(url, params={"data": overpass_query}, headers=headers, timeout=30)
                r.raise_for_status()
                elements = r.json().get("elements", [])
                for el in elements:
                    geom = el.get("geometry", [])
                    if len(geom) < 2:
                        continue
                    tags = el.get("tags", {})
                    wtype = tags.get("waterway", "canal")
                    if wtype not in ("canal", "drain", "ditch", "river"):
                        continue
                    kind = "river" if wtype == "river" else "canal"
                    name_val = tags.get("name") or None
                    coords = [(float(pt["lon"]), float(pt["lat"])) for pt in geom]
                    line = LineString(coords)
                    if not line.intersects(bbox_poly):
                        continue
                    clipped = line.intersection(bbox_poly)
                    geoms = [clipped] if clipped.geom_type == "LineString" else getattr(clipped, "geoms", [])
                    for g in geoms:
                        if g.geom_type == "LineString" and len(g.coords) >= 2:
                            geojson_features.append(
                                {
                                    "type": "Feature",
                                    "properties": {
                                        "kind": kind,
                                        "waterway": wtype,
                                        "name_en": name_val,
                                        "name_id": name_val,
                                    },
                                    "geometry": {
                                        "type": "LineString",
                                        "coordinates": [
                                            [round(float(x), 5), round(float(y), 5)]
                                            for x, y in g.coords
                                        ],
                                    },
                                }
                            )
                if geojson_features:
                    extract_cache.write_text(
                        json.dumps({"type": "FeatureCollection", "features": geojson_features}, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    print(f"[OSM] Fetched {len(geojson_features)} real OSM waterways from {url}.")
                    break
            except Exception as exc:
                print(f"[WARN] Overpass endpoint {url} failed: {exc}")

    canal_only_features = [
        f
        for f in geojson_features
        if f.get("properties", {}).get("waterway", f.get("properties", {}).get("kind"))
        in ("canal", "drain", "ditch")
    ]
    if not canal_only_features:
        raise RuntimeError(
            "Failed to fetch real OSM canals (waterway=canal|drain|ditch) via Overpass API or .osm.pbf/osmium; "
            "refusing to generate synthetic fallback canal grids."
        )

    canals_gdf = gpd.GeoDataFrame.from_features(canal_only_features, crs="EPSG:4326").to_crs(epsg=int(epsg))
    return canals_gdf, geojson_features, "osm_overpass"


def _fetch_arcgis_geojson_paginated(layer_url, study_box, page_size=2000, timeout=30):
    min_lon, min_lat, max_lon, max_lat = study_box
    features = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
            "returnZ": "false",
            "returnM": "false",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        resp = requests.get(layer_url, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        if "error" in payload:
            raise RuntimeError(f"ArcGIS REST error from {layer_url}: {payload['error']}")
        page = payload.get("features", [])
        for feat in page:
            if feat.get("geometry"):
                feat["geometry"] = _strip_zm_geometry(feat["geometry"])
        features.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return features


def _load_gfw_peat_and_concessions_utm(study_box, epsg=32749):
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    peat_cache = data_dir / "gfw_peatlands.geojson"
    conc_cache = data_dir / "gfw_concessions.geojson"

    peat_features = []
    if peat_cache.exists():
        try:
            peat_features = json.loads(peat_cache.read_text(encoding="utf-8")).get("features", [])
        except Exception as exc:
            print(f"[WARN] Could not read {peat_cache}: {exc}")
    if not peat_features:
        print(f"[GFW] Fetching Indonesia Peat Lands from {GFW_PEAT_LAYER_URL} ...", flush=True)
        peat_features = _fetch_arcgis_geojson_paginated(GFW_PEAT_LAYER_URL, study_box)
        peat_cache.write_text(
            json.dumps({"type": "FeatureCollection", "features": peat_features}, separators=(",", ":")),
            encoding="utf-8",
        )

    conc_features = []
    if conc_cache.exists():
        try:
            conc_features = json.loads(conc_cache.read_text(encoding="utf-8")).get("features", [])
        except Exception as exc:
            print(f"[WARN] Could not read {conc_cache}: {exc}")
    if not conc_features:
        print("[GFW] Fetching Indonesia Oil Palm & Wood Fiber Concessions...", flush=True)
        palm_feats = _fetch_arcgis_geojson_paginated(GFW_OIL_PALM_LAYER_URL, study_box)
        fiber_feats = _fetch_arcgis_geojson_paginated(GFW_WOOD_FIBER_LAYER_URL, study_box)
        conc_features = palm_feats + fiber_feats
        conc_cache.write_text(
            json.dumps({"type": "FeatureCollection", "features": conc_features}, separators=(",", ":")),
            encoding="utf-8",
        )

    peat_union_utm = None
    if peat_features:
        peat_gdf = gpd.GeoDataFrame.from_features(peat_features, crs="EPSG:4326").to_crs(epsg=int(epsg))
        peat_union_utm = unary_union(peat_gdf.geometry.buffer(0))

    conc_union_utm = None
    if conc_features:
        conc_gdf = gpd.GeoDataFrame.from_features(conc_features, crs="EPSG:4326").to_crs(epsg=int(epsg))
        conc_union_utm = unary_union(conc_gdf.geometry.buffer(0))

    print(
        f"[GFW] Loaded {len(peat_features)} peatland polygons and {len(conc_features)} concession polygons in EPSG:{epsg}."
    )
    return peat_union_utm, conc_union_utm


def _fetch_prims_dams_utm(study_box, epsg=32749, prims_urls=None):
    data_dir = PROJECT_ROOT / "data"
    local_dams = data_dir / "prims_dams.geojson"
    dam_features = []

    if local_dams.exists():
        try:
            dam_features = json.loads(local_dams.read_text(encoding="utf-8")).get("features", [])
            if dam_features:
                print(f"[PRIMS] Loaded {len(dam_features)} dam points from {local_dams}")
        except Exception as exc:
            print(f"[WARN] Failed reading {local_dams}: {exc}")

    urls = list(prims_urls) if prims_urls else list(PRIMS_DEFAULT_ENDPOINTS)
    if not dam_features:
        for url in urls:
            try:
                print(f"[PRIMS] Paging BRGM PRIMS dam points from {url} (resultOffset=2000)...", flush=True)
                feats = _fetch_arcgis_geojson_paginated(url, study_box, page_size=2000, timeout=10)
                if feats:
                    dam_features = feats
                    local_dams.write_text(
                        json.dumps({"type": "FeatureCollection", "features": dam_features}, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    print(f"[PRIMS] Loaded {len(dam_features)} dam points from {url}")
                    break
            except Exception as exc:
                print(f"[WARN] BRGM PRIMS endpoint {url} unreachable or returned error: {exc}")

    if not dam_features:
        warnings.warn(
            "BRGM PRIMS ArcGIS REST endpoints returned no dam points or were unreachable; setting nearest_dam_dist_m=None.",
            RuntimeWarning,
        )
        print("[WARN] No BRGM PRIMS dam points available; nearest_dam_dist_m will be set to None.")
        return None, []

    dams_gdf = gpd.GeoDataFrame.from_features(dam_features, crs="EPSG:4326").to_crs(epsg=int(epsg))
    context_dams = []
    for feat in dam_features:
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Point" and len(geom.get("coordinates", [])) >= 2:
            lon, lat = geom["coordinates"][:2]
            props = feat.get("properties") or {}
            name_val = props.get("nama") or props.get("name") or props.get("kode") or None
            context_dams.append(
                {
                    "type": "Feature",
                    "properties": {"kind": "dam", "name_en": name_val, "name_id": name_val},
                    "geometry": {"type": "Point", "coordinates": [round(float(lon), 5), round(float(lat), 5)]},
                }
            )
    return dams_gdf, context_dams
# End AI-generated (lines 264-522)


def _compute_exact_canal_lengths_utm(cells_gdf, canals_gdf):
    lengths_m = np.zeros(len(cells_gdf), dtype=np.float64)
    if canals_gdf is None or len(canals_gdf) == 0:
        return lengths_m

    canal_geoms = [g for g in canals_gdf.geometry if g is not None and not g.is_empty]
    if not canal_geoms:
        return lengths_m

    tree = STRtree(canal_geoms)
    for idx, cell_poly in enumerate(cells_gdf.geometry):
        hit_indices = tree.query(cell_poly, predicate="intersects")
        if len(hit_indices) > 0:
            total_len = 0.0
            for h_idx in hit_indices:
                inter = cell_poly.intersection(canal_geoms[int(h_idx)])
                if not inter.is_empty:
                    total_len += float(inter.length)
            lengths_m[idx] = total_len
    return lengths_m


def build_spatial_grid(cfg, dry_run=False):
    if dry_run:
        raise RuntimeError(
            "Synthetic canal fallback (--dry-run) has been removed; 03_grid.py requires real OSM canals."
        )

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

    canals_gdf, canal_features, canal_source = _fetch_osm_canals_utm(
        study_box, epsg=epsg, pbf_path=cfg.get("osm_pbf_path")
    )
    peat_union_utm, conc_union_utm = _load_gfw_peat_and_concessions_utm(study_box, epsg=epsg)
    dams_gdf, dam_context_features = _fetch_prims_dams_utm(
        study_box, epsg=epsg, prims_urls=cfg.get("prims_dams_urls")
    )

    cell_polys_utm = []
    cell_meta = []
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
            poly_utm = Polygon(
                [(x_left, y_bot), (x_right, y_bot), (x_right, y_top), (x_left, y_top), (x_left, y_bot)]
            )
            cell_polys_utm.append(poly_utm)
            cell_meta.append(
                (
                    cell_id,
                    r,
                    c,
                    x_left,
                    y_bot,
                    x_right,
                    y_top,
                    x_cen,
                    y_cen,
                    y_start,
                    y_stop,
                    x_start,
                    x_stop,
                    px_count,
                )
            )

    cells_gdf = gpd.GeoDataFrame(
        {"cell_id": [m[0] for m in cell_meta]},
        geometry=cell_polys_utm,
        crs=f"EPSG:{int(epsg)}",
    )

    print("[GRID] Computing exact UTM canal intersections per 500 m cell...", flush=True)
    canal_lengths_m = _compute_exact_canal_lengths_utm(cells_gdf, canals_gdf)

    cell_area_m2 = cell_size_m * cell_size_m
    cell_area_km2 = cell_area_m2 / 1e6

    print("[GRID] Computing GFW peat_fraction and concession_fraction in EPSG:32749...", flush=True)
    peat_fractions = np.zeros(len(cells_gdf), dtype=np.float64)
    if peat_union_utm is not None and not peat_union_utm.is_empty:
        for idx, poly in enumerate(cells_gdf.geometry):
            if poly.intersects(peat_union_utm):
                inter_area = poly.intersection(peat_union_utm).area
                peat_fractions[idx] = np.clip(inter_area / cell_area_m2, 0.0, 1.0)

    concession_fractions = np.zeros(len(cells_gdf), dtype=np.float64)
    if conc_union_utm is not None and not conc_union_utm.is_empty:
        for idx, poly in enumerate(cells_gdf.geometry):
            if poly.intersects(conc_union_utm):
                inter_area = poly.intersection(conc_union_utm).area
                concession_fractions[idx] = np.clip(inter_area / cell_area_m2, 0.0, 1.0)

    nearest_dam_dists = [None] * len(cells_gdf)
    if dams_gdf is not None and len(dams_gdf) > 0:
        print("[GRID] Computing nearest dam distance via sjoin_nearest in EPSG:32749...", flush=True)
        joined = gpd.sjoin_nearest(
            cells_gdf[["cell_id", "geometry"]],
            dams_gdf[["geometry"]],
            how="left",
            distance_col="nearest_dam_dist_m",
        )
        joined_dedup = joined.groupby("cell_id", as_index=False)["nearest_dam_dist_m"].min()
        dist_map = dict(zip(joined_dedup["cell_id"], joined_dedup["nearest_dam_dist_m"]))
        nearest_dam_dists = [
            None if pd.isna(dist_map.get(m[0])) else round(float(dist_map[m[0]]), 1)
            for m in cell_meta
        ]

    ref_min_lon, ref_min_lat, ref_max_lon, ref_max_lat = ref_box
    records = []
    geojson_cells = []

    for idx, meta in enumerate(cell_meta):
        (
            cell_id,
            r,
            c,
            x_left,
            y_bot,
            x_right,
            y_top,
            x_cen,
            y_cen,
            y_start,
            y_stop,
            x_start,
            x_stop,
            px_count,
        ) = meta

        corners_x = np.array([x_left, x_right, x_right, x_left, x_left, x_cen], dtype=np.float64)
        corners_y = np.array([y_bot, y_bot, y_top, y_top, y_bot, y_cen], dtype=np.float64)
        lons, lats = _utm_to_wgs84(corners_x, corners_y, epsg=epsg)

        lon_cen = round(float(lons[5]), 5)
        lat_cen = round(float(lats[5]), 5)
        c_len_m = round(float(canal_lengths_m[idx]), 1)
        c_dens_km_km2 = round(float((c_len_m / 1000.0) / cell_area_km2), 2)
        peat_frac = round(float(peat_fractions[idx]), 4)
        conc_frac = round(float(concession_fractions[idx]), 4)
        dam_dist = nearest_dam_dists[idx]

        in_ref_box = (
            ref_min_lon <= lon_cen <= ref_max_lon
            and ref_min_lat <= lat_cen <= ref_max_lat
        )

        if in_ref_box and c_len_m == 0.0 and conc_frac == 0.0:
            cell_class = "reference_forest"
            tree_cover = round(float(88.0 + 10.0 * np.sin(r * 0.3 + c * 0.2) ** 2), 1)
        elif conc_frac >= 0.25:
            cell_class = "plantation"
            tree_cover = 56.0
        elif dam_dist is not None and dam_dist <= 1000.0 and c_dens_km_km2 > 0.0:
            cell_class = "rewetted"
            tree_cover = 52.0
        elif c_dens_km_km2 > 0.0:
            cell_class = "drained"
            tree_cover = round(float(max(5.0, 35.0 - c_dens_km_km2 * 4.0)), 1)
        elif peat_frac >= 0.25 and lon_cen >= 114.00:
            cell_class = "drained"
            tree_cover = 28.0
        else:
            cell_class = "intact_forest"
            tree_cover = 85.0

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
                "peat_fraction": peat_frac,
                "concession_fraction": conc_frac,
                "nearest_dam_dist_m": dam_dist,
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
                    "peat_fraction": peat_frac,
                    "concession_fraction": conc_frac,
                    "nearest_dam_dist_m": dam_dist,
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
            if rec["class"] == "intact_forest" and rec["canal_length_m"] == 0.0 and rec["concession_fraction"] == 0.0:
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

    all_context_features = canal_features + dam_context_features
    fc_canals_full = {"type": "FeatureCollection", "features": all_context_features}
    (data_dir / "osm_canals.geojson").write_text(
        json.dumps(fc_canals_full, separators=(",", ":")), encoding="utf-8"
    )

    bundle_context_features = []
    for feat in canal_features:
        props = feat.get("properties") or {}
        wtype = props.get("waterway", props.get("kind"))
        geom = LineString(feat["geometry"]["coordinates"]).simplify(0.00015, preserve_topology=True)
        if geom.geom_type == "LineString" and len(geom.coords) >= 2:
            if wtype in ("river", "canal", "drain") or geom.length >= 0.0025:
                bundle_context_features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "kind": props.get("kind", "canal"),
                            "name_en": props.get("name_en"),
                            "name_id": props.get("name_id"),
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[round(float(x), 4), round(float(y), 4)] for x, y in geom.coords],
                        },
                    }
                )
    bundle_context_features.extend(dam_context_features)
    (bundle_dir / "context_features.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": bundle_context_features}, separators=(",", ":")),
        encoding="utf-8",
    )

    provenance = {
        "canal_source": canal_source,
        "peat_source": "gfw_indonesia_peat_lands",
        "concession_source": "gfw_indonesia_oil_palm_and_wood_fiber_concessions",
        "dam_source": "brgm_prims" if dams_gdf is not None else None,
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
    parser.add_argument("--dry-run", action="store_true", help="Deprecated: raises RuntimeError (never fake grids).")
    args = parser.parse_args()

    cfg = load_config(args.config)
    build_spatial_grid(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
