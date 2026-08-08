"""Build the habitat-summary JSON from habitat polygons and 10 m squares."""

import argparse
import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


AREA_CRS = "EPSG:27700"
SUMMARY_SCHEMA_VERSION = 2
REQUIRED_POLYGON_COLUMNS = {"year", "broad", "biomscore"}
REQUIRED_SQUARE_COLUMNS = {"year", "broad"}
SAMPLING_YEAR_PATTERN = re.compile(r"^\s*(\d{4})\s*[-/]\s*(\d{2}|\d{4})\s*$")


def require_columns(frame, required, label):
    """Raise a clear error when an input is missing columns needed for processing."""
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required column(s): {', '.join(missing)}")


def clean_text(series, missing_value="Unknown"):
    """Strip text labels and replace empty or null values with a display-safe label."""
    cleaned = series.astype("string").str.strip()
    return cleaned.mask(cleaned.isna() | cleaned.eq(""), missing_value)


def normalise_sampling_years(series, label):
    """Normalise annual labels to YYYY-YY and reject ambiguous values.

    Both `2025-26` and `2025/2026` are accepted. A habitat summary must not
    create separate columns merely because two source files format the same
    sampling year differently.
    """
    normalised = pd.Series(pd.NA, index=series.index, dtype="string")
    invalid_values = []
    for index, value in series.items():
        if pd.isna(value) or not str(value).strip():
            invalid_values.append("<missing>")
            continue
        match = SAMPLING_YEAR_PATTERN.fullmatch(str(value))
        if not match:
            invalid_values.append(str(value))
            continue
        start = int(match.group(1))
        end_text = match.group(2)
        end = int(end_text) if len(end_text) == 4 else (start // 100) * 100 + int(end_text)
        if end != start + 1:
            invalid_values.append(str(value))
            continue
        normalised.at[index] = f"{start}-{end % 100:02d}"

    if invalid_values:
        examples = sorted(set(invalid_values))[:5]
        raise ValueError(
            f"{label} contains {len(invalid_values)} missing or invalid sampling "
            f"year value(s): {examples}. Expected YYYY-YY or YYYY/YYYY."
        )
    return normalised


def parse_biomscore(series):
    """Parse numeric scores or labels beginning with an integer score from 0 to 3."""
    numeric = pd.to_numeric(series, errors="coerce")
    leading_number = series.astype("string").str.extract(r"^\s*([0-3])(?:\D|$)", expand=False)
    parsed = numeric.combine_first(pd.to_numeric(leading_number, errors="coerce"))
    return parsed.where(parsed.isin([0, 1, 2, 3]))


def validate_source_crs(gdf):
    """Reject missing or obviously mislabelled CRS metadata before reprojection.

    A geographic CRS stores longitude/latitude values in degrees. Coordinates
    outside the worldwide longitude/latitude ranges usually mean that projected
    metre coordinates were incorrectly labelled as latitude/longitude. Allowing
    that mistake through would produce invalid or near-zero habitat areas.
    """
    if gdf.crs is None:
        raise ValueError(
            "Habitat polygons have no CRS, so their areas cannot be calculated safely."
        )
    if gdf.empty:
        raise ValueError("Habitat polygon file contains no records.")

    if gdf.crs.is_geographic:
        min_x, min_y, max_x, max_y = gdf.total_bounds
        bounds = np.array([min_x, min_y, max_x, max_y], dtype=float)
        if not np.isfinite(bounds).all():
            raise ValueError("Habitat polygons contain invalid coordinate bounds.")
        if min_x < -180 or max_x > 180 or min_y < -90 or max_y > 90:
            raise ValueError(
                "Habitat polygons are labelled with a geographic CRS, but their "
                "coordinates are outside longitude/latitude ranges. Correct the "
                "source CRS instead of assigning EPSG:4326."
            )


def calculate_polygon_areas(gdf):
    """Calculate reliable square-metre areas using British National Grid.

    Area must never be calculated directly in EPSG:4326 because its units are
    degrees, not metres. Invalid polygons are repaired in memory where possible;
    the original GeoPackage is not changed.
    """
    validate_source_crs(gdf)
    projected = gdf.to_crs(AREA_CRS).copy()
    geometry = projected.geometry.copy()

    # Check emptiness first to retain consistent behaviour across GeoPandas
    # versions (the historical behaviour of GeoSeries.notna() has changed).
    usable = ~geometry.is_empty & geometry.notna()
    invalid = usable & ~geometry.is_valid
    if invalid.any():
        print(f"Warning: repairing {invalid.sum():,} invalid habitat polygon(s) before area calculation.")
        geometry.loc[invalid] = geometry.loc[invalid].make_valid()

    areas = geometry.area.astype(float)
    areas = areas.where(usable & np.isfinite(areas))
    zero_area = areas.eq(0)
    if zero_area.any():
        print(f"Warning: {zero_area.sum():,} habitat polygon(s) have zero area.")
    if not areas.gt(0).any():
        raise ValueError(
            "All calculated habitat areas are zero or invalid. Check the input "
            "geometry and CRS before publishing the summary."
        )
    return areas


def validate_year_area_totals(gdf):
    """Ensure every displayed year has a positive calculated habitat area."""
    totals = gdf.groupby("year", dropna=False)["area_m2"].sum(min_count=1)
    invalid = totals[totals.isna() | totals.le(0)]
    if not invalid.empty:
        years = ", ".join(str(year) for year in invalid.index)
        raise ValueError(
            f"Calculated habitat area is zero or invalid for year(s): {years}. "
            "Check those polygons and their CRS."
        )
    for year, area_m2 in totals.items():
        print(f"Calculated habitat area for {year}: {area_m2 / 10_000:,.3f} ha")


def sort_habitats(values):
    """Sort habitat labels alphabetically while keeping Unknown at the bottom."""
    return sorted(values, key=lambda value: (str(value).casefold() == "unknown", str(value).casefold()))


def json_number(value, digits=None):
    """Convert pandas numbers to JSON-safe values while preserving missing data as null."""
    if pd.isna(value):
        return None
    number = float(value)
    return round(number, digits) if digits is not None else number


def build_polygon_summary(gdf):
    """Summarise habitat area and mean Biomscore for each habitat and year."""
    require_columns(gdf, REQUIRED_POLYGON_COLUMNS, "Habitat polygon file")
    gdf = gdf.copy()
    gdf["year"] = normalise_sampling_years(gdf["year"], "Habitat polygon file")
    gdf["broad"] = clean_text(gdf["broad"])
    gdf["area_m2"] = calculate_polygon_areas(gdf)
    validate_year_area_totals(gdf)
    gdf["bscore"] = parse_biomscore(gdf["biomscore"])

    invalid = gdf["biomscore"].notna() & gdf["bscore"].isna()
    if invalid.any():
        examples = gdf.loc[invalid, "biomscore"].astype("string").drop_duplicates().head(5).tolist()
        print(f"Warning: ignoring {invalid.sum()} invalid Biomscore value(s): {examples}")

    total_area = gdf.groupby("year", dropna=False)["area_m2"].sum().rename("total_year_area_m2")
    summary = gdf.groupby(["year", "broad"], dropna=False).agg(
        total_area_m2=("area_m2", "sum"),
        biomscore=("bscore", "mean"),
    ).reset_index()
    summary = summary.merge(total_area, on="year", how="left")
    summary["areaha"] = summary["total_area_m2"] / 10_000
    summary["percent_area"] = summary["total_area_m2"] / summary["total_year_area_m2"] * 100
    year_scores = gdf.groupby("year", dropna=False)["bscore"].mean().to_dict()
    return summary, year_scores


def build_square_summary(gdf):
    """Count surveyed 10 m squares for each habitat and year."""
    require_columns(gdf, REQUIRED_SQUARE_COLUMNS, "10 m square file")
    data = pd.DataFrame(gdf.drop(columns="geometry", errors="ignore"))
    data["year"] = normalise_sampling_years(data["year"], "10 m square file")
    data["broad"] = clean_text(data["broad"])
    summary = data.groupby(["year", "broad"], dropna=False).size().reset_index(name="no10msquares")
    totals = summary.groupby("year")["no10msquares"].sum().rename("total_year_squares")
    summary = summary.merge(totals, on="year", how="left")
    summary["percent_squares"] = summary["no10msquares"] / summary["total_year_squares"] * 100
    return summary


def validate_square_year_coverage(poly_summary, square_summary):
    """Require square data for every year represented by habitat polygons."""
    polygon_years = set(poly_summary["year"].dropna())
    square_totals = square_summary.groupby("year")["no10msquares"].sum()
    missing = sorted(
        year for year in polygon_years
        if year not in square_totals.index or square_totals.get(year, 0) <= 0
    )
    if missing:
        raise ValueError(
            "10 m square file contains no square records for habitat year(s): "
            f"{', '.join(missing)}. Upload an updated 10 m square file; these "
            "values must not be silently displayed as zero."
        )


def create_output(poly_summary, square_summary, year_scores):
    """Combine polygon and square summaries into the JSON structure used by the API."""
    summary = poly_summary[["year", "broad", "areaha", "percent_area", "biomscore"]].merge(
        square_summary[["year", "broad", "no10msquares", "percent_squares"]],
        on=["year", "broad"],
        how="outer",
    )
    for column in ("areaha", "percent_area", "no10msquares", "percent_squares"):
        summary[column] = summary[column].fillna(0)

    years = sorted(summary["year"].dropna().unique().tolist())
    habitats = sort_habitats(summary["broad"].dropna().unique().tolist())
    # The version and method labels make it easy to distinguish newly generated
    # summaries from legacy JSON files that used different calculations.
    output = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "methods": {
            "area": "Geometry reprojected to EPSG:27700; result reported in hectares",
            "biomscore": "Arithmetic mean of valid polygon scores from 0 to 3",
        },
        "years": years,
        "habitats": [],
        "totals": {},
    }

    for year in years:
        records = summary[summary["year"] == year]
        output["totals"][year] = {
            "areaha": json_number(records["areaha"].sum(), 4),
            "percent_area": 100.0,
            "biomscore": json_number(year_scores.get(year), 2),
            "no10msquares": int(records["no10msquares"].sum()),
            "percent_squares": 100.0,
        }

    for habitat in habitats:
        entry = {"name": habitat, "metrics": {}}
        for year in years:
            record = summary[(summary["broad"] == habitat) & (summary["year"] == year)]
            if record.empty:
                entry["metrics"][year] = {
                    "areaha": 0.0,
                    "percent_area": 0.0,
                    "biomscore": None,
                    "no10msquares": 0,
                    "percent_squares": 0.0,
                }
                continue
            row = record.iloc[0]
            entry["metrics"][year] = {
                "areaha": json_number(row["areaha"], 4),
                "percent_area": json_number(row["percent_area"], 2),
                "biomscore": json_number(row["biomscore"], 2),
                "no10msquares": int(row["no10msquares"]),
                "percent_squares": json_number(row["percent_squares"], 2),
            }
        output["habitats"].append(entry)
    return output


def validate_output(output):
    """Stop invalid summary values from being written and deployed."""
    if output.get("schema_version") != SUMMARY_SCHEMA_VERSION:
        raise ValueError("Habitat summary schema version is missing or incorrect.")
    if not output.get("years"):
        raise ValueError("Habitat summary contains no years.")

    for year in output["years"]:
        total = output.get("totals", {}).get(year, {})
        if not total.get("areaha") or total["areaha"] <= 0:
            raise ValueError(f"Habitat summary area is zero or missing for {year}.")

    scores = []
    for habitat in output.get("habitats", []):
        for metrics in habitat.get("metrics", {}).values():
            if metrics.get("biomscore") is not None:
                scores.append(float(metrics["biomscore"]))
    scores.extend(
        float(total["biomscore"])
        for total in output.get("totals", {}).values()
        if total.get("biomscore") is not None
    )
    if any(score < 0 or score > 3 for score in scores):
        raise ValueError("Habitat summary contains a Biomscore outside the valid 0-3 range.")


def process_habitat_data(polygons_path, squares_path, output_path):
    """Read both habitat inputs, calculate summaries, and write the dashboard JSON."""
    polygons_file = Path(polygons_path)
    squares_file = Path(squares_path)
    if not polygons_file.is_file():
        raise FileNotFoundError(f"Habitat polygon file not found: {polygons_file}")
    if not squares_file.is_file():
        raise FileNotFoundError(f"10 m square file not found: {squares_file}")

    polygons = gpd.read_file(polygons_file)
    squares = gpd.read_file(squares_file)
    print(f"Loaded {len(polygons):,} habitat polygons and {len(squares):,} 10 m squares.")
    polygon_summary, year_scores = build_polygon_summary(polygons)
    square_summary = build_square_summary(squares)
    validate_square_year_coverage(polygon_summary, square_summary)
    output = create_output(polygon_summary, square_summary, year_scores)
    validate_output(output)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, ensure_ascii=True)
    print(f"Saved habitat summary for {len(output['years'])} year(s): {destination}")


def main():
    """Parse command-line paths and run habitat summary processing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("polygons_input", help="Habitat Polygons all-years GeoPackage.")
    parser.add_argument("squares_input", help="10 m square habitats GeoPackage.")
    parser.add_argument("json_output", help="Output habitat summary JSON path.")
    args = parser.parse_args()
    process_habitat_data(args.polygons_input, args.squares_input, args.json_output)


if __name__ == "__main__":
    main()
