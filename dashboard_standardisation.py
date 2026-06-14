import re

import geopandas as gpd
import pandas as pd


TEXT_NULLS = {"", "nan", "none", "null", "n/a", "na"}

STANDARD_COLUMNS = [
    {"name": "Date", "datatype": "date", "alt_names": ["date", "date_obs", "date observed", "date_observed"]},
    {"name": "species", "datatype": "text", "alt_names": ["species", "species name", "scientific_name", "scientific name"]},
    {"name": "Taxa", "datatype": "text", "alt_names": ["taxa"]},
    {"name": "obs", "datatype": "text", "alt_names": ["observer", "observer name", "observer_name", "obs"]},
    {"name": "height", "datatype": "numeric", "alt_names": ["height"]},
    {"name": "radius", "datatype": "numeric", "alt_names": ["radius"]},
    {"name": "photoid", "datatype": "text", "alt_names": ["photoid", "photo_id"]},
    {"name": "count", "datatype": "numeric", "alt_names": ["count"]},
    {"name": "year", "datatype": "text", "alt_names": ["school_year", "year"]},
    {"name": "year1", "datatype": "numeric", "alt_names": ["calendar_year", "cal_year", "year1"]},
    {"name": "month", "datatype": "numeric", "alt_names": ["month"]},
    {"name": "day", "datatype": "numeric", "alt_names": ["day"]},
    {"name": "comment", "datatype": "text", "alt_names": ["comment", "comments"]},
    {"name": "type", "datatype": "text", "alt_names": ["type"]},
    {"name": "english_name", "datatype": "text", "alt_names": ["english_name", "english name", "english"]},
    {"name": "longitude", "datatype": "numeric", "alt_names": ["longitude", "long", "lon", "lng"]},
    {"name": "latitude", "datatype": "numeric", "alt_names": ["latitude", "lat"]},
]


def clean_column_key(name):
    return re.sub(r"_+", "_", str(name).strip().lower().replace(" ", "_"))


def standard_column_name_map():
    name_map = {}
    for column in STANDARD_COLUMNS:
        for alt in [column["name"], *column["alt_names"]]:
            name_map[clean_column_key(alt)] = column["name"]
    return name_map


def merge_duplicate_columns(gdf):
    result = pd.DataFrame(index=gdf.index)
    for col in dict.fromkeys(gdf.columns):
        matching = gdf.loc[:, gdf.columns == col]
        result[col] = matching.iloc[:, 0] if matching.shape[1] == 1 else matching.bfill(axis=1).iloc[:, 0]

    geometry_name = getattr(getattr(gdf, "geometry", None), "name", None)
    if geometry_name in result.columns:
        return gpd.GeoDataFrame(result, geometry=geometry_name, crs=getattr(gdf, "crs", None))
    return result


def normalise_input_columns(gdf):
    gdf = gdf.copy()
    gdf.columns = [clean_column_key(col) for col in gdf.columns]
    gdf = merge_duplicate_columns(gdf)
    name_map = standard_column_name_map()

    for source in list(gdf.columns):
        target = name_map.get(source)
        if target is None or source == target:
            continue
        if target in gdf.columns:
            gdf[target] = gdf[target].combine_first(gdf[source])
            gdf = gdf.drop(columns=[source])
        else:
            gdf = gdf.rename(columns={source: target})
    return gdf


def clean_text_series(series, title_case=False):
    cleaned = series.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    cleaned = cleaned.mask(cleaned.str.lower().isin(TEXT_NULLS), pd.NA)
    if title_case:
        cleaned = cleaned.str.lower().str.title()
    return cleaned


def standardise_date_value(value):
    if pd.isna(value):
        return pd.NaT

    if isinstance(value, str):
        cleaned = value.strip()
        if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", cleaned):
            timestamp = pd.to_datetime(cleaned, errors="coerce", yearfirst=True)
        else:
            timestamp = pd.to_datetime(cleaned, errors="coerce", dayfirst=True)
    else:
        timestamp = pd.to_datetime(value, errors="coerce")

    if pd.isna(timestamp):
        return pd.NaT
    if getattr(timestamp, "tzinfo", None) is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp


def standardise_date_series(series):
    return pd.to_datetime(series.apply(standardise_date_value), errors="coerce").astype("datetime64[ms]")


def date_from_split_columns(gdf):
    if not {"year1", "month", "day"}.issubset(gdf.columns):
        return pd.Series(pd.NaT, index=gdf.index, dtype="datetime64[ms]")

    parts = pd.DataFrame({
        "year": pd.to_numeric(gdf["year1"], errors="coerce"),
        "month": pd.to_numeric(gdf["month"], errors="coerce"),
        "day": pd.to_numeric(gdf["day"], errors="coerce"),
    })

    valid = (
        parts["year"].between(1900, 2100)
        & parts["month"].between(1, 12)
        & parts["day"].between(1, 31)
    )
    dates = pd.Series(pd.NaT, index=gdf.index, dtype="datetime64[ms]")
    dates.loc[valid] = pd.to_datetime(parts.loc[valid], errors="coerce").astype("datetime64[ms]")
    return dates


def calculate_sampling_year(date_value):
    if pd.isna(date_value):
        return None
    year, month = date_value.year, date_value.month
    if month >= 5:
        return f"{year}-{str(year + 1)[-2:]}"
    return f"{year - 1}-{str(year)[-2:]}"


def add_longitude_latitude(gdf):
    if isinstance(gdf, gpd.GeoDataFrame) and gdf.geometry.name in gdf.columns:
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")

        point_mask = gdf.geometry.notna() & (gdf.geometry.geom_type == "Point")
        gdf.loc[point_mask, "longitude"] = gdf.loc[point_mask].geometry.x
        gdf.loc[point_mask, "latitude"] = gdf.loc[point_mask].geometry.y
        gdf = gdf.drop(columns=[gdf.geometry.name])
    return gdf


def standardise_dashboard_gdf(gdf):
    gdf = normalise_input_columns(gdf)
    gdf = add_longitude_latitude(gdf)

    split_dates = date_from_split_columns(gdf)
    parsed_dates = standardise_date_series(gdf["Date"]) if "Date" in gdf.columns else split_dates

    if "Date" in gdf.columns or split_dates.notna().any():
        gdf["Date"] = split_dates.combine_first(parsed_dates)
        gdf["year1"] = gdf["Date"].dt.year
        gdf["month"] = gdf["Date"].dt.month
        gdf["day"] = gdf["Date"].dt.day
        gdf["year"] = gdf["Date"].apply(calculate_sampling_year)

    for column in STANDARD_COLUMNS:
        name = column["name"]
        if name not in gdf.columns:
            continue
        if column["datatype"] == "text":
            gdf[name] = clean_text_series(gdf[name], title_case=name in {"obs", "Taxa", "type"})
        elif column["datatype"] == "numeric":
            cleaned = gdf[name].astype("string").str.replace(",", "", regex=False)
            gdf[name] = pd.to_numeric(cleaned, errors="coerce")

    return gdf
