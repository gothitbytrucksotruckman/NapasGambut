import argparse
import importlib.util
import io
import json
import os
import time
from pathlib import Path

import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

import numpy as np
from PIL import Image, ImageFilter
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

_spec = importlib.util.spec_from_file_location(
    "census_mod", Path(__file__).resolve().parent / "00_census.py"
)
_census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_census)
load_config = _census.load_config


def _resolve_reveal_date(cfg):
    manifest_path = PROJECT_ROOT / cfg.get("bundle_dir", "bundle") / "manifest.json"
    if manifest_path.exists():
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            rev_date = m.get("images", {}).get("reveal", {}).get("date")
            if rev_date:
                return rev_date
        except Exception:
            pass

    qc_path = PROJECT_ROOT / cfg.get("qc_report_json", "data/qc_report.json")
    if qc_path.exists():
        try:
            qc = json.loads(qc_path.read_text(encoding="utf-8"))
            kept = qc.get("kept_dates", [])
            if kept:
                sept = [d for d in kept if d.startswith("2026-09")]
                return sept[-1] if sept else kept[-1]
        except Exception:
            pass

    return "2026-09-26"


def _fetch_gibs_smoke_image(study_box, target_date, width=1024, height=1024, dry_run=False):
    min_lon, min_lat, max_lon, max_lat = study_box
    if not dry_run:
        wms_url = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
        layers_to_try = [
            "VIIRS_SNPP_CorrectedReflectance_TrueColor",
            "MODIS_Terra_CorrectedReflectance_TrueColor",
            "MODIS_Aqua_CorrectedReflectance_TrueColor",
        ]
        # Only the reveal date itself: a picture from another year must never stand in for it.
        dates_to_try = [target_date]
        for dt in dates_to_try:
            for layer in layers_to_try:
                params = {
                    "SERVICE": "WMS",
                    "VERSION": "1.1.1",
                    "REQUEST": "GetMap",
                    "LAYERS": layer,
                    "SRS": "EPSG:4326",
                    "BBOX": f"{min_lon},{min_lat},{max_lon},{max_lat}",
                    "WIDTH": str(width),
                    "HEIGHT": str(height),
                    "FORMAT": "image/png",
                    "TIME": dt,
                }
                try:
                    r = requests.get(wms_url, params=params, timeout=30)
                    if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/"):
                        img = Image.open(io.BytesIO(r.content)).convert("RGB")
                        arr = np.asarray(img, dtype=np.float32)
                        if np.std(arr) > 4.0 and np.mean(arr) > 15.0:
                            print(f"[GIBS] Downloaded NASA Worldview TrueColor ({layer} @ {dt})")
                            return img, f"{layer} ({dt})"
                except Exception as exc:
                    print(f"[WARN] GIBS WMS {layer} @ {dt} failed: {exc}")

        raise RuntimeError(
            f"No usable Worldview true-colour image for {target_date}. "
            "Re-run later, or use --dry-run for a labelled synthetic test image."
        )

    print("[GIBS] --dry-run: generating a SYNTHETIC smoke haze test image (not an observation)...")
    rng = np.random.default_rng(seed=926)
    y_idx, x_idx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = x_idx / width
    ny = y_idx / height

    base_r = 45.0 + 55.0 * nx + 15.0 * np.sin(nx * 12.0)
    base_g = 85.0 - 20.0 * nx + 12.0 * np.cos(ny * 10.0)
    base_b = 40.0 + 10.0 * nx

    plume = (
        np.exp(-(((nx - 0.65) ** 2) / 0.12 + ((ny - 0.60) ** 2) / 0.15))
        + 0.75 * np.exp(-(((nx - 0.42) ** 2) / 0.18 + ((ny - 0.40) ** 2) / 0.14))
        + 0.45 * np.exp(-(((nx - 0.25) ** 2) / 0.20 + ((ny - 0.25) ** 2) / 0.20))
    )
    noise = rng.normal(0.0, 12.0, size=(height, width)).astype(np.float32)
    smoke_alpha = np.clip(plume * 0.82, 0.0, 0.92)

    smoke_r = 218.0 + noise * 0.5
    smoke_g = 212.0 + noise * 0.5
    smoke_b = 202.0 + noise * 0.5

    r_ch = np.clip(base_r * (1.0 - smoke_alpha) + smoke_r * smoke_alpha, 0, 255).astype(np.uint8)
    g_ch = np.clip(base_g * (1.0 - smoke_alpha) + smoke_g * smoke_alpha, 0, 255).astype(np.uint8)
    b_ch = np.clip(base_b * (1.0 - smoke_alpha) + smoke_b * smoke_alpha, 0, 255).astype(np.uint8)

    img = Image.fromarray(np.stack([r_ch, g_ch, b_ch], axis=-1), mode="RGB")
    img = img.filter(ImageFilter.GaussianBlur(radius=1.5))
    return img, f"SYNTHETIC test image, not NASA Worldview ({target_date})"


def run_context_visuals(cfg, dry_run=False):
    t0 = time.perf_counter()
    study_box = list(cfg["study_box"])
    min_lon, min_lat, max_lon, max_lat = study_box
    reveal_date = _resolve_reveal_date(cfg)

    images_dir = PROJECT_ROOT / cfg.get("images_dir", "bundle/images")
    images_dir.mkdir(parents=True, exist_ok=True)
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    smoke_img, source_label = _fetch_gibs_smoke_image(
        study_box, reveal_date, width=1024, height=1024, dry_run=dry_run
    )

    smoke_paths = [
        images_dir / "smoke_reveal.png",
        images_dir / "reveal_optical.png",
        data_dir / "smoke_reveal.png",
    ]
    for p in smoke_paths:
        smoke_img.save(p, format="PNG", optimize=True)
    size_kb = round(smoke_paths[0].stat().st_size / 1024.0, 1)
    print(f"[SAVED] {smoke_paths[0]} ({size_kb} KB) | source={source_label}")


    visuals_meta = {
        "reveal_date": reveal_date,
        "optical_file": "images/smoke_reveal.png",
        "radar_file": f"images/radar_{reveal_date}.png",
        "bounds": [
            [min_lon, max_lat],
            [max_lon, max_lat],
            [max_lon, min_lat],
            [min_lon, min_lat],
        ],
        "bbox": study_box,
        "source": source_label,
        # No Sentinel-1 scene has been read yet, so there are no C-band numbers to report (design principle 7).
        "sentinel1_contrast": None,
    }
    meta_path = data_dir / "context_visuals.json"
    meta_path.write_text(json.dumps(visuals_meta, indent=2), encoding="utf-8")
    print(f"[SAVED] {meta_path}")
    print(f"=== 06_context_visuals.py Complete in {round(time.perf_counter() - t0, 2)}s ===")
    return visuals_meta


def main():
    parser = argparse.ArgumentParser(description="Fetch the Worldview smoke reveal PNG for the reveal date.")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--dry-run", action="store_true", help="Generate offline smoke reveal image.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    run_context_visuals(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
