"""Stage 8: write the app's data bundle (build brief section 5) from the pipeline outputs.

Reads stages 2 to 7, writes manifest.json, cells.geojson, context_features.geojson, series.json,
context.json, scorecard.json and images/ into public/bundle/ (the folder the app serves), then runs
`npm run check-bundle` so the app's own loader validates the result.

Rules from the design doc (Rev 2):
- Every 12-day pass from the first to the last date has a slot (context_summary.json dates). A pass with
  no radar data is a dropped date with its reason; its radar values are null and its state is 1.
- A missing number stays missing. The export refuses inputs marked synthetic (fallback canals, rule-of-thumb
  classes, the coherence proxy, a synthetic smoke image). --allow-unverified writes them anyway for testing,
  labels the bundle "mock" so the app shows its "Simulated data" badge, and writes to bundle_test/.
- The scorecard is computed here, from the exact numbers being exported, with the same definitions as the
  simulated generator (scripts/mock/scorecard.ts), so the screen and the scorecard can never disagree.

Run: py pipeline/08_export.py [--out DIR] [--allow-unverified] | --self-test
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
WORK_BUNDLE = PROJECT_ROOT / "bundle"  # stages 2, 3 and 6 write images and geojson here
PUBLIC_BUNDLE = PROJECT_ROOT / "public" / "bundle"
TEST_BUNDLE = PROJECT_ROOT / "bundle_test"

# ASF NISAR Known Issues: no data collected 2026-07-27T22:03:25Z to 2026-08-10T00:55:27Z (permanent).
GAP_FIRST, GAP_LAST = "2026-07-27", "2026-08-10"

STATE_LABELS = [
    (1, "no_data", "No data", "Tidak ada data"),
    (2, "fire_radar", "Fire, radar agrees", "Api, radar mendeteksi"),
    (3, "fire_silent", "Fire, radar silent", "Api, radar tidak mendeteksi"),
    (4, "burned", "Burned", "Terbakar"),
    (5, "rewetting", "Re-wetting", "Membasah kembali"),
    (6, "deep_drying", "Deep drying", "Mengering parah"),
    (7, "drying", "Drying", "Mengering"),
    (8, "stable", "Stable", "Stabil"),
]
CLASS_LABELS = [
    ("drained", "Drained peat", "Gambut terdrainase"),
    ("rewetted", "Rewetted peat", "Gambut yang dibasahi kembali"),
    ("plantation", "Plantation on peat", "Perkebunan di atas gambut"),
    ("intact_forest", "Intact peat swamp forest", "Hutan rawa gambut utuh"),
    ("reference_forest", "Reference forest (mineral soil)", "Hutan acuan (tanah mineral)"),
    ("settlement", "Settlement", "Permukiman"),
]
NO_DATA, FIRE_RADAR, FIRE_SILENT, REWETTING = 1, 2, 3, 5
LANDCLASS_VERSION = "nisar_landclass_v1"  # 04c_landclass.py VERSION

NOTE_EN = "Descriptive only. Neighbouring cells are not independent, so read this as a pattern, not proof."
NOTE_ID = "Hanya deskriptif. Sel yang bertetangga tidak saling bebas, jadi baca ini sebagai pola, bukan bukti."  # REVIEW


# ---------- small statistics, matching scripts/mock/stats.ts ----------

def round_half_up(v: float, d: int = 2) -> float:
    """JavaScript Math.round semantics, so Python and the simulated generator round alike."""
    f = 10 ** d
    return math.floor(v * f + 0.5) / f


def quantile(v: list[float], p: float) -> float:
    """Linear interpolation between order statistics (R type 7)."""
    if not v:
        raise ValueError("quantile of empty list")
    s = sorted(v)
    h = (len(s) - 1) * p
    lo = math.floor(h)
    return s[lo] + (h - lo) * (s[min(lo + 1, len(s) - 1)] - s[lo])


def median(v: list[float]) -> float:
    return quantile(v, 0.5)


def spearman(a: list[float], b: list[float]) -> float:
    """Pearson correlation of average ranks (ties share their mean rank)."""
    ra = pd.Series(a).rank(method="average").to_numpy()
    rb = pd.Series(b).rank(method="average").to_numpy()
    ra, rb = ra - ra.mean(), rb - rb.mean()
    return float((ra * rb).sum() / math.sqrt((ra ** 2).sum() * (rb ** 2).sum()))


# ---------- inputs ----------

def _load_config():
    spec = importlib.util.spec_from_file_location("census_mod", Path(__file__).resolve().parent / "00_census.py")
    census = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(census)
    return census.load_config(PROJECT_ROOT / "config.yaml")


def _json(path: Path, default=None, stage: str = "the stage that writes it"):
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"{path} is missing; run {stage} first")
    return json.loads(path.read_text(encoding="utf-8"))


def _landclass_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; run 04c_landclass.py first")
    return pd.read_csv(path, dtype={"cell_id": str, "cover_set": str, "label_map": str, "class_model": str})


def _cube_attrs(cube: Path) -> dict:
    """Root attrs of the radar cube: zarr v2 (.zattrs or consolidated .zmetadata) or v3 (zarr.json)."""
    if (cube / ".zattrs").exists():
        return _json(cube / ".zattrs")
    if (cube / ".zmetadata").exists():
        return _json(cube / ".zmetadata")["metadata"].get(".zattrs", {})
    if (cube / "zarr.json").exists():
        return _json(cube / "zarr.json").get("attributes", {})
    raise FileNotFoundError(f"{cube} has no zarr metadata; run 01_fetch.py first")


def load_inputs() -> dict:
    """Everything the export reads, from the paths stages 0 to 7 write."""
    cfg = _load_config()
    return {
        "config": cfg,
        "cube_attrs": _cube_attrs(PROJECT_ROOT / cfg.get("merged_cube_zarr", "data/gcov_cube.zarr")),
        "landclass_report": _json(DATA_DIR / "landclass_report.json", stage="04c_landclass.py"),
        "landclass": _landclass_csv(DATA_DIR / "landclass.csv"),
        "fire_report": _json(DATA_DIR / "fire_risk_report.json", stage="07b_fire_risk.py"),
        "quality": _json(DATA_DIR / "quality_report.json"),
        "scenes": _json(DATA_DIR / "selected_scenes.json"),
        "noise": _json(DATA_DIR / "noise_floor.json"),
        "context": _json(DATA_DIR / "context_summary.json"),
        "coherence_report": _json(DATA_DIR / "coherence_report.json"),
        "provenance": _json(DATA_DIR / "grid_provenance.json", default={}),
        "visuals": _json(DATA_DIR / "context_visuals.json"),
        "cells_fc": _json(WORK_BUNDLE / "cells.geojson"),
        "context_fc": _json(WORK_BUNDLE / "context_features.geojson"),
        "stats": pd.read_parquet(DATA_DIR / "cell_stats.parquet", columns=["cell_id", "date", "hh_tenths", "hv_tenths"]),
        "coherence": pd.read_parquet(DATA_DIR / "coherence.parquet", columns=["cell_id", "date_start", "date_end", "coh"]),
        "fires": pd.read_parquet(DATA_DIR / "fires.parquet"),
        "states": pd.read_parquet(DATA_DIR / "states.parquet"),
        "images_dir": WORK_BUNDLE / "images",
    }


def provenance_problems(inp: dict) -> list[str]:
    """Inputs that are stand-ins, not observations or cited datasets (design doc principle 7)."""
    p = inp["provenance"]
    problems = []
    if inp["cube_attrs"].get("data_source") != "asf_live_stream":
        problems.append("the radar cube is not marked as streamed from ASF (dry-run or unknown origin); re-run 01_fetch.py live")
    lr = inp["landclass_report"]
    if p.get("class_source") == LANDCLASS_VERSION and (lr.get("status") != "used" or lr.get("version") != LANDCLASS_VERSION):
        problems.append(f"cell classes are marked as {LANDCLASS_VERSION}, but landclass_report.json says status "
                        f"'{lr.get('status')}', version '{lr.get('version')}' (re-run 04c_landclass.py)")
    if lr.get("status") == "used" and p.get("class_source") != LANDCLASS_VERSION:
        problems.append(f"landclass_report.json says the model is used, but grid_provenance.json class_source is "
                        f"'{p.get('class_source')}' (re-run 04c_landclass.py)")
    if p.get("canal_source") != "osm_overpass":
        problems.append(f"canals are '{p.get('canal_source', 'unknown')}', not OpenStreetMap (re-run 03_grid.py online)")
    if p.get("class_source", "heuristic_rules") == "heuristic_rules":
        problems.append("cell classes come from rule-of-thumb boxes in 03_grid.py, not a cited land-cover map")
    if p.get("tree_cover_source", "heuristic_constants") == "heuristic_constants":
        problems.append("tree cover comes from constants in 03_grid.py, not a cited tree-cover map")
    if inp["coherence_report"].get("proxy_used") or any(
        r.get("source") == "gcov_radiometric_fallback" for r in inp["coherence_report"].get("per_interval", [])
    ):
        problems.append("coherence contains the GCOV brightness proxy (re-run 05_coherence.py without --allow-proxy)")
    if str(inp["visuals"].get("source", "")).startswith("SYNTHETIC"):
        problems.append("the smoke reveal picture is synthetic (re-run 06_context_visuals.py without --dry-run)")
    return problems


# ---------- the bundle ----------

def _pivot(df: pd.DataFrame, value: str, cells: list[str], cols: list, col_key: str = "date") -> list[list]:
    """cells x cols matrix of Python ints or None (never NaN)."""
    wide = df.pivot(index="cell_id", columns=col_key, values=value).reindex(index=cells, columns=cols)
    out = []
    for row in wide.itertuples(index=False):
        out.append([None if (v is None or v is pd.NA or (isinstance(v, float) and math.isnan(v))) else int(v) for v in row])
    return out


def dropped_reason(date: str, quality: dict) -> tuple[str, str]:
    summary = {d["date"]: d for d in quality.get("dates_summary", [])}
    if date in summary and summary[date].get("status") != "ok":
        s = summary[date]
        return (s.get("reason_en") or s.get("reason") or "Failed the quality check",
                s.get("reason_id") or s.get("reason") or "Tidak lolos pemeriksaan kualitas")  # REVIEW
    if GAP_FIRST <= date <= GAP_LAST:
        return ("No data collected: NISAR instrument data gap, 27 Jul to 10 Aug 2026",
                "Tidak ada data: celah data instrumen NISAR, 27 Jul sampai 10 Agu 2026")  # REVIEW
    return ("No NISAR scene found for this pass", "Tidak ada citra NISAR untuk lintasan ini")  # REVIEW


def build_scorecard(cells_props: list[dict], hh: list[list], states: list[list], dates: list[str]) -> dict:
    """Build brief 5.9 and 6.7, computed on the exported numbers. Port of scripts/mock/scorecard.ts."""
    n = len(cells_props)
    D = [[None if v is None else v / 10 for v in row] for row in hh]
    is_fire = lambda s: s in (FIRE_RADAR, FIRE_SILENT)  # noqa: E731
    burned = [any(is_fire(s) for s in states[i]) for i in range(n)]

    min_info = []
    for i in range(n):
        best, at = math.inf, 0
        for t, v in enumerate(D[i]):
            if v is not None and states[i][t] != NO_DATA and v < best:
                best, at = v, t
        min_info.append((None if best == math.inf else best, at))

    by_class = []
    for cls, _, _ in CLASS_LABELS:
        idx = [i for i in range(n) if cells_props[i]["class"] == cls]
        mins = [min_info[i][0] for i in idx if min_info[i][0] is not None]
        if not idx or not mins:
            continue  # a class absent from this landscape has no row
        recov = []
        for i in idx:
            at = min_info[i][1]
            r = next((t for t, s in enumerate(states[i]) if t > at and s == REWETTING), None)
            if r is not None:
                recov.append(r - at)
        by_class.append({
            "class": cls,
            "n_cells": len(idx),
            "median_min_hh_db": round_half_up(median(mins)),
            "p25_min_hh_db": round_half_up(quantile(mins, 0.25)),
            "p75_min_hh_db": round_half_up(quantile(mins, 0.75)),
            "share_burned": round_half_up(sum(burned[i] for i in idx) / len(idx), 3),
            "median_passes_to_recovery": median(recov) if recov else None,
        })
    row = {r["class"]: r for r in by_class}
    if "drained" not in row:
        raise ValueError("no drained cells with data: the scorecard needs them as its baseline")
    drained_median = row["drained"]["median_min_hh_db"]

    order = sorted(
        (i for i in range(n) if cells_props[i]["class"] in ("drained", "plantation") and min_info[i][0] is not None),
        key=lambda i: (min_info[i][0], i),
    )
    fastest_drying = [
        {"cell": cells_props[i]["id"], "class": cells_props[i]["class"],
         "min_hh_db": round_half_up(min_info[i][0]), "date_of_min": dates[min_info[i][1]]}
        for i in order[:20]
    ]
    dams = sorted(
        (i for i in range(n) if cells_props[i]["class"] == "rewetted"
         and min_info[i][0] is not None and min_info[i][0] < drained_median),
        key=lambda i: min_info[i][0],
    )
    dams_to_inspect = [
        {"cell": cells_props[i]["id"], "min_hh_db": round_half_up(min_info[i][0]),
         "gap_vs_drained_median_db": round_half_up(min_info[i][0] - drained_median)}
        for i in dams
    ]

    peat = [i for i in range(n) if min_info[i][0] is not None and cells_props[i]["class"] in ("drained", "rewetted", "plantation")]
    rho = spearman([cells_props[i]["canal_density_km_per_km2"] for i in peat], [min_info[i][0] for i in peat]) if len(peat) > 2 else 0.0

    unburned_peat = [i for i in peat if not burned[i]]
    diffs = []
    for i in range(n):
        t = next((t for t, s in enumerate(states[i]) if is_fire(s)), -1)
        # The last pass with radar data before the fire (t - 1 unless a pass was dropped, as in Aug 2026),
        # and never the baseline pass, whose index is 0 by definition.
        tb = next((u for u in range(t - 1, 0, -1) if D[i][u] is not None and states[i][u] != NO_DATA), None)
        if t <= 1 or tb is None:
            continue
        others = [D[j][tb] for j in unburned_peat if D[j][tb] is not None]
        if others:
            diffs.append(D[i][tb] - median(others))

    # Peak drought: the valid date where the drained cells' median index is lowest.
    drained_idx = [i for i in range(n) if cells_props[i]["class"] == "drained"]
    medians_by_t = {}
    for t in range(1, len(dates)):
        vals = [D[i][t] for i in drained_idx if D[i][t] is not None]
        if vals:
            medians_by_t[t] = median(vals)
    peak = min(medians_by_t, key=medians_by_t.get) if medians_by_t else len(dates) - 1
    forest_peak = [abs(D[i][peak]) for i in range(n) if cells_props[i]["class"] == "intact_forest" and D[i][peak] is not None]

    rew = row.get("rewetted")
    tests = [
        {
            "id": "canal_vs_drying",
            "name_en": "More canals, more drying",
            "name_id": "Makin banyak kanal, makin kering",  # REVIEW
            "statistic": "Spearman rank correlation",
            "value": round_half_up(rho, 3),
            "n": len(peat),
            "note_en": f"{NOTE_EN} A negative value means cells with more canal length reached lower (drier) minimums.",
            "note_id": f"{NOTE_ID} Nilai negatif berarti sel dengan kanal lebih panjang mencapai titik terendah yang lebih kering.",  # REVIEW
        },
    ]
    if rew:
        tests.append({
            "id": "rewetted_vs_drained",
            "name_en": "Rewetted cells dry less",
            "name_id": "Sel yang dibasahi kembali lebih sedikit mengering",  # REVIEW
            "statistic": f"Difference in median minimum HH index, dB (rewetted n={rew['n_cells']}, drained n={row['drained']['n_cells']})",
            "value": round_half_up(rew["median_min_hh_db"] - drained_median),
            "n": rew["n_cells"] + row["drained"]["n_cells"],
            "note_en": f"{NOTE_EN} A positive value means rewetted cells stayed wetter.",
            "note_id": f"{NOTE_ID} Nilai positif berarti sel yang dibasahi kembali tetap lebih basah.",  # REVIEW
        })
    if diffs:
        tests.append({
            "id": "drying_before_fire",
            "name_en": "Drying comes before fire",
            "name_id": "Pengeringan mendahului api",  # REVIEW
            "statistic": "Median HH index on the last pass before the fire, burned minus unburned cells, dB",
            "value": round_half_up(median(diffs)),
            "n": len(diffs),
            "note_en": f"{NOTE_EN} A negative value means cells were already drier than their neighbours one pass before burning.",
            "note_id": f"{NOTE_ID} Nilai negatif berarti sel sudah lebih kering dari sekitarnya satu lintasan sebelum terbakar.",  # REVIEW
        })
    if forest_peak:
        tests.append({
            "id": "forest_flat",
            "name_en": "Intact forest shows little signal",
            "name_id": "Hutan utuh hanya menunjukkan sedikit sinyal",  # REVIEW
            "statistic": f"Median absolute HH index of intact forest at peak drought ({dates[peak]}), dB",
            "value": round_half_up(median(forest_peak)),
            "n": len(forest_peak),
            "note_en": f"{NOTE_EN} L-band radar sees little of the peat surface under dense canopy.",
            "note_id": f"{NOTE_ID} Radar pita L hanya sedikit melihat permukaan gambut di bawah tajuk yang rapat.",  # REVIEW
        })
    return {"by_class": by_class, "rankings": {"fastest_drying": fastest_drying, "dams_to_inspect": dams_to_inspect}, "tests": tests}


def build_bundle(inp: dict, data_kind: str, generated_at: str) -> dict[str, bytes]:
    """Pure: inputs in, {relative path: bytes} out. No file is written here."""
    cfg, quality, noise, ctx = inp["config"], inp["quality"], inp["noise"], inp["context"]
    dates: list[str] = ctx["dates"]
    T = len(dates)
    kept = set(quality["kept_dates"]) - {d.get("date") if isinstance(d, dict) else d for d in quality.get("dropped_dates", [])}
    if not kept <= set(dates):
        raise ValueError(f"kept dates not in the pass calendar: {sorted(kept - set(dates))}")
    if dates[0] not in kept:
        raise ValueError("the first pass must have radar data: it is the baseline of every index")

    # Cells: contract properties only, in the work bundle's order (series.cells is authoritative).
    features = inp["cells_fc"]["features"]
    keep_props = ("id", "row", "col", "class", "canal_density_km_per_km2", "tree_cover_pct", "n_pixels", "centroid")
    cells_fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": f["geometry"], "properties": {k: f["properties"][k] for k in keep_props}}
        for f in features
    ]}
    props = [f["properties"] for f in cells_fc["features"]]
    cell_ids = [p["id"] for p in props]

    # Land model (04c): when it passed its gates, its classes replace the map's, before the scorecard is computed.
    lr = inp["landclass_report"]
    if lr["status"] not in ("used", "not_used"):
        raise ValueError(f"landclass_report.json status '{lr['status']}' is not used/not_used; re-run 04c_landclass.py")
    land_used = lr["status"] == "used"
    if land_used:
        lc = inp["landclass"].set_index("cell_id")
        if not lc.index.is_unique:
            raise ValueError("landclass.csv repeats a cell_id; re-run 04c_landclass.py")
        missing = [c for c in cell_ids if c not in lc.index]
        if missing:
            raise ValueError(f"landclass.csv has no row for {len(missing)} cells (e.g. {missing[0]}); re-run 04c_landclass.py")
        for p in props:
            r = lc.loc[p["id"]]
            p["class"] = str(r["class_model"])
            cs = r["cover_set"]
            p["cover_set"] = cs.split("|") if isinstance(cs, str) and cs else []  # "" is read back as NaN
            if int(r["map_check"]) == 1:
                if len(p["cover_set"]) != 1:
                    raise ValueError(f"{p['id']} is flagged map_check without a one-class radar set")
                p["map_check"] = str(r["label_map"])
    reasons = "; ".join(lr.get("reasons", []))
    land_model = {
        "status": lr["status"],
        "version": lr["version"],
        "confidence_level": lr["confidence_level"],
        "reason_en": None if land_used else f"The radar land model did not pass its checks, so the classes come from the maps: {reasons}",
        "reason_id": None if land_used else f"Model lahan radar tidak lolos pemeriksaannya, jadi kelas berasal dari peta: {reasons}",  # REVIEW
    }

    # Series. Values exist only on passes with radar data; everything else is null.
    hh = _pivot(inp["stats"], "hh_tenths", cell_ids, dates)
    hv = _pivot(inp["stats"], "hv_tenths", cell_ids, dates)
    for mat in (hh, hv):
        for row in mat:
            for t, d in enumerate(dates):
                if d not in kept:
                    row[t] = None
            if row[0] not in (0, None):
                raise ValueError("hh/hv at the first date must be 0: the index is change since the first pass")
    coh_df = inp["coherence"].assign(k=[
        {(dates[k], dates[k + 1]): k for k in range(T - 1)}.get(p, -1)
        for p in zip(inp["coherence"]["date_start"], inp["coherence"]["date_end"])
    ])
    coh = _pivot(coh_df[coh_df["k"] >= 0], "coh", cell_ids, list(range(T - 1)), col_key="k")
    fire_cols = [f"fires_int_{k}" for k in range(T - 1)]
    missing = [c for c in fire_cols if c not in inp["fires"].columns]
    if missing or f"fires_int_{T - 1}" in inp["fires"].columns:
        raise ValueError("fires.parquet intervals do not match the pass calendar; re-run 06_context_tabular.py")
    fires_wide = inp["fires"].set_index("cell_id").reindex(cell_ids)[fire_cols]
    fires = [[None if pd.isna(v) else int(v) for v in row] for row in fires_wide.itertuples(index=False)]
    state = _pivot(inp["states"], "state", cell_ids, dates)
    for i, row in enumerate(state):
        if any(v is None for v in row):
            raise ValueError(f"states.parquet has no state for {cell_ids[i]} on some date; re-run 07_states.py")
        for t, d in enumerate(dates):
            if d not in kept and row[t] != NO_DATA:
                raise ValueError(f"{cell_ids[i]} has state {row[t]} on {d}, which has no radar data")
    series = {"dates": dates, "cells": cell_ids, "hh": hh, "hv": hv, "coh": coh, "fires": fires, "state": state}

    context = {
        "dates": dates,
        "rain_3day_mm": ctx.get("rain_3day_mm", ctx.get("rain_3d_mm")),
        "rain_interval_mm": ctx["rain_interval_mm"],
        "fires_region": ctx["fires_region"],
        "quality": ["ok" if d in kept else "dropped" for d in dates],
    }

    th = noise["thresholds"]
    sigma_by_date = dict(zip(noise["dates"], th["sigma_db"]))
    sigma = [None if (t == 0 or d not in kept) else sigma_by_date.get(d) for t, d in enumerate(dates)]
    if any(s is None for t, s in enumerate(sigma) if t > 0 and dates[t] in kept):
        raise ValueError("noise_floor.json has no sigma for a pass with radar data")

    sel = inp["scenes"]
    geom = sel.get("selected_geometry", {})
    direction = geom.get("flightDirection") or geom.get("direction")
    scenes = sorted(
        ({"date": s["date"], "name": s["scene_name"], "version": s.get("version") or s.get("crid") or ""}
         for s in sel.get("selected_scenes", []) if s.get("date") in kept),
        key=lambda s: s["date"],
    )

    images: dict[str, bytes] = {}
    img_dir = Path(inp["images_dir"])
    radar = []
    for r in quality.get("radar_images", []):
        if r["date"] in kept:
            radar.append({"date": r["date"], "file": f"images/radar_{r['date']}.png"})
            images[f"images/radar_{r['date']}.png"] = (img_dir / Path(r["file"]).name).read_bytes()
    vis = inp["visuals"]
    reveal_date = vis["reveal_date"]
    if reveal_date not in kept:
        raise ValueError(f"reveal date {reveal_date} has no radar picture")
    images["images/reveal_optical.png"] = (img_dir / Path(vis["optical_file"]).name).read_bytes()
    images["images/reveal_radar.png"] = (img_dir / f"radar_{reveal_date}.png").read_bytes()

    prov = inp["provenance"]
    sources = [
        {"name": "NISAR L-band GCOV (NASA-ISRO), via ASF DAAC", "url": "https://asf.alaska.edu/nisar/",
         "role_en": "Radar brightness (HH and HV) for every pass. Scene names and versions are listed above.",
         "role_id": "Kecerahan radar (HH dan HV) untuk setiap lintasan. Nama dan versi citra tercantum di atas."},  # REVIEW
        {"name": "NASA FIRMS active fire data", "url": "https://firms.modaps.eosdis.nasa.gov/",
         "role_en": ctx.get("fire_source", "Fire detections per cell and interval."),
         "role_id": "Deteksi api per sel dan interval."},  # REVIEW
        {"name": "Open-Meteo historical weather archive", "url": "https://open-meteo.com/en/docs/historical-weather-api",
         "role_en": ctx.get("rain_source", "Daily rainfall."),
         "role_id": "Curah hujan harian (reanalisis keluarga ERA5) di tengah kotak studi."},  # REVIEW
        {"name": "NASA Worldview (GIBS)", "url": "https://worldview.earthdata.nasa.gov/",
         "role_en": f"True-colour picture for the opening comparison: {vis.get('source', '')}.",
         "role_id": "Citra warna asli untuk perbandingan pembuka."},  # REVIEW
        {"name": "OpenStreetMap", "url": "https://www.openstreetmap.org/copyright",
         "role_en": "Canals and waterways for canal density, and basemap tiles."
         if prov.get("canal_source") == "osm_overpass" else "Basemap tiles. Canals here are NOT from OpenStreetMap.",
         "role_id": "Kanal dan saluran air untuk kepadatan kanal, serta ubin peta dasar."},  # REVIEW
    ]

    bbox = [float(v) for v in cfg["study_box"]]
    manifest = {
        "schema_version": "0.2",
        "data_kind": data_kind,
        "generated_at": generated_at,
        "generator": {"name": "napas-gambut-pipeline", "version": "0.1.0", "seed": None},
        "study_area": {
            "name_en": "Central Kalimantan peat landscape",
            "name_id": "Lanskap gambut Kalimantan Tengah",
            "bbox": bbox,
            "cell_size_m": cfg.get("cell_size_m", 500),
        },
        "geometry": {
            "track": int(geom["track"]) if geom.get("track") is not None else None,
            "frame": int(geom["frame"]) if geom.get("frame") is not None else None,
            "direction": direction if direction in ("A", "D") else None,
        },
        "dates": dates,
        "dropped_dates": [
            dict(zip(("date", "reason_en", "reason_id"), (d, *dropped_reason(d, quality)))) for d in dates if d not in kept
        ],
        "scenes": scenes,
        "thresholds": {
            "sigma_db": sigma,
            "change_k": float(th["change_k"]),
            "headline_k": float(th["headline_k"]),
            "deep_k": float(th["deep_k"]),
            "rain_return_mm": float(cfg["rain_return_mm"]),
        },
        "classes": [{"id": i, "label_en": e, "label_id": l} for i, e, l in CLASS_LABELS],
        "land_model": land_model,
        "states": [{"code": c, "key": k, "label_en": e, "label_id": l} for c, k, e, l in STATE_LABELS],
        "images": {
            "bounds": quality["image_bounds"],
            "radar": radar,
            "reveal": {"date": reveal_date, "optical_file": "images/reveal_optical.png", "radar_file": "images/reveal_radar.png"},
        },
        "sources": sources,
    }

    scorecard = build_scorecard(props, hh, state, dates)
    tests = scorecard["tests"]
    if land_used:
        m = lr["metrics"]
        tests.append({
            "id": "land_model_coverage",
            "name_en": "Radar land classes agree with the maps",
            "name_id": "Kelas lahan radar sesuai dengan peta",  # REVIEW
            "statistic": "Share of held-out cells whose map class is inside the radar's class set (target 90%)",
            "value": m["check_coverage"]["value"],
            "n": m["check_coverage"]["n"],
            "note_en": "Checked on held-out 5 km blocks against the 2021 maps, not against the ground.",
            "note_id": "Diperiksa pada blok 5 km yang disisihkan terhadap peta 2021, bukan terhadap kondisi lapangan.",  # REVIEW
        })
        tests.append({
            "id": "map_out_of_date",
            "name_en": "Radar disagrees with the older map",
            "name_id": "Radar tidak sesuai dengan peta lama",  # REVIEW
            "statistic": "Share of cells where the radar confidently disagrees with the 2021 maps",
            "value": round_half_up(m["n_map_check"] / m["n_cells"], 3),
            "n": m["n_cells"],
            "note_en": "Worth checking on the ground; many are mixed cells, not real change.",
            "note_id": "Layak diperiksa di lapangan; banyak di antaranya sel campuran, bukan perubahan nyata.",  # REVIEW
        })

    # Fire-risk hindcast (07b), copied from its report. It is a ranking test, never a forecast.
    fr = inp["fire_report"]
    if fr["status"] not in ("passed", "not_passed", "not_run"):
        raise ValueError(f"fire_risk_report.json status '{fr['status']}' is unknown; re-run 07b_fire_risk.py")
    model = fr.get("model") or {}
    ci = model.get("pr_auc_ci")
    bb = fr.get("best_baseline")
    scorecard["fire_risk"] = {
        "status": fr["status"],
        "test_dates": fr["test_dates"],
        "model_pr_auc": model.get("pr_auc"),
        "model_pr_auc_ci": ci if ci and None not in ci else None,
        "best_baseline": {"id": bb["id"], "pr_auc": bb["pr_auc"]} if bb else None,
        "lift": [{"quintile": q["quintile"], "n": q["n"], "fires": q["fires"], "rate": round_half_up(q["rate"], 3)}
                 for q in fr.get("lift", [])],
    }
    if fr["status"] == "passed":
        bid = bb["id"]
        tests.append({
            "id": "fire_risk_capture",
            "name_en": "Fire-risk hindcast ranks burned cells higher",
            "name_id": "Hindcast risiko kebakaran menempatkan sel yang terbakar lebih tinggi",  # REVIEW
            "statistic": "Share of next-interval fires in the top 10% of cells, ranked within each pass "
                         f"(best simple rule {bid}: {round_half_up(fr['baselines'][bid]['top10_capture'], 3)})",
            "value": model["top10_capture"],
            "n": fr["n_test_fires"],
            "note_en": "Hindcast of the 2026 season at one site, not a forecast.",
            "note_id": "Hindcast musim 2026 di satu lokasi, bukan prakiraan.",  # REVIEW
        })

    def enc(v) -> bytes:  # compact, and allow_nan=False makes a stray NaN an error instead of invalid JSON
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")

    context_fc = {"type": "FeatureCollection", "features": [
        f for f in inp["context_fc"]["features"] if f["properties"].get("kind") in ("canal", "river", "dam", "town")
    ]}
    files = {
        "manifest.json": enc(manifest),
        "cells.geojson": enc(cells_fc),
        "context_features.geojson": enc(context_fc),
        "series.json": enc(series),
        "context.json": enc(context),
        "scorecard.json": enc(scorecard),
        **images,
    }
    data = sum(len(b) for k, b in files.items() if not k.endswith(".png"))
    img = sum(len(b) for k, b in files.items() if k.endswith(".png"))
    if data > 6e6:
        raise ValueError(f"non-image files are {data / 1e6:.2f} MB, over the 6 MB budget (see design doc, size targets)")
    if img > 10e6:
        raise ValueError(f"images are {img / 1e6:.2f} MB, over the 10 MB budget")
    return files


# ---------- writing and checking ----------

def write_bundle(files: dict[str, bytes], out: Path) -> None:
    out = out.resolve()
    if out in (PROJECT_ROOT.resolve(), WORK_BUNDLE.resolve(), DATA_DIR.resolve()) or WORK_BUNDLE.resolve().is_relative_to(out):
        raise ValueError(f"refusing to replace {out}: it holds pipeline inputs")
    if out.exists():
        shutil.rmtree(out)
    for name, buf in files.items():
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(buf)


def check_with_app_loader(out: Path) -> None:
    """Validate with the app's own loader (scripts/check-bundle.ts). Needs Node and `npm install`."""
    tsx = PROJECT_ROOT / "node_modules" / "tsx" / "dist" / "cli.mjs"
    if not tsx.exists() or shutil.which("node") is None:
        print("[WARN] Node or node_modules missing: run `npm install` then `npm run check-bundle -- <dir>` yourself.")
        return
    r = subprocess.run(["node", str(tsx), "scripts/check-bundle.ts", str(out)], cwd=PROJECT_ROOT, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        raise SystemExit(f"The app would not load this bundle:\n{r.stderr}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write the app's data bundle from the pipeline outputs.")
    ap.add_argument("--out", type=Path, default=None, help="default: public/bundle (verified) or bundle_test (unverified)")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="Testing only: export despite synthetic inputs; labelled 'mock' so the app shows the Simulated badge.")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return run_self_test()

    inp = load_inputs()
    problems = provenance_problems(inp)
    if problems and not args.allow_unverified:
        print("Refusing to export a real-data bundle. These inputs are stand-ins, not observations:")
        for p in problems:
            print(f"  - {p}")
        print("Fix them, or use --allow-unverified for a local test bundle.")
        return 1
    data_kind = "mock" if problems else "nisar"
    out = args.out or (TEST_BUNDLE if problems else PUBLIC_BUNDLE)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    files = build_bundle(inp, data_kind, generated_at)
    write_bundle(files, out)
    print(f"[SAVED] {len(files)} files to {out} (data_kind={data_kind})")
    for p in problems:
        print(f"[WARN] unverified: {p}")
    check_with_app_loader(out)
    return 0


# ---------- self-test: a tiny landscape through the whole export, then the app's loader ----------

def _fake_inputs(tmp: Path) -> dict:
    """3 cells, 5 passes on the 12-day calendar; the 3rd pass has no radar data (like the Aug 2026 gap)."""
    dates = ["2026-07-04", "2026-07-16", "2026-07-28", "2026-08-09", "2026-08-21"]
    kept = ["2026-07-04", "2026-07-16", "2026-08-09", "2026-08-21"]
    img_dir = tmp / "images"
    img_dir.mkdir(parents=True)
    png = b"\x89PNG\r\n\x1a\n"  # the loader does not decode images
    for d in kept:
        (img_dir / f"radar_{d}.png").write_bytes(png)
    (img_dir / "smoke_reveal.png").write_bytes(png)

    cls = ["drained", "rewetted", "intact_forest"]
    feats = [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[114.0 + c * 0.005, -2.0], [114.005 + c * 0.005, -2.0],
                                                          [114.005 + c * 0.005, -2.005], [114.0 + c * 0.005, -2.005], [114.0 + c * 0.005, -2.0]]]},
        "properties": {"id": f"r000c{c:03d}", "row": 0, "col": c, "class": cls[c], "class_id": cls[c],
                       "canal_density_km_per_km2": [3.0, 1.0, 0.0][c], "tree_cover_pct": 20.0, "n_pixels": 625,
                       "centroid": [114.0025 + c * 0.005, -2.0025], "extra_field": "dropped by the export"},
    } for c in range(3)]
    hh = {"r000c000": [0, -12, None, -25, -31], "r000c001": [0, -4, None, -8, -9], "r000c002": [0, -1, None, -2, -1]}
    stats_rows = [(cid, d, v[t], v[t] and v[t] // 3) for cid, v in hh.items() for t, d in enumerate(dates) if d in kept]
    st = {"r000c000": [8, 7, 1, 3, 4], "r000c001": [8, 8, 1, 7, 7], "r000c002": [8, 8, 1, 8, 8]}
    # Land model: the radar can't tell cell 1 (""), and confidently calls the map's forest cell 2 plantation.
    pd.DataFrame({
        "cell_id": list(hh), "label_map": ["degraded", "degraded", "forest"], "cover_set": ["degraded", "", "plantation"],
        "set_size": [1, 0, 1], "map_check": [0, 0, 1], "class_map": cls, "class_model": ["drained", "rewetted", "plantation"],
    }).to_csv(tmp / "landclass.csv", index=False)
    lift = [{"quintile": 1, "n": 2, "fires": 1, "rate": 0.5}, {"quintile": 2, "n": 3, "fires": 1, "rate": 0.3333}]
    return {
        "cube_attrs": {"epsg": 32749, "data_source": "asf_live_stream"},
        "landclass_report": {"version": LANDCLASS_VERSION, "status": "used", "reasons": [], "confidence_level": 0.9,
                             "metrics": {"check_coverage": {"value": 0.9123, "n": 2}, "n_map_check": 1, "n_cells": 3}},
        "landclass": _landclass_csv(tmp / "landclass.csv"),
        "fire_report": {"status": "passed", "test_dates": ["2026-08-09", "2026-08-21"], "n_test_fires": 5,
                        "model": {"pr_auc": 0.31, "pr_auc_ci": [0.2, 0.42], "top10_capture": 0.4, "brier": 0.1},
                        "baselines": {k: {"pr_auc": v, "pr_auc_ci": [0.05, 0.2], "top10_capture": c}
                                      for k, v, c in (("B1", 0.05, 0.1), ("B2", 0.12, 0.2), ("B3", 0.15, 0.3))},
                        "best_baseline": {"id": "B3", "pr_auc": 0.15}, "lift": lift},
        "config": {"study_box": [114.0, -2.01, 114.02, -2.0], "cell_size_m": 500, "rain_return_mm": 50},
        "quality": {"kept_dates": kept, "dropped_dates": [],
                    "image_bounds": [[114.0, -2.0], [114.02, -2.0], [114.02, -2.01], [114.0, -2.01]],
                    "radar_images": [{"date": d, "file": f"images/radar_{d}.png"} for d in kept],
                    "dates_summary": [{"date": d, "status": "ok"} for d in kept]},
        "scenes": {"selected_geometry": {"track": "126", "frame": "001", "flightDirection": "A"},
                   "selected_scenes": [{"date": d, "scene_name": f"NISAR_TEST_{d}", "version": "P05023_001"} for d in kept]},
        "noise": {"dates": kept, "thresholds": {"sigma_db": [None, 0.12, 0.11, 0.12], "change_k": 2.0, "headline_k": 3.0, "deep_k": 4.0}},
        "context": {"dates": dates, "rain_3day_mm": [1.0, 0.0, None, 3.0, 2.0], "rain_interval_mm": [10.0, 4.0, 0.0, 60.0],
                    "fires_region": [0, 0, 2, 5], "rain_source": "test rain", "fire_source": "test fires"},
        "coherence_report": {"proxy_used": False, "per_interval": []},
        "provenance": {"canal_source": "osm_overpass", "class_source": LANDCLASS_VERSION, "tree_cover_source": "test"},
        "visuals": {"reveal_date": "2026-08-21", "optical_file": "images/smoke_reveal.png", "source": "VIIRS test"},
        "cells_fc": {"type": "FeatureCollection", "features": feats},
        "context_fc": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[114.0, -2.0], [114.02, -2.0]]},
             "properties": {"kind": "canal", "name_en": None, "name_id": None}}]},
        "stats": pd.DataFrame(stats_rows, columns=["cell_id", "date", "hh_tenths", "hv_tenths"]).astype({"hh_tenths": "Int64", "hv_tenths": "Int64"}),
        # Only real 12-day pairs; the 07-16 -> 08-09 pair spans the gap and must not land anywhere.
        "coherence": pd.DataFrame([("r000c000", "2026-07-04", "2026-07-16", 55), ("r000c000", "2026-07-16", "2026-08-09", 30),
                                   ("r000c000", "2026-08-09", "2026-08-21", 12)], columns=["cell_id", "date_start", "date_end", "coh"]).astype({"coh": "Int64"}),
        "fires": pd.DataFrame({"cell_id": list(hh), "fires_int_0": [0, 0, 0], "fires_int_1": [0, 0, 0],
                               "fires_int_2": [2, 0, 0], "fires_int_3": [3, 0, 0]}),
        "states": pd.DataFrame([(cid, d, v[t]) for cid, v in st.items() for t, d in enumerate(dates)], columns=["cell_id", "date", "state"]),
        "images_dir": img_dir,
    }


def run_self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        inp = _fake_inputs(tmp / "in")
        assert provenance_problems(inp) == []
        files = build_bundle(inp, "nisar", "2026-11-14T00:00:00Z")
        assert all(b"NaN" not in b for k, b in files.items() if not k.endswith(".png"))
        m = json.loads(files["manifest.json"])
        s = json.loads(files["series.json"])
        sc = json.loads(files["scorecard.json"])
        cp = [f["properties"] for f in json.loads(files["cells.geojson"])["features"]]
        assert m["schema_version"] == "0.2"
        assert m["dates"][2] == "2026-07-28" and m["dropped_dates"][0]["date"] == "2026-07-28", m["dropped_dates"]
        assert "NISAR instrument data gap" in m["dropped_dates"][0]["reason_en"]
        assert m["thresholds"]["sigma_db"] == [None, 0.12, None, 0.11, 0.12]
        assert [r["date"] for r in m["images"]["radar"]] == ["2026-07-04", "2026-07-16", "2026-08-09", "2026-08-21"]
        assert s["hh"][0] == [0, -12, None, -25, -31] and s["coh"][0] == [55, None, None, 12], s["coh"][0]
        assert "extra_field" not in cp[0]

        # Land model used: model classes, parsed sets, map_check only on the flagged cell, and the scorecard follows them.
        assert [p["class"] for p in cp] == ["drained", "rewetted", "plantation"]
        assert [p["cover_set"] for p in cp] == [["degraded"], [], ["plantation"]]
        assert [p.get("map_check") for p in cp] == [None, None, "forest"]
        assert m["land_model"] == {"status": "used", "version": LANDCLASS_VERSION, "confidence_level": 0.9,
                                   "reason_en": None, "reason_id": None}, m["land_model"]
        assert [t["id"] for t in sc["tests"]] == ["canal_vs_drying", "rewetted_vs_drained", "drying_before_fire",
                                                  "land_model_coverage", "map_out_of_date", "fire_risk_capture"]
        t = {t["id"]: t for t in sc["tests"]}
        assert (t["land_model_coverage"]["value"], t["land_model_coverage"]["n"]) == (0.9123, 2)
        assert (t["map_out_of_date"]["value"], t["map_out_of_date"]["n"]) == (0.333, 3)
        assert t["fire_risk_capture"]["value"] == 0.4 and t["fire_risk_capture"]["n"] == 5
        assert "best simple rule B3: 0.3" in t["fire_risk_capture"]["statistic"]
        assert sc["fire_risk"] == {"status": "passed", "test_dates": ["2026-08-09", "2026-08-21"], "model_pr_auc": 0.31,
                                   "model_pr_auc_ci": [0.2, 0.42], "best_baseline": {"id": "B3", "pr_auc": 0.15},
                                   "lift": [{"quintile": 1, "n": 2, "fires": 1, "rate": 0.5},
                                            {"quintile": 2, "n": 3, "fires": 1, "rate": 0.333}]}, sc["fire_risk"]
        words = json.dumps([m, sc]).lower()
        assert "probability" not in words and "predicts fire" not in words
        assert words.count("forecast") == words.count("not a forecast"), "forecast only in its negation"

        # Land model not used: the maps' classes, no sets; the four original tests; fire not_passed / not_run.
        lr_bad = dict(inp["landclass_report"], status="not_used", reasons=["check coverage 0.8 is below 0.87 (n=2 check cells)"])
        for fr in (dict(inp["fire_report"], status="not_passed"),
                   dict(inp["fire_report"], status="not_run", model=None, baselines=None, best_baseline=None)):
            f2 = build_bundle(dict(inp, landclass_report=lr_bad, fire_report=fr), "nisar", "2026-11-14T00:00:00Z")
            m2, sc2 = json.loads(f2["manifest.json"]), json.loads(f2["scorecard.json"])
            cp2 = [f["properties"] for f in json.loads(f2["cells.geojson"])["features"]]
            assert [p["class"] for p in cp2] == ["drained", "rewetted", "intact_forest"]
            assert not any("cover_set" in p or "map_check" in p for p in cp2)
            assert m2["land_model"]["status"] == "not_used" and "check coverage 0.8 is below 0.87" in m2["land_model"]["reason_en"]
            assert "check coverage 0.8 is below 0.87" in m2["land_model"]["reason_id"]
            assert [t["id"] for t in sc2["tests"]] == ["canal_vs_drying", "rewetted_vs_drained", "drying_before_fire", "forest_flat"]
            assert sc2["rankings"]["fastest_drying"][0] == {"cell": "r000c000", "class": "drained", "min_hh_db": -3.1, "date_of_min": "2026-08-21"}
            assert sc2["fire_risk"]["status"] == fr["status"] and len(sc2["fire_risk"]["lift"]) == 2
        assert sc2["fire_risk"]["model_pr_auc"] is None and sc2["fire_risk"]["best_baseline"] is None

        # Guards: synthetic inputs are named, and a NaN can never be written.
        bad = dict(inp, provenance={"canal_source": "synthetic_fallback"}, coherence_report={"proxy_used": True}, cube_attrs={})
        assert len(provenance_problems(bad)) == 6, provenance_problems(bad)
        assert any("not marked as streamed from ASF" in p for p in provenance_problems(bad))
        model_not_used = dict(inp, landclass_report=lr_bad)
        assert len(provenance_problems(model_not_used)) == 1 and LANDCLASS_VERSION in provenance_problems(model_not_used)[0]
        map_source = dict(inp, provenance=dict(inp["provenance"], class_source="esa_worldcover_2021_v200_and_gfw_peat_concessions"))
        assert len(provenance_problems(map_source)) == 1 and "says the model is used" in provenance_problems(map_source)[0]
        try:
            build_scorecard([{"id": "r000c000", "class": "intact_forest", "canal_density_km_per_km2": 0}], [[0, -1]], [[8, 8]], ["a", "b"])
            raise AssertionError("scorecard without drained cells must fail")
        except ValueError:
            pass

        out = tmp / "out"
        write_bundle(files, out)
        check_with_app_loader(out)
    print("08_export self-test: passed (calendar gap, nulls, scorecard, land model, fire risk, guards, app loader)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
