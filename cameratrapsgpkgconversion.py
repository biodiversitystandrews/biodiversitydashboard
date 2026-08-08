"""Convert camera-trap records into one GeoJSON file per May-April sampling year."""

import argparse
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd


YEAR_ALIASES = ("sampling_year", "survey_year", "school_year", "samp_year", "year", "year1", "calendar_year")
MONTH_ALIASES = ("monthout", "month_out", "deployment_month", "month")
TARGET_CRS = "EPSG:4326"


def normalise_column_name(name):
    """Return a lowercase underscore form used to match alternative column names."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def find_column(gdf, aliases):
    """Find the first input column matching one of the supplied semantic aliases."""
    normalised = {normalise_column_name(column): column for column in gdf.columns}
    return next((normalised[name] for name in aliases if name in normalised), None)


def normalise_sampling_year(value):
    """Return YYYY-YY when a value already contains a valid sampling-year label."""
    if pd.isna(value):
        return None
    match = re.fullmatch(r"\s*(\d{4})\s*[-/]\s*(\d{2}|\d{4})\s*", str(value))
    if not match:
        return None
    start = int(match.group(1))
    end_text = match.group(2)
    end = int(end_text) if len(end_text) == 4 else (start // 100) * 100 + int(end_text)
    return f"{start}-{str(end)[-2:]}" if end == start + 1 else None


def derive_sampling_year(year_value, month_value):
    """Use an existing sampling year or derive May-April year from calendar year/month."""
    existing = normalise_sampling_year(year_value)
    if existing:
        return existing

    year = pd.to_numeric(pd.Series([year_value]), errors="coerce").iloc[0]
    month = pd.to_numeric(pd.Series([month_value]), errors="coerce").iloc[0]
    if pd.isna(year) or pd.isna(month) or not 1 <= int(month) <= 12:
        return None
    calendar_year = int(year)
    start = calendar_year if int(month) >= 5 else calendar_year - 1
    return f"{start}-{str(start + 1)[-2:]}"


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


def convert_cameratraps_by_year(input_path, output_directory):
    """Read one camera-trap GeoPackage and write cameratraps_YYYY-YY GeoJSON files."""
    input_file = Path(input_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    gdf = prepare_geodata(gpd.read_file(input_file))
    year_column = find_column(gdf, YEAR_ALIASES)
    month_column = find_column(gdf, MONTH_ALIASES)
    if year_column is None:
        raise ValueError(f"No year column found. Accepted names: {', '.join(YEAR_ALIASES)}")

    existing_years = gdf[year_column].map(normalise_sampling_year)
    if existing_years.notna().all():
        gdf["_output_year"] = existing_years
    else:
        if month_column is None:
            raise ValueError(f"Calendar years require a month column. Accepted names: {', '.join(MONTH_ALIASES)}")
        gdf["_output_year"] = [
            derive_sampling_year(year, month)
            for year, month in zip(gdf[year_column], gdf[month_column])
        ]

    invalid = gdf["_output_year"].isna()
    if invalid.any():
        examples = gdf.loc[invalid, [year_column, month_column]].head(5).to_dict("records")
        raise ValueError(f"Could not derive sampling year for {invalid.sum()} camera-trap record(s): {examples}")

    gdf["sampling_year"] = gdf["_output_year"]
    output_dir = Path(output_directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for year, records in gdf.groupby("_output_year", sort=True):
        output_file = output_dir / f"cameratraps_{year}.geojson"
        records.drop(columns="_output_year").to_file(output_file, driver="GeoJSON")
        written.append(output_file)
        print(f"Saved {len(records):,} camera-trap records for {year}: {output_file}")
    return written


def main():
    """Parse command-line paths and run the annual camera-trap conversion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_gpkg", help="Input camera-trap GeoPackage.")
    parser.add_argument("output_directory", help="Directory for annual camera-trap GeoJSON files.")
    args = parser.parse_args()
    convert_cameratraps_by_year(args.input_gpkg, args.output_directory)


if __name__ == "__main__":
    main()
