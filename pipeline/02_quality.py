import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer
import xarray as xr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

_spec = importlib.util.spec_from_file_location("census_mod", Path(__file__).resolve().parent / "00_census.py")
_census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_census)
load_config = _census.load_config


def _resolve_path(rel_or_abs):
    p = Path(rel_or_abs)
    return p if p.is_absolute() else PROJECT_ROOT / p


def compute_valid_mask(hhhh_arr, mask_arr=None):
    valid = np.isfinite(hhhh_arr) & (hhhh_arr > 0.0)
    if mask_arr is not None:
        m = np.asarray(mask_arr)
        valid = valid & (m > 0) & (m < 10)
    return valid


def compute_wgs84_bounds_from_utm(x_coords, y_coords, epsg=32749, fallback_box=None):
    x_arr = np.asarray(x_coords, dtype=np.float64)
    y_arr = np.asarray(y_coords, dtype=np.float64)
    if x_arr.size < 2 or y_arr.size < 2:
        west, south, east, north = fallback_box or [113.75, -2.25, 114.25, -1.75]
    else:
        dx = float(abs(x_arr[1] - x_arr[0]))
        dy = float(abs(y_arr[1] - y_arr[0]))
        u_minx = float(np.min(x_arr)) - dx / 2.0
        u_maxx = float(np.max(x_arr)) + dx / 2.0
        u_miny = float(np.min(y_arr)) - dy / 2.0
        u_maxy = float(np.max(y_arr)) + dy / 2.0

        transformer = Transformer.from_crs(f"EPSG:{int(epsg)}", "EPSG:4326", always_xy=True)
        lons, lats = transformer.transform(
            [u_minx, u_maxx, u_maxx, u_minx],
            [u_maxy, u_maxy, u_miny, u_miny],
        )
        west = round(float(min(lons)), 6)
        east = round(float(max(lons)), 6)
        south = round(float(min(lats)), 6)
        north = round(float(max(lats)), 6)

    bbox_wgs84 = [west, south, east, north]
    corners = [
        [west, north],
        [east, north],
        [east, south],
        [west, south],
    ]
    return bbox_wgs84, corners


def evaluate_date_quality(date_str, hhhh_arr, mask_arr, min_valid_fraction=0.5, ref_median_db=None):
    valid_mask = compute_valid_mask(hhhh_arr, mask_arr)
    total_px = int(hhhh_arr.size)
    valid_px = int(np.count_nonzero(valid_mask))
    valid_fraction = round(valid_px / total_px, 4) if total_px > 0 else 0.0

    if valid_fraction < min_valid_fraction:
        pct = round(valid_fraction * 100.0, 1)
        min_pct = round(min_valid_fraction * 100.0, 1)
        reason_en = f"Valid pixel fraction {valid_fraction:.3f} ({pct}%) below threshold {min_valid_fraction} ({min_pct}%)"
        reason_id = f"Fraksi piksel valid {pct}% di bawah ambang batas minimum {min_pct}%"
        return {
            "date": date_str,
            "status": "dropped",
            "valid_fraction": valid_fraction,
            "valid_pixels": valid_px,
            "total_pixels": total_px,
            "reason": reason_en,
            "reason_en": reason_en,
            "reason_id": reason_id,
            "p2_db": None,
            "p98_db": None,
            "median_hh_db": None,
            "std_hh_db": None,
        }

    hh_db = 10.0 * np.log10(np.clip(hhhh_arr, 1e-6, None))
    valid_db = hh_db[valid_mask]
    p2, p50, p98 = np.percentile(valid_db, [2.0, 50.0, 98.0])
    std_db = float(np.std(valid_db))

    if std_db < 0.05 or (p98 - p2) < 0.15:
        reason_en = f"Sensor artifact detected: flat dynamic range (std={std_db:.3f} dB)"
        reason_id = f"Artefak sensor terdeteksi: rentang dinamis datar (std={std_db:.3f} dB)"
        return {
            "date": date_str,
            "status": "dropped",
            "valid_fraction": valid_fraction,
            "valid_pixels": valid_px,
            "total_pixels": total_px,
            "reason": reason_en,
            "reason_en": reason_en,
            "reason_id": reason_id,
            "p2_db": round(float(p2), 3),
            "p98_db": round(float(p98), 3),
            "median_hh_db": round(float(p50), 3),
            "std_hh_db": round(std_db, 3),
        }

    if ref_median_db is not None and abs(float(p50) - float(ref_median_db)) > 6.0:
        shift = round(float(p50) - float(ref_median_db), 2)
        reason_en = f"Sensor calibration jump ({shift:+.2f} dB vs reference median)"
        reason_id = f"Lonjakan kalibrasi sensor ({shift:+.2f} dB terhadap median referensi)"
        return {
            "date": date_str,
            "status": "dropped",
            "valid_fraction": valid_fraction,
            "valid_pixels": valid_px,
            "total_pixels": total_px,
            "reason": reason_en,
            "reason_en": reason_en,
            "reason_id": reason_id,
            "p2_db": round(float(p2), 3),
            "p98_db": round(float(p98), 3),
            "median_hh_db": round(float(p50), 3),
            "std_hh_db": round(std_db, 3),
        }

    return {
        "date": date_str,
        "status": "ok",
        "valid_fraction": valid_fraction,
        "valid_pixels": valid_px,
        "total_pixels": total_px,
        "reason": None,
        "reason_en": None,
        "reason_id": None,
        "p2_db": round(float(p2), 3),
        "p98_db": round(float(p98), 3),
        "median_hh_db": round(float(p50), 3),
        "std_hh_db": round(std_db, 3),
    }


# AI-generated (lines 151-250)
def render_radar_png(hhhh_arr, mask_arr, out_path, max_dim=512):
    valid_mask = compute_valid_mask(hhhh_arr, mask_arr)
    hh_db = 10.0 * np.log10(np.clip(hhhh_arr, 1e-6, None))

    if np.any(valid_mask):
        p2, p98 = np.percentile(hh_db[valid_mask], [2.0, 98.0])
    else:
        p2, p98 = -25.0, -5.0

    span = max(float(p98 - p2), 1e-3)
    scaled = np.where(valid_mask, np.clip((hh_db - float(p2)) / span, 0.0, 1.0), 0.0)
    gray = np.round(scaled * 255.0).astype(np.uint8)
    alpha = np.where(valid_mask, 255, 0).astype(np.uint8)

    rgba = np.stack([gray, gray, gray, alpha], axis=-1)
    img = Image.fromarray(rgba)

    if max_dim and max(img.size) > int(max_dim):
        w, h = img.size
        scale = float(max_dim) / float(max(w, h))
        new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        img = img.resize(new_size, resample=Image.Resampling.BILINEAR)

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(target, format="PNG", optimize=True)
    return target


def run_quality_control(cfg):
    cube_rel = cfg.get("merged_cube_zarr", "data/gcov_cube.zarr")
    cube_path = _resolve_path(cube_rel)
    if not cube_path.exists():
        raise FileNotFoundError(f"Merged Zarr cube not found at {cube_path}. Run 01_fetch.py first.")

    min_valid_fraction = float(cfg.get("min_valid_fraction", 0.5))
    images_rel = cfg.get("bundle_images_dir", "bundle/images")
    images_dir = _resolve_path(images_rel)
    images_dir.mkdir(parents=True, exist_ok=True)
    max_png_dim = int(cfg.get("max_png_dim", 512))

    ds = xr.open_zarr(cube_path)
    epsg = int(ds.attrs.get("epsg", 32749))
    study_box = list(cfg.get("study_box", [113.75, -2.25, 114.25, -1.75]))

    bbox_wgs84, corners = compute_wgs84_bounds_from_utm(
        ds.x.values,
        ds.y.values,
        epsg=epsg,
        fallback_box=study_box,
    )

    dates = [str(d) for d in ds.time.values]
    prelim_medians = []
    for t_idx in range(len(dates)):
        hh_t = ds["HHHH"].isel(time=t_idx).values
        m_t = ds["mask"].isel(time=t_idx).values if "mask" in ds else None
        vm = compute_valid_mask(hh_t, m_t)
        if np.mean(vm) >= min_valid_fraction:
            db_t = 10.0 * np.log10(np.clip(hh_t[vm], 1e-6, None))
            prelim_medians.append(float(np.median(db_t)))
    ref_median_db = float(np.median(prelim_medians)) if prelim_medians else None

    kept_dates = []
    dropped_dates = []
    dates_summary = []
    radar_images = []

    for t_idx, date_str in enumerate(dates):
        hh_t = ds["HHHH"].isel(time=t_idx).values
        m_t = ds["mask"].isel(time=t_idx).values if "mask" in ds else None

        metrics = evaluate_date_quality(
            date_str=date_str,
            hhhh_arr=hh_t,
            mask_arr=m_t,
            min_valid_fraction=min_valid_fraction,
            ref_median_db=ref_median_db,
        )

        if metrics["status"] == "ok":
            kept_dates.append(date_str)
            png_name = f"radar_{date_str}.png"
            png_path = images_dir / png_name
            render_radar_png(hh_t, m_t, png_path, max_dim=max_png_dim)
            metrics["png_file"] = f"images/{png_name}"
            radar_images.append({"date": date_str, "file": f"images/{png_name}"})
        else:
            dropped_dates.append(
                {
                    "date": date_str,
                    "valid_fraction": metrics["valid_fraction"],
                    "reason": metrics["reason"],
                    "reason_en": metrics["reason_en"],
                    "reason_id": metrics["reason_id"],
                }
            )
            metrics["png_file"] = None

        dates_summary.append(metrics)
# End AI-generated (lines 151-250)

    report = {
        "epsg": epsg,
        "min_valid_fraction": min_valid_fraction,
        "bbox_wgs84": bbox_wgs84,
        "bounds": corners,
        "image_bounds": corners,
        "total_dates": len(dates),
        "kept_dates": kept_dates,
        "dropped_dates": dropped_dates,
        "radar_images": radar_images,
        "dates_summary": dates_summary,
    }

    report_rel = cfg.get("quality_report_json", "data/quality_report.json")
    report_path = _resolve_path(report_rel)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    qc_alias_rel = cfg.get("qc_report_json")
    if qc_alias_rel and qc_alias_rel != report_rel:
        alias_path = _resolve_path(qc_alias_rel)
        alias_path.parent.mkdir(parents=True, exist_ok=True)
        alias_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"Quality gate complete | Kept={len(kept_dates)}/{len(dates)} "
        f"| Dropped={len(dropped_dates)} | Bounds={bbox_wgs84}"
    )
    for item in dates_summary:
        status_tag = "KEEP" if item["status"] == "ok" else f"DROP ({item['reason']})"
        print(
            f"  {item['date']} : valid_fraction={item['valid_fraction']:.4f} "
            f"| median_hh_db={item['median_hh_db']} | {status_tag}"
        )
    return report


def main():
    parser = argparse.ArgumentParser(description="Validate NISAR GCOV data cube and render radar PNG overlays.")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--dry-run", "--self-test", dest="dry_run", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    run_quality_control(cfg)


if __name__ == "__main__":
    main()
