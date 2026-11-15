"""Stage 7b: fire-risk hindcast (2026 season, one site).

Builds a cell x pass panel from the pipeline outputs, fits an L2 logistic model
on earlier passes, and scores it on the last two passes against three simple
baselines. This is a hindcast of one season at one site, not a forecast.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import warnings
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy import sparse
from scipy.spatial import cKDTree
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRAMING = "hindcast, 2026 season, one site"
PANEL_COLUMNS = [
    "cell_id", "block_id", "pass_date", "target_interval_end", "target_interval_days", "land_class",
    "canal_density_km_per_km2", "hv_index_db", "hv_index_change_db", "dist_prior_fire_km", "rain_interval_mm",
    "fire_within_2km_interval", "fire_next_interval",
]
FEATURES = [
    "hv_index_db", "hv_index_change_db", "canal_density_km_per_km2", "log_dist_prior_fire", "log_interval_days",
    "lc_degraded", "lc_plantation", "lc_built",
]
C_GRID = [0.01, 0.03, 0.1, 0.3, 1.0]
NEAR_FIRE_M = 2000.0
DIST_CAP_KM = 30.0
N_BOOT = 1000
BOOT_SEED = 0
MIN_TRAIN_FIRES = 10


# ---------------------------------------------------------------- panel


def build_panel(
    context: dict, quality: dict, stats: pd.DataFrame, fires: pd.DataFrame, grid: pd.DataFrame,
    landclass: pd.DataFrame, landclass_report: dict,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return (panel, info); info holds land_class_source and n_skipped_missing_hv."""
    dates = [str(d)[:10] for d in context["dates"]]
    rain = list(context["rain_interval_mm"])
    if len(rain) != len(dates) - 1:
        raise ValueError(f"rain_interval_mm has {len(rain)} entries, expected {len(dates) - 1}")
    pos = {d: k for k, d in enumerate(dates)}
    kept = sorted(str(d)[:10] for d in quality["kept_dates"])
    off_cal = [d for d in kept if d not in pos]
    if off_cal:
        raise ValueError(f"kept dates not in the context calendar: {off_cal}")

    g = grid.assign(cell_id=grid["cell_id"].astype(str)).sort_values("cell_id").reset_index(drop=True)
    ids = g["cell_id"].to_numpy()
    n_cells, n_int = len(ids), len(dates) - 1
    cell_ix = pd.Series(np.arange(n_cells), index=ids)

    fire_cols = [f"fires_int_{k}" for k in range(n_int)]
    missing = [c for c in fire_cols if c not in fires.columns]
    if missing or f"fires_int_{n_int}" in fires.columns:
        raise ValueError("fires.parquet intervals do not match context_summary dates; re-run 06_context_tabular.py")
    fire = np.zeros((n_cells, n_int), dtype=bool)
    fi = cell_ix.reindex(fires["cell_id"].astype(str)).to_numpy()
    ok = ~np.isnan(fi)
    fire[fi[ok].astype(int)] = fires[fire_cols].fillna(0).to_numpy()[ok] > 0

    dhv = np.full((n_cells, len(dates)), np.nan)
    si = cell_ix.reindex(stats["cell_id"].astype(str)).to_numpy()
    sd = stats["date"].astype(str).str[:10].map(pos).to_numpy(dtype=float)
    ok = ~np.isnan(si) & ~np.isnan(sd)
    dhv[si[ok].astype(int), sd[ok].astype(int)] = stats["D_hv"].to_numpy(dtype=float)[ok]

    used = landclass_report.get("status") == "used"
    lc_col = "cover_pred" if used else "label_map"
    lc = landclass.assign(cell_id=landclass["cell_id"].astype(str)).set_index("cell_id")[lc_col].reindex(ids).to_numpy()
    if pd.isna(lc).any():  # a missing class would silently count as forest, the reference class
        raise ValueError(f"{int(pd.isna(lc).sum())} grid cells have no land class in landclass.csv; re-run 04c_landclass.py")

    xy = g[["x_center", "y_center"]].to_numpy(dtype=float)
    tree = cKDTree(xy)
    nb = tree.query_ball_point(xy, NEAR_FIRE_M)  # includes the cell itself
    lens = np.fromiter((len(x) for x in nb), dtype=np.int64, count=n_cells)
    near = sparse.csr_matrix(
        (np.ones(lens.sum()), np.concatenate(nb).astype(np.int64), np.concatenate([[0], np.cumsum(lens)])),
        shape=(n_cells, n_cells),
    )
    first_fire = np.where(fire.any(1), fire.argmax(1), n_int)
    block = np.array([f"b{r // 10:02d}{c // 10:02d}" for r, c in zip(g["row"].astype(int), g["col"].astype(int))])
    canal = g["canal_density_km_per_km2"].to_numpy(dtype=float)

    parts, n_skipped = [], 0
    for i in range(1, len(kept) - 1):
        a, b, c = pos[kept[i - 1]], pos[kept[i]], pos[kept[i + 1]]
        alive = first_fire >= b  # rows stop after the first fire
        hv, chg = dhv[:, b], dhv[:, b] - dhv[:, a]
        has = alive & ~np.isnan(hv) & ~np.isnan(chg)
        n_skipped += int((alive & ~has).sum())

        b1 = (near @ fire[:, a:b].any(1).astype(float)) > 0
        burned = fire[:, :b].any(1)
        # Fire locations approximated by the centres of burned cells.
        if burned.any():
            d_m, _ = cKDTree(xy[burned]).query(xy, distance_upper_bound=DIST_CAP_KM * 1000.0)
            dist = np.minimum(d_m / 1000.0, DIST_CAP_KM)
        else:
            dist = np.full(n_cells, DIST_CAP_KM)
        win = rain[a:b]
        r = None if any(v is None for v in win) else float(sum(win))

        m = has
        parts.append(pd.DataFrame({
            "cell_id": ids[m], "block_id": block[m], "pass_date": kept[i], "target_interval_end": kept[i + 1],
            "target_interval_days": (date.fromisoformat(kept[i + 1]) - date.fromisoformat(kept[i])).days,
            "land_class": lc[m], "canal_density_km_per_km2": canal[m], "hv_index_db": hv[m],
            "hv_index_change_db": chg[m], "dist_prior_fire_km": np.round(dist[m], 3), "rain_interval_mm": r,
            "fire_within_2km_interval": b1[m].astype(int), "fire_next_interval": fire[m, b:c].any(1).astype(int),
        }))
    panel = pd.concat(parts, ignore_index=True)[PANEL_COLUMNS] if parts else pd.DataFrame(columns=PANEL_COLUMNS)
    return panel, {"land_class_source": lc_col, "n_skipped_missing_hv": n_skipped}


# ---------------------------------------------------------------- evaluation


def _design(df: pd.DataFrame) -> np.ndarray:
    lc = df["land_class"].astype(str)
    X = pd.DataFrame({
        "hv_index_db": df["hv_index_db"].astype(float),
        "hv_index_change_db": df["hv_index_change_db"].astype(float),
        "canal_density_km_per_km2": df["canal_density_km_per_km2"].astype(float),
        "log_dist_prior_fire": np.log1p(np.minimum(df["dist_prior_fire_km"].astype(float), DIST_CAP_KM)),
        "log_interval_days": np.log(df["target_interval_days"].astype(float) / 12.0),
        "lc_degraded": (lc == "degraded").astype(float),
        "lc_plantation": (lc == "plantation").astype(float),
        "lc_built": (lc == "built").astype(float),
    })
    return X[FEATURES].to_numpy()


def _logit() -> Any:
    # LogisticRegression is L2 by default; passing penalty= is deprecated in sklearn 1.8+.
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))


def _top10_capture(score: np.ndarray, y: np.ndarray, passes: np.ndarray) -> float:
    caught = 0
    for p in np.unique(passes):
        ix = np.flatnonzero(passes == p)
        k = max(1, round(0.10 * len(ix)))
        caught += int(y[ix[np.argsort(-score[ix], kind="stable")[:k]]].sum())
    return caught / max(1, int(y.sum()))


def _block_ci(scores: dict[str, np.ndarray], y: np.ndarray, blocks: np.ndarray) -> dict[str, list[float]]:
    rng = np.random.default_rng(BOOT_SEED)
    ub, inv = np.unique(blocks, return_inverse=True)
    rows = [np.flatnonzero(inv == j) for j in range(len(ub))]
    out: dict[str, list[float]] = {k: [] for k in scores}
    for _ in range(N_BOOT):
        ix = np.concatenate([rows[j] for j in rng.integers(0, len(ub), len(ub))])
        if y[ix].sum() == 0:
            continue
        for k, s in scores.items():
            out[k].append(average_precision_score(y[ix], s[ix]))
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v else [None, None] for k, v in out.items()}


def _lift(test: pd.DataFrame) -> list[dict[str, Any]]:
    q = pd.qcut(test["hv_index_db"].astype(float), 5, labels=False, duplicates="drop") + 1
    t = test.assign(q=q).groupby("q")["fire_next_interval"].agg(["size", "sum"])
    return [{"quintile": int(k), "n": int(r["size"]), "fires": int(r["sum"]), "rate": r["sum"] / r["size"]} for k, r in t.iterrows()]


def _round(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return round(float(obj), 4) if math.isfinite(obj) else None
    return obj


def _evaluate(panel: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame | None]:
    """Report plus the scored test rows (None when the model did not run)."""
    df = panel.copy()
    df["pass_date"] = df["pass_date"].astype(str)
    pass_dates = sorted(df["pass_date"].unique())
    test_dates, train_dates = pass_dates[-2:], pass_dates[:-2]
    is_test = df["pass_date"].isin(test_dates).to_numpy()
    train, test = df[~is_test].reset_index(drop=True), df[is_test].reset_index(drop=True)
    ytr, yte = train["fire_next_interval"].to_numpy(int), test["fire_next_interval"].to_numpy(int)

    report: dict[str, Any] = {
        "status": None, "reasons": [], "framing": FRAMING, "features": FEATURES,
        "train_dates": train_dates, "test_dates": test_dates,
        "n_train_rows": len(train), "n_train_fires": int(ytr.sum()),
        "n_test_rows": len(test), "n_test_fires": int(yte.sum()),
        "test_fire_rate": float(yte.mean()) if len(test) else None,
        "best_C": None, "cv_pr_auc": None, "coefficients": None,
        "model": None, "brier_training_rate": None, "baselines": None, "best_baseline": None,
        "lift": _lift(test) if len(test) else [],
        "land_class_source": None,
        "library_versions": {"numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__,
                             "scikit-learn": sklearn.__version__},
        "seeds": {"bootstrap": BOOT_SEED},
    }
    if ytr.sum() < MIN_TRAIN_FIRES:
        report["reasons"].append(f"training has {int(ytr.sum())} fires; need at least {MIN_TRAIN_FIRES}")
    if yte.sum() == 0:
        report["reasons"].append("the locked test passes have no fires")
    if report["reasons"]:
        report["status"] = "not_run"
        return _round(report), None

    Xtr, Xte = _design(train), _design(test)
    search = GridSearchCV(
        _logit(), {"logisticregression__C": C_GRID}, scoring="average_precision", cv=GroupKFold(n_splits=5),
    )
    # Without metadata routing enabled, sklearn 1.9 forwards fit(groups=...) to the CV splitter.
    search.fit(Xtr, ytr, groups=train["block_id"].astype(str).to_numpy())
    p_model = search.predict_proba(Xte)[:, 1]
    b3 = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    b3_cols = ["fire_within_2km_interval", "hv_index_db"]
    b3.fit(train[b3_cols].to_numpy(float), ytr)
    scores = {
        "model": p_model,
        "B1": test["fire_within_2km_interval"].to_numpy(float),
        "B2": -test["hv_index_db"].to_numpy(float),
        "B3": b3.predict_proba(test[b3_cols].to_numpy(float))[:, 1],
    }
    passes, blocks = test["pass_date"].to_numpy(), test["block_id"].astype(str).to_numpy()
    ci = _block_ci(scores, yte, blocks)
    ap = {k: average_precision_score(yte, s) for k, s in scores.items()}
    cap = {k: _top10_capture(s, yte, passes) for k, s in scores.items()}
    best = max(["B1", "B2", "B3"], key=lambda k: ap[k])
    train_rate = float(ytr.mean())
    coef = search.best_estimator_.named_steps["logisticregression"].coef_[0]

    report.update({
        "best_C": search.best_params_["logisticregression__C"],
        "cv_pr_auc": search.best_score_,
        "coefficients": dict(zip(FEATURES, map(float, coef))),
        "model": {"pr_auc": ap["model"], "pr_auc_ci": ci["model"], "top10_capture": cap["model"],
                  "brier": brier_score_loss(yte, p_model)},
        "brier_training_rate": brier_score_loss(yte, np.full(len(yte), train_rate)),
        "baselines": {k: {"pr_auc": ap[k], "pr_auc_ci": ci[k], "top10_capture": cap[k]} for k in ("B1", "B2", "B3")},
        "best_baseline": {"id": best, "pr_auc": ap[best]},
    })
    low = ci["model"][0]
    passed = low is not None and low > ap[best]
    report["status"] = "passed" if passed else "not_passed"
    if not passed:
        report["reasons"].append(f"model PR-AUC lower bound {low:.3f} is not above best baseline {best} {ap[best]:.3f}")
    return _round(report), test.assign(risk_score=p_model)


def evaluate(panel: pd.DataFrame) -> dict[str, Any]:
    return _evaluate(panel)[0]


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")


# ---------------------------------------------------------------- self-test


def _rain_evidence(mock: pd.DataFrame, C: float) -> None:
    train = mock[~mock["pass_date"].isin(sorted(mock["pass_date"].unique())[-2:])].reset_index(drop=True)
    y = train["fire_next_interval"].to_numpy(int)
    X0 = _design(train)
    X1 = np.column_stack([X0, train["rain_interval_mm"].to_numpy(float)])
    ap0, ap1 = [], []
    print(f"Rain evidence (mock train rows, C={C}; rain not used by the model):")
    for f, (tr, va) in enumerate(GroupKFold(n_splits=5).split(X0, y, groups=train["block_id"].to_numpy())):
        m0 = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000)).fit(X0[tr], y[tr])
        m1 = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000)).fit(X1[tr], y[tr])
        ap0.append(average_precision_score(y[va], m0.predict_proba(X0[va])[:, 1]))
        ap1.append(average_precision_score(y[va], m1.predict_proba(X1[va])[:, 1]))
        rc = m1.named_steps["logisticregression"].coef_[0][-1]
        print(f"  fold {f + 1}: rain coef {rc:+.4f} ({'+' if rc > 0 else '-'}), PR-AUC without {ap0[-1]:.4f}, with {ap1[-1]:.4f}")
    print(f"  mean CV PR-AUC without rain {np.mean(ap0):.4f}, with rain {np.mean(ap1):.4f}")


def _tiny_inputs() -> tuple:
    dates = ["2026-06-22", "2026-07-04", "2026-07-16", "2026-07-28", "2026-08-09", "2026-08-21", "2026-09-02"]
    kept = ["2026-06-22", "2026-07-04", "2026-07-16", "2026-08-21", "2026-09-02"]  # 07-28, 08-09: no radar
    context = {"dates": dates, "rain_interval_mm": [5.0, 7.0, 1.0, None, 2.0, 3.0]}
    grid = pd.DataFrame({
        "cell_id": ["c0", "c1", "c2", "c3", "c4", "c5"],
        "row": [0, 0, 0, 0, 1, 0], "col": [0, 1, 12, 40, 0, 99],
        "canal_density_km_per_km2": [0.5] * 6,
        "x_center": [0.0, 1500.0, 5000.0, 40000.0, 0.0, 100000.0],
        "y_center": [0.0, 0.0, 0.0, 0.0, 1500.0, 0.0],
    })
    fires = pd.DataFrame({"cell_id": grid["cell_id"]})
    for k in range(6):
        fires[f"fires_int_{k}"] = 0
    fires.loc[4, "fires_int_0"] = 1  # c4: before its first row
    fires.loc[1, "fires_int_1"] = 2  # c1: in its first target interval
    fires.loc[2, "fires_int_3"] = 1  # c2: inside the Jul-Aug gap
    recs = [(c, d, 0.1 * ci - kept.index(d)) for ci, c in enumerate(grid["cell_id"]) for d in kept]
    stats = pd.DataFrame(recs, columns=["cell_id", "date", "D_hv"])
    stats.loc[(stats.cell_id == "c0") & (stats.date == "2026-08-21"), "D_hv"] = np.nan
    stats = pd.concat([stats, pd.DataFrame([("c3", "2026-07-28", 99.0)], columns=stats.columns)], ignore_index=True)
    lcdf = pd.DataFrame({"cell_id": grid["cell_id"], "label_map": "forest", "cover_pred": "degraded"})
    return context, {"kept_dates": kept}, stats, fires, grid, lcdf


def _check_build_panel(mock_cols: list[str]) -> None:
    context, quality, stats, fires, grid, lcdf = _tiny_inputs()
    panel, info = build_panel(context, quality, stats, fires, grid, lcdf, {"status": "used"})
    assert list(panel.columns) == mock_cols == PANEL_COLUMNS
    assert info == {"land_class_source": "cover_pred", "n_skipped_missing_hv": 1}, info
    assert (panel["land_class"] == "degraded").all()
    rows = {(r.cell_id, r.pass_date): r for r in panel.itertuples()}
    want = {("c0", "2026-07-04"), ("c1", "2026-07-04"), ("c2", "2026-07-04"), ("c3", "2026-07-04"), ("c5", "2026-07-04"),
            ("c0", "2026-07-16"), ("c2", "2026-07-16"), ("c3", "2026-07-16"), ("c5", "2026-07-16"),
            ("c3", "2026-08-21"), ("c5", "2026-08-21")}
    assert set(rows) == want, sorted(set(rows) ^ want)
    gap = rows[("c2", "2026-07-16")]
    assert gap.target_interval_end == "2026-08-21" and gap.target_interval_days == 36 and gap.fire_next_interval == 1
    assert rows[("c1", "2026-07-04")].fire_next_interval == 1
    assert panel["fire_next_interval"].sum() == 2
    # B1 looks only at the interval that just ended.
    assert rows[("c0", "2026-07-04")].fire_within_2km_interval == 1  # c4 at 1.5 km, interval 0
    assert rows[("c1", "2026-07-04")].fire_within_2km_interval == 0  # c4 at 2.12 km
    assert rows[("c0", "2026-07-16")].fire_within_2km_interval == 1  # c1 at 1.5 km, interval 1
    assert rows[("c2", "2026-07-16")].fire_within_2km_interval == 0
    assert rows[("c3", "2026-08-21")].fire_within_2km_interval == 0
    assert abs(rows[("c0", "2026-07-04")].dist_prior_fire_km - 1.5) < 1e-9
    assert abs(rows[("c2", "2026-07-04")].dist_prior_fire_km - math.hypot(5, 1.5)) < 1e-3
    assert rows[("c3", "2026-07-04")].dist_prior_fire_km == 30.0 and rows[("c5", "2026-08-21")].dist_prior_fire_km == 30.0
    assert abs(rows[("c3", "2026-08-21")].hv_index_change_db - (-3 - (-2))) < 1e-9  # 07-16 -> 08-21, not 07-28
    assert abs(rows[("c3", "2026-07-04")].hv_index_db - (0.3 - 1)) < 1e-9
    assert rows[("c0", "2026-07-04")].rain_interval_mm == 5.0
    assert pd.isna(rows[("c3", "2026-08-21")].rain_interval_mm)
    assert (panel["block_id"][panel.cell_id == "c2"] == "b0001").all() and (panel["block_id"][panel.cell_id == "c3"] == "b0004").all()

    no_fire = fires.assign(**{c: 0 for c in fires.columns if c.startswith("fires_int_")})
    p2, info2 = build_panel(context, quality, stats, no_fire, grid, lcdf, {"status": "not_used"})
    assert info2["land_class_source"] == "label_map" and (p2["land_class"] == "forest").all()
    assert (p2["dist_prior_fire_km"] == 30.0).all() and p2["fire_within_2km_interval"].sum() == 0


def _synthetic(rng: np.random.Generator, n_cells: int = 600, test_fires: bool = True) -> pd.DataFrame:
    passes = ["2026-07-04", "2026-07-16", "2026-08-21", "2026-09-02", "2026-09-14", "2026-09-26", "2026-10-08", "2026-10-20"]
    rows = []
    for p in passes:
        hv, chg = rng.normal(0, 1, n_cells), rng.normal(0, 1, n_cells)
        # Fires depend on both hv index and its change, so the hv-only baselines cannot match the model.
        fire = ((hv + chg) < -2.0).astype(int)
        if not test_fires and p in passes[-2:]:
            fire[:] = 0
        rows.append(pd.DataFrame({
            "cell_id": [f"s{i:04d}" for i in range(n_cells)], "block_id": [f"b{i % 30:04d}" for i in range(n_cells)],
            "pass_date": p, "target_interval_end": p, "target_interval_days": 12,
            "land_class": rng.choice(["forest", "degraded", "plantation", "built"], n_cells),
            "canal_density_km_per_km2": rng.uniform(0, 2, n_cells), "hv_index_db": hv, "hv_index_change_db": chg,
            "dist_prior_fire_km": 30.0, "rain_interval_mm": 10.0, "fire_within_2km_interval": 0, "fire_next_interval": fire,
        }))
    return pd.concat(rows, ignore_index=True)[PANEL_COLUMNS]


def run_self_test() -> int:
    """Offline checks; writes only to a temp directory."""
    mock = pd.read_csv(PROJECT_ROOT / "ml/mock/fire_risk_mock.csv", dtype={"cell_id": str, "block_id": str})
    colab = pd.read_csv(PROJECT_ROOT / "ml/Firerisk/fire_risk_hindcast.csv", dtype={"cell_id": str})

    with warnings.catch_warnings():
        warnings.simplefilter("error", (DeprecationWarning, FutureWarning))
        rep, scored = _evaluate(mock)
    assert rep["status"] == "not_passed", (rep["status"], rep["reasons"])
    assert rep["n_test_rows"] == 1869 and rep["n_test_fires"] == 74, (rep["n_test_rows"], rep["n_test_fires"])
    assert abs(rep["model"]["pr_auc"] - 0.145) <= 0.03, rep["model"]
    assert rep["best_baseline"]["id"] in ("B3", "B2"), rep["best_baseline"]
    j = scored.merge(colab, on=["cell_id", "pass_date"], suffixes=("", "_colab"), validate="one_to_one")
    assert len(j) == 1869, len(j)
    rho = float(spearmanr(j["risk_score"], j["risk_score_colab"]).statistic)
    assert rho >= 0.9, rho
    lift = {q["quintile"]: q for q in rep["lift"]}
    assert lift[1]["rate"] > lift[5]["rate"], rep["lift"]
    with tempfile.TemporaryDirectory() as td:
        write_report(rep, Path(td) / "r.json")
        assert json.loads((Path(td) / "r.json").read_text(encoding="utf-8"))["framing"] == FRAMING

    _rain_evidence(mock, rep["best_C"])

    rng = np.random.default_rng(1)
    syn = evaluate(_synthetic(rng))
    assert syn["status"] == "passed", syn
    nr = evaluate(_synthetic(rng, test_fires=False))
    assert nr["status"] == "not_run" and nr["reasons"] and nr["lift"], nr

    _check_build_panel(list(mock.columns))

    m, bb, b = rep["model"], rep["best_baseline"], rep["baselines"]
    print(
        f"07b_fire_risk self-test: passed (mock: model PR-AUC {m['pr_auc']:.3f} [Colab 0.145], "
        f"B3 {b['B3']['pr_auc']:.3f} [0.142], B2 {b['B2']['pr_auc']:.3f} [0.139], B1 {b['B1']['pr_auc']:.3f} [0.047]; "
        f"best baseline {bb['id']}; model CI {m['pr_auc_ci'][0]:.3f}-{m['pr_auc_ci'][1]:.3f} [low 0.103]; "
        f"top-10% capture {m['top10_capture']:.3f} vs {b[bb['id']]['top10_capture']:.3f} [0.365 vs 0.311]; "
        f"test {rep['n_test_rows']} rows / {rep['n_test_fires']} fires [1,869 / 74]; "
        f"lift Q1 {lift[1]['rate']:.1%} vs Q5 {lift[5]['rate']:.1%} [11.9% vs 0%]; best C {rep['best_C']} [0.3]; "
        f"Spearman vs Colab {rho:.3f}; synthetic passed; no-test-fire not_run; build_panel checks ok)"
    )
    return 0


# ---------------------------------------------------------------- CLI


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    d = PROJECT_ROOT / "data"
    ap = argparse.ArgumentParser(description=f"Fire-risk {FRAMING}: panel, L2 logistic model, baselines.")
    ap.add_argument("--context", type=Path, default=d / "context_summary.json")
    ap.add_argument("--quality", type=Path, default=d / "quality_report.json")
    ap.add_argument("--stats", type=Path, default=d / "cell_stats.parquet")
    ap.add_argument("--fires", type=Path, default=d / "fires.parquet")
    ap.add_argument("--grid", type=Path, default=d / "grid_cells.parquet")
    ap.add_argument("--landclass", type=Path, default=d / "landclass.csv")
    ap.add_argument("--landclass-report", type=Path, default=d / "landclass_report.json")
    ap.add_argument("--out-panel", type=Path, default=d / "fire_risk_panel.csv")
    ap.add_argument("--report", type=Path, default=d / "fire_risk_report.json")
    ap.add_argument("--panel-only", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()

    def rj(p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8"))

    panel, info = build_panel(
        rj(args.context), rj(args.quality),
        pd.read_parquet(args.stats, columns=["cell_id", "date", "D_hv"]), pd.read_parquet(args.fires),
        pd.read_parquet(args.grid), pd.read_csv(args.landclass, dtype={"cell_id": str}), rj(args.landclass_report),
    )
    args.out_panel.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(args.out_panel, index=False)
    print(f"Panel: {len(panel)} rows, {int(panel['fire_next_interval'].sum())} fires, "
          f"{info['n_skipped_missing_hv']} rows skipped for missing D_hv; land class from {info['land_class_source']}")
    print(f"Saved {args.out_panel}")
    if args.panel_only:
        return 0

    report = evaluate(panel)
    report["land_class_source"] = info["land_class_source"]
    write_report(report, args.report)
    print(f"Fire-risk {FRAMING}: {report['status']}")
    for r in report["reasons"]:
        print(f"  - {r}")
    print(f"Saved {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
