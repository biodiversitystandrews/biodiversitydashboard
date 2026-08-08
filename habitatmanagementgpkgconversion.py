"""Convert habitat-management records into one GeoJSON file per sampling year."""

import argparse
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd


YEAR_ALIASES = ("year", "sampling_year", "survey_year", "school_year", "samp_year")
TARGET_CRS = "EPSG:4326"


def normalise_column_name(name):
    """Return a lowercase underscore form used to match alternative column names."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def find_column(gdf, aliases):
    """Find the first input column matching one of the supplied semantic aliases."""
    normalised = {normalise_column_name(column): column for column in gdf.columns}
    return next((normalised[name] for name in aliases if name in normalised), None)


def normalise_sampling_year(value):
    """Convert common sampling-year labels to YYYY-YY, returning None if invalid."""
    if pd.isna(value):
        return None
    match = re.fullmatch(r"\s*(\d{4})\s*[-/]\s*(\d{2}|\d{4})\s*", str(value))
    if not match:
        return None
    start = int(match.group(1))
    end_text = match.group(2)
    end = int(end_text) if len(end_text) == 4 else (start // 100) * 100 + int(end_text)
    if end != start + 1:
        return None
    return f"{start}-{str(end)[-2:]}"


def prepare_geodata(gdf):
    """Remove unusable geometries and transform valid records to web-map coordinates."""
    if gdf.crs is None:
        print("Warning: input CRS is missing; assuming EPSG:4326.")
        gdf = gdf.set_crs(TARGET_CRS)
    else:
        gdf = gdf.to_crs(TARGET_CRS)

    usable = ~gdf.geometry.is_empty & gdf.geometry.notna()
    if not usable.all():
        print(f"Warning: dropping {(~usable).sum()} records with missing or empty geometry.")
    return gdf.loc[usable].copy()


def convert_management_by_year(input_path, output_directory):
    """Read one management GeoPackage and write management_YYYY-YY GeoJSON files."""
    input_file = Path(input_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    gdf = prepare_geodata(gpd.read_file(input_file))
    year_column = find_column(gdf, YEAR_ALIASES)
    if year_column is None:
        raise ValueError(f"No sampling-year column found. Accepted names: {', '.join(YEAR_ALIASES)}")

    gdf["_output_year"] = gdf[year_column].map(normalise_sampling_year)
    invalid = gdf["_output_year"].isna()
    if invalid.any():
        examples = gdf.loc[invalid, year_column].astype("string").drop_duplicates().head(5).tolist()
        raise ValueError(f"Could not interpret {invalid.sum()} management year value(s): {examples}")

    output_dir = Path(output_directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for year, records in gdf.groupby("_output_year", sort=True):
        output_file = output_dir / f"management_{year}.geojson"
        records.drop(columns="_output_year").to_file(output_file, driver="GeoJSON")
        written.append(output_file)
        print(f"Saved {len(records):,} management records for {year}: {output_file}")
    return written


def main():
    """Parse command-line paths and run the annual management conversion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_gpkg", help="Input habitat-management GeoPackage.")
    parser.add_argument("output_directory", help="Directory for annual management GeoJSON files.")
    args = parser.parse_args()
    convert_management_by_year(args.input_gpkg, args.output_directory)


if __name__ == "__main__":
    main()
