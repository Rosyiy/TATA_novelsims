"""Line-delimited JSON over TCP (127.0.0.1). One envelope per connection.

Request : {"req_id": str, "method": str, "path": str, "body": obj, "token": str?}\n
Response: {"req_id": str, "status": int, "body": obj}\n
"""
import json
import logging
import socket
import socketserver
import sys
import threading

log = logging.getLogger("novelsims.tcp")
MAX_LINE = 1024 * 1024


def make_handler(router):
    class Handler(socketserver.StreamRequestHandler):
        timeout = 10

        def handle(self):
            try:
                line = self.rfile.readline(MAX_LINE + 1)
            except OSError:
                return
            if not line or len(line) > MAX_LINE:
                return
            try:
                env = json.loads(line.decode("utf-8"))
                method, path = env["method"], env["path"]
                rid = env.get("req_id", "")
                if not isinstance(method, str) or not isinstance(path, str):
                    raise ValueError("bad envelope")
            except (ValueError, KeyError, TypeError):
                out = {"req_id": "", "status": 400, "body": {"status": "error", "code": "invalid_envelope"}}
            else:
                status, body = router.dispatch(method, path, env.get("body"), env.get("token"))
                out = {"req_id": rid, "status": status, "body": body}
            try:
                self.wfile.write((json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                pass

    return Handler


class _Server(socketserver.ThreadingTCPServer):
    # SO_REUSEADDR on Windows lets a second NovelSims bind the same port and
    # silently serve the old process's pages. Exclusive use makes the second
    # start fail instead.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def start_tcp(router, host, port):
    server = _Server((host, port), make_handler(router))
    t = threading.Thread(target=server.serve_forever, name="ns-tcp", daemon=True)
    t.start()
    return server
