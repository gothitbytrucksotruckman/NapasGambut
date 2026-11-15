"""Stage 4c: Model A, the radar land-cover classifier (forest, degraded, plantation, built).

Trains on weak map labels (ESA WorldCover + GFW concessions), gives each cell a
conformal set of cover classes (empty = radar can't tell), flags cells whose map
label looks out of date (confident learning), and maps the cover onto the
contract classes with stage 03's rules. A gate decides whether 08_export may use
the model's classes; the reasons always go in the report.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_features04b() -> Any:
    spec = importlib.util.spec_from_file_location(
        "landclass_features04b", Path(__file__).resolve().parent / "04b_landclass_features.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lcf = _load_features04b()
FEATURES = list(lcf.FEATURES)
assert not any(f.endswith("_mock") or "canal" in f for f in FEATURES), FEATURES

VERSION = "nisar_landclass_v1"
COVER_CLASSES = ["forest", "degraded", "plantation", "built"]
SEED = 20261114
CONFIDENCE_LEVEL = 0.9
GATES = {"min_block_cv_accuracy": 0.75, "min_check_coverage": 0.87, "min_clean_training_per_class": 20}
CALIB_FRACTION = 0.2
CHECK_FRACTION = 0.2
LABEL_SOURCES = ["ESA WorldCover 2021 v200", "GFW Indonesia oil palm and wood fibre concessions"]
OUTPUT_COLUMNS = [
    "cell_id", "label_map", "label_purity", "n_maps_agree", "clean", "split", "cover_pred",
    "cover_set", "set_size", "map_check", "class_map", "class_model",
]


def weak_labels(grid: pd.DataFrame) -> pd.DataFrame:
    """label_map, label_purity, n_maps_agree per cell from stage 03's map shares."""
    conc = grid["concession_fraction"].astype(float)
    built = grid["built_up_share"].astype(float)
    forest = grid["tree_cover_pct"].astype(float) / 100.0
    shares = pd.DataFrame({"forest": forest, "degraded": (1.0 - forest - built).clip(lower=0.0), "built": built})
    plant = conc >= 0.5
    return pd.DataFrame(
        {
            "cell_id": grid["cell_id"].astype(str),
            "label_map": np.where(plant, "plantation", shares.idxmax(axis=1)),
            "label_purity": np.where(plant, conc, shares.max(axis=1)),
            "n_maps_agree": 1 + np.where(plant, built < 0.2, conc < 0.2).astype(int),
        }
    )


def assign_splits(block_ids: pd.Series, seed: int = SEED) -> pd.Series:
    """Seeded block split: 20% calibration, 20% check, rest training (per cell)."""
    blocks = np.array(sorted(block_ids.astype(str).unique()))
    np.random.default_rng(seed).shuffle(blocks)
    n_cal = int(round(CALIB_FRACTION * len(blocks)))
    n_chk = int(round(CHECK_FRACTION * len(blocks)))
    split_of = {b: "calibration" for b in blocks[:n_cal]}
    split_of.update({b: "check" for b in blocks[n_cal : n_cal + n_chk]})
    split_of.update({b: "training" for b in blocks[n_cal + n_chk :]})
    return block_ids.astype(str).map(split_of)


def _make_model() -> Any:
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(class_weight="balanced", random_state=0)


def _proba_in(model: Any, X: np.ndarray, classes: np.ndarray) -> np.ndarray:
    """predict_proba re-indexed to `classes` (0 for classes the model never saw)."""
    out = np.zeros((len(X), len(classes)))
    p = model.predict_proba(X)
    for j, c in enumerate(model.classes_):
        out[:, list(classes).index(c)] = p[:, j]
    return out


def conformal_sets(model: Any, X_cal: np.ndarray, y_cal: np.ndarray, X: np.ndarray) -> np.ndarray:
    """LAC sets (n, len(model.classes_)) bool; calibration labels the model never saw are dropped."""
    from mapie.classification import SplitConformalClassifier

    keep = np.isin(y_cal, model.classes_)  # MAPIE raises on unseen labels; the gate already fails then
    scc = SplitConformalClassifier(
        estimator=model, confidence_level=CONFIDENCE_LEVEL, conformity_score="lac", prefit=True
    ).conformalize(X_cal[keep], y_cal[keep])
    # Set columns follow the label encoder fitted on estimator.classes_ (mapie/classification.py _get_classes_info).
    assert list(scc._mapie_classifier.classes_) == list(model.classes_)
    return scc.predict_set(X)[1][:, :, 0]


def _rate(hits: np.ndarray) -> dict[str, Any]:
    n = int(len(hits))
    return {"value": round(float(np.mean(hits)), 4) if n else None, "n": n}


def fit_landclass(df: pd.DataFrame, seed: int = SEED) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Train Model A and build per-cell cover sets and the gate report (no I/O)."""
    from cleanlab.filter import find_label_issues
    from sklearn.model_selection import GroupKFold

    df = df.reset_index(drop=True)
    X = df[FEATURES].to_numpy(dtype=np.float64)
    y = df["label_map"].astype(str).to_numpy()
    blocks = df["block_id"].astype(str).to_numpy()
    split = assign_splits(df["block_id"], seed).to_numpy()
    clean = ((df["label_purity"] >= 0.8) & (df["n_maps_agree"] >= 2)).to_numpy()
    # Only training is cleaned; calibration/check stay unfiltered or the LAC threshold collapses.
    train = clean & (split == "training")

    final = _make_model().fit(X[train], y[train])
    classes = final.classes_

    oof = np.zeros((len(df), len(classes)))
    for _, fold in GroupKFold(n_splits=5).split(X, y, groups=blocks):
        fit_mask = train.copy()
        fit_mask[fold] = False
        oof[fold] = _proba_in(_make_model().fit(X[fit_mask], y[fit_mask]), X[fold], classes)
    oof_pred = classes[np.argmax(oof, axis=1)]

    cal = split == "calibration"
    sets = conformal_sets(final, X[cal], y[cal], X)
    set_size = sets.sum(axis=1)
    cover_pred = classes[np.argmax(final.predict_proba(X), axis=1)]
    cover_set = ["|".join(c for c in COVER_CLASSES if c in set(classes[row])) for row in sets]
    in_set = np.array([lab in s.split("|") for lab, s in zip(y, cover_set)])

    known = np.isin(y, classes)
    issue = np.zeros(len(df), dtype=bool)
    issue[known] = find_label_issues(
        labels=np.searchsorted(classes, y[known]), pred_probs=oof[known], n_jobs=1
    )  # n_jobs=1: Windows spawn would re-import this module in every worker
    map_check = issue & (set_size == 1)

    chk = split == "check"
    metrics: dict[str, Any] = {
        "n_cells": int(len(df)),
        "n_clean": int(clean.sum()),
        "block_cv_accuracy": _rate(oof_pred[train] == y[train]),
        "check_coverage": _rate(in_set[chk]),
        "check_accuracy": _rate(cover_pred[chk] == y[chk]),
        "hand_accuracy": None,
        "hand_coverage": None,
        "clean_training_per_class": {c: int(((y == c) & train).sum()) for c in COVER_CLASSES},
        "blocks_per_split": {s: int(len(set(blocks[split == s]))) for s in ("training", "calibration", "check")},
        "cells_per_split": {s: int((split == s).sum()) for s in ("training", "calibration", "check")},
        "set_size_counts": {str(k): int(v) for k, v in sorted(pd.Series(set_size).value_counts().items())},
        "n_label_issues": int(issue.sum()),
        "n_map_check": int(map_check.sum()),
        "n_calibration_label_unseen_by_model": int((cal & ~known).sum()),
    }
    if "hand_label" in df.columns and df["hand_label"].notna().any():
        h = df["hand_label"].notna().to_numpy()
        hand = df["hand_label"].astype(str).to_numpy()
        metrics["hand_accuracy"] = _rate(cover_pred[h] == hand[h])
        metrics["hand_coverage"] = _rate(np.array([lab in s.split("|") for lab, s in zip(hand[h], np.array(cover_set)[h])]))

    reasons = []
    acc, cov = metrics["block_cv_accuracy"], metrics["check_coverage"]
    if acc["value"] is None or acc["value"] < GATES["min_block_cv_accuracy"]:
        reasons.append(f"block-CV accuracy {acc['value']} is below {GATES['min_block_cv_accuracy']} (n={acc['n']} clean training cells)")
    if cov["value"] is None or cov["value"] < GATES["min_check_coverage"]:
        reasons.append(f"check coverage {cov['value']} is below {GATES['min_check_coverage']} (n={cov['n']} check cells)")
    for c, k in metrics["clean_training_per_class"].items():
        if k < GATES["min_clean_training_per_class"]:
            reasons.append(f"class '{c}' has {k} clean training cells, fewer than {GATES['min_clean_training_per_class']}")

    import cleanlab
    import mapie
    import sklearn

    report = {
        "version": VERSION,
        "status": "not_used" if reasons else "used",
        "reasons": reasons,
        "confidence_level": CONFIDENCE_LEVEL,
        "gates": dict(GATES),
        "metrics": metrics,
        "library_versions": {"sklearn": sklearn.__version__, "mapie": mapie.__version__, "cleanlab": cleanlab.__version__},
        "seed": seed,
        "label_sources": list(LABEL_SOURCES),
    }
    per_cell = pd.DataFrame(
        {
            "cell_id": df["cell_id"].astype(str),
            "label_map": y,
            "label_purity": df["label_purity"],
            "n_maps_agree": df["n_maps_agree"],
            "clean": clean.astype(int),
            "split": split,
            "cover_pred": cover_pred,
            "cover_set": cover_set,
            "set_size": set_size.astype(int),
            "map_check": map_check.astype(int),
            "label_issue": issue,  # working column for the self-test; not written
        }
    )
    return per_cell, report


def _rule_class(cover: str, peat: float, canal: float, dam: float | None) -> str | None:
    # Mirrors 03_grid.py _classify_cell_six_rules, with the radar cover in place of the map's cover signals.
    if cover == "built":
        return "settlement"
    if cover == "plantation":
        return "plantation"
    if peat >= 0.5 and canal > 0.0 and dam is not None and dam <= 1000.0:
        return "rewetted"
    if peat >= 0.5 and (canal > 0.0 or cover != "forest"):
        return "drained"
    if peat >= 0.5 and cover == "forest" and canal == 0.0:
        return "intact_forest"
    return None


def cover_to_class(cells: pd.DataFrame) -> tuple[np.ndarray, int]:
    """class_model from class_map, cover_pred, set_size and stage 03's peat/canal/dam columns.

    Only confident cells (set_size == 1) are re-ruled; reference_forest is always kept.
    Returns the classes and how many confident cells kept the map class because no rule fit.
    """
    out, n_no_rule = [], 0
    for r in cells.itertuples(index=False):
        if r.class_map == "reference_forest" or r.set_size != 1:
            out.append(r.class_map)
            continue
        dam = None if pd.isna(r.nearest_dam_dist_m) else float(r.nearest_dam_dist_m)
        cls = _rule_class(r.cover_pred, float(r.peat_fraction), float(r.canal_length_m), dam)
        n_no_rule += cls is None
        out.append(r.class_map if cls is None else cls)
    return np.array(out, dtype=object), int(n_no_rule)


def update_provenance(path: Path, status: str, reasons: list[str], report_ref: str) -> dict[str, Any]:
    """Idempotent: map_class_source keeps the map's source; a failed run restores it."""
    prov = json.loads(path.read_text(encoding="utf-8"))
    prov.setdefault("map_class_source", prov.get("class_source"))
    prov["class_source"] = VERSION if status == "used" else prov["map_class_source"]
    prov["landclass"] = {"status": status, "reasons": list(reasons), "report": report_ref}
    path.write_text(json.dumps(prov, indent=2), encoding="utf-8")
    return prov


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def run_self_test() -> int:
    """Offline checks on the simulated table; writes only to a temp directory."""
    from mapie.classification import SplitConformalClassifier

    mock = pd.read_csv(PROJECT_ROOT / "ml/mock/landclass_cells_mock.csv", dtype={"cell_id": str, "block_id": str})
    colab = pd.read_csv(PROJECT_ROOT / "ml/Lancdclass/landclass_predictions.csv", dtype={"cell_id": str})

    per_cell, rep = fit_landclass(mock)
    m = rep["metrics"]
    acc, h_acc, h_cov = m["block_cv_accuracy"]["value"], m["hand_accuracy"]["value"], m["hand_coverage"]["value"]
    n_empty = m["set_size_counts"].get("0", 0)
    n_single = m["set_size_counts"].get("1", 0)
    assert 0.82 <= acc <= 0.90, acc
    assert h_acc >= 0.88 and m["hand_accuracy"]["n"] == 100, m["hand_accuracy"]
    # Decided 2026-11-15: calibrate on all calibration cells against map labels, so "90%" means agreement with
    # the maps. Map errors then push q near 1: sets grow, empty sets are rare and fewer singletons can be flagged,
    # so Colab's 18 empty / 982 single / 114 flags (cleaner calibration labels) are not targets here.
    assert 0.85 <= h_cov <= 0.99, h_cov
    assert n_empty <= 45 and n_single >= 600, m["set_size_counts"]
    assert 40 <= m["n_map_check"] <= 160, m["n_map_check"]
    joined = per_cell.merge(colab, on="cell_id", validate="one_to_one")
    assert len(joined) == len(mock)
    agree = float((joined["cover_pred"] == joined["class_pred"]).mean())
    assert agree >= 0.90, agree

    assert per_cell["split"].isin(["training", "calibration", "check"]).all()
    for s in ("calibration", "check"):
        assert (per_cell.loc[per_cell["split"] == s, "clean"] == 0).any(), s
    assert (per_cell.assign(block_id=mock["block_id"]).groupby("block_id")["split"].nunique() == 1).all()
    assert rep["status"] == "used", rep["reasons"]
    json.dumps(_json_safe(rep), allow_nan=False)

    # The known bug: calibrating only on cells cleanlab did not flag
    X = mock[FEATURES].to_numpy(dtype=np.float64)
    y = mock["label_map"].to_numpy()
    train = (per_cell["clean"] == 1).to_numpy() & (per_cell["split"] == "training").to_numpy()
    final = _make_model().fit(X[train], y[train])
    chk = (per_cell["split"] == "check").to_numpy()
    cal_bad = (per_cell["split"] == "calibration").to_numpy() & ~per_cell["label_issue"].to_numpy()
    bad_sets = SplitConformalClassifier(
        estimator=final, confidence_level=CONFIDENCE_LEVEL, conformity_score="lac", prefit=True
    ).conformalize(X[cal_bad], y[cal_bad]).predict_set(X[chk])[1][:, :, 0]
    bad_cov = float(np.mean(bad_sets[np.arange(chk.sum()), np.searchsorted(final.classes_, y[chk])]))
    good_cov = m["check_coverage"]["value"]
    print(f"regression demo: check coverage {good_cov} (unfiltered calibration) vs {bad_cov:.4f} (calibration minus cleanlab flags)")
    assert bad_cov < good_cov  # held on 9 of 9 split seeds tried, by 0.05 to 0.19

    shuffled = mock.copy()
    shuffled["label_map"] = np.random.default_rng(SEED).permutation(shuffled["label_map"].to_numpy())
    _, rep_bad = fit_landclass(shuffled)
    bad_acc = rep_bad["metrics"]["block_cv_accuracy"]["value"]
    assert rep_bad["status"] == "not_used"
    assert any(f"block-CV accuracy {bad_acc}" in r for r in rep_bad["reasons"]), rep_bad["reasons"]

    wl = weak_labels(
        pd.DataFrame(
            {
                "cell_id": ["a", "b", "c", "d"],
                "tree_cover_pct": [90.0, 10.0, 20.0, 30.0],
                "built_up_share": [0.0, 0.7, 0.3, 0.1],
                "concession_fraction": [0.1, 0.3, 0.6, 0.0],
            }
        )
    ).set_index("cell_id")
    assert wl["label_map"].tolist() == ["forest", "built", "plantation", "degraded"]
    assert np.allclose(wl["label_purity"], [0.9, 0.7, 0.6, 0.6])
    assert wl["n_maps_agree"].tolist() == [2, 1, 1, 2]

    rules = pd.DataFrame(
        [
            # class_map, cover_pred, set_size, peat, canal, dam -> expected
            ("reference_forest", "built", 1, 0.9, 0.0, None, "reference_forest"),
            ("drained", "built", 1, 0.9, 10.0, None, "settlement"),
            ("drained", "plantation", 1, 0.9, 10.0, None, "plantation"),
            ("drained", "forest", 1, 0.9, 50.0, 800.0, "rewetted"),
            ("intact_forest", "degraded", 1, 0.9, 0.0, None, "drained"),
            ("drained", "forest", 1, 0.9, 0.0, None, "intact_forest"),
            ("settlement", "forest", 0, 0.9, 0.0, None, "settlement"),
            ("plantation", "forest", 2, 0.9, 0.0, None, "plantation"),
            ("drained", "forest", 1, 0.2, 0.0, None, "drained"),  # no rule fits: keeps map class
        ],
        columns=["class_map", "cover_pred", "set_size", "peat_fraction", "canal_length_m", "nearest_dam_dist_m", "expected"],
    )
    got, n_no_rule = cover_to_class(rules)
    assert got.tolist() == rules["expected"].tolist(), got
    assert n_no_rule == 1

    with tempfile.TemporaryDirectory() as tmp:
        prov_path = Path(tmp) / "grid_provenance.json"
        prov_path.write_text(json.dumps({"class_source": "esa_map"}), encoding="utf-8")
        assert update_provenance(prov_path, "used", [], "r.json")["class_source"] == VERSION
        p2 = update_provenance(prov_path, "not_used", ["x"], "r.json")
        assert p2["class_source"] == "esa_map" and p2["map_class_source"] == "esa_map"
        assert p2["landclass"] == {"status": "not_used", "reasons": ["x"], "report": "r.json"}

    print(
        f"04c_landclass self-test: passed (block-CV acc {acc} n={m['block_cv_accuracy']['n']} [Colab 0.859], "
        f"hand acc {h_acc} / cov {h_cov} n={m['hand_accuracy']['n']} [Colab 0.92 / 0.89, n=100], "
        f"check cov {good_cov} acc {m['check_accuracy']['value']} n={m['check_coverage']['n']}, "
        f"sets empty {n_empty} single {n_single} [Colab 18 / 982], map_check {m['n_map_check']} [Colab 114], "
        f"agree with Colab {agree:.3f}, shuffled labels -> not_used at acc {bad_acc})"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Model A (radar land cover) with conformal sets and a gate.")
    parser.add_argument("--features", type=Path, default=PROJECT_ROOT / "data/landclass_features.csv")
    parser.add_argument("--grid", type=Path, default=PROJECT_ROOT / "data/grid_cells.parquet")
    parser.add_argument("--hand-labels", type=Path, default=None, help="optional CSV cell_id,hand_label")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data/landclass.csv")
    parser.add_argument("--report", type=Path, default=PROJECT_ROOT / "data/landclass_report.json")
    parser.add_argument("--provenance", type=Path, default=PROJECT_ROOT / "data/grid_provenance.json")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()

    rp = lcf.s04._resolve_path
    feats = pd.read_csv(rp(args.features), dtype={"cell_id": str, "block_id": str})
    grid = pd.read_parquet(rp(args.grid))
    grid["cell_id"] = grid["cell_id"].astype(str)
    df = feats.merge(weak_labels(grid), on="cell_id", how="left", validate="one_to_one")
    if df["label_map"].isna().any():
        raise ValueError(f"{int(df['label_map'].isna().sum())} feature cells are missing from {args.grid}.")
    if args.hand_labels is not None:
        if rp(args.hand_labels).exists():
            hand = pd.read_csv(rp(args.hand_labels), dtype={"cell_id": str})[["cell_id", "hand_label"]]
            df = df.merge(hand, on="cell_id", how="left", validate="one_to_one")
        else:
            print(f"No hand labels at {args.hand_labels}; skipping.")

    per_cell, report = fit_landclass(df)
    g = grid.set_index("cell_id").reindex(per_cell["cell_id"])
    per_cell["class_map"] = g["class"].to_numpy()
    per_cell["class_model"], report["metrics"]["n_kept_map_class_no_rule"] = cover_to_class(
        per_cell.assign(**{c: g[c].to_numpy() for c in ("peat_fraction", "canal_length_m", "nearest_dam_dist_m")})
    )

    out_path, report_path = rp(args.out), rp(args.report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    per_cell[OUTPUT_COLUMNS].to_csv(out_path, index=False)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(_json_safe(report), indent=2, allow_nan=False), encoding="utf-8")
    try:
        report_ref = report_path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        report_ref = str(report_path)
    update_provenance(rp(args.provenance), report["status"], report["reasons"], report_ref)

    print(f"Model A status: {report['status']}")
    for r in report["reasons"]:
        print(f"  - {r}")
    print(f"Saved {out_path}, {report_path}; updated {rp(args.provenance)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
