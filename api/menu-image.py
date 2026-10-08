import hashlib
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from server.menu_cloud import fetch_menu_image


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        sources = parse_qs(urlparse(self.path).query).get("source", [])
        if len(sources) != 1:
            self.send_error(400, "One official menu image source is required")
            return
        try:
            content, mime = fetch_menu_image(sources[0])
        except ValueError:
            self.send_error(400, "Unsupported official menu image")
            return
        except Exception:
            self.send_error(502, "Official menu image is temporarily unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "public, max-age=300, s-maxage=3600")
        self.send_header("ETag", '"' + hashlib.sha256(content).hexdigest() + '"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)
