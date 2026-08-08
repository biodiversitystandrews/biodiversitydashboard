"""Regression tests for annual layers, habitat areas, and Biomscore parsing."""

import unittest

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from cameratrapsgpkgconversion import derive_sampling_year
from habitatmanagementgpkgconversion import normalise_sampling_year
from habitatsummaryprocessing import build_polygon_summary, calculate_polygon_areas, parse_biomscore


class AnnualLayerTests(unittest.TestCase):
    """Document accepted sampling-year formats and May-April conversion."""

    def test_management_year_formats(self):
        self.assertEqual(normalise_sampling_year("2025/2026"), "2025-26")
        self.assertEqual(normalise_sampling_year("2025-26"), "2025-26")
        self.assertIsNone(normalise_sampling_year("2025-27"))

    def test_camera_calendar_year_uses_may_to_april_cycle(self):
        self.assertEqual(derive_sampling_year(2025, 4), "2024-25")
        self.assertEqual(derive_sampling_year(2025, 5), "2025-26")

    def test_biomscore_accepts_numeric_and_labelled_values(self):
        result = parse_biomscore(pd.Series([0, "1 - Low", "3 High", None, "bad"]))
        self.assertEqual(result.iloc[:3].tolist(), [0.0, 1.0, 3.0])
        self.assertTrue(pd.isna(result.iloc[3]))
        self.assertTrue(pd.isna(result.iloc[4]))

    def test_geographic_polygons_are_projected_before_area_calculation(self):
        """EPSG:4326 geometry must produce real square metres, not square degrees."""
        polygons = gpd.GeoDataFrame(
            {
                "year": ["2025-26"],
                "broad": ["grassland"],
                "biomscore": ["2 - Moderate"],
            },
            geometry=[box(-2.80, 56.33, -2.79, 56.34)],
            crs="EPSG:4326",
        )
        areas = calculate_polygon_areas(polygons)
        self.assertGreater(areas.iloc[0], 100_000)

        summary, _ = build_polygon_summary(polygons)
        self.assertGreater(summary.loc[0, "areaha"], 10)
        self.assertAlmostEqual(summary.loc[0, "percent_area"], 100.0)

    def test_missing_crs_stops_area_processing(self):
        """A missing CRS must fail clearly instead of publishing incorrect zeros."""
        polygons = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)])
        with self.assertRaisesRegex(ValueError, "no CRS"):
            calculate_polygon_areas(polygons)

    def test_mislabelled_geographic_coordinates_are_rejected(self):
        """British National Grid coordinates labelled as EPSG:4326 are unsafe."""
        polygons = gpd.GeoDataFrame(
            geometry=[box(345000, 719000, 345100, 719100)],
            crs="EPSG:4326",
        )
        with self.assertRaisesRegex(ValueError, "outside longitude/latitude"):
            calculate_polygon_areas(polygons)


if __name__ == "__main__":
    unittest.main()
