import json
import unittest
from datetime import datetime, timedelta, timezone
from server.kiosk_analysis import analyze_kiosk, CORNERS, timeline


class KioskAnalysisTests(unittest.TestCase):
    def test_noon_story_and_repeatability(self):
        data = analyze_kiosk(12)
        self.assertEqual(data, analyze_kiosk(12))
        self.assertTrue(data["surge_momentum"]["is_surging"])
        special = data["corners"]["special"]
        self.assertEqual(special["status"], "CONGESTED")
        self.assertTrue(30 <= special["remaining_stock"] <= 45)
        self.assertTrue(0 < special["mins_to_sold_out"] <= 20)
        self.assertTrue(special["expected_sold_out_time"].startswith("12:"))
        self.assertIsNotNone(data["golden_time_stats"]["recommended_time"])

    def test_queue_and_stock_conservation_for_entire_day(self):
        for key, cfg in CORNERS.items():
            tickets, served, queues, stocks = timeline("demo", key)
            cumulative = processed = 0
            for t in range(1440):
                cumulative += tickets[t]
                processed += served[t]
                self.assertEqual(cfg["daily_limit"] - stocks[t], cumulative)
                self.assertEqual(cumulative - processed, queues[t])
                self.assertGreaterEqual(stocks[t], 0)
                self.assertLessEqual(served[t], cfg["service_rate"])

    def test_adjacent_windows_and_inventory_do_not_rewrite_history(self):
        first, second = analyze_kiosk(11, 55), analyze_kiosk(12, 0)
        for key in CORNERS:
            a, b = first["corners"][key], second["corners"][key]
            self.assertEqual(a["history_5m"][:5], b["history_5m"][1:])
            self.assertEqual(a["remaining_stock"] - b["remaining_stock"], b["history_5m"][0])

    def test_departures_are_subset_of_people_currently_seated(self):
        for hour in range(24):
            for minute in (0, 30):
                data = analyze_kiosk(hour, minute)
                staying = data["staying_estimation"]
                self.assertTrue(0 <= staying["leaving_in_10m"] <= staying["current_eating"])
                json.dumps(data, allow_nan=False)

    def test_time_zone_and_demo_clock(self):
        now = datetime(2026, 10, 14, 14, 50, tzinfo=timezone.utc)
        self.assertEqual(analyze_kiosk(now=now)["simulated_hour"], 23)
        data = analyze_kiosk(11, 30, now)
        self.assertEqual(data["as_of"], "2026-10-14T11:30:00+09:00")
        later = analyze_kiosk(11, 30, now + timedelta(days=1))
        self.assertEqual(data["corners"], later["corners"])

    def test_closed_quiet_and_zero_baseline(self):
        night = analyze_kiosk(0)
        self.assertFalse(night["operating"])
        self.assertEqual(night["surge_momentum"]["surge_rate_percent"], 0)
        self.assertIsNone(night["golden_time_stats"]["recommended_time"])
        self.assertTrue(all(c["mins_to_sold_out"] is None for c in night["corners"].values()))
        afternoon = analyze_kiosk(15)
        self.assertIsNone(afternoon["surge_momentum"]["surge_rate_percent"])
        self.assertTrue(afternoon["corners"]["special"]["sold_out"])
        self.assertIsNone(afternoon["golden_time_stats"]["recommended_time"])

    def test_validation(self):
        for hour, minute in [(-1, None), (24, None), (12, 60), (None, 30), (True, None), (12.5, None)]:
            with self.assertRaises(ValueError):
                analyze_kiosk(hour, minute)


if __name__ == "__main__":
    unittest.main()
