"""Regression tests for dashboard KPI and polygon-removal calculations."""

import unittest
from unittest.mock import patch

import pandas as pd

from main import calculate_diversity_metrics, get_polygon_removal_summary


class PolygonKpiTests(unittest.TestCase):
    """Keep removal results consistent with the main dashboard KPI rules."""

    def test_diversity_metrics_count_records_and_species(self):
        frame = pd.DataFrame({"species": ["A", "A", "B"], "count": [None, None, None]})
        metrics = calculate_diversity_metrics(frame)
        self.assertEqual(metrics["total_records"], 3)
        self.assertEqual(metrics["species_richness"], 2)

    def test_removal_summary_supports_year_and_reports_species_loss(self):
        frame = pd.DataFrame(
            {
                "species": ["A", "B", "C"],
                "year": ["2025-26", "2025-26", "2024-25"],
                "longitude": [-2.80, -2.70, -2.80],
                "latitude": [56.34, 56.34, 56.34],
                "count": [None, None, None],
            }
        )
        payload = {
            "year": "2025-26",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-2.81, 56.33], [-2.79, 56.33], [-2.79, 56.35],
                    [-2.81, 56.35], [-2.81, 56.33],
                ]],
            },
        }
        with patch("main.get_dataframe", return_value=frame):
            result = get_polygon_removal_summary(payload)

        self.assertEqual(result["baseline"]["species_richness"], 2)
        self.assertEqual(result["inside_polygon"]["species_richness"], 1)
        self.assertEqual(result["remaining"]["species_richness"], 1)
        self.assertEqual(result["species_lost_from_dataset"], 1)
        self.assertEqual(
            set(result["change"]),
            {"total_records", "species_richness", "shannon", "simpson"},
        )
        self.assertEqual(result["change"]["total_records"]["absolute"], -1.0)
        self.assertEqual(result["change"]["species_richness"]["absolute"], -1.0)
        self.assertLess(result["change"]["shannon"]["absolute"], 0)
        self.assertLess(result["change"]["simpson"]["absolute"], 0)


if __name__ == "__main__":
    unittest.main()
