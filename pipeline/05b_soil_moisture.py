"""Stage 5b: Provisional NISAR SME2 (200 m EASE-Grid 2.0) soil moisture ingestion.

Queries NASA ASF (or NASA CMR fallback) for provisional NISAR L2 SME2 soil moisture
products matching the locked GCOV geometry (track, frame, flightDirection) and
study dates over `study_box`.

Inspects and prints the HDF5 group hierarchy on the first file to resolve the
DSG / PMI / TSR soil moisture layers, uncertainty, vegetation water content (VWC),
and rain/quality flags. Streams via `fsspec` + `h5netcdf` (or `h5py` / local `.h5`
files), masks flagged pixels (dense vegetation VWC > 5 kg/m2, rain flag, or invalid
quality flag), reprojects from EASE-Grid 2.0 (EPSG:6933) to UTM 49S (EPSG:32749),
averages per 500 m grid cell from `data/grid_cells.parquet`, and writes
`data/sme2_cells.parquet` and `data/sme2_report.json`.

Important: SME2 is PROVISIONAL and untested on tropical peat. If no SME2 granules
are available or Earthdata streaming is unavailable, this stage records an honest
`unavailable` status in `data/sme2_report.json` and does NOT emit synthetic data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
VWC_MAX_KG_M2 = 5.0

DATE_SINGLE_RE = re.compile(r"(\d{8})T\d{6}")


def _resolve_path(path: Path) -> Path:
    """Resolve relative paths against PROJECT_ROOT if not already existing in cwd."""
    if path.is_absolute() or path.exists():
        return path
    return PROJECT_ROOT / path


def _load_config(config_path: Path | None) -> dict[str, Any]:
    """Load config.yaml with safe defaults."""
    cfg: dict[str, Any] = {
        "study_box": [113.75, -2.25, 114.25, -1.75],
        "cell_size_m": 500,
        "track": None,
        "frame": None,
        "flightDirection": None,
        "start_date": "2026-06-01T00:00:00Z",
        "end_date": "2026-11-15T23:59:59Z",
    }
    if config_path is None or not config_path.exists():
        return cfg
    try:
        import yaml
    except ImportError:
        return cfg
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if isinstance(raw, dict):
        cfg.update({k: v for k, v in raw.items() if v is not None})
    return cfg


def _get_earthdata_token() -> str:
    """Read NASA Earthdata bearer token from environment or .env."""
    token = os.environ.get("EARTHDATA_TOKEN") or os.environ.get("EDL_TOKEN")
    if token:
        return token.strip()
    for env_path in (PROJECT_ROOT / ".env", Path.home() / ".env"):
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("EARTHDATA_TOKEN=") or line.startswith("EDL_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def load_locked_geometry_and_dates(
    cfg: dict[str, Any],
    data_dir: Path,
) -> tuple[dict[str, str | None], list[str]]:
    """Resolve locked GCOV track/frame/direction and target pass dates."""
    geom: dict[str, str | None] = {
        "track": str(cfg["track"]).zfill(3) if cfg.get("track") is not None else None,
        "frame": str(cfg["frame"]).zfill(3) if cfg.get("frame") is not None else None,
        "flightDirection": (
            str(cfg["flightDirection"]) if cfg.get("flightDirection") is not None else None
        ),
    }

    sel_path = data_dir / "selected_scenes.json"
    if sel_path.exists():
        payload = json.loads(sel_path.read_text(encoding="utf-8"))
        sel = payload.get("selected_geometry") or {}
        if not geom["track"] and sel.get("track"):
            geom["track"] = str(sel["track"]).zfill(3)
        if not geom["frame"] and sel.get("frame"):
            geom["frame"] = str(sel["frame"]).zfill(3)
        if not geom["flightDirection"] and sel.get("flightDirection"):
            geom["flightDirection"] = str(sel["flightDirection"])

    zattrs_path = data_dir / "gcov_cube.zarr" / ".zattrs"
    if zattrs_path.exists():
        zattrs = json.loads(zattrs_path.read_text(encoding="utf-8"))
        if not geom["track"] and zattrs.get("track"):
            geom["track"] = str(zattrs["track"]).zfill(3)
        if not geom["frame"] and zattrs.get("frame"):
            geom["frame"] = str(zattrs["frame"]).zfill(3)
        if not geom["flightDirection"] and zattrs.get("flightDirection"):
            geom["flightDirection"] = str(zattrs["flightDirection"])

    dates: list[str] = []
    kept_path = data_dir / "kept_dates.json"
    qual_path = data_dir / "quality_report.json"
    stats_path = data_dir / "cell_stats.parquet"
    if kept_path.exists():
        raw = json.loads(kept_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            dates = [str(d)[:10] for d in raw]
        elif isinstance(raw, dict):
            dates = [str(d)[:10] for d in raw.get("kept_dates", [])]
    elif qual_path.exists():
        q = json.loads(qual_path.read_text(encoding="utf-8"))
        dates = [str(d)[:10] for d in q.get("kept_dates", [])]
    elif stats_path.exists():
        df_dates = pd.read_parquet(stats_path, columns=["date"])
        dates = sorted({str(d)[:10] for d in df_dates["date"].dropna().tolist()})

    return geom, sorted(set(dates))


def parse_sme2_filename(filename: str, url: str = "") -> dict[str, Any] | None:
    """Parse NISAR L3/L2 SME2 filename metadata for geometry, mode, date, CRID, and counter."""
    name = Path(filename).name
    if not name.endswith(".h5") or "SME2" not in name or name.endswith("_QA_STATS.h5"):
        return None
    parts = name[:-3].split("_")
    m = DATE_SINGLE_RE.search(name)
    if not m:
        return None
    d_raw = m.group(1)
    date_str = f"{d_raw[:4]}-{d_raw[4:6]}-{d_raw[6:8]}"

    # Actual NISAR naming: NISAR_L3_PR_SME2_<cycle>_<track>_<dir>_<frame>_<mode>_<pol>_...
    track = parts[5].zfill(3) if len(parts) > 5 and parts[5].isdigit() else None
    direction = parts[6] if len(parts) > 6 and parts[6] in ("A", "D") else None
    frame = parts[7].zfill(3) if len(parts) > 7 and parts[7].isdigit() else None
    mode = parts[8] if len(parts) > 8 else None
    pol = parts[9] if len(parts) > 9 else None
    crid = next(
        (p for p in parts if len(p) == 6 and p[0] in ("P", "R") and p[1:].isdigit()),
        "P00000",
    )
    try:
        counter = int(parts[-1])
    except ValueError:
        counter = 0

    return {
        "scene_name": name,
        "track": track,
        "flightDirection": direction,
        "frame": frame,
        "mode": mode,
        "pol": pol,
        "date": date_str,
        "crid": crid,
        "counter": counter,
        "url": url,
    }


def _match_target_dates(
    candidate_date: str,
    target_dates: list[str],
    max_day_diff: int = 2,
) -> str | None:
    """Match an SME2 pass date to the nearest GCOV date within max_day_diff days."""
    if not target_dates:
        return candidate_date
    if candidate_date in target_dates:
        return candidate_date
    c_dt = dt.date.fromisoformat(candidate_date)
    best_date = None
    best_diff = max_day_diff + 1
    for t_str in target_dates:
        t_dt = dt.date.fromisoformat(t_str)
        diff = abs((c_dt - t_dt).days)
        if diff <= max_day_diff and diff < best_diff:
            best_diff = diff
            best_date = t_str
    return best_date


def search_asf_sme2_scenes(
    study_box: list[float],
    target_dates: list[str],
    geometry: dict[str, str | None],
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Query NASA ASF (REST + asf_search) and CMR L3 collections for NISAR SME2 granules."""
    minx, miny, maxx, maxy = [float(v) for v in study_box]
    wkt = f"POLYGON(({minx} {miny}, {maxx} {miny}, {maxx} {maxy}, {minx} {maxy}, {minx} {miny}))"
    t_start = start_date or (f"{target_dates[0]}T00:00:00Z" if target_dates else "2026-06-01T00:00:00Z")
    t_end = end_date or (f"{target_dates[-1]}T23:59:59Z" if target_dates else "2026-11-15T23:59:59Z")

    urls: list[str] = []
    search_method = "none"

    try:
        import asf_search as asf  # type: ignore

        search_method = "asf_search"
        proc_level = getattr(getattr(asf, "PRODUCT_TYPE", object()), "SME2", "SME2")
        params: dict[str, Any] = {
            "dataset": getattr(getattr(asf, "DATASET", object()), "NISAR", "NISAR"),
            "processingLevel": proc_level,
            "intersectsWith": wkt,
            "start": t_start,
            "end": t_end,
        }
        if geometry.get("flightDirection"):
            params["flightDirection"] = geometry["flightDirection"]

        response = asf.search(opts=asf.ASFSearchOptions(**params))
        urls = list(response.find_urls(extension=".h5", directAccess=False))
    except ImportError:
        search_method = "asf_rest"
        try:
            import requests

            bbox_str = f"{minx},{miny},{maxx},{maxy}"
            asf_resp = requests.get(
                "https://api.daac.asf.alaska.edu/services/search/param",
                params={
                    "dataset": "NISAR",
                    "processingLevel": "SME2",
                    "bbox": bbox_str,
                    "start": t_start,
                    "end": t_end,
                    "output": "json",
                },
                timeout=20,
            )
            if asf_resp.status_code == 200:
                raw_json = asf_resp.json()
                items = (
                    raw_json[0]
                    if isinstance(raw_json, list) and raw_json and isinstance(raw_json[0], list)
                    else raw_json
                )
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            u = str(item.get("downloadUrl") or item.get("fileName") or "")
                            if u.endswith(".h5") and "QA_STATS" not in u:
                                urls.append(u)

            if not urls:
                search_method = "cmr_rest"
                for short_name in (
                    "NISAR_L3_SME2_PROVISIONAL_V1",
                    "NISAR_L3_SME2_BETA_V1",
                    "NISAR_L2_SME2_PROVISIONAL_V1",
                ):
                    resp = requests.get(
                        "https://cmr.earthdata.nasa.gov/search/granules.json",
                        params={
                            "short_name": short_name,
                            "bounding_box": bbox_str,
                            "temporal": f"{t_start},{t_end}",
                            "page_size": 200,
                        },
                        timeout=15,
                    )
                    if resp.status_code == 200:
                        entries = resp.json().get("feed", {}).get("entry", [])
                        for entry in entries:
                            for link in entry.get("links", []):
                                href = str(link.get("href", ""))
                                if href.endswith(".h5") and "QA_STATS" not in href:
                                    urls.append(href)
                        if urls:
                            break
        except Exception as exc:
            print(f"[WARN] SME2 catalog query failed: {exc}", file=sys.stderr)
            return [], f"catalog_error: {exc}"
    except Exception as exc:
        print(f"[WARN] ASF SME2 catalog query failed: {exc}", file=sys.stderr)
        return [], f"asf_error: {exc}"

    target_track = geometry.get("track")
    target_frame = geometry.get("frame")
    target_dir = geometry.get("flightDirection")
    latest_by_date: dict[str, dict[str, Any]] = {}

    def _score(rec: dict[str, Any]) -> tuple[int, int, str, int]:
        is_2005 = 1 if rec.get("mode") == "2005" else 0
        is_dh = 1 if (rec.get("pol") or "").startswith("DH") else 0
        return (is_2005, is_dh, str(rec["crid"]), int(rec["counter"]))

    for url in urls:
        parsed = parse_sme2_filename(Path(url).name, url=url)
        if not parsed:
            continue
        if target_track and parsed["track"] and parsed["track"] != target_track:
            continue
        if target_frame and parsed["frame"] and parsed["frame"] != target_frame:
            continue
        if target_dir and parsed["flightDirection"] and parsed["flightDirection"] != target_dir:
            continue

        matched_date = _match_target_dates(parsed["date"], target_dates)
        if matched_date is None:
            continue
        parsed["matched_date"] = matched_date

        prev = latest_by_date.get(matched_date)
        if prev is None or _score(parsed) > _score(prev):
            latest_by_date[matched_date] = parsed

    scenes = sorted(latest_by_date.values(), key=lambda r: r["matched_date"])
    return scenes, search_method


def inspect_sme2_hdf5_groups(
    h5_obj: Any,
    print_tree: bool = True,
) -> dict[str, Any]:
    """Walk an open SME2 HDF5 object, print discovered groups/datasets, and map key layers."""
    groups: list[str] = []
    datasets: dict[str, tuple[int, ...]] = {}

    def _walk(prefix: str, node: Any) -> None:
        keys = list(node.keys())
        for key in keys:
            child = node[key]
            path = f"{prefix}/{key}" if prefix != "/" else f"/{key}"
            if hasattr(child, "keys"):
                groups.append(path)
                _walk(path, child)
            else:
                shape = tuple(int(s) for s in getattr(child, "shape", ()))
                datasets[path] = shape

    _walk("", h5_obj)

    if print_tree:
        print("[SME2 HDF5] Discovered groups and datasets:")
        for g in groups:
            print(f"  [GRP] {g}")
        for d_path, d_shape in datasets.items():
            print(f"  [DST] {d_path}  shape={d_shape}")

    def _pick(substrings: tuple[str, ...], exclude: tuple[str, ...] = ()) -> str | None:
        scored: list[tuple[int, str]] = []
        for path in datasets:
            low = path.lower()
            if any(ex in low for ex in exclude):
                continue
            for rank, sub in enumerate(substrings):
                if sub in low:
                    score = 100 - rank * 10
                    if "sme2" in low:
                        score += 5
                    if "grids" in low:
                        score += 5
                    scored.append((score, path))
                    break
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][1] if scored else None

    mapping = {
        "groups": groups,
        "datasets": {k: list(v) for k, v in datasets.items()},
        "paths": {
            "sm_dsg": _pick(("dsg", "soilmoisture_dsg"), exclude=("uncertainty", "flag", "mask")),
            "sm_pmi": _pick(("pmi", "soilmoisture_pmi"), exclude=("uncertainty", "flag", "mask")),
            "sm_tsr": _pick(("tsr", "soilmoisture_tsr"), exclude=("uncertainty", "flag", "mask")),
            "sm_uncertainty": _pick(("uncertainty", "soilmoistureuncertainty")),
            "vwc": _pick(("vegetationwatercontent", "vwc", "watercontent")),
            "rain_flag": _pick(("rainflag", "rain_flag", "precipitationflag")),
            "quality_flag": _pick(("qualityflag", "quality_flag", "validity", "mask")),
            "x_coords": _pick(("xcoordinates", "/x")),
            "y_coords": _pick(("ycoordinates", "/y")),
            "projection": _pick(("projection", "crs")),
        },
    }
    return mapping


# ---------------------------------------------------------------------------
# Coordinate transforms: EASE-Grid 2.0 Global (EPSG:6933) <-> WGS84 <-> UTM 49S
# ---------------------------------------------------------------------------

_WGS84_A = 6378137.0
_WGS84_F = 1.0 / 298.257223563
_WGS84_E2 = 2.0 * _WGS84_F - _WGS84_F ** 2
_WGS84_E = math.sqrt(_WGS84_E2)


def _ease2_k0_and_qpolar() -> tuple[float, float]:
    phi1 = math.radians(30.0)
    sin_phi1 = math.sin(phi1)
    k0 = math.cos(phi1) / math.sqrt(1.0 - _WGS84_E2 * sin_phi1 ** 2)
    q_polar = (1.0 - _WGS84_E2) * (
        1.0 / (1.0 - _WGS84_E2)
        - (1.0 / (2.0 * _WGS84_E)) * math.log((1.0 - _WGS84_E) / (1.0 + _WGS84_E))
    )
    return k0, q_polar


def wgs84_to_ease2_6933(lon_deg: np.ndarray, lat_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Transform WGS84 lon/lat (degrees) to NSIDC EASE-Grid 2.0 Global (EPSG:6933, meters)."""
    lon = np.radians(np.asarray(lon_deg, dtype=np.float64))
    lat = np.radians(np.asarray(lat_deg, dtype=np.float64))
    k0, _ = _ease2_k0_and_qpolar()
    sin_lat = np.sin(lat)
    e_sin = _WGS84_E * sin_lat
    q = (1.0 - _WGS84_E2) * (
        sin_lat / (1.0 - _WGS84_E2 * sin_lat ** 2)
        - (1.0 / (2.0 * _WGS84_E)) * np.log((1.0 - e_sin) / (1.0 + e_sin))
    )
    x = _WGS84_A * k0 * lon
    y = _WGS84_A * q / (2.0 * k0)
    return x, y


def ease2_6933_to_wgs84(x_m: np.ndarray, y_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Inverse-project NSIDC EASE-Grid 2.0 (EPSG:6933, meters) to WGS84 lon/lat (degrees)."""
    x = np.asarray(x_m, dtype=np.float64)
    y = np.asarray(y_m, dtype=np.float64)
    k0, q_polar = _ease2_k0_and_qpolar()
    lon = x / (_WGS84_A * k0)
    arg = np.clip(2.0 * k0 * y / (_WGS84_A * q_polar), -1.0, 1.0)
    beta = np.arcsin(arg)

    e2 = _WGS84_E2
    e4 = e2 * e2
    e6 = e4 * e2
    c2 = e2 / 3.0 + 31.0 * e4 / 180.0 + 517.0 * e6 / 5040.0
    c4 = 23.0 * e4 / 360.0 + 251.0 * e6 / 3780.0
    c6 = 761.0 * e6 / 45360.0
    lat = beta + c2 * np.sin(2.0 * beta) + c4 * np.sin(4.0 * beta) + c6 * np.sin(6.0 * beta)
    return np.degrees(lon), np.degrees(lat)


def wgs84_to_utm49s(lon_deg: np.ndarray, lat_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project WGS84 lon/lat (degrees) to UTM Zone 49S (EPSG:32749, meters)."""
    lon = np.radians(np.asarray(lon_deg, dtype=np.float64))
    lat = np.radians(np.asarray(lat_deg, dtype=np.float64))
    lon0 = math.radians(111.0)  # Zone 49 central meridian: 6*49 - 183 = 111 E
    k0 = 0.9996
    fe = 500000.0
    fn = 10000000.0

    e2 = _WGS84_E2
    ep2 = e2 / (1.0 - e2)

    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    tan_lat = np.tan(lat)

    N = _WGS84_A / np.sqrt(1.0 - e2 * sin_lat ** 2)
    T = tan_lat ** 2
    C = ep2 * (cos_lat ** 2)
    A = cos_lat * (lon - lon0)

    e4 = e2 * e2
    e6 = e4 * e2
    M = _WGS84_A * (
        (1.0 - e2 / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0) * lat
        - (3.0 * e2 / 8.0 + 3.0 * e4 / 32.0 + 45.0 * e6 / 1024.0) * np.sin(2.0 * lat)
        + (15.0 * e4 / 256.0 + 45.0 * e6 / 1024.0) * np.sin(4.0 * lat)
        - (35.0 * e6 / 3072.0) * np.sin(6.0 * lat)
    )

    east = fe + k0 * N * (
        A
        + (1.0 - T + C) * (A ** 3) / 6.0
        + (5.0 - 18.0 * T + T * T + 72.0 * C - 58.0 * ep2) * (A ** 5) / 120.0
    )
    north = fn + k0 * (
        M
        + N
        * tan_lat
        * (
            (A * A) / 2.0
            + (5.0 - T + 9.0 * C + 4.0 * C * C) * (A ** 4) / 24.0
            + (61.0 - 58.0 * T + T * T + 600.0 * C - 330.0 * ep2) * (A ** 6) / 720.0
        )
    )
    return east, north


def reproject_ease2_points_to_utm49s(
    x_ease: np.ndarray,
    y_ease: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Reproject EASE-Grid 2.0 coordinates (EPSG:6933) to UTM 49S (EPSG:32749)."""
    if importlib.util.find_spec("pyproj") is not None:
        from pyproj import Transformer  # type: ignore

        tr = Transformer.from_crs("EPSG:6933", "EPSG:32749", always_xy=True)
        return tr.transform(x_ease, y_ease)

    lon, lat = ease2_6933_to_wgs84(x_ease, y_ease)
    return wgs84_to_utm49s(lon, lat)


def reproject_sme2_arrays_to_grid(
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    sm_dsg: np.ndarray,
    sm_pmi: np.ndarray | None,
    sm_tsr: np.ndarray | None,
    sm_unc: np.ndarray | None,
    vwc: np.ndarray | None,
    rain_flag: np.ndarray | None,
    quality_flag: np.ndarray | None,
    grid_df: pd.DataFrame,
    date_str: str,
    src_crs: str = "EPSG:6933",
) -> pd.DataFrame:
    """Mask flagged 200 m SME2 pixels, reproject to EPSG:32749, and aggregate to 500 m cells."""
    dsg_arr = np.asarray(sm_dsg, dtype=np.float64)
    pmi_arr = np.asarray(sm_pmi, dtype=np.float64) if sm_pmi is not None else None
    tsr_arr = np.asarray(sm_tsr, dtype=np.float64) if sm_tsr is not None else None
    unc_arr = np.asarray(sm_unc, dtype=np.float64) if sm_unc is not None else None
    vwc_arr = np.asarray(vwc, dtype=np.float64) if vwc is not None else None
    rain_arr = np.asarray(rain_flag) if rain_flag is not None else None
    qual_arr = np.asarray(quality_flag) if quality_flag is not None else None

    # Primary soil moisture layer: DSG preferred, fallback to PMI or TSR where missing
    sm_primary = dsg_arr.copy()
    if pmi_arr is not None:
        need = ~np.isfinite(sm_primary)
        sm_primary[need] = pmi_arr[need]
    if tsr_arr is not None:
        need = ~np.isfinite(sm_primary)
        sm_primary[need] = tsr_arr[need]

    # Build validity & quality masks
    unflagged = np.isfinite(sm_primary) & (sm_primary > 0.0) & (sm_primary <= 1.0)
    if vwc_arr is not None:
        unflagged &= ~np.isfinite(vwc_arr) | (vwc_arr <= VWC_MAX_KG_M2)
    if rain_arr is not None:
        unflagged &= rain_arr == 0
    if qual_arr is not None:
        unflagged &= qual_arr == 0

    # If rioxarray is installed and grid bounds exist, keep spatial metadata clean via xarray DataArray
    use_riox = (
        importlib.util.find_spec("rioxarray") is not None
        and importlib.util.find_spec("pyproj") is not None
    )
    if use_riox and src_crs.upper() == "EPSG:6933":
        try:
            import rioxarray  # noqa: F401
            import xarray as xr

            da_sm = xr.DataArray(
                np.where(unflagged, sm_primary, np.nan),
                dims=("y", "x"),
                coords={"y": y_coords, "x": x_coords},
            ).rio.write_crs(src_crs)
            # Reproject onto cell resolution (200 m -> EPSG:32749)
            da_utm = da_sm.rio.reproject("EPSG:32749", resolution=200.0)
            ux = da_utm["x"].to_numpy()
            uy = da_utm["y"].to_numpy()
            grid_xx, grid_yy = np.meshgrid(ux, uy)
            valid_utm = np.isfinite(da_utm.to_numpy())
            return _aggregate_points_to_cells(
                x_utm=grid_xx.ravel(),
                y_utm=grid_yy.ravel(),
                sm_primary=da_utm.to_numpy().ravel(),
                sm_dsg=None,
                sm_pmi=None,
                sm_tsr=None,
                sm_unc=None,
                vwc=None,
                unflagged=valid_utm.ravel(),
                grid_df=grid_df,
                date_str=date_str,
            )
        except Exception:
            pass

    xx, yy = np.meshgrid(np.asarray(x_coords, dtype=np.float64), np.asarray(y_coords, dtype=np.float64))
    if src_crs.upper() == "EPSG:32749":
        x_utm, y_utm = xx.ravel(), yy.ravel()
    elif src_crs.upper() == "EPSG:4326":
        x_utm, y_utm = wgs84_to_utm49s(xx.ravel(), yy.ravel())
    else:
        x_utm, y_utm = reproject_ease2_points_to_utm49s(xx.ravel(), yy.ravel())

    return _aggregate_points_to_cells(
        x_utm=x_utm,
        y_utm=y_utm,
        sm_primary=sm_primary.ravel(),
        sm_dsg=dsg_arr.ravel(),
        sm_pmi=pmi_arr.ravel() if pmi_arr is not None else None,
        sm_tsr=tsr_arr.ravel() if tsr_arr is not None else None,
        sm_unc=unc_arr.ravel() if unc_arr is not None else None,
        vwc=vwc_arr.ravel() if vwc_arr is not None else None,
        unflagged=unflagged.ravel(),
        grid_df=grid_df,
        date_str=date_str,
    )


def _aggregate_points_to_cells(
    x_utm: np.ndarray,
    y_utm: np.ndarray,
    sm_primary: np.ndarray,
    sm_dsg: np.ndarray | None,
    sm_pmi: np.ndarray | None,
    sm_tsr: np.ndarray | None,
    sm_unc: np.ndarray | None,
    vwc: np.ndarray | None,
    unflagged: np.ndarray,
    grid_df: pd.DataFrame,
    date_str: str,
) -> pd.DataFrame:
    """Assign UTM 49S pixels to 500 m grid cells with O(N) numpy bincount aggregation."""
    x_min_all = float(grid_df["x_min"].min())
    y_min_all = float(grid_df["y_min"].min())
    x_max_all = float(grid_df["x_max"].max())
    y_max_all = float(grid_df["y_max"].max())

    in_box = (
        (x_utm >= x_min_all)
        & (x_utm < x_max_all)
        & (y_utm >= y_min_all)
        & (y_utm < y_max_all)
    )
    if not np.any(in_box):
        return pd.DataFrame(
            columns=[
                "cell_id",
                "date",
                "class",
                "sm_dsg",
                "sm_pmi",
                "sm_tsr",
                "soil_moisture",
                "sm_uncertainty",
                "vwc_mean",
                "n_total_pixels",
                "n_unflagged_pixels",
                "unflagged_fraction",
                "is_flagged",
            ]
        )

    rows = grid_df["row"].to_numpy(dtype=np.int64)
    cols = grid_df["col"].to_numpy(dtype=np.int64)
    row_offset = int(rows.min())
    col_offset = int(cols.min())
    cell_size_x = float((grid_df["x_max"] - grid_df["x_min"]).median())
    cell_size_y = float((grid_df["y_max"] - grid_df["y_min"]).median())

    n_grid_r = int(rows.max() - row_offset + 1)
    n_grid_c = int(cols.max() - col_offset + 1)
    rc_to_cell_idx = np.full(n_grid_r * n_grid_c, -1, dtype=np.int64)
    rc_to_cell_idx[(rows - row_offset) * n_grid_c + (cols - col_offset)] = np.arange(len(grid_df))

    # Map pixel x_utm -> column index and y_utm -> row index consistent with grid_cells.parquet
    y_increases_with_row = bool(
        grid_df.sort_values(["row", "col"])
        .groupby("row")["y_center"]
        .mean()
        .diff()
        .dropna()
        .median()
        > 0
    )
    px = x_utm[in_box]
    py = y_utm[in_box]
    p_unflagged = unflagged[in_box]
    p_sm = sm_primary[in_box]
    p_dsg = sm_dsg[in_box] if sm_dsg is not None else p_sm
    p_pmi = sm_pmi[in_box] if sm_pmi is not None else None
    p_tsr = sm_tsr[in_box] if sm_tsr is not None else None
    p_unc = sm_unc[in_box] if sm_unc is not None else None
    p_vwc = vwc[in_box] if vwc is not None else None

    c_idx = np.floor((px - x_min_all) / cell_size_x).astype(np.int64)
    if y_increases_with_row:
        r_idx = np.floor((py - y_min_all) / cell_size_y).astype(np.int64)
    else:
        r_idx = np.floor((y_max_all - py) / cell_size_y).astype(np.int64)

    valid_rc = (r_idx >= 0) & (r_idx < n_grid_r) & (c_idx >= 0) & (c_idx < n_grid_c)
    cell_idx = np.full(len(px), -1, dtype=np.int64)
    cell_idx[valid_rc] = rc_to_cell_idx[r_idx[valid_rc] * n_grid_c + c_idx[valid_rc]]

    keep = cell_idx >= 0
    cell_idx = cell_idx[keep]
    p_unflagged = p_unflagged[keep]
    p_sm = p_sm[keep]
    p_dsg = p_dsg[keep]
    if p_pmi is not None:
        p_pmi = p_pmi[keep]
    if p_tsr is not None:
        p_tsr = p_tsr[keep]
    if p_unc is not None:
        p_unc = p_unc[keep]
    if p_vwc is not None:
        p_vwc = p_vwc[keep]

    n_cells = len(grid_df)
    total_counts = np.bincount(cell_idx, minlength=n_cells)
    good = p_unflagged & np.isfinite(p_sm)
    good_idx = cell_idx[good]
    good_counts = np.bincount(good_idx, minlength=n_cells)

    def _mean_by_cell(vals: np.ndarray | None, mask: np.ndarray) -> np.ndarray:
        out = np.full(n_cells, np.nan, dtype=np.float64)
        if vals is None:
            return out
        m = mask & np.isfinite(vals)
        if not np.any(m):
            return out
        sums = np.bincount(cell_idx[m], weights=vals[m], minlength=n_cells)
        cnts = np.bincount(cell_idx[m], minlength=n_cells)
        nz = cnts > 0
        out[nz] = sums[nz] / cnts[nz]
        return out

    sm_mean = _mean_by_cell(p_sm, good)
    dsg_mean = _mean_by_cell(p_dsg, good)
    pmi_mean = _mean_by_cell(p_pmi, good)
    tsr_mean = _mean_by_cell(p_tsr, good)
    unc_mean = _mean_by_cell(p_unc, good)
    vwc_mean = _mean_by_cell(p_vwc, np.ones(len(cell_idx), dtype=bool))

    unflagged_frac = np.where(total_counts > 0, good_counts / np.maximum(total_counts, 1), 0.0)
    is_flagged = (good_counts == 0) | ~np.isfinite(sm_mean)

    return pd.DataFrame(
        {
            "cell_id": grid_df["cell_id"].to_numpy(),
            "date": date_str,
            "class": grid_df["class"].to_numpy(),
            "sm_dsg": dsg_mean,
            "sm_pmi": pmi_mean,
            "sm_tsr": tsr_mean,
            "soil_moisture": sm_mean,
            "sm_uncertainty": unc_mean,
            "vwc_mean": vwc_mean,
            "n_total_pixels": total_counts.astype(np.int32),
            "n_unflagged_pixels": good_counts.astype(np.int32),
            "unflagged_fraction": np.round(unflagged_frac, 4),
            "is_flagged": is_flagged,
        }
    )


def _extract_2d_array(h5_obj: Any, path: str | None) -> np.ndarray | None:
    if not path or path not in h5_obj:
        return None
    ds = h5_obj[path]
    arr = np.asarray(ds[...], dtype=np.float64)
    if arr.ndim == 3:
        arr = arr[0]
    return arr


def _read_single_sme2_h5(
    h5_obj: Any,
    grid_df: pd.DataFrame,
    date_str: str,
    print_groups: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Inspect groups, read arrays from an open SME2 HDF5 object, and aggregate to 500 m cells."""
    info = inspect_sme2_hdf5_groups(h5_obj, print_tree=print_groups)
    paths = info["paths"]

    sm_dsg = _extract_2d_array(h5_obj, paths["sm_dsg"])
    sm_pmi = _extract_2d_array(h5_obj, paths["sm_pmi"])
    sm_tsr = _extract_2d_array(h5_obj, paths["sm_tsr"])
    if sm_dsg is None and sm_pmi is not None:
        sm_dsg = sm_pmi
    if sm_dsg is None and sm_tsr is not None:
        sm_dsg = sm_tsr
    if sm_dsg is None:
        raise ValueError("No soil moisture dataset (DSG/PMI/TSR) located in SME2 HDF5 file.")

    x_raw = h5_obj[paths["x_coords"]][...] if paths["x_coords"] and paths["x_coords"] in h5_obj else None
    y_raw = h5_obj[paths["y_coords"]][...] if paths["y_coords"] and paths["y_coords"] in h5_obj else None
    if x_raw is None or y_raw is None:
        raise ValueError("Missing xCoordinates or yCoordinates in SME2 HDF5 file.")

    src_crs = "EPSG:6933"
    if paths["projection"] and paths["projection"] in h5_obj:
        proj_attrs = getattr(h5_obj[paths["projection"]], "attrs", {})
        epsg_val = proj_attrs.get("epsg_code") or proj_attrs.get("EPSG")
        if epsg_val:
            src_crs = f"EPSG:{int(epsg_val)}"

    df_date = reproject_sme2_arrays_to_grid(
        x_coords=np.asarray(x_raw, dtype=np.float64),
        y_coords=np.asarray(y_raw, dtype=np.float64),
        sm_dsg=sm_dsg,
        sm_pmi=sm_pmi,
        sm_tsr=sm_tsr,
        sm_unc=_extract_2d_array(h5_obj, paths["sm_uncertainty"]),
        vwc=_extract_2d_array(h5_obj, paths["vwc"]),
        rain_flag=_extract_2d_array(h5_obj, paths["rain_flag"]),
        quality_flag=_extract_2d_array(h5_obj, paths["quality_flag"]),
        grid_df=grid_df,
        date_str=date_str,
        src_crs=src_crs,
    )
    return df_date, info


def _open_remote_h5(url: str, token: str):
    """Open a remote NISAR SME2 .h5 via fsspec + h5netcdf (or h5py fallback)."""
    import fsspec

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    fs = fsspec.filesystem("http", client_kwargs={"headers": headers})
    fobj = fs.open(url, "rb")
    if importlib.util.find_spec("h5netcdf") is not None:
        import h5netcdf.legacyapi as netcdf  # type: ignore

        return fobj, netcdf.Dataset(fobj, "r")
    if importlib.util.find_spec("h5py") is not None:
        import h5py  # type: ignore

        return fobj, h5py.File(fobj, "r")
    raise ImportError("Neither h5netcdf nor h5py is installed to read remote SME2 HDF5 files.")


def run_stage_5b(
    config_path: Path = DEFAULT_CONFIG_PATH,
    data_dir: Path = PROJECT_ROOT / "data",
    local_h5_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute Stage 5b NISAR SME2 soil moisture discovery, streaming, and cell aggregation."""
    cfg = _load_config(_resolve_path(config_path))
    data_dir = _resolve_path(data_dir)
    out_parquet = data_dir / "sme2_cells.parquet"
    out_report = data_dir / "sme2_report.json"

    grid_path = data_dir / "grid_cells.parquet"
    if not grid_path.exists():
        raise FileNotFoundError(f"Missing grid file: {grid_path}")
    grid_df = pd.read_parquet(grid_path)
    geometry, target_dates = load_locked_geometry_and_dates(cfg, data_dir)
    study_box = [float(v) for v in cfg["study_box"]]

    scenes: list[dict[str, Any]] = []
    search_method = "none"

    if local_h5_dir is not None and local_h5_dir.exists():
        search_method = "local_h5_dir"
        for h5_path in sorted(local_h5_dir.glob("*.h5")):
            parsed = parse_sme2_filename(h5_path.name, url=str(h5_path))
            if parsed:
                parsed["matched_date"] = _match_target_dates(parsed["date"], target_dates) or parsed["date"]
                parsed["local_path"] = str(h5_path)
                scenes.append(parsed)
    else:
        scenes, search_method = search_asf_sme2_scenes(
            study_box=study_box,
            target_dates=target_dates,
            geometry=geometry,
            start_date=str(cfg.get("start_date", "")),
            end_date=str(cfg.get("end_date", "")),
        )

    token = _get_earthdata_token()
    can_read_h5 = (
        importlib.util.find_spec("h5netcdf") is not None
        or importlib.util.find_spec("h5py") is not None
    )

    if not scenes:
        # Remove any stale parquet so missing SME2 is never mistaken for real output
        if out_parquet.exists():
            out_parquet.unlink()
        report = {
            "status": "unavailable",
            "reason": (
                "No provisional NISAR SME2 granules matched the locked geometry/dates "
                f"(search_method={search_method})."
            ),
            "provisional_disclaimer": (
                "NISAR SME2 is provisional and was omitted rather than fabricated."
            ),
            "geometry": geometry,
            "study_box": study_box,
            "target_dates": target_dates,
            "scenes_found": 0,
            "scenes_processed": 0,
            "hdf5_groups": [],
            "output_parquet": None,
        }
        out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[WARN] {report['reason']}")
        print(f"Wrote honest status report: {out_report}")
        return report

    if local_h5_dir is None and (not token or not can_read_h5):
        if out_parquet.exists():
            out_parquet.unlink()
        missing_parts = []
        if not token:
            missing_parts.append("EARTHDATA_TOKEN")
        if not can_read_h5:
            missing_parts.append("h5netcdf/h5py")
        report = {
            "status": "unavailable",
            "reason": (
                f"Found {len(scenes)} SME2 scene(s), but cannot stream HDF5 without: "
                + ", ".join(missing_parts)
            ),
            "provisional_disclaimer": (
                "NISAR SME2 is provisional and was omitted rather than fabricated."
            ),
            "geometry": geometry,
            "study_box": study_box,
            "target_dates": target_dates,
            "scenes_found": len(scenes),
            "scenes": [s["scene_name"] for s in scenes],
            "scenes_processed": 0,
            "hdf5_groups": [],
            "output_parquet": None,
        }
        out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[WARN] {report['reason']}")
        print(f"Wrote honest status report: {out_report}")
        return report

    frames: list[pd.DataFrame] = []
    first_info: dict[str, Any] | None = None
    processed_names: list[str] = []

    for idx, scene in enumerate(scenes):
        try:
            if scene.get("local_path"):
                if importlib.util.find_spec("h5netcdf") is not None:
                    import h5netcdf.legacyapi as netcdf  # type: ignore

                    with netcdf.Dataset(scene["local_path"], "r") as ds:
                        df_scene, info = _read_single_sme2_h5(
                            ds, grid_df, scene["matched_date"], print_groups=(idx == 0)
                        )
                elif importlib.util.find_spec("h5py") is not None:
                    import h5py  # type: ignore

                    with h5py.File(scene["local_path"], "r") as ds:
                        df_scene, info = _read_single_sme2_h5(
                            ds, grid_df, scene["matched_date"], print_groups=(idx == 0)
                        )
                else:
                    raise ImportError("Neither h5netcdf nor h5py installed.")
            else:
                fobj, ds = _open_remote_h5(scene["url"], token)
                try:
                    df_scene, info = _read_single_sme2_h5(
                        ds, grid_df, scene["matched_date"], print_groups=(idx == 0)
                    )
                finally:
                    try:
                        ds.close()
                    finally:
                        fobj.close()

            if first_info is None:
                first_info = info
            frames.append(df_scene)
            processed_names.append(scene["scene_name"])
        except Exception as exc:
            print(f"[WARN] Failed reading SME2 scene {scene['scene_name']}: {exc}", file=sys.stderr)

    if not frames:
        if out_parquet.exists():
            out_parquet.unlink()
        report = {
            "status": "unavailable",
            "reason": f"Found {len(scenes)} SME2 scene(s), but zero readable granules succeeded.",
            "provisional_disclaimer": "NISAR SME2 is provisional and omitted on failure.",
            "geometry": geometry,
            "study_box": study_box,
            "target_dates": target_dates,
            "scenes_found": len(scenes),
            "scenes_processed": 0,
            "hdf5_groups": [],
            "output_parquet": None,
        }
        out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    out_df = pd.concat(frames, ignore_index=True)
    out_df.to_parquet(out_parquet, index=False)

    report = {
        "status": "ok",
        "reason": "Provisional NISAR SME2 streamed, quality-masked (VWC <= 5 kg/m2, no rain), and aggregated.",
        "provisional_disclaimer": "Provisional SME2 product used strictly as a multi-sensor consistency check.",
        "geometry": geometry,
        "study_box": study_box,
        "target_dates": target_dates,
        "scenes_found": len(scenes),
        "scenes_processed": len(processed_names),
        "processed_scenes": processed_names,
        "hdf5_groups": first_info["groups"] if first_info else [],
        "discovered_paths": first_info["paths"] if first_info else {},
        "rows": int(len(out_df)),
        "unflagged_cell_dates": int((~out_df["is_flagged"]).sum()),
        "output_parquet": str(out_parquet),
    }
    out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved SME2 cells ({len(out_df)} rows): {out_parquet}")
    print(f"Saved SME2 report: {out_report}")
    return report


# ---------------------------------------------------------------------------
# In-memory HDF5-like mock tree for standalone --self-test verification
# ---------------------------------------------------------------------------


class _MockDataset:
    def __init__(self, data: np.ndarray, attrs: dict[str, Any] | None = None):
        self._data = np.asarray(data)
        self.shape = self._data.shape
        self.attrs = attrs or {}

    def __getitem__(self, item: Any) -> np.ndarray:
        return self._data[item] if item is not Ellipsis else self._data


class _MockGroup:
    def __init__(self, children: dict[str, Any] | None = None):
        self._children: dict[str, Any] = children or {}

    def keys(self):
        return self._children.keys()

    def __getitem__(self, path: str):
        cur: Any = self
        for part in path.strip("/").split("/"):
            if not part:
                continue
            cur = cur._children[part]
        return cur

    def __contains__(self, path: str) -> bool:
        try:
            _ = self[path]
            return True
        except KeyError:
            return False


def run_self_test() -> int:
    """Verify HDF5 group inspection, quality masking, EASE2->UTM49S reprojection, and parquet output."""
    print("Running 05b_soil_moisture.py --self-test ...")
    lon0, lat0 = 113.85, -2.05
    e0, n0 = wgs84_to_utm49s(np.array([lon0]), np.array([lat0]))
    x0_utm, y0_utm = float(e0[0]), float(n0[0])

    # Build a small 2x2 grid of 500 m cells in UTM 49S
    rows_meta = []
    for r in range(2):
        for c in range(2):
            xmin = x0_utm + c * 500.0
            ymin = y0_utm + r * 500.0
            rows_meta.append(
                {
                    "cell_id": f"r{r:03d}c{c:03d}",
                    "row": r,
                    "col": c,
                    "class": "drained" if r == 0 else "reference_forest",
                    "x_min": xmin,
                    "x_max": xmin + 500.0,
                    "y_min": ymin,
                    "y_max": ymin + 500.0,
                    "x_center": xmin + 250.0,
                    "y_center": ymin + 250.0,
                }
            )
    grid_df = pd.DataFrame(rows_meta)

    # Create a 200 m EASE-Grid 2.0 raster covering the 2x2 UTM box
    ex_c, ey_c = wgs84_to_ease2_6933(
        np.array([lon0 - 0.02, lon0 + 0.03]),
        np.array([lat0 - 0.02, lat0 + 0.03]),
    )
    x_ease = np.arange(float(ex_c.min()), float(ex_c.max()), 200.0)
    y_ease = np.arange(float(ey_c.max()), float(ey_c.min()), -200.0)
    ny, nx = len(y_ease), len(x_ease)

    dsg = np.full((ny, nx), 0.32, dtype=np.float64)
    pmi = np.full((ny, nx), 0.30, dtype=np.float64)
    tsr = np.full((ny, nx), 0.28, dtype=np.float64)
    unc = np.full((ny, nx), 0.04, dtype=np.float64)
    vwc = np.full((ny, nx), 1.8, dtype=np.float64)
    rain_flag = np.zeros((ny, nx), dtype=np.int16)
    qual_flag = np.zeros((ny, nx), dtype=np.int16)

    # Map pixels back to UTM so we can test dense-veg (> 5 kg/m2) & rain masking on specific cells
    g_xx, g_yy = np.meshgrid(x_ease, y_ease)
    p_utm_x, p_utm_y = reproject_ease2_points_to_utm49s(g_xx.ravel(), g_yy.ravel())
    p_utm_x = p_utm_x.reshape(ny, nx)
    p_utm_y = p_utm_y.reshape(ny, nx)

    # Flag entire r001c001 (reference_forest) as VWC = 6.5 > 5.0 kg/m2 (must be masked!)
    r1c1_mask = (
        (p_utm_x >= rows_meta[3]["x_min"])
        & (p_utm_x < rows_meta[3]["x_max"])
        & (p_utm_y >= rows_meta[3]["y_min"])
        & (p_utm_y < rows_meta[3]["y_max"])
    )
    vwc[r1c1_mask] = 6.5

    # Flag entire r000c001 as rain_flag = 1 (must be masked!)
    r0c1_mask = (
        (p_utm_x >= rows_meta[1]["x_min"])
        & (p_utm_x < rows_meta[1]["x_max"])
        & (p_utm_y >= rows_meta[1]["y_min"])
        & (p_utm_y < rows_meta[1]["y_max"])
    )
    rain_flag[r0c1_mask] = 1

    mock_h5 = _MockGroup(
        {
            "science": _MockGroup(
                {
                    "LSAR": _MockGroup(
                        {
                            "SME2": _MockGroup(
                                {
                                    "grids": _MockGroup(
                                        {
                                            "frequencyA": _MockGroup(
                                                {
                                                    "xCoordinates": _MockDataset(x_ease),
                                                    "yCoordinates": _MockDataset(y_ease),
                                                    "projection": _MockDataset(
                                                        np.array([0]), {"epsg_code": 6933}
                                                    ),
                                                    "DSG": _MockDataset(dsg),
                                                    "PMI": _MockDataset(pmi),
                                                    "TSR": _MockDataset(tsr),
                                                    "soilMoistureUncertainty": _MockDataset(unc),
                                                    "vegetationWaterContent": _MockDataset(vwc),
                                                    "rainFlag": _MockDataset(rain_flag),
                                                    "qualityFlag": _MockDataset(qual_flag),
                                                }
                                            )
                                        }
                                    )
                                }
                            )
                        }
                    )
                }
            )
        }
    )

    df_out, info = _read_single_sme2_h5(mock_h5, grid_df, "2026-06-22", print_groups=True)

    assert "/science/LSAR/SME2/grids/frequencyA" in info["groups"]
    assert info["paths"]["sm_dsg"] == "/science/LSAR/SME2/grids/frequencyA/DSG"

    by_id = df_out.set_index("cell_id")
    assert len(df_out) == 4
    assert not bool(by_id.loc["r000c000", "is_flagged"])
    assert math.isclose(float(by_id.loc["r000c000", "soil_moisture"]), 0.32, rel_tol=1e-4)
    assert bool(by_id.loc["r000c001", "is_flagged"]), "Rain-flagged cell must be flagged"
    assert bool(by_id.loc["r001c001", "is_flagged"]), "Dense vegetation (VWC > 5) must be flagged"

    with tempfile.TemporaryDirectory() as tmp:
        pq_path = Path(tmp) / "sme2_cells.parquet"
        df_out.to_parquet(pq_path, index=False)
        reloaded = pd.read_parquet(pq_path)
        assert len(reloaded) == 4

    print("[PASS] 05b_soil_moisture.py --self-test passed all assertions.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 5b: Provisional NISAR SME2 ingestion.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--local-h5-dir", type=Path, default=None)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    run_stage_5b(config_path=args.config, data_dir=args.data_dir, local_h5_dir=args.local_h5_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
