"""Convert one all-years habitat GeoPackage into year-specific GeoJSON files."""

import argparse
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

try:
    from shapely import make_valid
except ImportError:
    from shapely.validation import make_valid


# Accepted alternatives for the ecological/survey year column.
YEAR_COLUMN_NAMES = ("year", "school_year", "survey_year", "sampling_year", "samp_year")
YEAR_PATTERN = re.compile(r"^(?P<start>\d{4})\s*[-_/]\s*(?P<end>\d{2}|\d{4})$")


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


def repair_habitat_geometry(geometry):
    """Repair one habitat geometry and retain only its polygonal components."""
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


def clean_habitat_geometries(gdf):
    """Remove empty locations and repair invalid habitat polygons."""
    missing_count = int(gdf.geometry.isna().sum())
    non_missing = gdf[gdf.geometry.notna()].copy()
    empty_count = int(non_missing.geometry.is_empty.sum())
    non_empty = non_missing[~non_missing.geometry.is_empty].copy()
    invalid_count = int((~non_empty.geometry.is_valid).sum())

    non_empty["geometry"] = non_empty.geometry.map(repair_habitat_geometry)
    unusable_count = int(non_empty.geometry.isna().sum())
    cleaned = non_empty[non_empty.geometry.notna()].copy()

    if missing_count or empty_count:
        print(
            "Warning: removed "
            f"{missing_count} missing and {empty_count} empty habitat geometries."
        )
    if invalid_count:
        print(f"Repaired {invalid_count} invalid habitat geometries.")
    if unusable_count:
        print(
            f"Warning: removed {unusable_count} non-polygonal or unrepairable geometries."
        )
    if cleaned.empty:
        raise ValueError("No usable habitat polygon geometries remain.")
    return cleaned


def normalise_column_name(name):
    """Make a source column name comparable with the accepted alternatives."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def find_year_column(gdf):
    """Return the source column containing the habitat survey year."""
    normalised_columns = {
        normalise_column_name(column): column
        for column in gdf.columns
    }
    for candidate in YEAR_COLUMN_NAMES:
        if candidate in normalised_columns:
            return normalised_columns[candidate]
    raise ValueError(
        "No habitat year column was found. Expected one of: "
        + ", ".join(YEAR_COLUMN_NAMES)
    )


def normalise_year(value):
    """Convert common year formats such as 2025/26 and 2025-2026 to 2025-26."""
    if pd.isna(value):
        return None

    match = YEAR_PATTERN.fullmatch(str(value).strip())
    if not match:
        return None

    start = int(match.group("start"))
    end_text = match.group("end")
    end = int(end_text[-2:])
    expected_end = (start + 1) % 100
    if end != expected_end:
        return None
    return f"{start:04d}-{end:02d}"


def read_habitats(input_path):
    """Read habitat features and convert their geometry to web-map coordinates."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Source GeoPackage not found: {input_path}")

    gdf = gpd.read_file(input_path)
    if gdf.empty:
        raise ValueError("The habitat GeoPackage contains no features.")

    if gdf.crs is None:
        print("Warning: No CRS was recorded; assuming EPSG:4326.")
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")
    return clean_habitat_geometries(gdf)


def convert_all_years(input_gpkg_path, output_directory):
    """Write one habitats_YYYY-YY.geojson file for every valid input year."""
    input_path = Path(input_gpkg_path)
    output_dir = Path(output_directory)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("--- Starting all-years habitat conversion ---")
    print(f"Input GeoPackage: {input_path}")
    print(f"Output directory: {output_dir}")

    gdf = read_habitats(input_path)
    year_column = find_year_column(gdf)
    normalised_years = gdf[year_column].map(normalise_year)

    invalid_count = int(normalised_years.isna().sum())
    if invalid_count:
        invalid_examples = (
            gdf.loc[normalised_years.isna(), year_column]
            .drop_duplicates()
            .astype(str)
            .head(10)
            .tolist()
        )
        raise ValueError(
            f"{invalid_count} habitat feature(s) have a missing or invalid year. "
            f"Examples: {invalid_examples}"
        )

    gdf = gdf.copy()
    gdf["year"] = normalised_years
    generated_files = []

    for year, year_gdf in gdf.groupby("year", sort=True):
        output_path = output_dir / f"habitats_{year}.geojson"
        year_gdf.to_file(output_path, driver="GeoJSON")
        generated_files.append(output_path)
        print(f"Created {output_path} with {len(year_gdf)} feature(s).")

    print(f"Conversion complete: generated {len(generated_files)} annual file(s).")
    return generated_files


def parse_arguments():
    """Read command-line paths for the source package and output directory."""
    parser = argparse.ArgumentParser(
        description=(
            "Split an all-years habitat GeoPackage into annual GeoJSON files."
        )
    )
    parser.add_argument("input_gpkg", help="Path to the all-years habitat GPKG.")
    parser.add_argument(
        "output_directory",
        help="Directory in which habitats_YYYY-YY.geojson files are written.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    convert_all_years(arguments.input_gpkg, arguments.output_directory)
