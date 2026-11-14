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

    fires_path = base_dir / "fires.parquet"
    context_path = base_dir / "context_summary.json"
    grid_cells_path = base_dir / "grid_cells.parquet"
    cell_stats_path = base_dir / "cell_stats.parquet"
    noise_floor_path = base_dir / "noise_floor.json"
    coherence_path = base_dir / "coherence.parquet"

    df_fires = pd.read_parquet(fires_path)
    with open(context_path, "r", encoding="utf-8") as f:
        context_summary = json.load(f)

    df_grid_cells = pd.read_parquet(grid_cells_path)
    df_cell_stats = pd.read_parquet(cell_stats_path)

    with open(noise_floor_path, "r", encoding="utf-8") as f:
        noise_floor = json.load(f)

    df_coherence = pd.read_parquet(coherence_path)

    return {
        "df_fires": df_fires,
        "context_summary": context_summary,
        "df_grid_cells": df_grid_cells,
        "df_cell_stats": df_cell_stats,
        "noise_floor": noise_floor,
        "df_coherence": df_coherence,
    }


def main():
    data = load_pipeline_data()
    print(f"fires.parquet: {len(data['df_fires'])} rows")
    print(f"context_summary.json: {len(data['context_summary'].get('dates', []))} dates")
    print(f"grid_cells.parquet: {len(data['df_grid_cells'])} rows")
    print(f"cell_stats.parquet: {len(data['df_cell_stats'])} rows")
    print(f"noise_floor.json: {len(data['noise_floor'].get('per_date', []))} date records")
    print(f"coherence.parquet: {len(data['df_coherence'])} rows")


if __name__ == "__main__":
    main()
