import json
import os
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


def classify_states(df_cell_stats, df_grid_cells, df_fires, df_coherence, context_summary, noise_floor):
    cell_order = df_grid_cells["cell_id"].tolist()
    cell_map = {cid: idx for idx, cid in enumerate(cell_order)}
    n_cells = len(cell_order)

    dates = context_summary["dates"]
    n_dates = len(dates)
    date_map = {d: idx for idx, d in enumerate(dates)}

    sigma_arr = np.array(
        [
            item.get("sigma_hh_db") or item.get("sigma_manifest_db") or item.get("mean_speckle_db") or 0.12
            for item in noise_floor.get("per_date", [])
        ],
        dtype=np.float64,
    )
    sigma_arr[sigma_arr == 0] = 0.12
    rain_arr = np.array(context_summary.get("rain_interval_mm", []), dtype=np.float64)

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

    fire_mat = np.zeros((n_cells, n_dates - 1), dtype=np.int32)
    for k in range(n_dates - 1):
        col = f"fires_int_{k}"
        if col in df_fires.columns:
            f_cidx = df_fires["cell_id"].map(cell_map).values
            fire_mat[f_cidx, k] = df_fires[col].values

    coh_mat = np.full((n_cells, n_dates - 1), np.nan, dtype=np.float64)
    coh_cidx = df_coherence["cell_id"].map(cell_map).values
    coh_kidx = df_coherence["interval_idx"].values
    coh_mat[coh_cidx, coh_kidx] = df_coherence["coh_mean"].values

    states_mat = np.zeros((n_cells, n_dates), dtype=np.int32)
    burned_before = np.zeros(n_cells, dtype=bool)
    min_d_hh = np.full(n_cells, np.inf, dtype=np.float64)

    for t in range(n_dates):
        sigma_t = sigma_arr[t]
        d_hh = d_hh_mat[:, t]
        d_hv = d_hv_mat[:, t]
        valid = valid_mat[:, t]

        if t == 0:
            states_mat[:, 0] = np.where(~valid, 1, 8)
            valid_mask = valid & ~np.isnan(d_hh)
            min_d_hh[valid_mask] = np.minimum(min_d_hh[valid_mask], d_hh[valid_mask])
        else:
            k = t - 1
            fires_k = fire_mat[:, k]
            coh_k = coh_mat[:, k]
            rain_k = rain_arr[k] if k < len(rain_arr) else 0.0

            s = np.zeros(n_cells, dtype=np.int32)

            cond1 = ~valid
            s[cond1] = 1

            cond2 = (~cond1) & (fires_k > 0) & ((d_hv < -2.0 * sigma_t) | (coh_k < 0.25))
            s[cond2] = 2
            burned_before[cond2] = True

            cond3 = (~cond1) & (~cond2) & (fires_k > 0)
            s[cond3] = 3
            burned_before[cond3] = True

            cond4 = (~cond1) & (~cond2) & (~cond3) & burned_before
            s[cond4] = 4

            cond5 = (~cond1) & (~cond2) & (~cond3) & (~cond4) & (d_hh - min_d_hh > 2.0 * sigma_t) & (rain_k > 5.0)
            s[cond5] = 5

            cond6 = (~cond1) & (~cond2) & (~cond3) & (~cond4) & (~cond5) & (d_hh < -4.0 * sigma_t)
            s[cond6] = 6

            cond7 = (~cond1) & (~cond2) & (~cond3) & (~cond4) & (~cond5) & (~cond6) & (d_hh < -2.0 * sigma_t)
            s[cond7] = 7

            cond8 = (~cond1) & (~cond2) & (~cond3) & (~cond4) & (~cond5) & (~cond6) & (~cond7)
            s[cond8] = 8

            states_mat[:, t] = s
            valid_mask = valid & ~np.isnan(d_hh)
            min_d_hh[valid_mask] = np.minimum(min_d_hh[valid_mask], d_hh[valid_mask])

    records = []
    for c_i, cid in enumerate(cell_order):
        for t_i, d_str in enumerate(dates):
            records.append((cid, d_str, int(states_mat[c_i, t_i])))

    df_states = pd.DataFrame(records, columns=["cell_id", "date", "state"])
    states_path = DATA_DIR / "states.parquet"
    df_states.to_parquet(states_path, index=False)

    return df_states


def run_statistical_tests(df_cell_stats, df_grid_cells, df_fires):
    min_d_hh_per_cell = (
        df_cell_stats.groupby("cell_id")["D_hh"].min().reset_index().rename(columns={"D_hh": "min_D_hh"})
    )
    merged = df_grid_cells.merge(min_d_hh_per_cell, on="cell_id", how="left")

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
        },
        "test2_rewetted_vs_drained": {
            "name": "Mann-Whitney U rewetted vs drained min D_hh",
            "statistic": float(test2.statistic),
            "p_value": float(test2.pvalue),
            "rewetted_median_db": float(rewetted_min.median()),
            "drained_median_db": float(drained_min.median()),
        },
        "test3_pre_fire_drying": {
            "name": "Mann-Whitney U pre-fire D_hh (burned vs unburned)",
            "statistic": float(test3.statistic),
            "p_value": float(test3.pvalue),
            "burned_pre_median_db": float(pd.Series(burned_pre_vals).median()),
            "unburned_pre_median_db": float(pd.Series(unburned_pre_vals).median()),
        },
        "test4_forest_vs_open_drift": {
            "name": "Mann-Whitney U raw dB drift (forest vs open peat)",
            "statistic": float(test4.statistic),
            "p_value": float(test4.pvalue),
            "forest_mean_abs_drift_db": float(forest_drift.mean()),
            "open_mean_abs_drift_db": float(open_drift.mean()),
        },
    }

    return test_results, merged


def generate_rankings(merged_cells, test_results):
    drained_cells = merged_cells[merged_cells["class"] == "drained"].copy()
    drained_cells["block_score"] = drained_cells["canal_density"] * drained_cells["min_D_hh"].abs()
    top_block_canals = (
        drained_cells.sort_values(by=["block_score", "min_D_hh"], ascending=[False, True])
        .head(20)[["cell_id", "canal_density", "min_D_hh", "class"]]
        .to_dict(orient="records")
    )

    rewetted_cells = merged_cells[merged_cells["class"] == "rewetted"].copy()
    drained_median = test_results["test2_rewetted_vs_drained"]["drained_median_db"]
    rewetted_cells["anomaly_depth"] = drained_median - rewetted_cells["min_D_hh"]
    top_dam_inspect = (
        rewetted_cells.sort_values(by="min_D_hh", ascending=True)
        .head(20)[["cell_id", "canal_density", "min_D_hh", "class"]]
        .to_dict(orient="records")
    )

    scorecard_raw = {
        "statistical_tests": test_results,
        "recommendations": {
            "top_20_canals_to_block": top_block_canals,
            "top_20_dams_to_inspect": top_dam_inspect,
        },
    }

    with open(DATA_DIR / "scorecard_raw.json", "w", encoding="utf-8") as f:
        json.dump(scorecard_raw, f, indent=2)

    return scorecard_raw


def main():
    data = load_pipeline_data()

    df_states = classify_states(
        data["df_cell_stats"],
        data["df_grid_cells"],
        data["df_fires"],
        data["df_coherence"],
        data["context_summary"],
        data["noise_floor"],
    )

    print("df['state'].value_counts():")
    print(df_states["state"].value_counts().sort_index())

    test_results, merged_cells = run_statistical_tests(
        data["df_cell_stats"],
        data["df_grid_cells"],
        data["df_fires"],
    )

    generate_rankings(merged_cells, test_results)

    print("\nStatistical Test Results:")
    for key, res in test_results.items():
        print(f"  {res['name']} -> p-value: {res['p_value']:.4e} (stat: {res['statistic']:.4f})")


if __name__ == "__main__":
    main()
