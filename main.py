import os
import sys
import gzip
import pandas as pd
import numpy as np
import re
from functools import lru_cache
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response, JSONResponse
from typing import Optional, List
from pathlib import Path
from math import ceil, floor
from threading import Lock
from scipy.stats import entropy
from dashboard_standardisation import standardise_date_series

app = FastAPI(title="Biodiversity Dashboard", version="1.0.0")

origins = [
    "https://biodiversitydashboard-ls.netlify.app",
    "https://biodiversitydashboard-new.netlify.app",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress larger API responses before sending them to the browser.
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.head("/")
def read_root_head():
    return Response(status_code=200)

DATA_PATH = Path(__file__).parent / "data"

# Static map files only change when new data is deployed, so loading them once
# avoids repeatedly reading and encoding the same JSON for every visitor.
@lru_cache(maxsize=32)
def load_static_json(filename: str) -> bytes:
    return (DATA_PATH / filename).read_bytes()


def static_json_response(filename: str, missing_message: str):
    """Return a cached JSON file with short-lived browser caching enabled."""
    file_path = DATA_PATH / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=missing_message)
    return Response(
        content=load_static_json(filename),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=300"},
    )

_cached_df = None
_dataframe_lock = Lock()

MAP_COLUMNS = [
    "id",
    "english_name",
    "species",
    "obs",
    "Date",
    "taxa",
    "latitude",
    "longitude",
]

POLYGON_ANALYSIS_COLUMNS = [
    "english_name",
    "species",
    "obs",
    "Date",
    "taxa",
    "latitude",
    "longitude",
]

MAP_AGGREGATION_THRESHOLD = 10_000
MAP_GRID_DEGREES = 0.001

def get_dataframe() -> pd.DataFrame:
    """Return the shared DataFrame, loading it once even under concurrent calls."""
    global _cached_df
    if _cached_df is not None:
        return _cached_df

    with _dataframe_lock:
        if _cached_df is None:
            _cached_df = load_dataframe_from_disk()
    return _cached_df


def load_dataframe_from_disk() -> pd.DataFrame:
    """Load, standardise, and optimise all dashboard Parquet records."""
    print("Cache is empty. Loading data from disk...")
    parquet_files = list(DATA_PATH.glob("*.parquet"))
    if not parquet_files:
        raise HTTPException(status_code=500, detail="No parquet data files found on server.")

    try:
        frames = [pd.read_parquet(file) for file in parquet_files]
        dataframe = pd.concat(frames, ignore_index=True)

        if "Taxa" in dataframe.columns:
            dataframe = dataframe.rename(columns={"Taxa": "taxa"})

        if "Date" in dataframe.columns:
            dataframe["Date"] = standardise_date_series(dataframe["Date"])
            dataframe["month"] = dataframe["Date"].dt.month

        if "year" in dataframe.columns:
            dataframe["year"] = dataframe["year"].astype("category")

        for column in ["english_name", "species", "obs", "taxa"]:
            if column in dataframe.columns:
                dataframe[column] = dataframe[column].astype("category")

        if "count" in dataframe.columns:
            dataframe["count"] = pd.to_numeric(dataframe["count"], errors="coerce")
        if "id" not in dataframe.columns:
            dataframe.reset_index(inplace=True)
            dataframe = dataframe.rename(columns={"index": "id"})

        print("Data loaded and cached successfully.")
        return dataframe
    except Exception as error:
        print(f"Error loading data: {error}", file=sys.stderr)
        raise HTTPException(
            status_code=500,
            detail="Could not load or process data files.",
        ) from error


def prepare_map_dataframe(
    query_df: pd.DataFrame,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Select and clean the fields required by map and polygon interfaces."""
    selected_columns = columns or MAP_COLUMNS
    map_df = query_df.dropna(subset=["latitude", "longitude"]).copy()
    map_df = map_df[selected_columns]
    return (
        map_df.replace([np.inf, -np.inf], None)
        .astype(object)
        .where(pd.notnull(map_df), None)
    )


def aggregate_map_dataframe(map_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate large overview maps while retaining drill-down cell bounds."""
    if len(map_df) <= MAP_AGGREGATION_THRESHOLD:
        map_df["is_aggregate"] = False
        map_df["record_count"] = 1
        map_df["unique_species"] = map_df["species"].notna().astype("int64")
        return map_df

    working = map_df.copy()
    working["taxa"] = working["taxa"].astype(object).where(
        working["taxa"].notna(),
        "Unknown",
    )
    working["grid_latitude"] = (
        np.floor(pd.to_numeric(working["latitude"]) / MAP_GRID_DEGREES)
        * MAP_GRID_DEGREES
    )
    working["grid_longitude"] = (
        np.floor(pd.to_numeric(working["longitude"]) / MAP_GRID_DEGREES)
        * MAP_GRID_DEGREES
    )

    grouped = working.groupby(
        ["grid_latitude", "grid_longitude", "taxa"],
        observed=True,
        dropna=False,
    )
    aggregated = grouped.agg(
        id=("id", "first"),
        english_name=("english_name", "first"),
        species=("species", "first"),
        obs=("obs", "first"),
        Date=("Date", "max"),
        record_count=("id", "size"),
        unique_species=("species", "nunique"),
    ).reset_index()
    aggregated["latitude"] = aggregated["grid_latitude"] + MAP_GRID_DEGREES / 2
    aggregated["longitude"] = aggregated["grid_longitude"] + MAP_GRID_DEGREES / 2
    aggregated["bbox_west"] = aggregated["grid_longitude"]
    aggregated["bbox_south"] = aggregated["grid_latitude"]
    aggregated["bbox_east"] = aggregated["grid_longitude"] + MAP_GRID_DEGREES
    aggregated["bbox_north"] = aggregated["grid_latitude"] + MAP_GRID_DEGREES
    aggregated["is_aggregate"] = True
    return aggregated.drop(columns=["grid_latitude", "grid_longitude"])


@lru_cache(maxsize=1)
def get_polygon_analysis_payload() -> bytes:
    """Serialise the unfiltered polygon dataset once per API process."""
    map_df = prepare_map_dataframe(get_dataframe(), POLYGON_ANALYSIS_COLUMNS)
    map_df["Date"] = pd.to_datetime(map_df["Date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    return map_df.to_json(
        orient="values",
    ).encode("utf-8")


@lru_cache(maxsize=1)
def get_compressed_polygon_analysis_payload() -> bytes:
    """Compress the polygon payload once instead of once per visitor."""
    return gzip.compress(get_polygon_analysis_payload(), compresslevel=6)

def apply_filters(
    query_df: pd.DataFrame,
    english_name: Optional[str] = None,
    species: Optional[str] = None,
    obs: Optional[str] = None,
    taxa: Optional[str] = None,
    year: Optional[str] = None, 
    month: Optional[int] = None,
    bbox: Optional[str] = None,
) -> pd.DataFrame:
    if english_name:
        query_df = query_df[query_df["english_name"].isin(english_name.split(","))]
    if species:
        query_df = query_df[query_df["species"].isin(species.split(","))]
    if obs:
        query_df = query_df[query_df["obs"].isin(obs.split(","))]
    if taxa:
        query_df = query_df[query_df["taxa"].isin(taxa.split(","))]
    
    if year:
        query_df = query_df[query_df["year"] == year]

    if month:
        query_df = query_df[query_df["month"] == int(month)]
    if bbox:
        try:
            xmin, ymin, xmax, ymax = map(float, bbox.split(','))
            query_df = query_df[
                (query_df['longitude'] >= xmin) &
                (query_df['longitude'] <= xmax) &
                (query_df['latitude'] >= ymin) &
                (query_df['latitude'] <= ymax)
            ]
        except (ValueError, IndexError):
            pass
    return query_df

def _get_options(df_source: pd.DataFrame, key_name: str):
    return sorted(df_source[key_name].dropna().unique().tolist())

@app.get("/")
def root():
    return {"status": "ok", "message": "Biodiversity Dashboard API root"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/api/management_years")
def get_management_years():
    years = []
    pattern = re.compile(r"management_(\d{4}-\d{2})\.geojson")
    for f in DATA_PATH.glob("management_*.geojson"):
        match = pattern.match(f.name)
        if match:
            years.append(match.group(1))
    return sorted(years, reverse=True)

@app.get("/api/management_points")
def get_management_points(year: str):
    return static_json_response(
        f"management_{year}.geojson",
        f"Management data for year {year} not found.",
    )

@app.get("/api/cameratrap_years")
def get_cameratrap_years():
    years = []
    pattern = re.compile(r"cameratraps_(\d{4}-\d{2})\.geojson")
    for f in DATA_PATH.glob("cameratraps_*.geojson"):
        match = pattern.match(f.name)
        if match:
            years.append(match.group(1))
    return sorted(years, reverse=True)

@app.get("/api/cameratrap_points")
def get_cameratrap_points(year: str):
    return static_json_response(
        f"cameratraps_{year}.geojson",
        f"Camera trap data for year {year} not found.",
    )

@app.get("/api/habitat_polygons")
def get_habitat_polygons(year: Optional[str] = "2024-25"):
    return static_json_response(
        f"habitats_{year}.geojson",
        f"Habitat data for year {year} not found.",
    )


@app.get("/api/estate-boundary")
def get_estate_boundary():
    """Return the pre-unioned University Estate habitat boundary."""
    return static_json_response(
        "university_estate_boundary.geojson",
        "The combined University Estate boundary has not been generated yet.",
    )

@app.get("/api/summary/habitat")
def get_habitat_summary():
    return static_json_response(
        "habitat_summary.json",
        "Habitat summary file not found.",
    )


@app.get("/api/hotspots/{metric}")
def get_hotspots(metric: str):
    """Return a precomputed biodiversity or survey-effort hotspot layer."""
    hotspot_files = {
        "biodiversity": "biodiversity_hotspots.geojson",
        "effort": "survey_effort_hotspots.geojson",
    }
    filename = hotspot_files.get(metric.lower())
    if filename is None:
        raise HTTPException(
            status_code=400,
            detail="Metric must be either 'biodiversity' or 'effort'.",
        )
    return static_json_response(
        filename,
        f"The {metric} hotspot layer has not been generated yet.",
    )

@app.get("/api/all_unique_species")
def get_all_unique_species(page: int = 1, page_size: int = 10):
    df = get_dataframe()
    all_unique_species = sorted(df['species'].dropna().unique().tolist())
    total_species = len(all_unique_species)
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    paginated_species = all_unique_species[start_index:end_index]
    return {
        "species_list": paginated_species,
        "total_records": total_species,
        "page": page,
        "total_pages": ceil(total_species / page_size)
    }

@app.get("/api/filter-options")
def get_filter_options(
    english_name: Optional[str] = None,
    species: Optional[str] = None,
    obs: Optional[str] = None,
    taxa: Optional[str] = None,
    year: Optional[str] = None,
    month: Optional[str] = None,
):
    base_df = get_dataframe()
    options = {}
    temp_df = apply_filters(base_df, species=species, obs=obs, taxa=taxa, year=year, month=month)
    options["english_name"] = _get_options(temp_df, "english_name")
    temp_df = apply_filters(base_df, english_name=english_name, obs=obs, taxa=taxa, year=year, month=month)
    options["species"] = _get_options(temp_df, "species")
    temp_df = apply_filters(base_df, english_name=english_name, species=species, taxa=taxa, year=year, month=month)
    options["obs"] = _get_options(temp_df, "obs")
    temp_df = apply_filters(base_df, english_name=english_name, species=species, obs=obs, year=year, month=month)
    options["taxa"] = _get_options(temp_df, "taxa")
    temp_df = apply_filters(base_df, english_name=english_name, species=species, obs=obs, taxa=taxa, month=month)
    options["year"] = _get_options(temp_df, "year")
    temp_df = apply_filters(base_df, english_name=english_name, species=species, obs=obs, taxa=taxa, year=year)
    options["month"] = _get_options(temp_df, "month")
    return options

@app.get("/api/records")
def get_records(
    page: int = 1,
    page_size: int = 100,
    english_name: Optional[str] = None,
    species: Optional[str] = None,
    obs: Optional[str] = None,
    taxa: Optional[str] = None,
    year: Optional[str] = None,
    month: Optional[int] = None,
    bbox: Optional[str] = None,
):
    df = get_dataframe()
    df.sort_values(by=['Date', 'species', 'id'], ascending=[True, True, True], inplace=True)
    query_df = apply_filters(df, english_name, species, obs, taxa, year, month, bbox)
    total_records = len(query_df)
    paginated_data = query_df.iloc[(page - 1) * page_size : page * page_size].copy()
    paginated_data = (
        paginated_data.replace([np.inf, -np.inf], None)
        .astype(object)
        .where(pd.notnull(paginated_data), None)
    )
    return jsonable_encoder(
        {
            "total_records": total_records,
            "page": page,
            "total_pages": int(np.ceil(total_records / page_size)),
            "records": paginated_data.to_dict(orient="records"),
        }
    )

@app.get("/api/record_page")
def get_record_page(
    record_id: int,
    page_size: int = 100,
    english_name: Optional[str] = None,
    species: Optional[str] = None,
    obs: Optional[str] = None,
    taxa: Optional[str] = None,
    year: Optional[str] = None,
    month: Optional[int] = None,
    bbox: Optional[str] = None,
):
    df = get_dataframe()
    df.sort_values(by=['Date', 'species', 'id'], ascending=[True, True, True], inplace=True)
    query_df = apply_filters(df, english_name, species, obs, taxa, year, month, bbox)
    try:
        sorted_ids = query_df['id'].tolist()
        position = sorted_ids.index(record_id)
        page = floor(position / page_size) + 1
        return {"page": page}
    except (ValueError, IndexError):
        raise HTTPException(status_code=404, detail="Record not found in the current filter context.")

@app.get("/api/map_data")
def get_map_data(
    english_name: Optional[str] = None,
    species: Optional[str] = None,
    obs: Optional[str] = None,
    taxa: Optional[str] = None,
    year: Optional[str] = None,
    month: Optional[int] = None,
    bbox: Optional[str] = None,
):
    df = get_dataframe()
    query_df = apply_filters(df, english_name, species, obs, taxa, year, month, bbox)
    map_df = prepare_map_dataframe(query_df)
    map_df = aggregate_map_dataframe(map_df)
    records = map_df.to_dict(orient="records")
    return JSONResponse(content=jsonable_encoder(records))


@app.get("/api/polygon-analysis-data")
def get_polygon_analysis_data(request: Request):
    """Return a cached compact dataset for the dedicated polygon tool."""
    accepts_gzip = "gzip" in request.headers.get("accept-encoding", "").lower()
    headers = {"Cache-Control": "public, max-age=300"}
    payload = get_polygon_analysis_payload()
    if accepts_gzip:
        payload = get_compressed_polygon_analysis_payload()
        headers["Content-Encoding"] = "gzip"

    return Response(
        content=payload,
        media_type="application/json",
        headers=headers,
    )

@app.get("/api/summary/diversity")
def get_diversity_summary(
    english_name: Optional[str] = None,
    species: Optional[str] = None,
    obs: Optional[str] = None,
    taxa: Optional[str] = None,
    year: Optional[str] = None,
    month: Optional[int] = None,
    bbox: Optional[str] = None,
):
    df = get_dataframe()
    query_df = apply_filters(df, english_name, species, obs, taxa, year, month, bbox)
    
    if query_df.empty:
        return {"shannon": 0, "simpson": 0, "species_richness": 0, "total_records": 0}

    use_count_column = "count" in query_df.columns and query_df["count"].notna().sum() > (len(query_df) / 2)

    if use_count_column:
        species_counts = query_df.groupby("species", observed=True)["count"].sum()
    else:
        species_counts = query_df.groupby("species", observed=True).size()

    species_richness = len(species_counts)
    shannon_index = 0
    gini_simpson_index = 0

    if not species_counts.empty and species_counts.sum() > 0 and species_richness > 1:
        proportions = species_counts[species_counts > 0] / species_counts.sum()
        shannon_index = entropy(proportions, base=np.e)
        gini_simpson_index = 1 - (proportions**2).sum()

    return {
        "shannon": round(float(shannon_index), 3),
        "simpson": round(float(gini_simpson_index), 3),
        "species_richness": int(species_richness),
        "total_records": len(query_df)
    }

@app.get("/api/summary/annual_trends")
def get_annual_trends():
    df = get_dataframe()
    if 'year' not in df.columns or df['year'].isnull().all():
        return {"trends": []}

    yearly_data = []
    for year, group in sorted(df.groupby('year', observed=True), key=lambda x: x[0]):
        total_records = len(group)
        
        use_count_column = "count" in group.columns and group["count"].notna().sum() > (len(group) / 2)

        if use_count_column:
            species_counts = group.groupby("species", observed=True)["count"].sum()
        else:
            species_counts = group.groupby("species", observed=True).size()

        species_richness = len(species_counts)
        shannon_index = 0
        gini_simpson_index = 0

        if not species_counts.empty and species_counts.sum() > 0 and species_richness > 1:
            proportions = species_counts[species_counts > 0] / species_counts.sum()
            shannon_index = entropy(proportions, base=np.e)
            gini_simpson_index = 1 - (proportions**2).sum()

        yearly_data.append({
            "year": year, 
            "total_records": int(total_records),
            "unique_species": int(species_richness),
            "shannon": round(float(shannon_index), 3),
            "simpson": round(float(gini_simpson_index), 3),
        })
    
    return {"trends": yearly_data}

@app.get("/api/summary/species_distribution")
def get_species_distribution(
    english_name: Optional[str] = None,
    species: Optional[str] = None,
    obs: Optional[str] = None,
    taxa: Optional[str] = None,
    year: Optional[str] = None,
    month: Optional[int] = None,
    bbox: Optional[str] = None,
):
    df = get_dataframe()
    query_df = apply_filters(df, english_name, species, obs, taxa, year, month, bbox)
    if query_df.empty:
        return []
    species_counts = query_df['english_name'].value_counts()
    top_20_names = species_counts.nlargest(20).index.tolist()
    top_20_df = query_df[query_df['english_name'].isin(top_20_names)]
    taxa_map = top_20_df.groupby('english_name', observed=True)['taxa'].first()
    result = []
    for name in top_20_names:
        result.append({
            "name": name,
            "count": int(species_counts[name]),
            "taxa": taxa_map.get(name, "Unknown")
        })
    return result

@app.get("/api/summary/temporal_trends")
def get_temporal_trends(
    english_name: Optional[str] = None,
    species: Optional[str] = None,
    obs: Optional[str] = None,
    taxa: Optional[str] = None,
    year: Optional[str] = None,
    month: Optional[int] = None,
    bbox: Optional[str] = None,
):
    df = get_dataframe()
    query_df = apply_filters(df, english_name, species, obs, taxa, year, month, bbox)
    if query_df.empty:
        return {}
    summary = query_df.groupby("month").size().reindex(range(1, 13), fill_value=0)
    return summary.to_dict()

@app.get("/api/summary/observer_comparison")
def get_observer_comparison(
    english_name: Optional[str] = None,
    species: Optional[str] = None,
    obs: Optional[str] = None,
    taxa: Optional[str] = None,
    year: Optional[str] = None,
    month: Optional[int] = None,
    bbox: Optional[str] = None,
):
    if not obs:
        return {}
    df = get_dataframe()
    query_df = apply_filters(df, english_name, species, taxa=taxa, year=year, month=month, bbox=bbox)
    query_df = query_df[query_df["obs"].isin(obs.split(","))]
    if query_df.empty:
        return {}
    comparison = query_df.groupby(["obs", "taxa"], observed=True).size().unstack(fill_value=0)
    return comparison.to_dict(orient="dict")

@app.get("/api/summary/observer/{observer_name}")
def get_observer_stats(
    observer_name: str,
    english_name: Optional[str] = None,
    species: Optional[str] = None,
    taxa: Optional[str] = None,
    year: Optional[str] = None,
    month: Optional[int] = None,
    bbox: Optional[str] = None,
):
    df = get_dataframe()
    query_df = apply_filters(df, english_name, species, None, taxa, year, month, bbox)
    observer_df = query_df[query_df["obs"] == observer_name]
    if observer_df.empty:
        return {}
    specialization = observer_df.groupby('taxa', observed=True).size().sort_values(ascending=False)
    other_breakdown = {}
    if len(specialization) > 20:
        top_20 = specialization.head(20)
        other_taxa = specialization.tail(-20)
        other_sum = other_taxa.sum()
        if other_sum > 0:
            other_breakdown = other_taxa.to_dict()
            other_series = pd.Series([other_sum], index=['Other'])
            specialization = pd.concat([top_20, other_series])
    return {
        "specialization": specialization.to_dict(),
        "other_breakdown": other_breakdown
    }
