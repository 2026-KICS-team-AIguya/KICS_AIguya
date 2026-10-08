import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from server.menu_cloud import cloud_menu_service


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        force = parse_qs(urlparse(self.path).query).get("refresh", [""])[0].lower() in {"true", "1"}
        catalog = cloud_menu_service.refresh(force=force)
        payload = json.dumps(catalog, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store" if force else "public, max-age=0, s-maxage=300, stale-while-revalidate=60")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
