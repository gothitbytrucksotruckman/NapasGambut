import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def load_pipeline_data(base_dir=None):
    if base_dir is None:
        base_dir = DATA_DIR

    df_fires = pd.read_parquet(base_dir / "fires.parquet")
    with open(base_dir / "context_summary.json", "r", encoding="utf-8") as f:
        context_summary = json.load(f)

    df_grid_cells = pd.read_parquet(base_dir / "grid_cells.parquet")
    df_cell_stats = pd.read_parquet(base_dir / "cell_stats.parquet")

    with open(base_dir / "noise_floor.json", "r", encoding="utf-8") as f:
        noise_floor = json.load(f)

    df_coherence = pd.read_parquet(base_dir / "coherence.parquet")

    return {
        "df_fires": df_fires,
        "context_summary": context_summary,
        "df_grid_cells": df_grid_cells,
        "df_cell_stats": df_cell_stats,
        "noise_floor": noise_floor,
        "df_coherence": df_coherence,
    }


def classify_states(
    df_cell_stats, df_grid_cells, df_fires, df_coherence, context_summary, noise_floor,
    rain_return_mm=50.0, out_path=DATA_DIR / "states.parquet",
):
    """State per cell and date, build brief 6.6 (first match wins). Same rules as scripts/mock/states.ts.

    Fire counts "since the last valid pass", so a fire during a dropped pass (the 27 Jul - 10 Aug 2026
    NISAR gap) is not lost. Thresholds come from noise_floor.json; a missing sigma on a valid date is an error.
    """
    cell_order = df_grid_cells["cell_id"].tolist()
    cell_map = {cid: idx for idx, cid in enumerate(cell_order)}
    n_cells = len(cell_order)

    dates = context_summary["dates"]
    n_dates = len(dates)
    date_map = {d: idx for idx, d in enumerate(dates)}

    th = noise_floor["thresholds"]
    # context_summary dates are the full 12-day calendar; noise_floor only has the dates with radar data.
    sigma_by_date = dict(zip(noise_floor["dates"], th["sigma_db"]))
    sigma_list = [sigma_by_date.get(d) for d in dates]
    change_k, deep_k = float(th["change_k"]), float(th["deep_k"])
    rain_list = context_summary.get("rain_interval_mm", [])
    if len(rain_list) != n_dates - 1:
        raise ValueError(f"rain_interval_mm has {len(rain_list)} entries, expected {n_dates - 1}")

    d_hh_mat = np.full((n_cells, n_dates), np.nan, dtype=np.float64)
    d_hv_mat = np.full((n_cells, n_dates), np.nan, dtype=np.float64)
    valid_mat = np.ones((n_cells, n_dates), dtype=bool)

    c_idx = df_cell_stats["cell_id"].map(cell_map).values
    d_idx = df_cell_stats["date"].map(date_map).values

    d_hh_mat[c_idx, d_idx] = df_cell_stats["D_hh"].values
    d_hv_mat[c_idx, d_idx] = df_cell_stats["D_hv"].values
    valid_mat[c_idx, d_idx] = (df_cell_stats["valid_fraction"].values >= 0.5) & (
        ~df_cell_stats["is_dropped_date"].values
    )

    fire_cols = [f"fires_int_{k}" for k in range(n_dates - 1)]
    if [c for c in fire_cols if c not in df_fires.columns] or f"fires_int_{n_dates - 1}" in df_fires.columns:
        raise ValueError("fires.parquet intervals do not match context_summary dates; re-run 06_context_tabular.py")
    fire_mat = np.zeros((n_cells, n_dates - 1), dtype=np.int32)
    f_cidx = df_fires["cell_id"].map(cell_map).values
    for k, col in enumerate(fire_cols):
        fire_mat[f_cidx, k] = df_fires[col].values

    # Coherence on the 0..100 scale (column "coh"), matched by its two dates; null where no real GUNW pair
    # exists, including any pair that spans a missing pass.
    coh_mat = np.full((n_cells, n_dates - 1), np.nan, dtype=np.float64)
    pair_k = {(dates[k], dates[k + 1]): k for k in range(n_dates - 1)}
    coh_kidx = np.array([pair_k.get(p, -1) for p in zip(df_coherence["date_start"], df_coherence["date_end"])], dtype=np.int64)
    on_cal = coh_kidx >= 0
    coh_cidx = df_coherence["cell_id"].map(cell_map).values
    coh_vals = df_coherence["coh"].astype("Float64").to_numpy(dtype=np.float64, na_value=np.nan)
    coh_mat[coh_cidx[on_cal], coh_kidx[on_cal]] = coh_vals[on_cal]

    states_mat = np.ones((n_cells, n_dates), dtype=np.int32)
    burned_before = np.zeros(n_cells, dtype=bool)
    min_d_hh = np.full(n_cells, np.inf, dtype=np.float64)
    last_hv = np.full(n_cells, np.nan, dtype=np.float64)
    fires_since = np.zeros(n_cells, dtype=np.int64)
    rain_returned = False

    for t in range(n_dates):
        if t > 0:
            if (rain_list[t - 1] or 0.0) >= rain_return_mm:
                rain_returned = True
            fires_since += fire_mat[:, t - 1]
        d_hh = d_hh_mat[:, t]
        d_hv = d_hv_mat[:, t]
        ok = valid_mat[:, t] & np.isfinite(d_hh)  # rule 1 for everything else

        if t == 0:
            states_mat[ok, 0] = 8
        elif ok.any():
            sigma_t = sigma_list[t]
            if sigma_t is None:
                raise ValueError(f"sigma_db is null at valid date {dates[t]}")
            with np.errstate(invalid="ignore"):
                fire = fires_since > 0
                hv_fell = np.isfinite(d_hv) & np.isfinite(last_hv) & (last_hv - d_hv > change_k * sigma_t)
                coh_low = np.isfinite(coh_mat[:, t - 1]) & (coh_mat[:, t - 1] < 20)
                rewet = rain_returned & (d_hh - min_d_hh > change_k * sigma_t)
                s = np.select(
                    [fire & (hv_fell | coh_low), fire, burned_before, rewet, d_hh < -deep_k * sigma_t, d_hh < -change_k * sigma_t],
                    [2, 3, 4, 5, 6, 7],
                    8,
                )
            states_mat[ok, t] = s[ok]
            burned_before |= ok & ((s == 2) | (s == 3))

        min_d_hh[ok] = np.minimum(min_d_hh[ok], d_hh[ok])
        hv_ok = ok & np.isfinite(d_hv)
        last_hv[hv_ok] = d_hv[hv_ok]
        fires_since[ok] = 0

    records = []
    for c_i, cid in enumerate(cell_order):
        for t_i, d_str in enumerate(dates):
            records.append((cid, d_str, int(states_mat[c_i, t_i])))

    df_states = pd.DataFrame(records, columns=["cell_id", "date", "state"])
    if out_path is not None:
        df_states.to_parquet(out_path, index=False)

    return df_states


def run_self_test():
    """Hand-built cells mirroring tests/mock/states.test.ts. 5 dates, sigma 0.5 dB, k 2/4, rain return 50 mm."""
    dates = ["d0", "d1", "d2", "d3", "d4"]

    def run(D=None, hv=None, coh=None, fires=None, dropped=None, rain=None, valid_fraction=1.0):
        D = D or [0, 0, 0, 0, 0]
        hv = hv or [0, 0, 0, 0, 0]
        coh = coh or [50, 50, 50, 50]
        fires = fires or [0, 0, 0, 0]
        dropped = dropped or [False] * 5
        rain = rain or [5, 5, 5, 5]
        stats_df = pd.DataFrame({
            "cell_id": ["c"] * 5, "date": dates,
            "D_hh": [np.nan if v is None else v for v in D], "D_hv": [np.nan if v is None else v for v in hv],
            "valid_fraction": [valid_fraction] * 5, "is_dropped_date": dropped,
        })
        fires_df = pd.DataFrame({"cell_id": ["c"], **{f"fires_int_{k}": [fires[k]] for k in range(4)}})
        coh_df = pd.DataFrame({
            "cell_id": ["c"] * 4, "date_start": dates[:-1], "date_end": dates[1:], "coh": pd.array(coh, dtype="Int64"),
        })
        kept = [d for d, x in zip(dates, dropped) if not x]
        sig = dict(zip(dates, [None, 0.5, 0.5, 0.5, 0.5]))
        noise = {"dates": kept, "thresholds": {"sigma_db": [sig[d] for d in kept], "change_k": 2, "deep_k": 4}}
        ctx = {"dates": dates, "rain_interval_mm": rain}
        out = classify_states(stats_df, pd.DataFrame({"cell_id": ["c"]}), fires_df, coh_df, ctx, noise, 50.0, out_path=None)
        return out["state"].tolist()

    cases = [
        ("all stable", run(), [8, 8, 8, 8, 8]),
        ("rule 1 dropped date", run(D=[0, 0, None, 0, 0], dropped=[False, False, True, False, False])[2], 1),
        ("rule 1 few pixels", run(valid_fraction=0.4), [1, 1, 1, 1, 1]),
        ("rule 2 HV drop", run(fires=[0, 3, 0, 0], hv=[0, 0, -1.2, -1.2, -1.2])[2], 2),
        ("rule 2 low coherence", run(fires=[0, 3, 0, 0], coh=[50, 15, 50, 50])[2], 2),
        ("rule 3 silent", run(fires=[0, 3, 0, 0])[2], 3),
        ("rule 4 burned after", run(fires=[0, 3, 0, 0])[3:], [4, 4]),
        ("fire beats deep drying", run(fires=[0, 3, 0, 0], D=[0, -1, -3, -3, -3])[2], 3),
        ("rule 5 rewetting", run(D=[0, -2.5, -2.5, -1.2, -1.2], rain=[5, 5, 60, 5])[3], 5),
        ("rule 5 not before rain", run(D=[0, -2.5, -2.5, -1.2, -1.2])[3], 7),
        ("rule 6 deep", run(D=[0, -2.5, 0, 0, 0])[1], 6),
        ("rule 7 drying", run(D=[0, -1.2, 0, 0, 0])[1], 7),
        ("null coherence is not low", run(fires=[0, 3, 0, 0], coh=[50, None, 50, 50])[2], 3),
        ("fire during a dropped pass counts next", run(D=[0, 0, None, 0, 0], dropped=[False, False, True, False, False], fires=[0, 3, 0, 0]), [8, 8, 1, 3, 4]),
    ]
    failed = [(name, got, want) for name, got, want in cases if got != want]
    for name, got, want in failed:
        print(f"[FAIL] {name}: got {got}, want {want}")
    print(f"07_states self-test: {len(cases) - len(failed)}/{len(cases)} passed")
    return 1 if failed else 0


def run_statistical_tests(df_cell_stats, df_grid_cells, df_fires):
    idx_min = df_cell_stats.groupby("cell_id")["D_hh"].idxmin()
    min_dates = df_cell_stats.loc[idx_min, ["cell_id", "date", "D_hh"]].rename(
        columns={"D_hh": "min_D_hh", "date": "date_of_min"}
    )
    merged = df_grid_cells.merge(min_dates, on="cell_id", how="left")

    non_forest = merged[merged["class"].isin(["drained", "plantation", "rewetted"])].dropna(
        subset=["canal_density", "min_D_hh"]
    )
    test1 = stats.spearmanr(non_forest["canal_density"], non_forest["min_D_hh"])

    rewetted_min = merged[merged["class"] == "rewetted"]["min_D_hh"].dropna()
    drained_min = merged[merged["class"] == "drained"]["min_D_hh"].dropna()
    test2 = stats.mannwhitneyu(rewetted_min, drained_min, alternative="two-sided")

    burned_pre_vals = []
    unburned_pre_vals = []
    dates = sorted(df_cell_stats["date"].unique())

    for k in range(len(dates) - 1):
        f_col = f"fires_int_{k}"
        if f_col not in df_fires.columns:
            continue
        burned_ids = set(df_fires[df_fires[f_col] > 0]["cell_id"])
        if not burned_ids:
            continue

        date_k = dates[k]
        sub = df_cell_stats[df_cell_stats["date"] == date_k]
        b_dhh = sub[sub["cell_id"].isin(burned_ids)]["D_hh"].dropna().tolist()
        ub_dhh = sub[~sub["cell_id"].isin(burned_ids)]["D_hh"].dropna().tolist()
        burned_pre_vals.extend(b_dhh)
        unburned_pre_vals.extend(ub_dhh)

    test3 = stats.mannwhitneyu(burned_pre_vals, unburned_pre_vals, alternative="two-sided")

    forest_drift = (
        df_cell_stats[df_cell_stats["class"].isin(["intact_forest", "reference_forest"])]["raw_delta_hh"]
        .dropna()
        .abs()
    )
    open_drift = (
        df_cell_stats[df_cell_stats["class"].isin(["drained", "plantation", "rewetted"])]["raw_delta_hh"]
        .dropna()
        .abs()
    )
    test4 = stats.mannwhitneyu(forest_drift, open_drift, alternative="two-sided")

    test_results = {
        "test1_canal_correlation": {
            "name": "Spearman canal density vs min D_hh",
            "statistic": float(test1.statistic),
            "p_value": float(test1.pvalue),
            "n": int(len(non_forest)),
        },
        "test2_rewetted_vs_drained": {
            "name": "Mann-Whitney U rewetted vs drained min D_hh",
            "statistic": float(test2.statistic),
            "p_value": float(test2.pvalue),
            "n": int(len(rewetted_min) + len(drained_min)),
            "rewetted_median_db": float(rewetted_min.median()),
            "drained_median_db": float(drained_min.median()),
        },
        "test3_pre_fire_drying": {
            "name": "Mann-Whitney U pre-fire D_hh (burned vs unburned)",
            "statistic": float(test3.statistic),
            "p_value": float(test3.pvalue),
            "n": int(len(burned_pre_vals) + len(unburned_pre_vals)),
            "burned_pre_median_db": float(pd.Series(burned_pre_vals).median()),
            "unburned_pre_median_db": float(pd.Series(unburned_pre_vals).median()),
        },
        "test4_forest_vs_open_drift": {
            "name": "Mann-Whitney U raw dB drift (forest vs open peat)",
            "statistic": float(test4.statistic),
            "p_value": float(test4.pvalue),
            "n": int(len(forest_drift) + len(open_drift)),
            "forest_mean_abs_drift_db": float(forest_drift.mean()),
            "open_mean_abs_drift_db": float(open_drift.mean()),
        },
    }

    return test_results, merged


def to_native_types(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating, float)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return [to_native_types(x) for x in obj.tolist()]
    elif isinstance(obj, dict):
        return {str(k): to_native_types(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return [to_native_types(x) for x in obj]
    elif pd.isna(obj):
        return None
    return obj


def generate_scorecard(df_states, merged_cells, test_results):
    burned_cells = set(df_states[df_states["state"].isin([2, 3, 4])]["cell_id"].unique())
    merged_cells["is_burned"] = merged_cells["cell_id"].isin(burned_cells)

    dates = sorted(df_states["date"].unique())
    date_to_idx = {d: i for i, d in enumerate(dates)}
    df_states_t = df_states.copy()
    df_states_t["t"] = df_states_t["date"].map(date_to_idx)
    pivot_states = df_states_t.pivot(index="cell_id", columns="t", values="state")

    recovery_passes = {}
    for cid, row in pivot_states.iterrows():
        vals = row.values
        first_fire = None
        for t, s in enumerate(vals):
            if s in (2, 3) and first_fire is None:
                first_fire = t
            elif first_fire is not None and s == 5:
                recovery_passes[cid] = t - first_fire
                break

    classes = ["drained", "rewetted", "plantation", "intact_forest", "reference_forest", "settlement"]
    by_class = []
    for c in classes:
        sub = merged_cells[merged_cells["class"] == c]
        if sub.empty:
            continue
        vals = sub["min_D_hh"].dropna()
        passes = sub["cell_id"].map(recovery_passes).dropna()
        by_class.append({
            "class": c,
            "n_cells": int(len(sub)),
            "median_min_hh_db": round(float(vals.median()), 4) if len(vals) > 0 else 0.0,
            "p25_min_hh_db": round(float(vals.quantile(0.25)), 4) if len(vals) > 0 else 0.0,
            "p75_min_hh_db": round(float(vals.quantile(0.75)), 4) if len(vals) > 0 else 0.0,
            "share_burned": round(float(sub["is_burned"].mean()), 4),
            "median_passes_to_recovery": round(float(passes.median()), 1) if len(passes) > 0 else None,
        })

    # Top 20 cells for canal blocking (deepest drying and high canal density)
    drained_cells = merged_cells[merged_cells["class"] == "drained"].copy()
    drained_cells["canal_density"] = drained_cells["canal_density"].fillna(0.0)
    drained_cells["block_priority_score"] = drained_cells["canal_density"] * drained_cells["min_D_hh"].abs()
    top_canals_df = drained_cells.sort_values(
        by=["block_priority_score", "min_D_hh"], ascending=[False, True]
    ).head(20)

    top_20_canals = [
        {
            "cell": str(r["cell_id"]),
            "class": str(r["class"]),
            "min_hh_db": round(float(r["min_D_hh"]), 3),
            "date_of_min": str(r["date_of_min"]),
            "canal_density_km_per_km2": round(float(r["canal_density"]), 2),
            "priority_score": round(float(r["block_priority_score"]), 3),
        }
        for _, r in top_canals_df.iterrows()
    ]

    # Top 20 dams/rewetted areas for inspection (rewetted cells with deepest anomaly below drained median)
    rewetted_cells = merged_cells[merged_cells["class"] == "rewetted"].copy()
    rewetted_cells["canal_density"] = rewetted_cells["canal_density"].fillna(0.0)
    drained_median = test_results["test2_rewetted_vs_drained"]["drained_median_db"]
    rewetted_cells["gap_vs_drained_median_db"] = drained_median - rewetted_cells["min_D_hh"]
    top_dams_df = rewetted_cells.sort_values(by="min_D_hh", ascending=True).head(20)

    top_20_dams = [
        {
            "cell": str(r["cell_id"]),
            "class": str(r["class"]),
            "min_hh_db": round(float(r["min_D_hh"]), 3),
            "gap_vs_drained_median_db": round(float(r["gap_vs_drained_median_db"]), 3),
            "canal_density_km_per_km2": round(float(r["canal_density"]), 2),
        }
        for _, r in top_dams_df.iterrows()
    ]

    # Fastest drying (all drained or plantation cells, lowest minimum first)
    dp_cells = merged_cells[merged_cells["class"].isin(["drained", "plantation"])].copy()
    fastest_drying_df = dp_cells.sort_values(by="min_D_hh", ascending=True).head(20)
    fastest_drying = [
        {
            "cell": str(r["cell_id"]),
            "class": str(r["class"]),
            "min_hh_db": round(float(r["min_D_hh"]), 3),
            "date_of_min": str(r["date_of_min"]),
        }
        for _, r in fastest_drying_df.iterrows()
    ]

    dams_to_inspect = [
        {
            "cell": str(r["cell_id"]),
            "min_hh_db": round(float(r["min_D_hh"]), 3),
            "gap_vs_drained_median_db": round(float(r["gap_vs_drained_median_db"]), 3),
        }
        for _, r in top_dams_df.iterrows()
    ]

    tests_list = [
        {
            "id": "test1_canal_correlation",
            "name_en": "Canal density vs peat subsidence drying",
            "name_id": "Kerapatan kanal vs penurunan kelembapan gambut",
            "statistic": "Spearman rank correlation",
            "value": round(float(test_results["test1_canal_correlation"]["statistic"]), 4),
            "n": int(test_results["test1_canal_correlation"]["n"]),
            "note_en": f"Spearman r = {test_results['test1_canal_correlation']['statistic']:.4f}, p = {test_results['test1_canal_correlation']['p_value']:.4f}",
            "note_id": f"Spearman r = {test_results['test1_canal_correlation']['statistic']:.4f}, p = {test_results['test1_canal_correlation']['p_value']:.4f}",
        },
        {
            "id": "test2_rewetted_vs_drained",
            "name_en": "Rewetted vs drained peat drying depth",
            "name_id": "Kedalaman pengeringan gambut basah kembali vs terdrainase",
            "statistic": "Mann-Whitney U",
            "value": round(float(test_results["test2_rewetted_vs_drained"]["statistic"]), 4),
            "n": int(test_results["test2_rewetted_vs_drained"]["n"]),
            "note_en": f"U = {test_results['test2_rewetted_vs_drained']['statistic']:.0f}, p = {test_results['test2_rewetted_vs_drained']['p_value']:.4e}",
            "note_id": f"U = {test_results['test2_rewetted_vs_drained']['statistic']:.0f}, p = {test_results['test2_rewetted_vs_drained']['p_value']:.4e}",
        },
        {
            "id": "test3_pre_fire_drying",
            "name_en": "Pre-fire moisture deficit (burned vs unburned)",
            "name_id": "Defisit kelembapan pra-kebakaran (terbakar vs tidak terbakar)",
            "statistic": "Mann-Whitney U",
            "value": round(float(test_results["test3_pre_fire_drying"]["statistic"]), 4),
            "n": int(test_results["test3_pre_fire_drying"]["n"]),
            "note_en": f"U = {test_results['test3_pre_fire_drying']['statistic']:.0f}, p = {test_results['test3_pre_fire_drying']['p_value']:.4e}",
            "note_id": f"U = {test_results['test3_pre_fire_drying']['statistic']:.0f}, p = {test_results['test3_pre_fire_drying']['p_value']:.4e}",
        },
        {
            "id": "test4_forest_vs_open_drift",
            "name_en": "Forest reference radar drift vs open peat",
            "name_id": "Drift radar hutan referensi vs gambut terbuka",
            "statistic": "Mann-Whitney U",
            "value": round(float(test_results["test4_forest_vs_open_drift"]["statistic"]), 4),
            "n": int(test_results["test4_forest_vs_open_drift"]["n"]),
            "note_en": f"U = {test_results['test4_forest_vs_open_drift']['statistic']:.0f}, p = {test_results['test4_forest_vs_open_drift']['p_value']:.4e}",
            "note_id": f"U = {test_results['test4_forest_vs_open_drift']['statistic']:.0f}, p = {test_results['test4_forest_vs_open_drift']['p_value']:.4e}",
        },
    ]

    scorecard_payload = {
        "by_class": by_class,
        "rankings": {
            "fastest_drying": fastest_drying,
            "dams_to_inspect": dams_to_inspect,
            "top_20_canals_to_block": top_20_canals,
            "top_20_dams_to_inspect": top_20_dams,
        },
        "tests": tests_list,
        "statistical_tests": test_results,
        "recommendations": {
            "top_20_canals_to_block": top_20_canals,
            "top_20_dams_to_inspect": top_20_dams,
        },
    }

    clean_scorecard = to_native_types(scorecard_payload)

    with open(DATA_DIR / "scorecard.json", "w", encoding="utf-8") as f:
        json.dump(clean_scorecard, f, indent=2)

    with open(DATA_DIR / "scorecard_raw.json", "w", encoding="utf-8") as f:
        json.dump(clean_scorecard, f, indent=2)

    return clean_scorecard


def _rain_return_mm():
    """rain_return_mm from config.yaml (build brief: 50 mm)."""
    spec = importlib.util.spec_from_file_location("census_mod", Path(__file__).resolve().parent / "00_census.py")
    census = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(census)
    return float(census.load_config(PROJECT_ROOT / "config.yaml")["rain_return_mm"])


def main():
    if "--self-test" in sys.argv:
        sys.exit(run_self_test())

    data = load_pipeline_data()

    df_states = classify_states(
        data["df_cell_stats"],
        data["df_grid_cells"],
        data["df_fires"],
        data["df_coherence"],
        data["context_summary"],
        data["noise_floor"],
        rain_return_mm=_rain_return_mm(),
    )

    print("df['state'].value_counts():")
    print(df_states["state"].value_counts().sort_index())

    test_results, merged_cells = run_statistical_tests(
        data["df_cell_stats"],
        data["df_grid_cells"],
        data["df_fires"],
    )

    scorecard = generate_scorecard(df_states, merged_cells, test_results)

    print("\nTop 3 Cells for Canal Blocking:")
    for item in scorecard["rankings"]["top_20_canals_to_block"][:3]:
        print(f"  {item['cell']} (class: {item['class']}) -> min D_hh: {item['min_hh_db']} dB, canal density: {item['canal_density_km_per_km2']} km/km2, priority: {item['priority_score']}")

    print("\nTop 3 Dams / Rewetted Areas for Inspection:")
    for item in scorecard["rankings"]["top_20_dams_to_inspect"][:3]:
        print(f"  {item['cell']} (class: {item['class']}) -> min D_hh: {item['min_hh_db']} dB, gap vs drained median: +{item['gap_vs_drained_median_db']} dB")

    print("\nStatistical Test Results:")
    for key, res in test_results.items():
        print(f"  {res['name']} -> p-value: {res['p_value']:.4e} (stat: {res['statistic']:.4f}, n: {res['n']})")


if __name__ == "__main__":
    main()
