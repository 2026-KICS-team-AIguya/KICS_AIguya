import contextlib
import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from ai.scripts.config import FEATURES, LEVELS
from pipeline.features import FeatureAssembler
from pipeline.stream_csi import CsvTail, active_raw_file, post_frame
from server.congestion_service import CongestionService, SensorScope
from server.main import create_app


class PredictorDouble:
    def __init__(self):
        self.calls = 0
        self.result = {"status": "ok", "level": LEVELS[1], "confidence": .8,
                       "proba": {LEVELS[0]: .1, LEVELS[1]: .8, LEVELS[2]: .1}}

    def check_schema(self, row):
        if set(FEATURES) - row.keys():
            raise ValueError("missing feature columns")

    def update(self, row):
        self.calls += 1
        return {"timestamp": row["timestamp"], "link_id": row["link_id"], **self.result}

    def reset_calibration(self):
        self.calls = 0


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000
        self.predictor = PredictorDouble()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.service = CongestionService(predictor=self.predictor, clock=lambda: self.now)
        self.client = TestClient(create_app(self.engine, self.service, menu_updates=False))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.engine.dispose()

    def reading(self, **changes):
        return {"timestamp": self.now - 5000, "identifier": "link_3", "features": dict.fromkeys(FEATURES, 1.0), **changes}

    def snapshot(self):
        return self.client.get("/congestion").json()

    def test_floor_scope_and_no_occupancy(self):
        self.assertEqual(self.snapshot()["floors"][0]["status"], "waiting")
        self.assertEqual(self.client.post("/ingest", json=self.reading()).status_code, 200)
        floors = self.snapshot()["floors"]
        self.assertEqual(floors[0]["level"], LEVELS[1])
        self.assertEqual(floors[0]["confidence"], .8)
        self.assertEqual([floor["status"] for floor in floors if floor["floor"] != 1], ["unconnected", "unconnected"])
        self.assertNotIn("seat_occupancy", floors[0])
        self.assertNotIn("wait_minutes", floors[0])
        self.assertEqual(self.client.get("/congestion?location_id=business").json()["floors"][0]["status"], "unconnected")

    def test_duplicate_does_not_call_ai_and_conflict_rejected(self):
        payload = self.reading()
        self.client.post("/ingest", json=payload)
        self.assertTrue(self.client.post("/ingest", json=payload).json()["duplicate"])
        self.assertEqual(self.predictor.calls, 1)
        payload["features"][FEATURES[0]] = 2
        self.assertEqual(self.client.post("/ingest", json=payload).status_code, 409)
        self.assertEqual(self.client.post("/ingest", json=self.reading(timestamp=self.now - 10000)).status_code, 409)

    def test_input_kind_cannot_contaminate_active_calibration(self):
        payload = self.reading(input_kind="synthetic")
        self.assertEqual(self.client.post("/ingest", json=payload).status_code, 200)
        self.assertTrue(self.client.post("/ingest", json=payload).json()["duplicate"])
        self.now += 5000
        self.assertEqual(self.client.post("/ingest", json=self.reading(input_kind="sensor")).status_code, 409)
        self.assertEqual(self.predictor.calls, 1)
        self.assertEqual(self.snapshot()["floors"][0]["input_kind"], "synthetic")
        self.now += 35000
        self.assertEqual(self.snapshot()["floors"][0]["input_kind"], "synthetic")

    def test_live_mode_rejects_replay_and_accepts_sensor(self):
        from tools.replay_send import to_payload
        self.service.scope = SensorScope(mode="live")
        for kind in ("synthetic", "replay", "unknown"):
            self.assertEqual(self.client.post("/ingest", json=self.reading(input_kind=kind)).status_code, 422)
        replay = to_payload(dict.fromkeys(FEATURES, "1"), self.now - 5000, "link_3")
        self.assertEqual(self.client.post("/ingest", json=replay).status_code, 422)
        self.assertEqual(self.predictor.calls, 0)
        self.assertEqual(self.client.post("/ingest", json=self.reading(input_kind="sensor")).status_code, 200)

    def test_restart_allows_new_sensor_baseline_without_old_history(self):
        self.client.post("/ingest", json=self.reading(input_kind="synthetic"))
        self.now += 5000
        service = CongestionService(predictor=PredictorDouble(), clock=lambda: self.now)
        with TestClient(create_app(self.engine, service, menu_updates=False)) as client:
            self.assertEqual(client.get("/congestion").json()["floors"][0]["status"], "waiting")
            self.assertEqual(client.post("/ingest", json=self.reading(input_kind="sensor")).status_code, 200)
            floor = client.get("/congestion").json()["floors"][0]
            self.assertEqual(floor["input_kind"], "sensor")
            self.assertEqual(sum(point["samples"] for point in floor["history"]), 1)

    def test_schema_scope_and_nonfinite_validation(self):
        invalid = [self.reading(identifier="link_1"), self.reading(floor=2), self.reading(source="mmwave"),
                   self.reading(timestamp=self.now - 1), self.reading(timestamp=self.now + 20000),
                   self.reading(features={}), self.reading(features={**dict.fromkeys(FEATURES, 1), FEATURES[0]: "inf"}),
                   self.reading(features={**dict.fromkeys(FEATURES, 1), FEATURES[0]: True}), self.reading(interval_ms=300000)]
        for payload in invalid:
            self.assertEqual(self.client.post("/ingest", json=payload).status_code, 422)
        alias = self.reading()
        alias["link_id"] = alias.pop("identifier")
        self.assertEqual(self.client.post("/ingest", json=alias).status_code, 200)

    def test_nonstandard_json_nan_does_not_break_error_response(self):
        payload = self.reading()
        payload["features"][FEATURES[0]] = float("nan")
        response = self.client.post("/ingest", content=json.dumps(payload), headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("detail", response.json())

    def test_model_missing_keeps_menu_server_alive(self):
        service = CongestionService(clock=lambda: self.now)
        with patch("ai.main.CongestionPredictor", side_effect=FileNotFoundError()), patch("server.congestion_service.logging.exception"), \
             patch("server.main.menu_service.refresh", return_value={"locations": {}}), \
             TestClient(create_app(self.engine, service, menu_updates=False)) as client:
            self.assertFalse(client.get("/").json()["ai_ready"])
            self.assertEqual(client.get("/congestion").json()["floors"][0]["status"], "unavailable")
            self.assertEqual(client.post("/ingest", json=self.reading()).status_code, 503)
            self.assertEqual(client.get("/menus").status_code, 200)

    def test_calibration_quality_and_stale_status(self):
        self.predictor.result = {"status": "calibrating", "progress": "1/24"}
        self.client.post("/ingest", json=self.reading())
        self.assertEqual(self.snapshot()["floors"][0]["progress"], "1/24")
        self.now += 5000
        self.predictor.result = {"status": "skipped", "reason": "missing"}
        self.client.post("/ingest", json=self.reading())
        floor = self.snapshot()["floors"][0]
        self.assertEqual(floor["status"], "skipped")
        self.assertIsNone(floor["level"])
        self.now += 35000
        self.assertEqual(self.snapshot()["floors"][0]["status"], "stale")

    def test_empty_packets_do_not_keep_sensor_online(self):
        self.client.post("/ingest", json=self.reading())
        self.now += 35000
        features = {**dict.fromkeys(FEATURES, 1), "csi_packet_count": 0}
        self.client.post("/ingest", json=self.reading(features=features))
        self.assertEqual(self.predictor.calls, 1)
        self.assertEqual(self.snapshot()["floors"][0]["status"], "stale")

    def test_kiosk_requires_complete_windows_and_handles_zero(self):
        self.assertEqual(self.snapshot()["kiosk"]["status"], "waiting")
        for index, timestamp in enumerate(range(self.now - 600000, self.now, 5000)):
            payload = {"location_id": "sangnok", "timestamp": timestamp, "count": 2 if index < 60 else 3}
            self.assertEqual(self.client.post("/kiosk/ingest", json=payload).status_code, 200)
            if index == 0:
                self.assertIsNone(self.snapshot()["kiosk"]["recent"])
        summary = self.snapshot()["kiosk"]
        self.assertEqual((summary["recent"], summary["previous"], summary["change"], summary["percent"]), (180, 120, 60, 50))
        self.assertTrue(self.client.post("/kiosk/ingest", json=payload).json()["duplicate"])
        self.assertEqual(self.client.post("/kiosk/ingest", json={**payload, "count": 4}).status_code, 409)
        self.now += 5000
        self.assertIsNone(self.snapshot()["kiosk"]["recent"])
        self.client.post("/kiosk/ingest", json={"location_id": "sangnok", "timestamp": self.now - 5000, "count": 4})
        self.assertEqual(self.snapshot()["kiosk"]["recent"], 181)
        self.assertEqual(self.snapshot()["kiosk"]["previous"], 121)
        self.now += 35000
        self.assertEqual(self.snapshot()["kiosk"]["status"], "stale")

    def test_zero_kiosk_is_distinct_from_no_data(self):
        for timestamp in range(self.now - 600000, self.now, 5000):
            self.client.post("/kiosk/ingest", json={"location_id": "sangnok", "timestamp": timestamp, "count": 0})
        summary = self.snapshot()["kiosk"]
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["recent"], 0)
        self.assertIsNone(summary["percent"])
        self.assertEqual(self.client.post("/kiosk/ingest", json={"location_id": "sangnok", "timestamp": self.now, "count": -1}).status_code, 422)
        self.assertEqual(self.client.post("/kiosk/ingest", json={"location_id": "sangnok", "timestamp": self.now, "count": 1}).status_code, 422)

    def test_real_model_calibration_when_artifact_available(self):
        path = Path(__file__).resolve().parents[1] / "data/ai/model_hgb_final.joblib"
        if not path.is_file():
            self.skipTest("Model artifact is shared separately")
        from ai.main import CongestionPredictor
        self.service.predictor = CongestionPredictor()
        for index in range(24):
            self.now += 5000
            payload = self.reading(features={name: i + 1 + index * .01 for i, name in enumerate(FEATURES)})
            response = self.client.post("/ingest", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["inference"]["status"], "calibrating" if index < 23 else "ok")
        snapshot = self.snapshot()["floors"][0]
        self.assertIn(snapshot["level"], LEVELS)
        self.assertEqual(len(snapshot["history"]), 1)
        self.assertEqual(snapshot["history"][0]["samples"], 1)

    def test_raw_windows_through_transport_to_real_ai(self):
        path = Path(__file__).resolve().parents[1] / "data/ai/model_hgb_final.joblib"
        if not path.is_file():
            self.skipTest("Model artifact is shared separately")
        from ai.main import CongestionPredictor
        self.service.predictor = CongestionPredictor()
        assembler = FeatureAssembler()
        start = self.now
        for window_index in range(24):
            timestamp = start + window_index * 5000
            for packet in range(40):
                iq = [value for subcarrier in range(128) for value in (
                      (packet + subcarrier + window_index) % 11 + 1,
                      (2 * packet + subcarrier + window_index) % 13 + 2)]
                assembler.add({"host_epoch_ms": timestamp + packet * 100, "link_id": "link_3",
                              "packet_id": window_index * 40 + packet, "rssi": -50 - packet % 3,
                              "csi_data": json.dumps(iq)})
            self.now = timestamp + 7000
            frames = list(assembler.complete(self.now))
            self.assertEqual(len(frames), 1)
            self.assertTrue(all(frames[0]["features"][name] is not None for name in FEATURES))
            result = post_frame(self.client, "http://testserver", frames[0], "sangnok", 1)
            self.assertEqual(result["inference"]["status"], "calibrating" if window_index < 23 else "ok")
        self.assertEqual(self.snapshot()["floors"][0]["status"], "ok")


class FeatureTests(unittest.TestCase):
    def test_auto_capture_ignores_archives_and_incomplete_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archived, partial, active = [root / name for name in ("csi_old.csv", "csi_partial.csv", "csi_active.csv")]
            header = "host_epoch_ms,link_id,packet_id,rssi,csi_data\n"
            archived.write_text(header, encoding="utf-8")
            partial.write_text(header.rstrip(), encoding="utf-8")
            os.utime(archived, (900, 900))
            os.utime(partial, (1000, 1000))
            self.assertIsNone(active_raw_file(root, now=1000))
            active.write_text(header, encoding="utf-8")
            os.utime(active, (995, 995))
            self.assertEqual(active_raw_file(root, now=1000), active)

    def test_live_tail_does_not_replay_existing_packets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.csv"
            path.write_text("host_epoch_ms,link_id\n10000,link_3\n", encoding="utf-8")
            tail = CsvTail(path)
            try:
                self.assertEqual(list(tail.rows()), [])
                with path.open("a") as file:
                    file.write("15000,link_3\n")
                self.assertEqual(list(tail.rows()), [{"host_epoch_ms": "15000", "link_id": "link_3"}])
            finally:
                tail.close()

    def test_stream_matches_offline_training_features(self):
        from candidate_features import process as candidate_process
        from offline_feature import process as base_process
        with tempfile.TemporaryDirectory() as directory:
            raw, base, candidate = [Path(directory) / name for name in ("raw.csv", "base.csv", "candidate.csv")]
            records = []
            for index in range(36):
                iq = [value for subcarrier in range(128) for value in ((index + subcarrier) % 11 + 1, (2 * index + subcarrier) % 13 + 2)]
                records.append({"host_epoch_ms": 10000 + index * 100 if index < 35 else 15000, "link_id": "link_3",
                                "packet_id": index, "rssi": -50 - index % 3, "csi_data": json.dumps(iq)})
            records.insert(3, dict(records[2]))
            with raw.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=records[0].keys())
                writer.writeheader()
                writer.writerows(records)
            with contextlib.redirect_stdout(io.StringIO()):
                base_process(raw, base, 36, 1, 1)
                candidate_process(raw, candidate, "link_3", None, False)
            with base.open() as file:
                base_row = next(csv.DictReader(file))
            with candidate.open() as file:
                candidate_row = next(csv.DictReader(file))
            expected = {**base_row, **candidate_row}
            assembler = FeatureAssembler()
            for record in records:
                assembler.add(record)
            result = list(assembler.complete(17000))[0]
            self.assertEqual(result["timestamp"], 10000)
            for feature in FEATURES:
                self.assertEqual(result["features"][feature], float(expected[feature]), feature)
            missing = list(assembler.complete(27000))[-1]
            self.assertTrue(all(missing["features"][feature] is None for feature in FEATURES))

    def test_csv_tail_waits_for_complete_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.csv"
            path.write_text("host_epoch_ms,link_id\n", encoding="utf-8")
            tail = CsvTail(path, from_start=True)
            try:
                self.assertEqual(list(tail.rows()), [])
                with path.open("a") as file:
                    file.write("10000,link_")
                self.assertEqual(list(tail.rows()), [])
                with path.open("a") as file:
                    file.write("3\n")
                self.assertEqual(list(tail.rows()), [{"host_epoch_ms": "10000", "link_id": "link_3"}])
            finally:
                tail.close()


if __name__ == "__main__":
    unittest.main()
