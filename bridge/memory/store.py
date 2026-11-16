"""Layer-1 (canon, locked) and layer-2 (dynamic) memory store.

Rules enforced here (spec 2.2 / 5.6):
  * canon memories are written only by card import, never by the API;
  * the API can only append *dynamic* memories;
  * ranking combines importance, recency and relevance to the target (spec 10).
"""
import json
import re
import uuid
from datetime import datetime, timezone

from ..errors import ApiError

CONTENT_MAX = 200
_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def check_save_key(save_key):
    if not isinstance(save_key, str) or not _KEY_RE.match(save_key):
        raise ApiError(400, "invalid_request", "save_key must match [A-Za-z0-9_.-]{1,64}")
    return save_key


def sanitize_text(text):
    """Remove characters the game's string system may treat as markup/tokens."""
    for ch in "{}<>":
        text = text.replace(ch, "")
    return "".join(c for c in text if c == "\n" or ord(c) >= 32).strip()


class MemoryStore(object):
    def __init__(self, db):
        self.db = db

    # -- canon -----------------------------------------------------------
    def replace_canon(self, character_id, items):
        """Called by card import only. Replaces importer-owned canon rows."""
        with self.db.session() as conn:
            conn.execute("DELETE FROM memories WHERE character_id=? AND layer='canon' "
                         "AND source='card_import'", (character_id,))
            for it in items:
                content = sanitize_text(str(it.get("content", "")))
                if not content:
                    continue
                conn.execute(
                    "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?)",
                    ("mem_" + uuid.uuid4().hex[:12], "*", character_id, "canon", content,
                     int(it.get("importance", 5)), 1, "card_import",
                     json.dumps(it.get("involves", []), ensure_ascii=False), now_iso()))

    # -- dynamic ---------------------------------------------------------
    def append_dynamic(self, save_key, character_id, content, importance,
                       involved=None, source="game"):
        check_save_key(save_key)
        if not isinstance(content, str):
            raise ApiError(400, "invalid_request", "content must be a string")
        content = sanitize_text(content)
        if not content or len(content) > CONTENT_MAX:
            raise ApiError(400, "invalid_request",
                           "content must be 1..%d characters" % CONTENT_MAX)
        if isinstance(importance, bool) or not isinstance(importance, int) \
                or not 1 <= importance <= 10:
            raise ApiError(400, "invalid_request", "importance must be an int in 1..10")
        involved = [str(x)[:64] for x in (involved or [])][:8]
        mem = {
            "memory_id": "mem_" + uuid.uuid4().hex[:12],
            "save_key": save_key, "character_id": character_id, "layer": "dynamic",
            "content": content, "importance": importance, "locked": 0,
            "source": source, "involved": involved, "created_at": now_iso(),
        }
        with self.db.session() as conn:
            conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (mem["memory_id"], save_key, character_id, "dynamic", content,
                          importance, 0, source, json.dumps(involved, ensure_ascii=False),
                          mem["created_at"]))
        return mem

    # -- query -----------------------------------------------------------
    def query(self, save_key, character_id, target_keys=None, target_names=None,
              limit_canon=5, limit_dynamic=5):
        check_save_key(save_key)
        target_keys = set(target_keys or [])
        target_names = [n for n in (target_names or []) if n]
        with self.db.session() as conn:
            canon = conn.execute(
                "SELECT * FROM memories WHERE character_id=? AND layer='canon'",
                (character_id,)).fetchall()
            dyn = conn.execute(
                "SELECT * FROM memories WHERE character_id=? AND layer='dynamic' "
                "AND save_key=? ORDER BY created_at DESC", (character_id, save_key)
            ).fetchall()

        def relevant(row):
            involved = set(json.loads(row["involved_json"]))
            if involved & target_keys:
                return True
            return any(n in row["content"] for n in target_names)

        def to_dict(row, score):
            return {"memory_id": row["memory_id"], "layer": row["layer"],
                    "content": row["content"], "importance": row["importance"],
                    "locked": bool(row["locked"]), "source": row["source"],
                    "created_at": row["created_at"], "score": round(score, 2)}

        c_scored = [(r["importance"] + (3 if relevant(r) else 0), r) for r in canon]
        d_scored = []
        for rank, r in enumerate(dyn):   # dyn is newest first
            score = r["importance"] + (3 if relevant(r) else 0) + max(0.0, 2 - 0.2 * rank)
            d_scored.append((score, r))
        c_scored.sort(key=lambda t: -t[0])
        d_scored.sort(key=lambda t: -t[0])
        return {"canon": [to_dict(r, s) for s, r in c_scored[:limit_canon]],
                "dynamic": [to_dict(r, s) for s, r in d_scored[:limit_dynamic]]}
