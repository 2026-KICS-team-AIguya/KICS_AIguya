import json
import unittest
from datetime import datetime, timedelta, timezone
from server.kiosk_analysis import analyze_kiosk, CORNERS, timeline, live_ticket, MAX_PEOPLE


class KioskAnalysisTests(unittest.TestCase):
    def test_noon_story_and_repeatability(self):
        data = analyze_kiosk(12)
        self.assertEqual(data["floor"], 1)
        self.assertNotIn("남아", data["summary_briefing"])
        self.assertNotIn("소진", data["summary_briefing"])
        self.assertNotIn("품절", data["golden_time_stats"]["tip"])
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
                self.assertLessEqual(staying["current_eating"], MAX_PEOPLE)
                json.dumps(data, allow_nan=False)

    def test_time_zone_and_demo_clock(self):
        now = datetime(2026, 10, 14, 14, 50, tzinfo=timezone.utc)
        self.assertEqual(analyze_kiosk(now=now)["as_of"], "2026-10-14T23:50:00+09:00")
        data = analyze_kiosk(11, 30, now)
        self.assertEqual(data["as_of"], "2026-10-14T11:30:00+09:00")
        later = analyze_kiosk(11, 30, now + timedelta(days=1))
        self.assertEqual(data["corners"], later["corners"])

    def test_live_clock_works_at_night_without_rewriting_history(self):
        now = datetime(2026, 10, 14, 23, 45, tzinfo=timezone(timedelta(hours=9)))
        first = analyze_kiosk(now=now)
        second = analyze_kiosk(now=now + timedelta(seconds=9))
        self.assertEqual(first["mode"], "random")
        self.assertEqual(first["as_of"], "2026-10-14T23:45:00+09:00")
        self.assertTrue(first["operating"])
        self.assertGreater(first["surge_momentum"]["recent_5m"], 0)
        self.assertGreater(first["staying_estimation"]["current_eating"], 0)
        self.assertEqual(first["staying_estimation"], second["staying_estimation"])
        self.assertEqual(first["surge_momentum"], second["surge_momentum"])
        live_ticket.cache_clear()  # A restart/new serverless instance reproduces the same events.
        self.assertEqual(first, analyze_kiosk(now=now))
        self.assertLessEqual(first["staying_estimation"]["leaving_in_10m"], first["staying_estimation"]["current_eating"])

    def test_live_flow_is_bounded_and_continuous_across_midnight(self):
        now = datetime(2026, 10, 14, 23, 30, tzinfo=timezone(timedelta(hours=9)))
        previous = analyze_kiosk(now=now)
        populations = set()
        for step in range(1, 361):
            current = analyze_kiosk(now=now + timedelta(seconds=step * 10))
            s, p = current["staying_estimation"], previous["staying_estimation"]
            self.assertTrue(0 <= s["leaving_in_10m"] <= s["current_eating"] <= MAX_PEOPLE)
            self.assertLessEqual(abs(s["current_eating"] - p["current_eating"]), 1)
            self.assertLessEqual(abs(current["surge_momentum"]["recent_5m"] - previous["surge_momentum"]["recent_5m"]), 1)
            self.assertEqual(s["total_5m_trend"][-1], current["surge_momentum"]["recent_5m"])
            self.assertEqual(s["total_5m_trend"][-2], current["surge_momentum"]["prev_5m"])
            populations.add(s["current_eating"])
            previous = current
        self.assertGreater(len(populations), 1)

    def test_live_five_minute_windows_shift_without_changing_past_events(self):
        now = datetime(2026, 10, 14, 12, tzinfo=timezone(timedelta(hours=9)))
        first = analyze_kiosk(now=now)
        second = analyze_kiosk(now=now + timedelta(minutes=5))
        self.assertEqual(first["staying_estimation"]["total_5m_trend"][1:], second["staying_estimation"]["total_5m_trend"][:-1])

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
