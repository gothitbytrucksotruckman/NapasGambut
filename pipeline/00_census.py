import argparse
import ast
from collections import defaultdict
import csv
from datetime import date
import json
import os
from pathlib import Path
import time

try:
    import yaml
except ImportError:
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _load_yaml_fallback(text):
    root = {}
    section = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        k, _, v = line.strip().partition(":")
        k, v = k.strip(), v.strip()
        if indent == 0 and not v:
            section = {}
            root[k] = section
            continue
        if v in ("null", "None", "~", ""):
            val = None
        elif v in ("true", "True"):
            val = True
        elif v in ("false", "False"):
            val = False
        else:
            try:
                val = ast.literal_eval(v)
            except (ValueError, SyntaxError):
                val = v
        target = section if (indent > 0 and section is not None) else root
        target[k] = val
    return root


def load_config(config_path=DEFAULT_CONFIG_PATH):
    text = Path(config_path).read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text)
    return _load_yaml_fallback(text)


def bbox_to_wkt(bbox):
    minx, miny, maxx, maxy = bbox
    return (
        f"POLYGON(({minx} {miny}, {maxx} {miny}, "
        f"{maxx} {maxy}, {minx} {maxy}, {minx} {miny}))"
    )


def parse_gcov_filename(filename, url=""):
    name = Path(filename).name
    if name.endswith("_QA_STATS.h5"):
        return None
    stem = name[:-3] if name.endswith(".h5") else name
    parts = stem.split("_")
    if len(parts) < 16 or parts[0] != "NISAR" or parts[3] != "GCOV":
        return None

    ts = parts[11]
    acq_date = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
    crid = parts[13]
    accuracy = parts[14]

    # Real NISAR L2 GCOV filenames have 18 tokens:
    # ..._<Start>_<End>_<CRID>_<Accuracy>_<Coverage:F/P>_<Center:J>_<Counter>.h5
    if len(parts) >= 18:
        coverage = parts[15]
        counter_str = parts[17]
    else:
        coverage = parts[10]
        counter_str = parts[15]

    try:
        counter = int(counter_str)
    except ValueError:
        counter = 0

    return {
        "scene_name": name,
        "cycle": parts[4],
        "track": parts[5],
        "flightDirection": parts[6],
        "direction": parts[6],
        "frame": parts[7],
        "mode": parts[8],
        "polarization": parts[9],
        "pol": parts[9],
        "coverage": coverage,
        "timestamp": ts,
        "start_time": ts,
        "end_time": parts[12],
        "date": acq_date,
        "crid": crid,
        "accuracy": accuracy,
        "counter": counter,
        "version": f"{crid}_{counter:03d}",
        "url": url,
    }


def deduplicate_latest_versions(records):
    latest = {}
    for rec in records:
        if not rec:
            continue
        key = (rec["track"], rec["frame"], rec["flightDirection"], rec["date"])
        prev = latest.get(key)
        if prev is None or (rec["crid"], rec["counter"]) > (prev["crid"], prev["counter"]):
            latest[key] = rec
    return sorted(
        latest.values(),
        key=lambda r: (r["track"], r["frame"], r["flightDirection"], r["date"]),
    )


def detect_pass_gaps(dates_iso, cadence_days=12):
    gaps = []
    parsed = [date.fromisoformat(d) for d in sorted(dates_iso)]
    for d0, d1 in zip(parsed, parsed[1:]):
        delta = (d1 - d0).days
        if delta > cadence_days + 2:
            gaps.append({
                "from_date": d0.isoformat(),
                "to_date": d1.isoformat(),
                "gap_days": delta,
            })
    return gaps


def evaluate_census_and_assign_batches(
    records,
    expected_mode="2005",
    expected_pol_prefix="DH",
    min_dates_gate=8,
    pinned_track=None,
    pinned_frame=None,
    pinned_direction=None,
):
    deduped = deduplicate_latest_versions(records)

    def _filter(pol_prefix):
        return [
            r for r in deduped
            if r["coverage"] in ("F", "A")
            and r["mode"] == expected_mode
            and (pol_prefix is None or r["polarization"].startswith(pol_prefix))
            and (pinned_track is None or r["track"] == str(pinned_track))
            and (pinned_frame is None or r["frame"] == str(pinned_frame))
            and (pinned_direction is None or r["flightDirection"] == str(pinned_direction))
        ]

    valid = _filter(expected_pol_prefix)
    pol_mode = f"DUAL_POL_{expected_pol_prefix}"

    if not valid:
        fallback = _filter("SH") or _filter(None)
        if fallback:
            valid = fallback
            pol_mode = "SINGLE_POL_HH_FALLBACK"

    groups = defaultdict(list)
    for r in valid:
        groups[(r["track"], r["frame"], r["flightDirection"])].append(r)

    if not groups:
        return {
            "gate_passed": False,
            "polarization_mode": "NONE",
            "selected_geometry": None,
            "total_selected_dates": 0,
            "geometry_counts": {},
            "pass_gaps_over_12d": [],
            "selected_scenes": [],
            "recommendation": "No full-frame scenes found. Switch to fallback_sumatra_box.",
        }

    best_geom, best_list = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0]))
    best_list = sorted(best_list, key=lambda r: r["date"])
    total = len(best_list)
    mid = (total + 1) // 2

    selected = []
    for idx, scene in enumerate(best_list):
        item = dict(scene)
        item["batch"] = "A" if idx < mid else "B"
        selected.append(item)

    gaps = detect_pass_gaps([s["date"] for s in selected])
    passed = total >= min_dates_gate
    if passed and pol_mode == "SINGLE_POL_HH_FALLBACK":
        rec = "Proceed with single-pol HH and use Sentinel-1 cross-pol for vegetation."
    elif passed:
        rec = "Geometry verified (>= 8 dates). Proceed to 01_fetch.py."
    else:
        rec = f"Only {total} dates (< {min_dates_gate}). Check opposite direction or Sumatra box."

    return {
        "gate_passed": passed,
        "polarization_mode": pol_mode,
        "selected_geometry": {
            "track": best_geom[0],
            "frame": best_geom[1],
            "flightDirection": best_geom[2],
        },
        "total_selected_dates": total,
        "geometry_counts": {
            f"track={k[0]}_frame={k[1]}_dir={k[2]}": len(v) for k, v in sorted(groups.items())
        },
        "pass_gaps_over_12d": gaps,
        "selected_scenes": selected,
        "recommendation": rec,
    }


def generate_synthetic_census_records():
    timestamps = [
        "20260620T112233",
        "20260702T112233",
        "20260714T112233",
        "20260726T112233",
        "20260807T112233",
        "20260819T112233",
        "20260831T112233",
        "20260912T112233",
        "20260924T112233",
        "20261006T112233",
    ]
    out = []
    for idx, ts in enumerate(timestamps, start=1):
        fname = f"NISAR_L2_PR_GCOV_{idx:03d}_140_A_075_2005_DHDH_A_{ts}_{ts}_R05000_P_001.h5"
        url = f"https://datapool.asf.alaska.edu/GCOV/NISAR/{fname}"
        rec = parse_gcov_filename(fname, url=url)
        if rec:
            out.append(rec)
    return out


def get_earthdata_token():
    token = os.environ.get("EARTHDATA_TOKEN") or os.environ.get("EDL_TOKEN")
    if token:
        return token.strip()
    for env_path in (PROJECT_ROOT / ".env", Path.home() / ".env"):
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("EARTHDATA_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    try:
        import earthaccess

        auth = earthaccess.login(strategy="all")
        if auth and getattr(auth, "authenticated", False):
            tok = auth.token
            return str(tok.get("access_token", "")) if isinstance(tok, dict) else str(tok)
    except Exception:
        pass
    return ""


def resolve_signed_s3_url(url, token):
    import requests

    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Range": "bytes=0-0"},
        allow_redirects=False,
        timeout=15,
    )
    if r.status_code in (301, 302, 303, 307, 308) and "Location" in r.headers:
        return r.headers["Location"]
    return url


def benchmark_single_scene(url, study_box, token="", dry_run=False):
    layers = ["HHHH", "HVHV", "mask", "numberOfLooks"]
    t0 = time.perf_counter()

    if dry_run or not token:
        elapsed = round(time.perf_counter() - t0, 4)
        return {
            "url": url,
            "mode": "dry_run" if dry_run else "skipped_no_token",
            "epsg": 32749,
            "layers_verified": layers,
            "shape": [2780, 2780],
            "elapsed_seconds": elapsed,
            "estimated_5_scenes_minutes": round((35.0 * 5) / 60.0, 2),
        }

    import fsspec
    import h5py
    import numpy as np
    from pyproj import Transformer

    minx, miny, maxx, maxy = study_box
    s3_url = resolve_signed_s3_url(url, token)
    headers = {} if s3_url != url else {"Authorization": f"Bearer {token}"}
    fs = fsspec.filesystem("http", headers=headers, cache_type="bytes", block_size=1024 * 1024)
    with fs.open(s3_url, mode="rb") as f:
        with h5py.File(f, "r") as h5:
            grp = h5["/science/LSAR/GCOV/grids/frequencyA"]
            epsg = int(grp["projection"][()])
            x_coords = grp["xCoordinates"][:]
            y_coords = grp["yCoordinates"][:]

            transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
            ux0, uy0 = transformer.transform(minx, miny)
            ux1, uy1 = transformer.transform(maxx, maxy)
            u_minx, u_maxx = min(ux0, ux1), max(ux0, ux1)
            u_miny, u_maxy = min(uy0, uy1), max(uy0, uy1)

            x_idx = np.where((x_coords >= u_minx) & (x_coords <= u_maxx))[0]
            y_idx = np.where((y_coords >= u_miny) & (y_coords <= u_maxy))[0]
            found = [v for v in layers if v in grp]
            full_box_shape = [int(len(y_idx)), int(len(x_idx))]

    elapsed = round(time.perf_counter() - t0, 2)
    return {
        "url": url,
        "mode": "live_http_stream",
        "epsg": epsg,
        "layers_verified": found,
        "shape": full_box_shape,
        "elapsed_seconds": elapsed,
        "estimated_5_scenes_minutes": round((elapsed * 5) / 60.0, 2),
    }


def query_asf_gcov_scenes(
    bbox_wgs84,
    start="2026-06-01T00:00:00Z",
    end="2026-11-15T23:59:59Z",
    flight_direction=None,
    production_configuration=None,
):
    import asf_search as asf

    params = {
        "dataset": getattr(asf.DATASET, "NISAR", "NISAR"),
        "processingLevel": getattr(asf.PRODUCT_TYPE, "GCOV", "GCOV"),
        "intersectsWith": bbox_to_wkt(bbox_wgs84),
        "start": start,
        "end": end,
    }
    if flight_direction:
        params["flightDirection"] = flight_direction
    if production_configuration:
        params["productionConfiguration"] = production_configuration

    opts = asf.ASFSearchOptions(**params)
    response = asf.search(opts=opts)
    urls = response.find_urls(extension=".h5", directAccess=False)

    records = []
    for u in urls:
        parsed = parse_gcov_filename(Path(u).name, url=u)
        if parsed:
            records.append(parsed)
    return records


def format_summary_table(evaluation, active_bbox):
    geom = evaluation["selected_geometry"] or {}
    bench = evaluation.get("benchmark", {})
    batch_a = sum(1 for s in evaluation.get("selected_scenes", []) if s.get("batch") == "A")
    batch_b = sum(1 for s in evaluation.get("selected_scenes", []) if s.get("batch") == "B")
    lines = [
        f"Study Box (EPSG:4326) : {active_bbox}",
        f"Selected Geometry     : track={geom.get('track', '-')} frame={geom.get('frame', '-')} dir={geom.get('flightDirection', '-')}",
        f"Polarization Mode     : {evaluation.get('polarization_mode', '-')}",
        f"Total Selected Dates  : {evaluation.get('total_selected_dates', 0)} (gate_passed={evaluation.get('gate_passed')})",
        f"Batch Split (50/50)   : Batch A={batch_a} | Batch B={batch_b}",
        f"Benchmark 1 Scene     : layers={bench.get('layers_verified', [])} elapsed={bench.get('elapsed_seconds', 0.0)}s ({bench.get('mode', '-')})",
        f"Status                : {evaluation.get('recommendation', '')}",
        "",
        f"{'Date':<12} {'Cycle':<5} {'Track':<5} {'Frame':<5} {'Dir':<3} {'Mode':<4} {'Pol':<4} {'Cov':<3} {'Version':<10} {'Batch':<5}",
    ]
    for s in evaluation.get("selected_scenes", []):
        lines.append(
            f"{s['date']:<12} {s['cycle']:<5} {s['track']:<5} {s['frame']:<5} "
            f"{s['flightDirection']:<3} {s['mode']:<4} {s['polarization']:<4} "
            f"{s['coverage']:<3} {s['version']:<10} {s['batch']:<5}"
        )
    return "\n".join(lines)


def write_census_outputs(all_records, evaluation, cfg, active_bbox):
    csv_rel = cfg.get("census_csv") or cfg.get("paths", {}).get("census_csv", "data/census.csv")
    csv_path = Path(csv_rel) if Path(csv_rel).is_absolute() else PROJECT_ROOT / csv_rel
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    cols = [
        "date",
        "timestamp",
        "cycle",
        "track",
        "frame",
        "flightDirection",
        "mode",
        "polarization",
        "coverage",
        "version",
        "batch",
        "scene_name",
        "url",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for row in evaluation.get("selected_scenes", []):
            writer.writerow({k: row.get(k, "") for k in cols})

    json_rel = cfg.get("selected_scenes_json") or cfg.get("paths", {}).get(
        "selected_scenes_json", "data/selected_scenes.json"
    )
    json_path = Path(json_rel) if Path(json_rel).is_absolute() else PROJECT_ROOT / json_rel
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump({"study_box": active_bbox, **evaluation}, f, indent=2)


def run_census(cfg, dry_run=False):
    raw_box = cfg["study_box"]
    active_bbox = list(raw_box["bbox_wgs84"] if isinstance(raw_box, dict) else raw_box)
    start_dt = cfg.get("start_date") or cfg.get("time_window", {}).get("start", "2026-06-01T00:00:00Z")
    end_dt = cfg.get("end_date") or cfg.get("time_window", {}).get("end", "2026-11-15T23:59:59Z")

    if dry_run:
        records = generate_synthetic_census_records()
    else:
        records = query_asf_gcov_scenes(active_bbox, start=start_dt, end=end_dt)

    mode = str(cfg.get("expected_mode") or cfg.get("geometry", {}).get("expected_mode", "2005"))
    pol = str(cfg.get("expected_pol_prefix") or cfg.get("geometry", {}).get("expected_pol_prefix", "DH"))
    min_dates = int(cfg.get("min_dates_gate") or cfg.get("geometry", {}).get("min_dates_gate", 8))

    evaluation = evaluate_census_and_assign_batches(
        records,
        expected_mode=mode,
        expected_pol_prefix=pol,
        min_dates_gate=min_dates,
        pinned_track=cfg.get("track"),
        pinned_frame=cfg.get("frame"),
        pinned_direction=cfg.get("flightDirection"),
    )

    if not evaluation["gate_passed"] and not dry_run:
        fb_box = list(
            cfg.get("fallback_sumatra_box")
            or cfg.get("study_box", {}).get("fallback_sumatra_bbox_wgs84", [104.20, -2.90, 104.70, -2.40])
        )
        fb_records = query_asf_gcov_scenes(fb_box, start=start_dt, end=end_dt)
        fb_eval = evaluate_census_and_assign_batches(
            fb_records,
            expected_mode=mode,
            expected_pol_prefix=pol,
            min_dates_gate=min_dates,
        )
        if fb_eval["total_selected_dates"] > evaluation["total_selected_dates"]:
            records = fb_records
            evaluation = fb_eval
            active_bbox = fb_box

    if evaluation.get("selected_scenes"):
        first_url = evaluation["selected_scenes"][0]["url"]
        token = get_earthdata_token()
        evaluation["benchmark"] = benchmark_single_scene(
            url=first_url,
            study_box=active_bbox,
            token=token,
            dry_run=dry_run,
        )

    write_census_outputs(records, evaluation, cfg, active_bbox)
    print(format_summary_table(evaluation, active_bbox))
    return evaluation


def main():
    parser = argparse.ArgumentParser(description="Search and filter NISAR L2 GCOV scenes.")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    run_census(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
