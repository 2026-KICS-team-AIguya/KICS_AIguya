import importlib.util
import io
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from server.main import create_app


class KioskApiTests(unittest.TestCase):
    def test_fastapi_validation_and_no_store(self):
        # No lifespan: this endpoint has no DB/model/menu dependencies.
        client = TestClient(create_app(menu_updates=False))
        response = client.get("/kiosk/comprehensive-analysis?test_hour=12&test_minute=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json()["data_source"], "mock")
        self.assertEqual(response.json()["floor"], 1)
        live = client.get("/kiosk/comprehensive-analysis")
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json()["mode"], "random")
        self.assertTrue(live.json()["operating"])
        self.assertGreater(live.json()["surge_momentum"]["recent_5m"], 0)
        for query in ("test_hour=24", "test_hour=-1", "test_minute=30", "test_hour=12&test_minute=60", "test_hour=12.5"):
            self.assertEqual(client.get("/kiosk/comprehensive-analysis?" + query).status_code, 422)

    def test_vercel_adapter_and_validation(self):
        spec = importlib.util.spec_from_file_location("kiosk_adapter", Path(__file__).parents[1] / "api/kiosk-analysis.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for query, expected in [("?test_hour=12", 200), ("?test_hour=24", 422), ("?test_minute=30", 422), ("?test_hour=", 422), ("?test_hour=12&test_hour=13", 422)]:
            handler = object.__new__(module.handler)
            handler.path = "/api/kiosk-analysis" + query
            handler.wfile = io.BytesIO()
            statuses, headers = [], {}
            handler.send_response = statuses.append
            handler.send_header = lambda key, value: headers.update({key: value})
            handler.end_headers = lambda: None
            handler.do_GET()
            self.assertEqual(statuses, [expected])
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(int(headers["Content-Length"]), len(handler.wfile.getvalue()))
