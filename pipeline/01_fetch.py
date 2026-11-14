import argparse
import csv
import importlib.util
import io
import json
import os
import shutil
import time
from pathlib import Path

import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

import h5py
import numpy as np
import requests
import xarray as xr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

_spec = importlib.util.spec_from_file_location("census_mod", Path(__file__).resolve().parent / "00_census.py")
_census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_census)

load_config = _census.load_config
get_earthdata_token = _census.get_earthdata_token
resolve_signed_s3_url = _census.resolve_signed_s3_url

LAYERS = ["HHHH", "HVHV", "mask", "numberOfLooks"]


class AutoRefreshRangeFile(io.RawIOBase):
    """Fast HTTP Range reader: 64 KB metadata cache + direct chunk reads + auto 403 URL refresh."""

    def __init__(self, orig_url, token, block_size=64 * 1024):
        super().__init__()
        self.orig_url = orig_url
        self.token = token
        self.block_size = block_size
        self.session = requests.Session()
        self.pos = 0
        self.cache = {}
        self.url = ""
        self.headers = {}
        self._refresh_url()
        self.size = self._fetch_size()

    def _refresh_url(self):
        fresh_tok = get_earthdata_token() or self.token
        self.token = fresh_tok
        self.url = resolve_signed_s3_url(self.orig_url, self.token)
        self.headers = {} if self.url != self.orig_url else {"Authorization": f"Bearer {self.token}"}

    def _range_get(self, start, end):
        for attempt in range(5):
            try:
                hdrs = dict(self.headers)
                hdrs["Range"] = f"bytes={start}-{end}"
                r = self.session.get(self.url, headers=hdrs, timeout=45)
                if r.status_code in (401, 403):
                    print("      [AUTH] Refreshing expired CloudFront URL...", flush=True)
                    self._refresh_url()
                    continue
                r.raise_for_status()
                return r
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
                self._refresh_url()

    def _fetch_size(self):
        r = self._range_get(0, 0)
        cr = r.headers.get("Content-Range", "")
        if "/" in cr:
            return int(cr.split("/")[-1])
        return int(r.headers.get("Content-Length", 0))

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self.pos = offset
        elif whence == io.SEEK_CUR:
            self.pos += offset
        elif whence == io.SEEK_END:
            self.pos = self.size + offset
        return self.pos

    def tell(self):
        return self.pos

    def _get_block(self, block_idx):
        if block_idx not in self.cache:
            if len(self.cache) >= 1024:
                oldest = next(iter(self.cache))
                del self.cache[oldest]
            start = block_idx * self.block_size
            end = min(self.size - 1, start + self.block_size - 1)
            r = self._range_get(start, end)
            self.cache[block_idx] = r.content
        return self.cache[block_idx]

    def read(self, size=-1):
        if self.pos >= self.size:
            return b""
        if size is None or size < 0:
            size = self.size - self.pos
        size = min(size, self.size - self.pos)
        if size == 0:
            return b""

        # Direct HTTP Range request for HDF5 data chunks (> 64 KB)
        if size > self.block_size:
            start = self.pos
            end = min(self.size - 1, start + size - 1)
            r = self._range_get(start, end)
            data = r.content
            self.pos += len(data)
            return data

        out = bytearray()
        remaining = size
        while remaining > 0 and self.pos < self.size:
            block_idx = self.pos // self.block_size
            offset_in_block = self.pos % self.block_size
            block = self._get_block(block_idx)
            take = min(remaining, len(block) - offset_in_block)
            if take <= 0:
                break
            out.extend(block[offset_in_block : offset_in_block + take])
            self.pos += take
            remaining -= take
        return bytes(out)

    def readinto(self, b):
        data = self.read(len(b))
        n = len(data)
        b[:n] = data
        return n

    def close(self):
        self.session.close()
        super().close()


def _wgs84_to_utm_xy(lon, lat, epsg=32749):
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
    return float(x), float(y)


def _load_census_rows(csv_path, batch=None):
    rows = []
    with Path(csv_path).open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if batch and batch.upper() != "ALL":
                if row.get("batch", "").strip().upper() != batch.upper():
                    continue
            rows.append(row)
    return sorted(rows, key=lambda r: r["date"])


def _build_canonical_utm_grid(study_box, epsg=32749, posting_m=20.0):
    minx, miny, maxx, maxy = study_box
    ux0, uy0 = _wgs84_to_utm_xy(minx, miny, epsg=epsg)
    ux1, uy1 = _wgs84_to_utm_xy(maxx, maxy, epsg=epsg)
    u_minx, u_maxx = min(ux0, ux1), max(ux0, ux1)
    u_miny, u_maxy = min(uy0, uy1), max(uy0, uy1)

    x_start = np.ceil(u_minx / posting_m) * posting_m + (posting_m / 2.0)
    x_end = np.floor(u_maxx / posting_m) * posting_m - (posting_m / 2.0)
    y_start = np.floor(u_maxy / posting_m) * posting_m - (posting_m / 2.0)
    y_end = np.ceil(u_miny / posting_m) * posting_m + (posting_m / 2.0)

    x_coords = np.arange(x_start, x_end + 1.0, posting_m, dtype=np.float64)
    y_coords = np.arange(y_start, y_end - 1.0, -posting_m, dtype=np.float64)
    return x_coords, y_coords


def _stream_single_scene(row, study_box, token, retries=3):
    url = row["url"]
    acq_date = row["date"]
    minx, miny, maxx, maxy = study_box

    last_err = None
    for attempt in range(1, retries + 1):
        t0 = time.perf_counter()
        try:
            with AutoRefreshRangeFile(url, token, block_size=64 * 1024) as fobj:
                with h5py.File(
                    fobj,
                    "r",
                    rdcc_nbytes=64 * 1024 * 1024,
                    rdcc_nslots=10007,
                ) as h5:
                    grp = h5["/science/LSAR/GCOV/grids/frequencyA"]
                    epsg = int(grp["projection"][()])
                    x_full = grp["xCoordinates"][:]
                    y_full = grp["yCoordinates"][:]

                    ux0, uy0 = _wgs84_to_utm_xy(minx, miny, epsg=epsg)
                    ux1, uy1 = _wgs84_to_utm_xy(maxx, maxy, epsg=epsg)
                    u_minx, u_maxx = min(ux0, ux1), max(ux0, ux1)
                    u_miny, u_maxy = min(uy0, uy1), max(uy0, uy1)

                    x_idx = np.where((x_full >= u_minx) & (x_full <= u_maxx))[0]
                    y_idx = np.where((y_full >= u_miny) & (y_full <= u_maxy))[0]
                    if len(x_idx) == 0 or len(y_idx) == 0:
                        raise ValueError(f"Empty spatial clip for {acq_date}")

                    x_slice = slice(int(x_idx[0]), int(x_idx[-1]) + 1)
                    y_slice = slice(int(y_idx[0]), int(y_idx[-1]) + 1)
                    x_sub = np.asarray(x_full[x_slice], dtype=np.float64)
                    y_sub = np.asarray(y_full[y_slice], dtype=np.float64)

                    data_vars = {}
                    for layer in LAYERS:
                        tl = time.perf_counter()
                        if layer in grp:
                            print(f"    -> Reading {layer} ...", end=" ", flush=True)
                            arr = grp[layer][y_slice, x_slice]
                            if layer in ("HHHH", "HVHV"):
                                arr = np.asarray(arr, dtype=np.float32)
                                arr[~np.isfinite(arr) | (arr <= 0.0)] = np.nan
                            elif layer == "mask":
                                arr = np.asarray(arr, dtype=np.uint8)
                            else:
                                arr = np.asarray(arr, dtype=np.float32)
                            print(f"{round(time.perf_counter() - tl, 1)}s", flush=True)
                        else:
                            fill = 0 if layer == "mask" else np.nan
                            dtype = np.uint8 if layer == "mask" else np.float32
                            arr = np.full((len(y_sub), len(x_sub)), fill, dtype=dtype)
                        data_vars[layer] = (("time", "y", "x"), arr[np.newaxis, :, :])

            elapsed = round(time.perf_counter() - t0, 2)
            print(
                f"  -> Done {acq_date} | shape=({len(y_sub)}, {len(x_sub)}) "
                f"| EPSG:{epsg} | {elapsed}s",
                flush=True,
            )
            return xr.Dataset(
                data_vars=data_vars,
                coords={
                    "time": np.array([acq_date], dtype="<U10"),
                    "y": y_sub,
                    "x": x_sub,
                },
                attrs={"epsg": epsg, "crs": f"EPSG:{epsg}"},
            )
        except Exception as exc:
            last_err = exc
            print(f"\n  [WARN] Attempt {attempt}/{retries} failed for {acq_date}: {exc}", flush=True)
            time.sleep(3 * attempt)

    raise RuntimeError(f"Failed to stream scene {acq_date} after {retries} retries: {last_err}")


def _generate_dry_run_scene(row, study_box, idx):
    epsg = 32749
    x_sub, y_sub = _build_canonical_utm_grid(study_box, epsg=epsg, posting_m=20.0)
    rng = np.random.default_rng(seed=100 + idx)
    shape = (1, len(y_sub), len(x_sub))

    hhhh = rng.uniform(0.02, 0.25, size=shape).astype(np.float32)
    hvhv = rng.uniform(0.005, 0.08, size=shape).astype(np.float32)
    mask = np.ones(shape, dtype=np.uint8)
    looks = np.full(shape, 4.0, dtype=np.float32)

    return xr.Dataset(
        data_vars={
            "HHHH": (("time", "y", "x"), hhhh),
            "HVHV": (("time", "y", "x"), hvhv),
            "mask": (("time", "y", "x"), mask),
            "numberOfLooks": (("time", "y", "x"), looks),
        },
        coords={
            "time": np.array([row["date"]], dtype="<U10"),
            "y": y_sub,
            "x": x_sub,
        },
        attrs={"epsg": epsg, "crs": f"EPSG:{epsg}"},
    )


def _align_to_ref_grid(ds, y_ref, x_ref):
    if np.array_equal(ds.y.values, y_ref) and np.array_equal(ds.x.values, x_ref):
        return ds
    return ds.reindex(y=y_ref, x=x_ref, method="nearest", tolerance=20.0)


def _save_zarr_with_alias(ds, primary_path, alias_path=None):
    primary = Path(primary_path)
    if primary.exists() or primary.is_symlink():
        if primary.is_symlink() or primary.is_file():
            primary.unlink()
        else:
            shutil.rmtree(primary)
    primary.parent.mkdir(parents=True, exist_ok=True)

    for var in ds.variables:
        ds[var].encoding.pop("chunks", None)
    chunked = ds.chunk({"time": 1, "y": 512, "x": 512})
    chunked.to_zarr(primary, mode="w")
    print(f"[SAVED] Zarr cube written to: {primary}", flush=True)

    if alias_path:
        alias = Path(alias_path)
        if alias.resolve() != primary.resolve():
            if alias.exists() or alias.is_symlink():
                if alias.is_symlink() or alias.is_file():
                    alias.unlink()
                else:
                    shutil.rmtree(alias)
            try:
                alias.symlink_to(primary.name)
                print(f"[ALIAS] Symlinked {alias} -> {primary.name}", flush=True)
            except Exception:
                shutil.copytree(primary, alias)
                print(f"[ALIAS] Copied {primary} -> {alias}", flush=True)


def run_fetch(cfg, batch="B", token="", dry_run=False):
    csv_rel = cfg.get("census_csv", "data/census.csv")
    csv_path = Path(csv_rel) if Path(csv_rel).is_absolute() else PROJECT_ROOT / csv_rel
    study_box = list(cfg["study_box"])

    rows = _load_census_rows(csv_path, batch=batch)
    if not rows:
        raise ValueError(f"No scenes found in {csv_path} for batch={batch}")

    if not dry_run and not token:
        token = get_earthdata_token()
        if not token:
            raise RuntimeError(
                "No Earthdata token found! Set EARTHDATA_TOKEN in .env or pass --token."
            )

    parts_dir = PROJECT_ROOT / f"data/parts_batch_{batch.lower()}"
    parts_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"=== Starting 01_fetch.py | Batch={batch.upper()} | Scenes={len(rows)} "
        f"| Mode={'DRY-RUN' if dry_run else 'LIVE-STREAM'} ===",
        flush=True,
    )

    datasets = []
    y_ref, x_ref = None, None
    for idx, row in enumerate(rows, start=1):
        part_path = parts_dir / f"{row['date']}.zarr"
        if part_path.exists() and not dry_run:
            print(f"[{idx}/{len(rows)}] Loading checkpoint {row['date']} from {part_path} ...", flush=True)
            ds_scene = xr.open_zarr(part_path).load()
        else:
            print(f"[{idx}/{len(rows)}] Fetching {row['date']} ({row['scene_name']}) ...", flush=True)
            if dry_run:
                ds_scene = _generate_dry_run_scene(row, study_box, idx)
            else:
                ds_scene = _stream_single_scene(row, study_box, token=token)
                ds_scene.chunk({"time": 1, "y": 512, "x": 512}).to_zarr(part_path, mode="w")
                print(f"    [CHECKPOINT] Saved {part_path}", flush=True)

        if y_ref is None:
            y_ref = ds_scene.y.values
            x_ref = ds_scene.x.values
        else:
            ds_scene = _align_to_ref_grid(ds_scene, y_ref, x_ref)
        datasets.append(ds_scene)

    cube = xr.concat(datasets, dim="time")
    epsg = int(datasets[0].attrs.get("epsg", 32749))
    cube.attrs.update(
        {
            "epsg": epsg,
            "crs": f"EPSG:{epsg}",
            "study_box": json.dumps(study_box),
            "track": str(rows[0]["track"]),
            "frame": str(rows[0]["frame"]),
            "flightDirection": str(rows[0]["flightDirection"]),
            "batch": batch.upper(),
            "dates": json.dumps([r["date"] for r in rows]),
            "scene_names": json.dumps([r["scene_name"] for r in rows]),
            "versions": json.dumps([r["version"] for r in rows]),
        }
    )

    batch_upper = batch.upper()
    if batch_upper == "A":
        primary = PROJECT_ROOT / "data/batch_a.zarr"
        alias = PROJECT_ROOT / cfg.get("batch_a_zarr", "data/cube_batch_a.zarr")
    elif batch_upper == "B":
        primary = PROJECT_ROOT / "data/batch_b.zarr"
        alias = PROJECT_ROOT / cfg.get("batch_b_zarr", "data/cube_batch_b.zarr")
    else:
        primary = PROJECT_ROOT / cfg.get("merged_cube_zarr", "data/gcov_cube.zarr")
        alias = None

    _save_zarr_with_alias(cube, primary, alias)
    return cube


def merge_batches(cfg):
    candidates_a = [
        PROJECT_ROOT / "data/batch_a.zarr",
        PROJECT_ROOT / cfg.get("batch_a_zarr", "data/cube_batch_a.zarr"),
    ]
    candidates_b = [
        PROJECT_ROOT / "data/batch_b.zarr",
        PROJECT_ROOT / cfg.get("batch_b_zarr", "data/cube_batch_b.zarr"),
    ]
    path_a = next((p for p in candidates_a if p.exists()), None)
    path_b = next((p for p in candidates_b if p.exists()), None)

    if not path_a or not path_b:
        raise FileNotFoundError(
            f"Cannot merge: missing batch Zarr store (found A={path_a}, B={path_b})"
        )

    ds_a = xr.open_zarr(path_a)
    ds_b = xr.open_zarr(path_b)
    ds_b_aligned = _align_to_ref_grid(ds_b, ds_a.y.values, ds_a.x.values)

    merged = xr.concat([ds_a, ds_b_aligned], dim="time").sortby("time")
    out_path = PROJECT_ROOT / cfg.get("merged_cube_zarr", "data/gcov_cube.zarr")
    _save_zarr_with_alias(merged, out_path)
    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Stream NISAR L2 GCOV study box subsets into Zarr cube."
    )
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument(
        "--batch",
        type=str,
        default="B",
        choices=["A", "B", "ALL", "a", "b", "all"],
        help="Which batch from census.csv to stream (default: B).",
    )
    parser.add_argument("--token", type=str, default="", help="Earthdata Bearer token.")
    parser.add_argument("--merge", action="store_true", help="Merge Batch A and B into gcov_cube.zarr.")
    parser.add_argument("--dry-run", action="store_true", help="Generate synthetic Zarr cube offline.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.merge:
        merge_batches(cfg)
    else:
        run_fetch(cfg, batch=args.batch, token=args.token, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
