"""HTTP front-end (stdlib). Bound to 127.0.0.1 by default."""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("novelsims.http")
MAX_BODY = 1024 * 1024


CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def make_handler(router, get_html=None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        allowed_hosts = set()
        allowed_origins = set()

        def log_message(self, fmt, *args):   # keep stdout quiet; never log headers
            log.debug("%s " + fmt, self.address_string(), *args)

        def _send(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, html):
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method):
            # DNS-rebinding / cross-site protection: only our own loopback origin may talk to us
            if (self.headers.get("Host") or "").lower() not in self.allowed_hosts:
                return self._send(403, {"status": "error", "code": "bad_host"})
            origin = self.headers.get("Origin")
            if origin and origin.lower() not in self.allowed_origins:
                return self._send(403, {"status": "error", "code": "bad_origin"})
            if method == "GET" and get_html and self.path.split("?")[0] in ("/", "/index.html"):
                return self._send_html(get_html())
            body = None
            if method in ("POST", "PUT"):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_BODY:
                    return self._send(413, {"status": "error", "code": "body_too_large"})
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                except ValueError:
                    return self._send(400, {"status": "error", "code": "invalid_json"})
            status, payload = router.dispatch(
                method, self.path, body, self.headers.get("X-NovelSims-Token"), channel="http",
                admin_token=self.headers.get("X-NovelSims-Admin"))
            self._send(status, payload)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

    return Handler


def start_http(router, host, port, get_html=None):
    handler = make_handler(router, get_html)
    server = ThreadingHTTPServer((host, port), handler)
    real = server.server_address[1]
    handler.allowed_hosts = {"127.0.0.1:%d" % real, "localhost:%d" % real, "[::1]:%d" % real}
    handler.allowed_origins = {"http://127.0.0.1:%d" % real, "http://localhost:%d" % real}
    server.daemon_threads = True
    t = threading.Thread(target=server.serve_forever, name="ns-http", daemon=True)
    t.start()
    return server
