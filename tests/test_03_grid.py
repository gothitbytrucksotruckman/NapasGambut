import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "grid_mod", PROJECT_ROOT / "pipeline" / "03_grid.py"
)
grid_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grid_mod)


def test_grid_cells_parquet_has_real_canals_peat_and_concessions():
    parquet_path = PROJECT_ROOT / "data" / "grid_cells.parquet"
    prov_path = PROJECT_ROOT / "data" / "grid_provenance.json"
    assert parquet_path.exists()
    assert prov_path.exists()

    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    assert prov["canal_source"] == "osm_overpass"
    assert prov["peat_source"] == "gfw_indonesia_peat_lands"
    assert prov["concession_source"] == "gfw_indonesia_oil_palm_and_wood_fiber_concessions"

    df = pd.read_parquet(parquet_path)
    assert len(df) > 10000
    assert "peat_fraction" in df.columns
    assert "concession_fraction" in df.columns
    assert "canal_length_m" in df.columns
    assert "nearest_dam_dist_m" in df.columns

    assert df["peat_fraction"].min() >= 0.0
    assert df["peat_fraction"].max() <= 1.0
    assert (df["peat_fraction"] > 0.5).sum() > 1000

    assert df["concession_fraction"].min() >= 0.0
    assert df["concession_fraction"].max() <= 1.0
    assert (df["concession_fraction"] > 0.5).sum() > 100

    assert (df["canal_length_m"] > 0.0).sum() > 500


# AI-generated (lines 51-108)
def test_dry_run_and_empty_osm_fail_loudly_with_runtime_error(tmp_path):
    cfg = grid_mod.load_config(PROJECT_ROOT / "config.yaml")
    with pytest.raises(RuntimeError, match="Synthetic canal fallback"):
        grid_mod.build_spatial_grid(cfg, dry_run=True)

    with patch.object(grid_mod, "PROJECT_ROOT", tmp_path):
        with patch("requests.get", side_effect= RuntimeError("Overpass offline")):
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
# End AI-generated (lines 51-108)
