import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import LineString, Point, Polygon

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "grid_mod", PROJECT_ROOT / "pipeline" / "03_grid.py"
)
grid_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grid_mod)


def test_grid_cells_parquet_has_real_canals_peat_concessions_and_worldcover():
    parquet_path = PROJECT_ROOT / "data" / "grid_cells.parquet"
    prov_path = PROJECT_ROOT / "data" / "grid_provenance.json"
    assert parquet_path.exists()
    assert prov_path.exists()

    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    assert prov["canal_source"] == "osm_overpass"
    assert prov["peat_source"] == "gfw_indonesia_peat_lands"
    assert prov["concession_source"] == "gfw_indonesia_oil_palm_and_wood_fiber_concessions"
    assert prov["class_source"] == "esa_worldcover_2021_v200_and_gfw_peat_concessions"
    assert prov["tree_cover_source"] == "esa_worldcover_10m_2021_v200"
    assert prov["license"] == "CC BY 4.0"
    assert any("CC BY 4.0" in str(s.get("license")) for s in prov.get("sources", []))

    df = pd.read_parquet(parquet_path)
    assert len(df) > 5000
    for col in (
        "peat_fraction",
        "concession_fraction",
        "built_up_share",
        "tree_cover_pct",
        "canal_length_m",
        "nearest_dam_dist_m",
    ):
        assert col in df.columns

    valid_classes = {
        "drained",
        "rewetted",
        "plantation",
        "intact_forest",
        "reference_forest",
        "settlement",
    }
    assert set(df["class"].unique()).issubset(valid_classes)
    assert "other" not in set(df["class"].unique())


# AI-generated (lines 61-136)
def test_worldcover_bincount_and_six_first_match_rules():
    vals = np.full((100, 100), 10, dtype=np.uint8)
    vals[0:50, 0:50] = 50
    xs = np.arange(800005.0, 801005.0, 10.0, dtype=np.float64)
    ys = np.arange(9770995.0, 9769995.0, -10.0, dtype=np.float64)
    fake_da = xr.DataArray(vals, coords={"y": ys, "x": xs}, dims=("y", "x"))

    tree_pct, built_share, counts = grid_mod._compute_worldcover_cell_shares_bincount(
        fake_da, 800000.0, 9771000.0, 2, 2, 500.0
    )
    assert counts[0] == 2500
    assert pytest.approx(built_share[0], rel=1e-5) == 1.0
    assert pytest.approx(tree_pct[0], rel=1e-5) == 0.0
    assert pytest.approx(tree_pct[1], rel=1e-5) == 100.0

    assert grid_mod._classify_cell_six_rules(0.15, 0.0, 0.0, 0.0, None, 10.0, False) == "settlement"
    assert grid_mod._classify_cell_six_rules(0.02, 0.80, 0.80, 500.0, None, 40.0, False) == "plantation"
    assert grid_mod._classify_cell_six_rules(0.0, 0.0, 0.90, 400.0, 350.0, 45.0, False) == "rewetted"
    assert grid_mod._classify_cell_six_rules(0.0, 0.0, 0.90, 400.0, None, 80.0, False) == "drained"
    assert grid_mod._classify_cell_six_rules(0.0, 0.0, 0.90, 0.0, None, 92.0, True) == "reference_forest"
    assert grid_mod._classify_cell_six_rules(0.0, 0.0, 0.90, 0.0, None, 92.0, False) == "intact_forest"
    assert grid_mod._classify_cell_six_rules(0.0, 0.0, 0.10, 0.0, None, 40.0, False) is None


def test_dry_run_and_empty_osm_fail_loudly_with_runtime_error(tmp_path):
    cfg = grid_mod.load_config(PROJECT_ROOT / "config.yaml")
    with pytest.raises(RuntimeError, match="Synthetic canal fallback"):
        grid_mod.build_spatial_grid(cfg, dry_run=True)

    with patch.object(grid_mod, "PROJECT_ROOT", tmp_path):
        with patch("requests.get", side_effect=RuntimeError("Overpass offline")):
            with pytest.raises(RuntimeError, match="Failed to fetch real OSM canals"):
                grid_mod._fetch_osm_canals_utm([113.75, -2.25, 114.25, -1.75], epsg=32749)


def test_exact_canal_intersection_and_prims_sjoin_nearest(tmp_path):
    cell_poly = Polygon([(800000.0, 9770000.0), (800500.0, 9770000.0), (800500.0, 9770500.0), (800000.0, 9770500.0)])
    cells_gdf = gpd.GeoDataFrame({"cell_id": ["r000c000"]}, geometry=[cell_poly], crs="EPSG:32749")

    canal_line = LineString([(799900.0, 9770250.0), (800600.0, 9770250.0)])
    canals_gdf = gpd.GeoDataFrame({"waterway": ["canal"]}, geometry=[canal_line], crs="EPSG:32749")

    lengths = grid_mod._compute_exact_canal_lengths_utm(cells_gdf, canals_gdf)
    assert pytest.approx(lengths[0], rel=1e-5) == 500.0

    dam_pt = Point(800750.0, 9770250.0)
    dams_gdf = gpd.GeoDataFrame({"name": ["Dam-1"]}, geometry=[dam_pt], crs="EPSG:32749")
    joined = gpd.sjoin_nearest(
        cells_gdf[["cell_id", "geometry"]],
        dams_gdf[["geometry"]],
        how="left",
        distance_col="nearest_dam_dist_m",
    )
    assert pytest.approx(float(joined["nearest_dam_dist_m"].iloc[0]), rel=1e-5) == 250.0

    with patch.object(grid_mod, "PROJECT_ROOT", tmp_path):
        with patch.object(grid_mod, "_fetch_arcgis_geojson_paginated", return_value=[]):
            with pytest.warns(RuntimeWarning, match="BRGM PRIMS"):
                dams_out, ctx_out = grid_mod._fetch_prims_dams_utm(
                    [113.75, -2.25, 114.25, -1.75],
                    epsg=32749,
                    prims_urls=["https://example.com/prims/query"],
                )
                assert dams_out is None
                assert ctx_out == []
# End AI-generated (lines 61-136)
