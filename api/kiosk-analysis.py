"""Vercel adapter for the same simulator served by FastAPI."""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from server.kiosk_analysis import analyze_kiosk


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        try:
            values = {}
            for key in ("test_hour", "test_minute"):
                if key in query:
                    if len(query[key]) != 1:
                        raise ValueError("시간 파라미터는 한 번만 지정하세요.")
                    values[key] = int(query[key][0])
            data, status = analyze_kiosk(**values), 200
        except ValueError as error:
            data, status = {"detail": str(error)}, 422
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
