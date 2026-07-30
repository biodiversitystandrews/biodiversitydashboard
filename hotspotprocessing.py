
"""Generate biodiversity and survey-effort hotspot GeoJSON layers.

The script summarises all dashboard Parquet records into a regular grid in
British National Grid coordinates (EPSG:27700). The newest habitat layer is
used as the University Estate analysis boundary unless an explicit boundary
file is supplied.
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

try:
    from shapely import make_valid
except ImportError:
    from shapely.validation import make_valid

from dashboard_standardisation import standardise_date_series


WGS84 = "EPSG:4326"
BRITISH_NATIONAL_GRID = "EPSG:27700"
DEFAULT_DATA_DIR = Path(__file__).parent / "data"
DEFAULT_BIODIVERSITY_OUTPUT = DEFAULT_DATA_DIR / "biodiversity_hotspots.geojson"
DEFAULT_EFFORT_OUTPUT = DEFAULT_DATA_DIR / "survey_effort_hotspots.geojson"
DEFAULT_BOUNDARY_OUTPUT = DEFAULT_DATA_DIR / "university_estate_boundary.geojson"


def polygon_parts(geometry):
    """Return every polygon contained in a polygonal or collection geometry."""
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon) or hasattr(geometry, "geoms"):
        parts = []
        for child in geometry.geoms:
            parts.extend(polygon_parts(child))
        return parts
    return []


def repair_boundary_geometry(geometry):
    """Repair one boundary feature and discard non-polygonal components."""
    if geometry is None or geometry.is_empty:
        return None

    repaired = make_valid(geometry) if not geometry.is_valid else geometry
    parts = polygon_parts(repaired)
    if not parts:
        return None

    polygon = parts[0] if len(parts) == 1 else unary_union(parts)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return None if polygon.is_empty else polygon


def parse_arguments():
    """Read command-line paths and grid settings."""
    parser = argparse.ArgumentParser(
        description="Generate biodiversity and survey-effort hotspot layers."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--boundary",
        type=Path,
        default=None,
        help="Optional boundary file; otherwise the newest habitat layer is used.",
    )
    parser.add_argument(
        "--biodiversity-output",
        type=Path,
        default=DEFAULT_BIODIVERSITY_OUTPUT,
    )
    parser.add_argument("--effort-output", type=Path, default=DEFAULT_EFFORT_OUTPUT)
    parser.add_argument(
        "--boundary-output",
        type=Path,
        default=DEFAULT_BOUNDARY_OUTPUT,
        help="Combined estate boundary output used by browser analysis.",
    )
    parser.add_argument(
        "--cell-size",
        type=float,
        default=100.0,
        help="Grid-cell width and height in metres (default: 100).",
    )
    return parser.parse_args()


def load_observation_data(data_dir):
    """Load and combine all dashboard Parquet observation files."""
    parquet_files = sorted(data_dir.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No Parquet files found in {data_dir}")

    frames = []
    for parquet_file in parquet_files:
        frame = pd.read_parquet(parquet_file)
        frame["_source_file"] = parquet_file.name
        frames.append(frame)
        print(f"Loaded {len(frame):,} rows from {parquet_file.name}")

    observations = pd.concat(frames, ignore_index=True, sort=False)

    if "Taxa" in observations.columns and "taxa" not in observations.columns:
        observations = observations.rename(columns={"Taxa": "taxa"})

    required = {"species", "latitude", "longitude"}
    missing = sorted(required - set(observations.columns))
    if missing:
        raise ValueError(
            "Observation data is missing required columns: " + ", ".join(missing)
        )

    observations["latitude"] = pd.to_numeric(
        observations["latitude"], errors="coerce"
    )
    observations["longitude"] = pd.to_numeric(
        observations["longitude"], errors="coerce"
    )
    observations = observations.dropna(subset=["latitude", "longitude", "species"])
    observations = observations[
        observations["latitude"].between(-90, 90)
        & observations["longitude"].between(-180, 180)
    ].copy()

    if "Date" in observations.columns:
        observations["_survey_date"] = standardise_date_series(
            observations["Date"]
        ).dt.strftime("%Y-%m-%d")
    else:
        observations["_survey_date"] = pd.NA

    if "taxa" not in observations.columns:
        observations["taxa"] = pd.NA
    if "obs" not in observations.columns:
        observations["obs"] = pd.NA

    if observations.empty:
        raise ValueError("No observations with valid species and coordinates remain.")

    return observations


def load_boundary(boundary_path, data_dir):
    """Load an explicit boundary or use the newest habitat estate layer."""
    selected_path = boundary_path
    boundary_source = "explicit_estate_boundary"

    if selected_path is not None and not selected_path.is_file():
        raise FileNotFoundError(f"Explicit boundary file not found: {selected_path}")

    if selected_path is None:
        habitat_files = sorted(data_dir.glob("habitats_*.geojson"))
        if not habitat_files:
            habitat_files = sorted(data_dir.glob("habitats*.geojson"))
        if not habitat_files:
            raise FileNotFoundError(
                "No explicit estate boundary or habitat estate layer was found."
            )

        selected_path = habitat_files[-1]
        boundary_source = f"habitat_estate_boundary:{selected_path.name}"
        print(f"Using habitat estate boundary: {selected_path.name}")

    boundary = gpd.read_file(selected_path)
    boundary = boundary[boundary.geometry.notna()].copy()
    boundary = boundary[~boundary.geometry.is_empty].copy()
    if boundary.empty:
        raise ValueError(f"Boundary file contains no usable geometry: {selected_path}")

    if boundary.crs is None:
        print(f"WARNING: {selected_path.name} has no CRS; assuming EPSG:4326.")
        boundary = boundary.set_crs(WGS84)

    boundary = boundary.to_crs(BRITISH_NATIONAL_GRID)
    invalid_count = int((~boundary.geometry.is_valid).sum())
    boundary["geometry"] = boundary.geometry.map(repair_boundary_geometry)
    boundary = boundary[boundary.geometry.notna()].copy()
    if boundary.empty:
        raise ValueError(
            f"Boundary file contains no repairable polygon geometry: {selected_path}"
        )
    if invalid_count:
        print(f"Repaired {invalid_count} invalid boundary geometries.")

    if hasattr(boundary.geometry, "union_all"):
        try:
            boundary_geometry = boundary.geometry.union_all(grid_size=0.01)
        except TypeError:
            boundary_geometry = boundary.geometry.union_all()
    else:
        boundary_geometry = boundary.geometry.unary_union

    if boundary_geometry.is_empty:
        raise ValueError("The combined boundary geometry is empty.")

    return boundary_geometry, boundary_source


def build_grid(boundary_geometry, cell_size):
    """Create square cells clipped to the selected estate boundary."""
    if cell_size <= 0:
        raise ValueError("Cell size must be greater than zero.")

    min_x, min_y, max_x, max_y = boundary_geometry.bounds
    cells = []
    cell_ids = []
    cell_id = 0

    for x in np.arange(min_x, max_x, cell_size):
        for y in np.arange(min_y, max_y, cell_size):
            cell = box(x, y, x + cell_size, y + cell_size)
            if not cell.intersects(boundary_geometry):
                continue

            clipped = cell.intersection(boundary_geometry)
            if clipped.is_empty:
                continue

            cells.append(clipped)
            cell_ids.append(cell_id)
            cell_id += 1

    if not cells:
        raise ValueError("No grid cells intersect the selected boundary.")

    return gpd.GeoDataFrame(
        {"cell_id": cell_ids, "geometry": cells},
        geometry="geometry",
        crs=BRITISH_NATIONAL_GRID,
    )


def build_observation_points(observations):
    """Convert observation coordinates into projected point geometry."""
    points = gpd.GeoDataFrame(
        observations.copy(),
        geometry=gpd.points_from_xy(
            observations["longitude"], observations["latitude"]
        ),
        crs=WGS84,
    )
    return points.to_crs(BRITISH_NATIONAL_GRID)


def percentile_rank(series):
    """Return tie-aware percentile ranks while preserving missing values."""
    result = pd.Series(np.nan, index=series.index, dtype="float64")
    usable = series.notna()
    if usable.any():
        result.loc[usable] = series.loc[usable].rank(
            method="average", pct=True
        ) * 100
    return result


def summarise_grid(grid, points, boundary_source, cell_size):
    """Calculate biodiversity and recording-effort metrics for every grid cell."""
    columns = [
        "species",
        "taxa",
        "obs",
        "_survey_date",
        "geometry",
    ]
    joined = gpd.sjoin(
        points[columns],
        grid[["cell_id", "geometry"]],
        how="inner",
        predicate="within",
    )

    result = grid.set_index("cell_id").copy()
    result["records"] = 0
    result["unique_species"] = 0
    result["taxa_groups"] = 0
    result["survey_days"] = 0
    result["observers"] = 0

    if not joined.empty:
        grouped = joined.groupby("cell_id", observed=True)
        result.loc[grouped.size().index, "records"] = grouped.size()
        result.loc[grouped["species"].nunique().index, "unique_species"] = (
            grouped["species"].nunique()
        )
        result.loc[grouped["taxa"].nunique().index, "taxa_groups"] = grouped[
            "taxa"
        ].nunique()
        result.loc[grouped["_survey_date"].nunique().index, "survey_days"] = grouped[
            "_survey_date"
        ].nunique()
        result.loc[grouped["obs"].nunique().index, "observers"] = grouped[
            "obs"
        ].nunique()

    integer_columns = [
        "records",
        "unique_species",
        "taxa_groups",
        "survey_days",
        "observers",
    ]
    result[integer_columns] = result[integer_columns].fillna(0).astype("int64")

    result["biodiversity_index"] = np.where(
        result["records"] > 0,
        result["unique_species"] / result["records"],
        np.nan,
    )
    result["effort_percentile"] = percentile_rank(result["records"])
    result["survey_days_percentile"] = percentile_rank(result["survey_days"])

    sufficient_evidence = (result["records"] >= 5) & (result["survey_days"] >= 2)
    result["biodiversity_percentile"] = np.nan
    result["richness_percentile"] = np.nan
    result.loc[sufficient_evidence, "biodiversity_percentile"] = percentile_rank(
        result.loc[sufficient_evidence, "biodiversity_index"]
    )
    result.loc[sufficient_evidence, "richness_percentile"] = percentile_rank(
        result.loc[sufficient_evidence, "unique_species"]
    )
    result["biodiversity_category"] = "insufficient_data"
    result.loc[
        sufficient_evidence & (result["biodiversity_percentile"] < 40),
        "biodiversity_category",
    ] = "lower"
    result.loc[
        sufficient_evidence
        & result["biodiversity_percentile"].between(40, 74.999999),
        "biodiversity_category",
    ] = "moderate"
    result.loc[
        sufficient_evidence & (result["biodiversity_percentile"] >= 75),
        "biodiversity_category",
    ] = "high"

    result["effort_category"] = "lower"
    result.loc[result["effort_percentile"] >= 40, "effort_category"] = "moderate"
    result.loc[result["effort_percentile"] >= 75, "effort_category"] = "high"

    result["boundary_source"] = boundary_source
    result["cell_size_metres"] = float(cell_size)
    result = result.reset_index()
    return result


def prepare_output(grid_summary, output_type):
    """Select ordered public fields and convert geometry back to EPSG:4326."""
    common_columns = [
        "cell_id",
        "records",
        "unique_species",
        "taxa_groups",
        "survey_days",
        "observers",
        "biodiversity_index",
        "biodiversity_percentile",
        "richness_percentile",
        "effort_percentile",
        "survey_days_percentile",
        "biodiversity_category",
        "effort_category",
        "boundary_source",
        "cell_size_metres",
        "geometry",
    ]
    output = grid_summary[common_columns].copy()
    output["hotspot_type"] = output_type
    return output.to_crs(WGS84)


def save_geojson(gdf, output_path):
    """Write one generated hotspot layer as GeoJSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(output_path, driver="GeoJSON", index=False)
    print(f"Saved {len(gdf):,} cells to {output_path}")


def save_estate_boundary(boundary_geometry, boundary_source, output_path):
    """Save the combined habitat estate as one browser-ready boundary feature."""
    boundary = gpd.GeoDataFrame(
        {
            "boundary_source": [boundary_source],
            "geometry": [boundary_geometry],
        },
        geometry="geometry",
        crs=BRITISH_NATIONAL_GRID,
    ).to_crs(WGS84)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    boundary.to_file(output_path, driver="GeoJSON", index=False)
    print(f"Saved combined estate boundary to {output_path}")


def main():
    """Generate both hotspot outputs from the current dashboard data."""
    args = parse_arguments()
    observations = load_observation_data(args.data_dir)
    boundary_geometry, boundary_source = load_boundary(
        args.boundary,
        args.data_dir,
    )
    save_estate_boundary(
        boundary_geometry,
        boundary_source,
        args.boundary_output,
    )
    grid = build_grid(boundary_geometry, args.cell_size)
    points = build_observation_points(observations)
    summary = summarise_grid(
        grid,
        points,
        boundary_source,
        args.cell_size,
    )

    biodiversity = prepare_output(summary, "biodiversity")
    effort = prepare_output(summary, "survey_effort")
    save_geojson(biodiversity, args.biodiversity_output)
    save_geojson(effort, args.effort_output)

    print(
        f"Hotspot processing complete: {len(observations):,} observations, "
        f"{len(grid):,} grid cells, boundary={boundary_source}."
    )


if __name__ == "__main__":
    main()
