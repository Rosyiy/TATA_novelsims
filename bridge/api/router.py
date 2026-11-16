"""Transport independent request router. Returns (http_status, json_dict)."""
import hmac
import logging
import re
import time
from urllib.parse import parse_qs

from .. import __version__
from ..errors import ApiError

log = logging.getLogger("novelsims.router")
PREFIX = "/api/v1"
_CHAR_RE = re.compile(r"^" + re.escape(PREFIX) + r"/characters/([A-Za-z0-9_\-]{1,64})$")


class Router(object):
    def __init__(self, cfg, characters, memories, dialogue, admin=None, admin_token=None):
        self.admin = admin
        self.admin_token = admin_token
        self.cfg = cfg
        self.characters = characters
        self.memories = memories
        self.dialogue = dialogue

    def dispatch(self, method, path, body=None, token=None, channel="ipc", admin_token=None):
        """channel: 'http' (dashboard allowed) or 'ipc' (TCP / file mailbox: game only)."""
        try:
            clean, _, qs = path.partition("?")
            if clean.startswith(PREFIX + "/admin/"):
                return self._admin(method.upper(), clean[len(PREFIX) + 7:], body, parse_qs(qs),
                                   channel, admin_token)
            return self._dispatch(method.upper(), clean, body, token)
        except ApiError as exc:
            return exc.status, {"status": "error", "code": exc.code, "message": exc.message}
        except Exception:
            log.exception("unhandled error for %s %s", method, path)
            return 500, {"status": "error", "code": "internal_error"}

    def _admin(self, method, sub, body, query, channel, admin_token):
        if channel != "http" or self.admin is None:
            raise ApiError(404, "not_found", "admin api is HTTP-only")
        if not (self.admin_token and isinstance(admin_token, str)
                and hmac.compare_digest(admin_token, self.admin_token)):
            raise ApiError(401, "unauthorized", "missing or invalid admin token")
        return 200, self.admin.handle(method, sub, body, query)

    def _auth(self, token):
        if self.cfg.token and not (isinstance(token, str)
                                   and hmac.compare_digest(token, self.cfg.token)):
            raise ApiError(401, "unauthorized", "missing or invalid token")

    def _dispatch(self, method, path, body, token):
        if path == PREFIX + "/health" and method == "GET":
            return 200, {"status": "ok", "version": __version__,
                         "llm_provider": self.dialogue.provider.name,
                         "time": time.time()}
        self._auth(token)
        if path == PREFIX + "/characters" and method == "GET":
            return 200, {"characters": self.characters.list()}
        m = _CHAR_RE.match(path)
        if m and method == "GET":
            card = self.characters.get(m.group(1))
            if card is None:
                raise ApiError(404, "character_not_found", m.group(1))
            return 200, card
        if path == PREFIX + "/dialogue/generate" and method == "POST":
            return self.dialogue.generate(body)
        if path == PREFIX + "/memory/append" and method == "POST":
            return 201, {"memory": self._append(body)}
        if path == PREFIX + "/memory/query" and method == "POST":
            return 200, self._query(body)
        raise ApiError(404, "not_found", "%s %s" % (method, path))

    def _append(self, body):
        if not isinstance(body, dict):
            raise ApiError(400, "invalid_request", "body must be an object")
        if body.get("layer", "dynamic") != "dynamic":
            raise ApiError(403, "canon_locked", "only the dynamic layer can be written")
        cid = body.get("character_id")
        if not isinstance(cid, str) or self.characters.get(cid) is None:
            raise ApiError(404, "character_not_found", str(cid))
        return self.memories.append_dynamic(
            body.get("save_key"), cid, body.get("content"), body.get("importance"),
            body.get("involved"), source=str(body.get("source", "game"))[:32])

    def _query(self, body):
        if not isinstance(body, dict):
            raise ApiError(400, "invalid_request", "body must be an object")
        cid = body.get("character_id")
        if not isinstance(cid, str) or self.characters.get(cid) is None:
            raise ApiError(404, "character_not_found", str(cid))
        return self.memories.query(body.get("save_key"), cid,
                                   body.get("target_keys"), body.get("target_names"))
