"""Scientific self-checks (C1) and multi-sensor cross-checks (C2-C4) for scorecard.json.

Exposes `compute_all_tests(config, data_dir)` returning a list of test entries
compatible with both the Data Contract v0.1/v0.2 ScorecardSchema (`id`, `name_en`,
`name_id`, `statistic`, `value`, `n`, `note_en`, `note_id`) and shorthand keys
(`name`, `note`).

Implements:
- C1 internal self-checks:
  * Check 3:  `reference_steady`
  * Check 4:  `split_half_null` (seed 42)
  * Check 8:  `fire_agreement`
  * Check 10: `size_sensitivity` (500 m vs fallback_cell_size_m=1000 m)
- C2-C4 multi-sensor cross-checks:
  * C2:       `soil_moisture_agrees` (NISAR provisional SME2)
  * C3 (Ch 7): `cband_same_direction` (Sentinel-1 C-band vs NISAR L-band)
  * C4:       `burned_matches_modis` (MODIS/061/MCD64A1 monthly burn dates)

Strict rule: any test whose required input file is absent, empty, or degenerate
is omitted cleanly. Never emit `0` or synthetic stand-in values for missing data.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SPLIT_HALF_SEED = 42
PEAT_CLASSES = ("drained", "rewetted", "plantation")
PRIMARY_REF_CLASSES = ("reference_forest", "dense_forest")


def _resolve_path(path: Path | str) -> Path:
    p = Path(path)
    if p.is_absolute() or p.exists():
        return p
    return PROJECT_ROOT / p


def _normalize_config(config: dict[str, Any] | Path | str | None) -> dict[str, Any]:
    """Normalize config argument whether passed as a dict, YAML path, or None."""
    cfg: dict[str, Any] = {
        "cell_size_m": 500,
        "fallback_cell_size_m": 1000,
        "min_valid_fraction": 0.5,
        "sigma_threshold": 2.0,
        "change_k": 2.0,
    }
    if isinstance(config, dict):
        cfg.update({k: v for k, v in config.items() if v is not None})
    elif config is not None:
        cfg_path = _resolve_path(config)
        if cfg_path.exists():
            try:
                import yaml

                raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                if isinstance(raw, dict):
                    cfg.update({k: v for k, v in raw.items() if v is not None})
            except ImportError:
                pass
    if "change_k" not in cfg or cfg["change_k"] is None:
        cfg["change_k"] = cfg.get("sigma_threshold", 2.0)
    return cfg


def _make_test_entry(
    *,
    test_id: str,
    name_en: str,
    name_id: str,
    statistic: str,
    value: float,
    n: int,
    note_en: str,
    note_id: str,
    decimals: int = 4,
) -> dict[str, Any] | None:
    """Validate finiteness and return bilingual + shorthand ScorecardSchema entry."""
    val = float(value)
    if not math.isfinite(val) or int(n) <= 0:
        return None
    rounded = round(val, decimals)
    return {
        "id": test_id,
        "name": name_en,
        "name_en": name_en,
        "name_id": name_id,
        "statistic": statistic,
        "value": rounded,
        "n": int(n),
        "note": note_en,
        "note_en": note_en,
        "note_id": note_id,
    }


def _compute_mad(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return float("nan")
    med = float(np.median(finite))
    return float(1.4826 * np.median(np.abs(finite - med)))


def _get_reference_mask(df: pd.DataFrame) -> pd.Series:
    if "is_reference" in df.columns:
        mask = df["is_reference"].fillna(False).astype(bool)
        if bool(mask.any()):
            return mask
    if "class" in df.columns:
        return df["class"].astype(str).isin(PRIMARY_REF_CLASSES)
    return pd.Series(False, index=df.index)


def _filter_kept_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "is_dropped_date" in out.columns:
        out = out[~out["is_dropped_date"].fillna(False).astype(bool)]
    return out


def _get_canal_density_col(df: pd.DataFrame) -> str | None:
    for col in ("canal_density_km_per_km2", "canal_density"):
        if col in df.columns:
            return col
    return None


# ---------------------------------------------------------------------------
# 1000 m Aggregation Builder for Check 10 (Size Sensitivity)
# ---------------------------------------------------------------------------


def build_1000m_cell_stats(
    config: dict[str, Any] | Path | str | None,
    data_dir: Path | str = "data",
) -> Path | None:
    """Block-average 500 m cell_stats into 1000 m cells in linear power first.

    Writes `data_dir / 'cell_stats_1000m.parquet'` so `size_sensitivity` (Check 10)
    runs cleanly on real GCOV observations.
    """
    cfg = _normalize_config(config)
    ddir = _resolve_path(data_dir)
    stats_path = ddir / "cell_stats.parquet"
    grid_path = ddir / "grid_cells.parquet"
    if not stats_path.exists() or not grid_path.exists():
        return None

    grid_cols = ["cell_id", "row", "col", "class"]
    grid_schema_df = pd.read_parquet(grid_path)
    density_col = _get_canal_density_col(grid_schema_df)
    if "row" not in grid_schema_df.columns or "col" not in grid_schema_df.columns:
        return None
    if density_col:
        grid_cols.append(density_col)

    grid_sub = grid_schema_df[grid_cols].drop_duplicates("cell_id").copy()
    base_cell_m = float(cfg.get("cell_size_m", 500))
    target_cell_m = float(cfg.get("fallback_cell_size_m", 1000))
    factor = max(2, int(round(target_cell_m / base_cell_m)))

    grid_sub["row_1000"] = grid_sub["row"].astype(np.int64) // factor
    grid_sub["col_1000"] = grid_sub["col"].astype(np.int64) // factor
    grid_sub["cell_id_1000"] = [
        f"r{int(r):03d}c{int(c):03d}"
        for r, c in zip(grid_sub["row_1000"], grid_sub["col_1000"])
    ]

    stats_df = pd.read_parquet(stats_path)
    need_cols = {"cell_id", "date", "gamma_bar_hh", "n_valid_pixels"}
    if not need_cols.issubset(stats_df.columns):
        return None

    merged = stats_df.merge(
        grid_sub[["cell_id", "cell_id_1000", "row_1000", "col_1000"] + ([density_col] if density_col else [])],
        on="cell_id",
        how="inner",
        suffixes=("", "_grid"),
    )
    if merged.empty:
        return None

    # Derive static class & canal density per 1000 m super-cell
    cell_meta_rows: list[dict[str, Any]] = []
    for cid1000, grp in merged.drop_duplicates("cell_id").groupby("cell_id_1000", sort=True):
        cls_counts = grp["class"].astype(str).value_counts()
        n_sub = len(grp)
        n_ref = int(cls_counts.get("reference_forest", 0) + cls_counts.get("dense_forest", 0))
        # Reference forest super-cell only if strict majority reference and zero peat disturbance
        has_disturbed = any(c in ("drained", "plantation", "settlement", "rewetted") for c in cls_counts.index)
        is_ref_1000 = bool(n_ref >= max(1, (n_sub + 1) // 2) and not has_disturbed)
        if is_ref_1000:
            cls_1000 = "reference_forest"
        else:
            cls_1000 = str(cls_counts.index[0])

        cdens = float(grp[density_col].mean()) if density_col else float("nan")
        cell_meta_rows.append(
            {
                "cell_id_1000": cid1000,
                "class_1000": cls_1000,
                "is_reference_1000": is_ref_1000,
                "canal_density_km_per_km2": cdens,
                "canal_density": cdens,
            }
        )
    meta_1000 = pd.DataFrame(cell_meta_rows)

    merged["n_valid_f"] = merged["n_valid_pixels"].fillna(0).astype(np.float64)
    merged["total_f"] = (
        merged["total_pixels"].fillna(0).astype(np.float64)
        if "total_pixels" in merged.columns
        else merged["n_valid_f"]
    )
    merged["weighted_hh"] = np.where(
        np.isfinite(merged["gamma_bar_hh"]) & (merged["n_valid_f"] > 0),
        merged["gamma_bar_hh"].astype(np.float64) * merged["n_valid_f"],
        0.0,
    )
    has_hv = "gamma_bar_hv" in merged.columns
    if has_hv:
        merged["weighted_hv"] = np.where(
            np.isfinite(merged["gamma_bar_hv"]) & (merged["n_valid_f"] > 0),
            merged["gamma_bar_hv"].astype(np.float64) * merged["n_valid_f"],
            0.0,
        )
    else:
        merged["weighted_hv"] = 0.0

    merged["valid_w_hh"] = np.where(
        np.isfinite(merged["gamma_bar_hh"]) & (merged["n_valid_f"] > 0),
        merged["n_valid_f"],
        0.0,
    )
    merged["is_dropped_flag"] = (
        merged["is_dropped_date"].fillna(False).astype(bool)
        if "is_dropped_date" in merged.columns
        else False
    )

    agg = (
        merged.groupby(["cell_id_1000", "date"], sort=True, as_index=False)
        .agg(
            sum_w_hh=("weighted_hh", "sum"),
            sum_w_hv=("weighted_hv", "sum"),
            n_valid_pixels=("valid_w_hh", "sum"),
            total_pixels=("total_f", "sum"),
            is_dropped_date=("is_dropped_flag", "max"),
        )
    )

    agg["gamma_bar_hh"] = np.where(
        (agg["n_valid_pixels"] > 0) & (agg["sum_w_hh"] > 0),
        agg["sum_w_hh"] / np.maximum(agg["n_valid_pixels"], 1.0),
        np.nan,
    )
    if has_hv:
        agg["gamma_bar_hv"] = np.where(
            (agg["n_valid_pixels"] > 0) & (agg["sum_w_hv"] > 0),
            agg["sum_w_hv"] / np.maximum(agg["n_valid_pixels"], 1.0),
            np.nan,
        )
    else:
        agg["gamma_bar_hv"] = np.nan

    min_vf = float(cfg.get("min_valid_fraction", 0.5))
    agg["valid_fraction"] = np.where(
        agg["total_pixels"] > 0,
        agg["n_valid_pixels"] / np.maximum(agg["total_pixels"], 1.0),
        0.0,
    )
    enough = (~agg["is_dropped_date"]) & (agg["valid_fraction"] >= min_vf) & (agg["gamma_bar_hh"] > 0)
    agg["g_hh"] = np.where(enough, 10.0 * np.log10(np.maximum(agg["gamma_bar_hh"], 1e-12)), np.nan)
    agg["g_hv"] = np.where(
        enough & (agg["gamma_bar_hv"] > 0),
        10.0 * np.log10(np.maximum(agg["gamma_bar_hv"], 1e-12)),
        np.nan,
    )

    agg = agg.merge(meta_1000, on="cell_id_1000", how="left")
    agg = agg.rename(columns={"cell_id_1000": "cell_id", "class_1000": "class", "is_reference_1000": "is_reference"})

    kept_dates = sorted(agg.loc[~agg["is_dropped_date"] & agg["g_hh"].notna(), "date"].unique().tolist())
    if not kept_dates:
        return None
    t0 = kept_dates[0]

    base_hh = agg.loc[agg["date"] == t0, ["cell_id", "g_hh", "g_hv"]].rename(
        columns={"g_hh": "g_hh_t0", "g_hv": "g_hv_t0"}
    )
    agg = agg.merge(base_hh, on="cell_id", how="left")
    agg["raw_delta_hh"] = agg["g_hh"] - agg["g_hh_t0"]
    agg["raw_delta_hv"] = agg["g_hv"] - agg["g_hv_t0"]

    ref_medians = (
        agg.loc[agg["is_reference"] & agg["raw_delta_hh"].notna()]
        .groupby("date", as_index=False)
        .agg(ref_delta_hh=("raw_delta_hh", "median"), ref_delta_hv=("raw_delta_hv", "median"))
    )
    agg = agg.merge(ref_medians, on="date", how="left")
    agg["D_hh"] = agg["raw_delta_hh"] - agg["ref_delta_hh"]
    agg["D_hv"] = agg["raw_delta_hv"] - agg["ref_delta_hv"]
    t0_mask = agg["date"] == t0
    agg.loc[t0_mask, "D_hh"] = np.where(agg.loc[t0_mask, "g_hh"].notna(), 0.0, np.nan)
    agg.loc[t0_mask, "D_hv"] = np.where(agg.loc[t0_mask, "g_hv"].notna(), 0.0, np.nan)

    keep_cols = [
        "cell_id",
        "date",
        "class",
        "is_reference",
        "is_dropped_date",
        "canal_density_km_per_km2",
        "canal_density",
        "n_valid_pixels",
        "total_pixels",
        "gamma_bar_hh",
        "gamma_bar_hv",
        "g_hh",
        "g_hv",
        "raw_delta_hh",
        "raw_delta_hv",
        "D_hh",
        "D_hv",
    ]
    out_path = ddir / "cell_stats_1000m.parquet"
    agg[keep_cols].sort_values(["cell_id", "date"]).to_parquet(out_path, index=False)
    return out_path


# ---------------------------------------------------------------------------
# C1 Internal Self-Checks (Checks 3, 4, 8, 10)
# ---------------------------------------------------------------------------


def _test_reference_steady(data_dir: Path) -> dict[str, Any] | None:
    stats_path = data_dir / "cell_stats.parquet"
    if not stats_path.exists():
        return None
    df = _filter_kept_dates(pd.read_parquet(stats_path))
    if df.empty or "g_hh" not in df.columns:
        return None
    ref = df[_get_reference_mask(df) & df["g_hh"].notna()].copy()
    if ref.empty:
        return None

    per_date = ref.groupby("date", sort=True)["g_hh"].median().dropna()
    if len(per_date) < 2:
        return None
    diffs = np.abs(np.diff(per_date.to_numpy(dtype=np.float64)))
    idx_max = int(np.argmax(diffs))
    max_jump = float(diffs[idx_max])
    d_from = str(per_date.index[idx_max])
    d_to = str(per_date.index[idx_max + 1])
    n_ref = int(ref["cell_id"].nunique())

    return _make_test_entry(
        test_id="reference_steady",
        name_en="Reference forest stays steady",
        name_id="Hutan referensi tetap stabil",  # REVIEW
        statistic="Max consecutive-pass jump in reference-forest median raw HH backscatter, dB",
        value=max_jump,
        n=n_ref,
        note_en=(
            f"Largest pass-to-pass shift across {len(per_date)} kept dates was {max_jump:.3f} dB "
            f"({d_from} to {d_to}). A small value shows the reference forest did not drift."
        ),
        note_id=(
            f"Lonjakan terbesar antarlintasan di {len(per_date)} tanggal valid adalah {max_jump:.3f} dB "
            f"({d_from} ke {d_to}). Nilai kecil menunjukkan hutan referensi stabil."
        ),  # REVIEW
    )


def _test_split_half_null(cfg: dict[str, Any], data_dir: Path) -> dict[str, Any] | None:
    stats_path = data_dir / "cell_stats.parquet"
    if not stats_path.exists():
        return None
    df = _filter_kept_dates(pd.read_parquet(stats_path))
    if df.empty or "g_hh" not in df.columns:
        return None

    ref = df[_get_reference_mask(df) & df["g_hh"].notna()].copy()
    ref_ids = sorted(ref["cell_id"].astype(str).unique().tolist())
    if len(ref_ids) < 4:
        return None

    dates = sorted(ref["date"].astype(str).unique().tolist())
    if len(dates) < 2:
        return None
    t0 = dates[0]

    if "raw_delta_hh" not in ref.columns or ref["raw_delta_hh"].isna().all():
        base = ref.loc[ref["date"] == t0, ["cell_id", "g_hh"]].rename(columns={"g_hh": "g_hh_t0"})
        ref = ref.merge(base, on="cell_id", how="inner")
        ref["raw_delta_hh"] = ref["g_hh"] - ref["g_hh_t0"]
    ref = ref[ref["raw_delta_hh"].notna()].copy()

    # Load empirical noise floor sigma_t per date if noise_floor.json exists
    sigma_by_date: dict[str, float] = {}
    nf_path = data_dir / "noise_floor.json"
    if nf_path.exists():
        nf = json.loads(nf_path.read_text(encoding="utf-8"))
        for rec in nf.get("per_date", []):
            d = str(rec.get("date", ""))[:10]
            sig = rec.get("sigma_hh_db") or rec.get("sigma_manifest_db")
            if d and sig is not None and math.isfinite(float(sig)):
                sigma_by_date[d] = float(sig)

    rng = np.random.default_rng(SPLIT_HALF_SEED)
    perm = rng.permutation(np.array(ref_ids, dtype=object))
    half = len(perm) // 2
    half_a = set(perm[:half].tolist())
    half_b = set(perm[half:].tolist())

    change_k = float(cfg.get("change_k", cfg.get("sigma_threshold", 2.0)))
    within_flags: list[np.ndarray] = []

    for d_str in dates[1:]:
        sub = ref[ref["date"].astype(str) == d_str]
        a_vals = sub.loc[sub["cell_id"].astype(str).isin(half_a), "raw_delta_hh"].to_numpy(dtype=np.float64)
        b_vals = sub.loc[sub["cell_id"].astype(str).isin(half_b), "raw_delta_hh"].to_numpy(dtype=np.float64)
        if len(a_vals) == 0 or len(b_vals) == 0:
            continue
        ref_a = float(np.median(a_vals))
        sig_t = sigma_by_date.get(d_str)
        if sig_t is None or not math.isfinite(sig_t) or sig_t <= 0.0:
            sig_t = _compute_mad(a_vals - ref_a)
        if not math.isfinite(sig_t) or sig_t <= 0.0:
            continue
        d_b = b_vals - ref_a
        within_flags.append(np.abs(d_b) <= (change_k * sig_t))

    if not within_flags:
        return None
    all_flags = np.concatenate(within_flags)
    share_within = float(np.mean(all_flags))
    n_obs = int(len(all_flags))

    return _make_test_entry(
        test_id="split_half_null",
        name_en="Split-half reference null check",
        name_id="Uji nol belah-dua hutan referensi",  # REVIEW
        statistic=f"Share of held-out reference cell-passes inside +-{change_k:g}*sigma (seed={SPLIT_HALF_SEED})",
        value=share_within,
        n=n_obs,
        note_en=(
            f"Split {len(ref_ids)} reference cells 50/50 (seed {SPLIT_HALF_SEED}); "
            f"{share_within * 100:.1f}% of {n_obs} held-out cell-passes fell within +-2 sigma "
            "(~95% indicates calibrated noise bounds)."
        ),
        note_id=(
            f"Membagi {len(ref_ids)} sel referensi 50/50 (seed {SPLIT_HALF_SEED}); "
            f"{share_within * 100:.1f}% dari {n_obs} pengamatan berada dalam +-2 sigma (~95% diharapkan)."
        ),  # REVIEW
    )


def _load_states_long(states_path: Path) -> pd.DataFrame | None:
    if not states_path.exists():
        return None
    if states_path.suffix.lower() == ".parquet":
        return pd.read_parquet(states_path)
    if states_path.suffix.lower() == ".json":
        payload = json.loads(states_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "cells" in payload and "state" in payload:
            rows = []
            dates = payload.get("dates", [])
            for cid, seq in zip(payload["cells"], payload["state"]):
                for d_idx, st in enumerate(seq):
                    rows.append(
                        {
                            "cell_id": cid,
                            "date": dates[d_idx] if d_idx < len(dates) else str(d_idx),
                            "state": st,
                        }
                    )
            return pd.DataFrame(rows)
    return None


def _test_fire_agreement(data_dir: Path) -> dict[str, Any] | None:
    states_df = _load_states_long(data_dir / "states.parquet")
    if states_df is None or states_df.empty:
        return None
    state_col = "state" if "state" in states_df.columns else ("state_code" if "state_code" in states_df.columns else None)
    if state_col is None:
        return None

    fire_df = states_df[states_df[state_col].isin([2, 3])].copy()
    n_fire = int(len(fire_df))
    if n_fire == 0:
        return None

    n_agreed = int((fire_df[state_col] == 2).sum())
    share_agreed = float(n_agreed / n_fire)
    return _make_test_entry(
        test_id="fire_agreement",
        name_en="Radar and fire detections agree",
        name_id="Deteksi radar dan api selaras",  # REVIEW
        statistic="Share of active fire cell-passes where radar also moved (state 2 vs 3)",
        value=share_agreed,
        n=n_fire,
        note_en=(
            f"Of {n_fire} fire cell-passes (states 2 or 3), {n_agreed} ({share_agreed * 100:.1f}%) "
            "showed simultaneous radar change (state 2); the remainder were fire with silent radar (state 3)."
        ),
        note_id=(
            f"Dari {n_fire} pengamatan api (status 2 atau 3), {n_agreed} ({share_agreed * 100:.1f}%) "
            "menunjukkan perubahan radar (status 2); sisanya tidak terdeteksi radar (status 3)."
        ),  # REVIEW
    )


def _compute_peat_canal_drying_corr(
    stats_df: pd.DataFrame,
    grid_df: pd.DataFrame | None = None,
) -> tuple[float, int] | None:
    df = _filter_kept_dates(stats_df)
    if df.empty or "D_hh" not in df.columns:
        return None

    min_d = (
        df[df["D_hh"].notna()]
        .groupby("cell_id", as_index=False)
        .agg(min_d_hh=("D_hh", "min"), cls=("class", "first"))
    )
    if min_d.empty:
        return None

    density_col = _get_canal_density_col(df)
    if density_col:
        dens_map = df[["cell_id", density_col]].drop_duplicates("cell_id").rename(
            columns={density_col: "canal_density_val"}
        )
        merged = min_d.merge(dens_map, on="cell_id", how="inner")
    elif grid_df is not None:
        gcol = _get_canal_density_col(grid_df)
        if not gcol:
            return None
        dens_map = grid_df[["cell_id", gcol]].drop_duplicates("cell_id").rename(
            columns={gcol: "canal_density_val"}
        )
        merged = min_d.merge(dens_map, on="cell_id", how="inner")
    else:
        return None

    peat = merged[merged["cls"].astype(str).isin(PEAT_CLASSES)].copy()
    peat = peat[np.isfinite(peat["canal_density_val"]) & np.isfinite(peat["min_d_hh"])]
    if len(peat) < 3 or peat["canal_density_val"].nunique() < 2 or peat["min_d_hh"].nunique() < 2:
        return None

    res = stats.spearmanr(peat["canal_density_val"].to_numpy(), peat["min_d_hh"].to_numpy())
    rho = float(res.statistic)
    if not math.isfinite(rho):
        return None
    return rho, int(len(peat))


def _test_size_sensitivity(cfg: dict[str, Any], data_dir: Path) -> dict[str, Any] | None:
    p1000 = data_dir / "cell_stats_1000m.parquet"
    p500 = data_dir / "cell_stats.parquet"
    if not p1000.exists():
        return None

    df1000 = pd.read_parquet(p1000)
    res1000 = _compute_peat_canal_drying_corr(df1000)
    if res1000 is None:
        return None
    rho_1000, n_1000 = res1000

    rho_500_str = ""
    sign_note_en = ""
    sign_note_id = ""
    if p500.exists():
        df500 = pd.read_parquet(p500)
        grid500 = pd.read_parquet(data_dir / "grid_cells.parquet") if (data_dir / "grid_cells.parquet").exists() else None
        res500 = _compute_peat_canal_drying_corr(df500, grid500)
        if res500 is not None:
            rho_500, n_500 = res500
            same_sign = (rho_1000 < 0 and rho_500 < 0) or (rho_1000 > 0 and rho_500 > 0)
            rho_500_str = f" vs {rho_500:.3f} at 500 m (n={n_500})"
            sign_note_en = (
                " The negative canal-drying correlation keeps the same direction at 1,000 m."
                if (same_sign and rho_1000 < 0)
                else (" Correlation direction matches the 500 m run." if same_sign else " Warning: sign flipped at 1,000 m.")
            )
            sign_note_id = (
                " Korelasi negatif tetap searah pada resolusi 1.000 m."
                if (same_sign and rho_1000 < 0)
                else (" Arah korelasi sama dengan resolusi 500 m." if same_sign else " Peringatan: tanda korelasi berbalik pada 1.000 m.")
            )

    cell_1000_m = int(cfg.get("fallback_cell_size_m", 1000))
    return _make_test_entry(
        test_id="size_sensitivity",
        name_en=f"Trend holds at {cell_1000_m} m cell size",
        name_id=f"Tren bertahan pada sel {cell_1000_m} m",  # REVIEW
        statistic=f"Spearman rank correlation at {cell_1000_m} m (canal density vs season-min HH index)",
        value=rho_1000,
        n=n_1000,
        decimals=3,
        note_en=(
            f"Aggregated in linear power to {cell_1000_m} m cells: rho={rho_1000:.3f} (n={n_1000}){rho_500_str}."
            + sign_note_en
        ),
        note_id=(
            f"Diagregasi dalam daya linear ke sel {cell_1000_m} m: rho={rho_1000:.3f} (n={n_1000}){rho_500_str}."
            + sign_note_id
        ),  # REVIEW
    )


# ---------------------------------------------------------------------------
# C2-C4 Multi-Sensor Cross-Checks
# ---------------------------------------------------------------------------


def _test_soil_moisture_agrees(data_dir: Path) -> dict[str, Any] | None:
    sme2_path = data_dir / "sme2_cells.parquet"
    stats_path = data_dir / "cell_stats.parquet"
    if not sme2_path.exists() or not stats_path.exists():
        return None

    sm = pd.read_parquet(sme2_path)
    cs = _filter_kept_dates(pd.read_parquet(stats_path))
    if sm.empty or cs.empty or "soil_moisture" not in sm.columns or "D_hh" not in cs.columns:
        return None

    if "is_flagged" in sm.columns:
        sm = sm[~sm["is_flagged"].fillna(True).astype(bool)]
    sm = sm[sm["soil_moisture"].notna()].copy()
    if sm.empty:
        return None

    # Open drained peat cells on dates shared between GCOV and unflagged SME2
    cs_drained = cs[(cs["class"].astype(str) == "drained") & cs["D_hh"].notna()].copy()
    common_dates = sorted(set(cs_drained["date"].astype(str)) & set(sm["date"].astype(str)))
    if len(common_dates) < 2:
        return None

    t0 = common_dates[0]
    med_by_date = (
        cs_drained[cs_drained["date"].astype(str).isin(common_dates[1:])]
        .groupby("date")["D_hh"]
        .median()
    )
    if med_by_date.empty:
        return None
    t_peak = str(med_by_date.idxmin())

    sm_0 = sm[sm["date"].astype(str) == t0][["cell_id", "soil_moisture"]].rename(
        columns={"soil_moisture": "sm_t0"}
    )
    sm_p = sm[sm["date"].astype(str) == t_peak][["cell_id", "soil_moisture"]].rename(
        columns={"soil_moisture": "sm_peak"}
    )
    d_p = cs_drained[cs_drained["date"].astype(str) == t_peak][["cell_id", "D_hh"]]

    joined = sm_0.merge(sm_p, on="cell_id", how="inner").merge(d_p, on="cell_id", how="inner")
    joined["delta_sm"] = joined["sm_peak"] - joined["sm_t0"]
    joined = joined[np.isfinite(joined["delta_sm"]) & np.isfinite(joined["D_hh"])]

    if len(joined) < 3 or joined["delta_sm"].nunique() < 2 or joined["D_hh"].nunique() < 2:
        return None

    res = stats.spearmanr(joined["D_hh"].to_numpy(), joined["delta_sm"].to_numpy())
    rho = float(res.statistic)
    if not math.isfinite(rho):
        return None

    return _make_test_entry(
        test_id="soil_moisture_agrees",
        name_en="Soil moisture agrees with L-band drying",
        name_id="Kelembaban tanah sejalan dengan pengeringan pita-L",  # REVIEW
        statistic="Spearman rank correlation (peak-drought HH index vs SME2 delta since pass 1)",
        value=rho,
        n=int(len(joined)),
        decimals=3,
        note_en=(
            f"Consistency check on {len(joined)} open, unflagged drained peat cells comparing "
            f"{t_peak} against baseline {t0}. NISAR SME2 (200 m) is PROVISIONAL and untested on peat."
        ),
        note_id=(
            f"Uji konsistensi pada {len(joined)} sel gambut terdrainase terbuka tanpa penanda di {t_peak} "
            f"vs {t0}. NISAR SME2 (200 m) masih PROVISIONAL dan belum teruji di gambut."
        ),  # REVIEW
    )


def query_sentinel1_availability(
    study_box: list[float],
    early_date: str,
    peak_date: str,
    window_days: int = 12,
) -> dict[str, Any]:
    """Optional metadata check for Sentinel-1 IW scenes near early and peak-drought dates."""
    import datetime as dt_mod

    try:
        minx, miny, maxx, maxy = [float(v) for v in study_box]
        bbox_str = f"{minx},{miny},{maxx},{maxy}"
        results: dict[str, int] = {}

        for label, d_str in (("early", early_date), ("peak", peak_date)):
            d_mid = dt_mod.date.fromisoformat(d_str[:10])
            t0 = (d_mid - dt_mod.timedelta(days=window_days)).isoformat() + "T00:00:00Z"
            t1 = (d_mid + dt_mod.timedelta(days=window_days)).isoformat() + "T23:59:59Z"

            if _has_module("asf_search"):
                import asf_search as asf  # type: ignore

                wkt = f"POLYGON(({minx} {miny}, {maxx} {miny}, {maxx} {maxy}, {minx} {maxy}, {minx} {miny}))"
                resp = asf.search(
                    opts=asf.ASFSearchOptions(
                        platform="SENTINEL-1",
                        beamMode="IW",
                        intersectsWith=wkt,
                        start=t0,
                        end=t1,
                    )
                )
                results[label] = len(resp)
            else:
                import requests

                resp = requests.get(
                    "https://api.daac.asf.alaska.edu/services/search/param",
                    params={
                        "platform": "SENTINEL-1",
                        "beamMode": "IW",
                        "bbox": bbox_str,
                        "start": t0,
                        "end": t1,
                        "output": "count",
                    },
                    timeout=15,
                )
                results[label] = int(resp.text.strip()) if resp.status_code == 200 and resp.text.strip().isdigit() else 0
        return {"status": "ok", "counts": results}
    except Exception as exc:
        return {"status": "unavailable", "reason": str(exc)}


def _has_module(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def _test_cband_same_direction(data_dir: Path) -> dict[str, Any] | None:
    s1_path = None
    for candidate in ("sentinel1_cells.parquet", "cband_cells.parquet"):
        p = data_dir / candidate
        if p.exists():
            s1_path = p
            break
    stats_path = data_dir / "cell_stats.parquet"
    if s1_path is None or not stats_path.exists():
        return None

    s1 = pd.read_parquet(s1_path)
    cs = _filter_kept_dates(pd.read_parquet(stats_path))
    if s1.empty or cs.empty or "D_hh" not in cs.columns:
        return None

    # Allow either precomputed double-difference D_cband/D_s1, or early+peak g_cband backscatter (dB)
    d_c_col = next((c for c in ("D_cband", "D_s1", "D_vv", "D_c_hh") if c in s1.columns), None)
    date_col = "date" if "date" in s1.columns else None

    cs_ref_ids = set(cs.loc[_get_reference_mask(cs), "cell_id"].astype(str))
    cs_drained = cs[(cs["class"].astype(str) == "drained") & cs["D_hh"].notna()].copy()

    if d_c_col is not None:
        if date_col and "date" in s1.columns:
            common_dates = sorted(set(cs_drained["date"].astype(str)) & set(s1[date_col].astype(str)))
            if not common_dates:
                return None
            # Pick the common post-baseline date with strongest drained L-band drying
            post_dates = common_dates[1:] if len(common_dates) > 1 else common_dates
            med_l = cs_drained[cs_drained["date"].astype(str).isin(post_dates)].groupby("date")["D_hh"].median()
            t_peak = str(med_l.idxmin())
            s1_peak = s1[s1[date_col].astype(str) == t_peak][["cell_id", d_c_col]].rename(columns={d_c_col: "D_cband"})
            l_peak = cs_drained[cs_drained["date"].astype(str) == t_peak][["cell_id", "D_hh"]]
        else:
            # Summary table keyed by cell_id (and optional l_date / peak_date)
            med_l = cs_drained.groupby("date")["D_hh"].median()
            t_peak = str(med_l.idxmin())
            s1_peak = s1[["cell_id", d_c_col]].rename(columns={d_c_col: "D_cband"})
            l_peak = cs_drained[cs_drained["date"].astype(str) == t_peak][["cell_id", "D_hh"]]
        joined = l_peak.merge(s1_peak, on="cell_id", how="inner")
    else:
        # Compute C-band double difference from early vs peak g_db (or linear gamma0) on the 500 m grid
        val_col = next((c for c in ("g_db", "gamma0_db", "sigma0_db", "vv_db") if c in s1.columns), None)
        if val_col is None or date_col is None:
            lin_col = next((c for c in ("gamma0", "gamma0_lin", "vv_lin") if c in s1.columns), None)
            if lin_col is None or date_col is None:
                return None
            s1 = s1.copy()
            s1["_c_db"] = np.where(s1[lin_col] > 0, 10.0 * np.log10(np.maximum(s1[lin_col], 1e-12)), np.nan)
            val_col = "_c_db"

        s1_dates = sorted(s1[date_col].astype(str).unique().tolist())
        cs_dates = sorted(cs_drained["date"].astype(str).unique().tolist())
        if len(s1_dates) < 2 or len(cs_dates) < 2:
            return None
        s1_early, s1_late = s1_dates[0], s1_dates[-1]

        e_df = s1[s1[date_col].astype(str) == s1_early][["cell_id", val_col]].rename(columns={val_col: "c_early"})
        p_df = s1[s1[date_col].astype(str) == s1_late][["cell_id", val_col]].rename(columns={val_col: "c_late"})
        c_pair = e_df.merge(p_df, on="cell_id", how="inner")
        c_pair["c_raw_delta"] = c_pair["c_late"] - c_pair["c_early"]

        c_ref = c_pair[c_pair["cell_id"].astype(str).isin(cs_ref_ids) & c_pair["c_raw_delta"].notna()]
        if c_ref.empty:
            return None
        c_ref_delta = float(c_ref["c_raw_delta"].median())
        c_pair["D_cband"] = c_pair["c_raw_delta"] - c_ref_delta

        # Match NISAR L-band peak drought nearest to s1_late (or overall peak)
        t_peak = s1_late if s1_late in cs_dates else str(
            cs_drained[cs_drained["date"].astype(str) != cs_dates[0]].groupby("date")["D_hh"].median().idxmin()
        )
        l_peak = cs_drained[cs_drained["date"].astype(str) == t_peak][["cell_id", "D_hh"]]
        joined = l_peak.merge(c_pair[["cell_id", "D_cband"]], on="cell_id", how="inner")

    joined = joined[np.isfinite(joined["D_hh"]) & np.isfinite(joined["D_cband"])]
    nonzero = joined[(joined["D_hh"] != 0.0) & (joined["D_cband"] != 0.0)]
    if nonzero.empty:
        return None

    same_sign = (np.sign(nonzero["D_hh"]) == np.sign(nonzero["D_cband"])).to_numpy()
    share_same = float(np.mean(same_sign))
    med_l_db = float(nonzero["D_hh"].median())
    med_c_db = float(nonzero["D_cband"].median())

    return _make_test_entry(
        test_id="cband_same_direction",
        name_en="Sentinel-1 C-band shifts in the same direction",
        name_id="Pita-C Sentinel-1 bergeser searah dengan pita-L",  # REVIEW
        statistic="Share of open drained peat cells changing with the same sign in C-band and L-band",
        value=share_same,
        n=int(len(nonzero)),
        decimals=3,
        note_en=(
            f"Double-differenced against the same reference forest cells on {len(nonzero)} open drained cells: "
            f"{share_same * 100:.1f}% moved in the same direction "
            f"(L-band median {med_l_db:+.2f} dB, C-band median {med_c_db:+.2f} dB)."
        ),
        note_id=(
            f"Selisih-ganda terhadap hutan referensi pada {len(nonzero)} sel terdrainase: "
            f"{share_same * 100:.1f}% bergerak searah "
            f"(median pita-L {med_l_db:+.2f} dB, median pita-C {med_c_db:+.2f} dB)."
        ),  # REVIEW
    )


def _test_burned_matches_modis(data_dir: Path) -> dict[str, Any] | None:
    modis_path = None
    for candidate in ("modis_burned.parquet", "mcd64a1_cells.parquet"):
        p = data_dir / candidate
        if p.exists():
            modis_path = p
            break
    states_df = _load_states_long(data_dir / "states.parquet")
    if modis_path is None or states_df is None or states_df.empty:
        return None

    state_col = "state" if "state" in states_df.columns else ("state_code" if "state_code" in states_df.columns else None)
    if state_col is None or "cell_id" not in states_df.columns:
        return None

    modis = pd.read_parquet(modis_path)
    if modis.empty or "cell_id" not in modis.columns:
        return None

    if "modis_burned" in modis.columns:
        modis_flag = modis["modis_burned"].fillna(False).astype(bool)
    elif "burned" in modis.columns:
        modis_flag = modis["burned"].fillna(False).astype(bool)
    elif "burn_date" in modis.columns:
        modis_flag = modis["burn_date"].fillna(0).astype(np.float64) > 0
    else:
        return None

    universe = set(states_df["cell_id"].astype(str)) & set(modis["cell_id"].astype(str))
    if not universe:
        return None

    bundle_burned = set(
        states_df.loc[states_df[state_col].isin([2, 3, 4]) & states_df["cell_id"].astype(str).isin(universe), "cell_id"]
        .astype(str)
        .unique()
    )
    if not bundle_burned:
        return None

    modis_burned = set(
        modis.loc[modis_flag & modis["cell_id"].astype(str).isin(universe), "cell_id"]
        .astype(str)
        .unique()
    )
    both = bundle_burned & modis_burned
    forward_share = float(len(both) / len(bundle_burned))
    reverse_share = float(len(both) / len(modis_burned)) if modis_burned else 0.0

    return _make_test_entry(
        test_id="burned_matches_modis",
        name_en="Burned cells match MODIS MCD64A1",
        name_id="Sel terbakar cocok dengan MODIS MCD64A1",  # REVIEW
        statistic="Share of bundle burned cells (states 2, 3, or 4) also flagged by MODIS/061/MCD64A1",
        value=forward_share,
        n=int(len(bundle_burned)),
        decimals=3,
        note_en=(
            f"{len(both)} of {len(bundle_burned)} bundle burned cells ({forward_share * 100:.1f}%) "
            f"were also flagged by 500 m MODIS MCD64A1 over the study months; reverse share of MODIS "
            f"burned cells matched by the bundle is {reverse_share * 100:.1f}% ({len(both)}/{len(modis_burned)})."
        ),
        note_id=(
            f"{len(both)} dari {len(bundle_burned)} sel terbakar bundel ({forward_share * 100:.1f}%) "
            f"juga ditandai MODIS MCD64A1 500 m; pangsa sebaliknya dari sel MODIS yang cocok "
            f"adalah {reverse_share * 100:.1f}% ({len(both)}/{len(modis_burned)})."
        ),  # REVIEW
    )


# ---------------------------------------------------------------------------
# Public Entry Point for pipeline/08_export.py
# ---------------------------------------------------------------------------


def compute_all_tests(
    config: dict[str, Any] | Path | str | None,
    data_dir: Path | str = "data",
) -> list[dict[str, Any]]:
    """Compute all available C1 self-checks and C2-C4 cross-checks from data_dir.

    Omits any check whose required input file is missing or incomplete. Never
    emits placeholder 0s or fabricated data.
    """
    cfg = _normalize_config(config)
    ddir = _resolve_path(data_dir)
    if not ddir.exists():
        return []

    candidates = [
        _test_reference_steady(ddir),
        _test_split_half_null(cfg, ddir),
        _test_fire_agreement(ddir),
        _test_size_sensitivity(cfg, ddir),
        _test_soil_moisture_agrees(ddir),
        _test_cband_same_direction(ddir),
        _test_burned_matches_modis(ddir),
    ]
    return [entry for entry in candidates if entry is not None]


# ---------------------------------------------------------------------------
# Standalone Verification Suite (--self-test)
# ---------------------------------------------------------------------------


def _assert_entry_contract(entry: dict[str, Any]) -> None:
    req = ("id", "name", "name_en", "name_id", "statistic", "value", "n", "note", "note_en", "note_id")
    for k in req:
        assert k in entry, f"Missing required test key: {k}"
    assert isinstance(entry["value"], float) and math.isfinite(entry["value"])
    assert isinstance(entry["n"], int) and entry["n"] > 0


def run_self_test() -> int:
    """Validate missing-file omission and exact math across all 7 tests (C1-C4)."""
    print("Running scorecard_tests.py --self-test ...")
    cfg = _normalize_config(None)

    # 1. Empty folder must return [] (zero fabricated tests)
    with tempfile.TemporaryDirectory() as empty_dir:
        res_empty = compute_all_tests(cfg, empty_dir)
        assert res_empty == [], f"Expected [] on empty dir, got {res_empty}"

    # 2. Synthetic complete directory covering C1 (3,4,8,10) + C2 + C3 + C4
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        rng = np.random.default_rng(7)
        dates = ["2026-06-22", "2026-07-04", "2026-08-21", "2026-09-26"]

        # 8x8 grid of 500 m cells -> 4x4 grid of 1000 m blocks
        grid_rows = []
        for r in range(8):
            for c in range(8):
                cid = f"r{r:03d}c{c:03d}"
                if r < 4:
                    cls = "reference_forest"
                    cdens = 0.0
                else:
                    cls = "drained" if c < 6 else "rewetted"
                    cdens = 0.5 + 0.6 * (r - 4) + (0.2 * (5 - c) if cls == "drained" else 0.0)
                grid_rows.append(
                    {
                        "cell_id": cid,
                        "row": r,
                        "col": c,
                        "class": cls,
                        "canal_density_km_per_km2": cdens,
                        "canal_density": cdens,
                    }
                )
        grid_df = pd.DataFrame(grid_rows)
        grid_df.to_parquet(td / "grid_cells.parquet", index=False)

        # Build cell_stats across 4 dates with realistic drying & steady reference
        cs_rows = []
        sme2_rows = []
        s1_rows = []
        states_rows = []
        modis_rows = []

        for g_row in grid_rows:
            cid = g_row["cell_id"]
            cls = g_row["class"]
            cdens = g_row["canal_density"]
            for t_idx, d_str in enumerate(dates):
                ref_bias = 0.02 * math.sin(t_idx)
                if cls == "reference_forest":
                    d_hh = float(rng.normal(0.0, 0.08)) if t_idx > 0 else 0.0
                else:
                    # Stronger drying on higher canal_density, deepest on date 3 (2026-09-26)
                    scale = [0.0, -0.35, -0.95, -1.25][t_idx]
                    d_hh = scale * (0.5 + cdens) + float(rng.normal(0.0, 0.05)) if t_idx > 0 else 0.0
                g_hh = -8.0 + ref_bias + d_hh
                gamma_hh = 10.0 ** (g_hh / 10.0)
                cs_rows.append(
                    {
                        "cell_id": cid,
                        "date": d_str,
                        "class": cls,
                        "is_reference": cls == "reference_forest",
                        "is_dropped_date": False,
                        "total_pixels": 625,
                        "n_valid_pixels": 625,
                        "valid_fraction": 1.0,
                        "gamma_bar_hh": gamma_hh,
                        "gamma_bar_hv": gamma_hh * 0.2,
                        "g_hh": g_hh,
                        "g_hv": g_hh - 7.0,
                        "raw_delta_hh": 0.0 if t_idx == 0 else ref_bias + d_hh,
                        "D_hh": 0.0 if t_idx == 0 else d_hh,
                        "D_hv": 0.0 if t_idx == 0 else 0.5 * d_hh,
                    }
                )

                # States: 4 burned cells in late season (3 radar-agreed state=2, 1 silent state=3)
                st = 8 if cls == "reference_forest" else 7
                if t_idx == 3 and g_row["row"] == 7 and g_row["col"] < 4:
                    st = 2 if g_row["col"] < 3 else 3
                states_rows.append({"cell_id": cid, "date": d_str, "state": st})

                # SME2 soil moisture on pass 0 & pass 3 (correlates positively with D_hh)
                if t_idx in (0, 3):
                    sm_base = 0.42
                    sm_val = sm_base + (0.08 * d_hh if t_idx == 3 else 0.0)
                    is_flagged = bool(g_row["row"] == 4 and g_row["col"] == 0)  # test flag masking
                    sme2_rows.append(
                        {
                            "cell_id": cid,
                            "date": d_str,
                            "class": cls,
                            "soil_moisture": sm_val,
                            "n_unflagged_pixels": 0 if is_flagged else 4,
                            "is_flagged": is_flagged,
                        }
                    )

                # Sentinel-1 C-band on pass 0 & pass 3 moving in same direction as L-band
                if t_idx in (0, 3):
                    c_delta = 0.7 * d_hh + 0.05 * t_idx
                    s1_rows.append(
                        {
                            "cell_id": cid,
                            "date": d_str,
                            "g_db": -10.0 + (c_delta if t_idx == 3 else 0.0),
                        }
                    )

            # MODIS MCD64A1 agrees on first 3 of 4 burned cells + 1 extra MODIS-only cell
            m_burned = (g_row["row"] == 7 and g_row["col"] in (0, 1, 2, 5))
            modis_rows.append(
                {"cell_id": cid, "burn_date": 265 if m_burned else 0, "modis_burned": m_burned}
            )

        pd.DataFrame(cs_rows).to_parquet(td / "cell_stats.parquet", index=False)
        pd.DataFrame(states_rows).to_parquet(td / "states.parquet", index=False)
        pd.DataFrame(sme2_rows).to_parquet(td / "sme2_cells.parquet", index=False)
        pd.DataFrame(s1_rows).to_parquet(td / "sentinel1_cells.parquet", index=False)
        pd.DataFrame(modis_rows).to_parquet(td / "modis_burned.parquet", index=False)

        # Before building 1000m stats, size_sensitivity must be omitted
        pre_tests = {t["id"]: t for t in compute_all_tests(cfg, td)}
        assert "size_sensitivity" not in pre_tests, "Missing cell_stats_1000m must omit size_sensitivity"

        # Now build 1000 m stats and verify all 7 tests run cleanly
        out_1000 = build_1000m_cell_stats(cfg, td)
        assert out_1000 is not None and out_1000.exists()

        all_tests = compute_all_tests(cfg, td)
        by_id = {t["id"]: t for t in all_tests}
        expected_ids = {
            "reference_steady",
            "split_half_null",
            "fire_agreement",
            "size_sensitivity",
            "soil_moisture_agrees",
            "cband_same_direction",
            "burned_matches_modis",
        }
        assert set(by_id.keys()) == expected_ids, f"Mismatch: {set(by_id.keys())} vs {expected_ids}"
        for entry in all_tests:
            _assert_entry_contract(entry)

        assert by_id["fire_agreement"]["value"] == 0.75 and by_id["fire_agreement"]["n"] == 4
        assert by_id["burned_matches_modis"]["value"] == 0.75 and by_id["burned_matches_modis"]["n"] == 4
        assert "75.0%" in by_id["burned_matches_modis"]["note"]
        assert by_id["size_sensitivity"]["value"] < -0.5
        assert by_id["soil_moisture_agrees"]["value"] > 0.5
        assert by_id["cband_same_direction"]["value"] > 0.8

        # Delete states.parquet -> fire_agreement & burned_matches_modis must be omitted
        (td / "states.parquet").unlink()
        partial = {t["id"] for t in compute_all_tests(cfg, td)}
        assert "fire_agreement" not in partial
        assert "burned_matches_modis" not in partial
        assert {"reference_steady", "split_half_null", "size_sensitivity", "soil_moisture_agrees", "cband_same_direction"} == partial

    print("[PASS] scorecard_tests.py --self-test passed all assertions (C1-C4 & missing-file omission).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute Track C scorecard tests.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--skip-build-1000m", action="store_true")
    parser.add_argument("--check-sentinel1-catalog", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    cfg = _normalize_config(args.config)
    ddir = _resolve_path(args.data_dir)

    if not args.skip_build_1000m:
        p1000 = build_1000m_cell_stats(cfg, ddir)
        if p1000 is not None:
            print(f"Built 1000 m sensitivity stats: {p1000}")

    tests = compute_all_tests(cfg, ddir)
    all_possible = [
        "reference_steady",
        "split_half_null",
        "fire_agreement",
        "size_sensitivity",
        "soil_moisture_agrees",
        "cband_same_direction",
        "burned_matches_modis",
    ]
    present = {t["id"] for t in tests}
    omitted = [tid for tid in all_possible if tid not in present]

    payload: dict[str, Any] = {
        "tests": tests,
        "available_test_ids": [t["id"] for t in tests],
        "omitted_tests": omitted,
    }
    if args.check_sentinel1_catalog and (ddir / "cell_stats.parquet").exists():
        dates = sorted(pd.read_parquet(ddir / "cell_stats.parquet", columns=["date"])["date"].unique().tolist())
        if len(dates) >= 2:
            payload["sentinel1_catalog_check"] = query_sentinel1_availability(
                cfg.get("study_box", [113.75, -2.25, 114.25, -1.75]),
                dates[0],
                dates[-1],
            )

    out_path = ddir / "scorecard_tests.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nSaved {len(tests)} available scorecard test(s) -> {out_path}")
    for t in tests:
        print(f"  - {t['id']}: value={t['value']} (n={t['n']}) | {t['statistic']}")
    if omitted:
        print(f"Omitted due to missing inputs: {', '.join(omitted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
