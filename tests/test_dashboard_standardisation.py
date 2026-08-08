"""Regression tests documenting the shared observation-format rules."""

import unittest

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from dashboard_standardisation import standardise_dashboard_gdf


class DashboardStandardisationTests(unittest.TestCase):
    """Protect date precedence, aliases, duplicates, nulls, and coordinates."""

    def test_split_date_fields_override_ambiguous_date_text(self):
        frame = pd.DataFrame({
            "date": ["02/05/2026"],
            "cal_year": [2026],
            "month": [2],
            "day": [5],
        })
        result = standardise_dashboard_gdf(frame)
        self.assertEqual(result.loc[0, "Date"], pd.Timestamp("2026-02-05"))
        self.assertEqual(result.loc[0, "year"], "2025-26")

    def test_timezone_strings_keep_their_written_calendar_date(self):
        frame = pd.DataFrame({
            "date": ["2026-06-12T23:30:00+01:00", "2026-06-13T00:30:00Z"],
        })
        result = standardise_dashboard_gdf(frame)
        self.assertEqual(result["Date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-06-12", "2026-06-13"])

    def test_duplicate_observer_aliases_fill_each_others_gaps(self):
        frame = pd.DataFrame({
            "observer": ["Alice", None],
            "obs": [None, "Bob"],
        })
        result = standardise_dashboard_gdf(frame)
        self.assertEqual(result["obs"].tolist(), ["Alice", "Bob"])

    def test_text_null_tokens_become_missing(self):
        frame = pd.DataFrame({"comment": ["NULL", " useful note "]})
        result = standardise_dashboard_gdf(frame)
        self.assertTrue(pd.isna(result.loc[0, "comment"]))
        self.assertEqual(result.loc[1, "comment"], "useful note")

    def test_point_geometry_becomes_wgs84_coordinates(self):
        frame = gpd.GeoDataFrame(
            {"species": ["Example species"]},
            geometry=[Point(345000, 711000)],
            crs="EPSG:27700",
        )
        result = standardise_dashboard_gdf(frame)
        self.assertNotIn("geometry", result.columns)
        self.assertTrue(-3 < result.loc[0, "longitude"] < -2)
        self.assertTrue(56 < result.loc[0, "latitude"] < 57)


if __name__ == "__main__":
    unittest.main()
