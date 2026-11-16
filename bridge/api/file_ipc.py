"""File mailbox transport.

Layout under <ipc_dir>:
  outbox/<req_id>.json   game  -> bridge  (written atomically via .tmp + rename)
  inbox/<req_id>.json    bridge -> game
  bridge_alive.json      heartbeat written every ~1 s by the bridge
"""
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("novelsims.fileipc")
REQ_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


class FileIpcServer(object):
    def __init__(self, router, ipc_dir, poll_interval=0.2, stale_s=120.0, workers=4):
        self.router = router
        self.outbox = os.path.join(ipc_dir, "outbox")
        self.inbox = os.path.join(ipc_dir, "inbox")
        self.heartbeat = os.path.join(ipc_dir, "bridge_alive.json")
        self.poll_interval = poll_interval
        self.stale_s = stale_s
        self._pool = ThreadPoolExecutor(max_workers=workers)
        self._stop = threading.Event()
        self._thread = None
        for d in (self.outbox, self.inbox):
            os.makedirs(d, exist_ok=True)

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="ns-fileipc", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._pool.shutdown(wait=False)

    def _loop(self):
        last_hb = 0.0
        last_clean = 0.0
        while not self._stop.is_set():
            now = time.time()
            if now - last_hb >= 1.0:
                try:
                    atomic_write(self.heartbeat, json.dumps({"ts": now}))
                except OSError:
                    log.warning("heartbeat write failed")
                last_hb = now
            if now - last_clean >= 30.0:
                self._cleanup(now)
                last_clean = now
            try:
                names = [n for n in os.listdir(self.outbox) if n.endswith(".json")]
            except OSError:
                names = []
            for name in names:
                self._claim(name)
            self._stop.wait(self.poll_interval)

    def _claim(self, name):
        path = os.path.join(self.outbox, name)
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            os.remove(path)               # claim: never process twice
        except OSError:
            return
        self._pool.submit(self._process, name[:-5], raw)

    def _process(self, req_id, raw):
        if not REQ_ID_RE.match(req_id):
            return                          # path-traversal / garbage guard
        try:
            env = json.loads(raw.decode("utf-8"))
            method, path = env["method"], env["path"]
            if not isinstance(method, str) or not isinstance(path, str):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            out = {"req_id": req_id, "status": 400,
                   "body": {"status": "error", "code": "invalid_envelope"}}
        else:
            status, body = self.router.dispatch(method, path, env.get("body"), env.get("token"))
            out = {"req_id": req_id, "status": status, "body": body}
        try:
            atomic_write(os.path.join(self.inbox, req_id + ".json"),
                         json.dumps(out, ensure_ascii=False))
        except OSError:
            log.exception("could not write response %s", req_id)

    def _cleanup(self, now):
        for folder in (self.outbox, self.inbox):
            try:
                for n in os.listdir(folder):
                    p = os.path.join(folder, n)
                    if now - os.path.getmtime(p) > self.stale_s:
                        os.remove(p)
            except OSError:
                pass
