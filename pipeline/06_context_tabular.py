import concurrent.futures
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path

from dotenv import load_dotenv
import earthaccess
import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import box

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")
FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY")
EARTHDATA_TOKEN = os.getenv("EARTHDATA_TOKEN")


def load_inputs():
    cells_path = DATA_DIR / "grid_cells.parquet"
    dates_path = DATA_DIR / "kept_dates.json"

    df_cells = pd.read_parquet(cells_path)
    with open(dates_path, "r", encoding="utf-8") as f:
        dates = json.load(f)

    return df_cells, dates


REPEAT_DAYS = 12  # NISAR repeat cycle


def pass_calendar(kept_dates):
    """Every 12-day pass from the first to the last kept date, including passes with no radar data.

    Contract rule 4 of the design doc: a pass that was never acquired (the 27 Jul - 10 Aug 2026 NISAR gap)
    keeps its slot, so fire and rain are counted per real 12-day interval and the timeline stays honest.
    """
    first = datetime.strptime(kept_dates[0], "%Y-%m-%d")
    last = datetime.strptime(kept_dates[-1], "%Y-%m-%d")
    n = (last - first).days // REPEAT_DAYS
    cal = [(first + timedelta(days=REPEAT_DAYS * i)).strftime("%Y-%m-%d") for i in range(n + 1)]
    off = sorted(set(kept_dates) - set(cal))
    if off:
        raise ValueError(f"Kept dates not on the 12-day pass calendar: {off}")
    return cal


def fetch_firms_chunk(source, bbox_str, date_str, day_range=5):
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_MAP_KEY}/{source}/{bbox_str}/{day_range}/{date_str}"
    """Detections for one 5-day window, an empty frame when there were none, or None when the request failed."""
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200 or "latitude" not in resp.text[:500]:
            print(f"[WARN] FIRMS {source} {date_str}: HTTP {resp.status_code} {resp.text[:120]!r}")
            return None
        df = pd.read_csv(io.StringIO(resp.text))
        df["source"] = source
        return df
    except Exception as exc:
        print(f"[WARN] FIRMS {source} {date_str}: {exc}")
        return None


def fetch_firms_fires(bbox, start_date_str, end_date_str):
    # FIRMS moves older days from _NRT to _SP (standard processing); per sensor the two never overlap,
    # so querying both covers the whole season without double counting.
    sources = ["VIIRS_NOAA20_NRT", "VIIRS_NOAA20_SP", "VIIRS_NOAA21_NRT", "VIIRS_NOAA21_SP"]
    bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"

    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")

    query_dates = []
    curr = end_dt
    while curr >= start_dt:
        query_dates.append(curr.strftime("%Y-%m-%d"))
        curr -= timedelta(days=5)

    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for src in sources:
            for q_date in query_dates:
                tasks.append(executor.submit(fetch_firms_chunk, src, bbox_str, q_date, 5))

        frames = []
        failed = 0
        for future in concurrent.futures.as_completed(tasks):
            res = future.result()
            if res is None:
                failed += 1
            elif not res.empty:
                frames.append(res)

    # A failed window would silently read as "no fire" and change the states, so stop instead.
    if failed:
        raise RuntimeError(f"{failed} of {len(tasks)} FIRMS requests failed; fire counts would be incomplete.")

    if not frames:
        return gpd.GeoDataFrame(columns=["latitude", "longitude", "acq_date", "geometry"], crs="EPSG:4326")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["latitude", "longitude", "acq_date", "acq_time"])
    combined["acq_date"] = pd.to_datetime(combined["acq_date"]).dt.strftime("%Y-%m-%d")

    gdf = gpd.GeoDataFrame(
        combined,
        geometry=gpd.points_from_xy(combined.longitude, combined.latitude),
        crs="EPSG:4326",
    )
    return gdf


def process_fire_spatial_joins(df_cells, gdf_fires, dates):
    cell_geoms = [box(r.x_min, r.y_min, r.x_max, r.y_max) for r in df_cells.itertuples()]
    gdf_cells = gpd.GeoDataFrame(df_cells[["cell_id"]], geometry=cell_geoms, crs="EPSG:32749")

    gdf_fires_utm = gdf_fires.to_crs(epsg=32749) if not gdf_fires.empty else gdf_fires
    direct_fires = gdf_fires_utm.copy()

    buffered_fires = gdf_fires_utm.copy()
    if not buffered_fires.empty:
        buffered_fires["geometry"] = buffered_fires.geometry.buffer(187.5)

    n_intervals = len(dates) - 1
    fire_counts = {f"fires_int_{k}": [0] * len(df_cells) for k in range(n_intervals)}
    adjacent_flags = {f"adjacent_fire_{k}": [False] * len(df_cells) for k in range(n_intervals)}
    fires_region = [0] * n_intervals

    cell_id_to_idx = {cid: idx for idx, cid in enumerate(df_cells["cell_id"])}

    for k in range(n_intervals):
        d_start = dates[k]
        d_end = dates[k + 1]

        # Half-open (d_start, d_end], like the rain intervals: a fire on a pass date counts once, not twice.
        mask = (gdf_fires_utm["acq_date"] > d_start) & (gdf_fires_utm["acq_date"] <= d_end)
        int_fires_direct = direct_fires[mask]
        int_fires_buf = buffered_fires[mask]

        fires_region[k] = len(int_fires_direct)

        if not int_fires_direct.empty:
            joined_direct = gpd.sjoin(int_fires_direct, gdf_cells, how="inner", predicate="intersects")
            for cid in joined_direct["cell_id"]:
                idx = cell_id_to_idx.get(cid)
                if idx is not None:
                    fire_counts[f"fires_int_{k}"][idx] += 1

        if not int_fires_buf.empty:
            joined_buf = gpd.sjoin(int_fires_buf, gdf_cells, how="inner", predicate="intersects")
            for cid in joined_buf["cell_id"]:
                idx = cell_id_to_idx.get(cid)
                if idx is not None:
                    adjacent_flags[f"adjacent_fire_{k}"][idx] = True

    df_out = pd.DataFrame({"cell_id": df_cells["cell_id"]})
    for k in range(n_intervals):
        df_out[f"fires_int_{k}"] = fire_counts[f"fires_int_{k}"]
        df_out[f"adjacent_fire_{k}"] = adjacent_flags[f"adjacent_fire_{k}"]
        df_out[f"fire_count_{dates[k]}_{dates[k+1]}"] = fire_counts[f"fires_int_{k}"]

    df_out["total_fires"] = df_out[[f"fires_int_{k}" for k in range(n_intervals)]].sum(axis=1)
    return df_out, fires_region


def fetch_daily_rainfall(bbox, start_date, end_date):
    lat_mid = (bbox[1] + bbox[3]) / 2.0
    lon_mid = (bbox[0] + bbox[2]) / 2.0

    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat_mid:.2f}&longitude={lon_mid:.2f}&"
        f"start_date={start_date}&end_date={end_date}&"
        f"daily=precipitation_sum&timezone=UTC"
    )
    # Open-Meteo archive: ERA5-family reanalysis at the box centre, about 5 days behind real time. Not IMERG.
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Open-Meteo archive returned HTTP {resp.status_code}: {resp.text[:200]}")
    daily = resp.json().get("daily", {})
    times = daily.get("time", [])
    rain = daily.get("precipitation_sum", [])
    # A missing day stays missing (None), never 0 mm.
    return {t: float(v) for t, v in zip(times, rain) if v is not None}


def compute_rainfall_metrics(dates, bbox):
    if EARTHDATA_TOKEN:
        os.environ["EARTHDATA_TOKEN"] = EARTHDATA_TOKEN
        try:
            earthaccess.login(strategy="environment")
        except Exception:
            pass

    first_dt = datetime.strptime(dates[0], "%Y-%m-%d") - timedelta(days=5)
    last_dt = datetime.strptime(dates[-1], "%Y-%m-%d") + timedelta(days=1)
    daily_rain = fetch_daily_rainfall(bbox, first_dt.strftime("%Y-%m-%d"), last_dt.strftime("%Y-%m-%d"))

    rain_3d_mm = []
    for d_str in dates:
        dt = datetime.strptime(d_str, "%Y-%m-%d")
        three_days = [(dt - timedelta(days=i)).strftime("%Y-%m-%d") for i in (1, 2, 3)]
        rain_3d_mm.append(_sum_or_none(daily_rain, three_days))

    rain_interval_mm = []
    for k in range(len(dates) - 1):
        d0 = datetime.strptime(dates[k], "%Y-%m-%d")
        d1 = datetime.strptime(dates[k + 1], "%Y-%m-%d")
        days = []
        cur = d0 + timedelta(days=1)
        while cur <= d1:
            days.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        rain_interval_mm.append(_sum_or_none(daily_rain, days))

    return rain_3d_mm, rain_interval_mm


def _sum_or_none(daily_rain, days):
    """Total over the days, or None if any day has no value (the contract's null, not a guessed 0)."""
    if any(day not in daily_rain for day in days):
        return None
    return round(sum(daily_rain[day] for day in days), 2)


def main():
    print("[1/4] Loading input grid cells and kept dates...")
    df_cells, kept_dates = load_inputs()
    dates = pass_calendar(kept_dates)
    missing = [d for d in dates if d not in kept_dates]
    if missing:
        print(f"      Passes with no radar data (kept as dropped slots): {missing}")
    bbox = [
        float(df_cells["lon"].min()),
        float(df_cells["lat"].min()),
        float(df_cells["lon"].max()),
        float(df_cells["lat"].max()),
    ]
    print(f"      Grid cells: {len(df_cells)} | Dates ({len(dates)}): {dates[0]} to {dates[-1]}")
    print(f"      Study bbox: [{bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f}]")

    print("[2/4] Querying NASA FIRMS VIIRS Active Fires (NOAA-20 & NOAA-21)...")
    gdf_fires = fetch_firms_fires(bbox, dates[0], dates[-1])
    print(f"      Total FIRMS fire detections in bbox: {len(gdf_fires)}")

    print("[3/4] Performing spatial joins and aggregating per cell & interval...")
    df_fires, fires_region = process_fire_spatial_joins(df_cells, gdf_fires, dates)
    fires_path = DATA_DIR / "fires.parquet"
    df_fires.to_parquet(fires_path, index=False)
    print(f"      Saved {fires_path} ({len(df_fires)} cells, total fire occurrences: {df_fires['total_fires'].sum()})")

    print("[4/4] Ingesting Open-Meteo archive rainfall (ERA5-family reanalysis)...")
    rain_3d_mm, rain_interval_mm = compute_rainfall_metrics(dates, bbox)

    summary = {
        "dates": dates,
        # 08_export copies these into manifest.sources so the app names the providers actually used.
        "rain_source": "Open-Meteo historical weather archive (ERA5-family reanalysis), daily precipitation_sum at the box centre",
        "fire_source": "NASA FIRMS area API, VIIRS NOAA-20 and NOAA-21, NRT and SP",
        "rain_3d_mm": rain_3d_mm,
        "rain_3day_mm": rain_3d_mm,
        "rain_interval_mm": rain_interval_mm,
        "fires_region": fires_region,
        "total_regional_fires": int(sum(fires_region)),
        "intervals": [
            {"index": k, "start": dates[k], "end": dates[k + 1], "fires": fires_region[k], "rain_mm": rain_interval_mm[k]}
            for k in range(len(dates) - 1)
        ],
    }

    summary_path = DATA_DIR / "context_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"      Saved {summary_path}")
    print("=== 06_context_tabular.py execution complete ===")


if __name__ == "__main__":
    main()
