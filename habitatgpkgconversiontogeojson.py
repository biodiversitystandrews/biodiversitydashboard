"""Convert one all-years habitat GeoPackage into year-specific GeoJSON files."""

import argparse
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd


# Accepted alternatives for the ecological/survey year column.
YEAR_COLUMN_NAMES = ("year", "school_year", "survey_year", "sampling_year", "samp_year")
YEAR_PATTERN = re.compile(r"^(?P<start>\d{4})\s*[-_/]\s*(?P<end>\d{2}|\d{4})$")


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
    return gdf


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
