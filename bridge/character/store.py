"""Character cards. IDs are generated here, never by the game (spec 5.2)."""
import glob
import json
import logging
import os
import uuid

from ..memory.store import now_iso

log = logging.getLogger("novelsims.characters")
REQUIRED_FIELDS = ("name", "identity", "core_personality", "speech_style")


def validate_card(card):
    if not isinstance(card, dict):
        return "card must be an object"
    missing = [f for f in REQUIRED_FIELDS if not card.get(f)]
    if missing:
        return "missing required fields: " + ", ".join(missing)
    return None


class CharacterStore(object):
    def __init__(self, db):
        self.db = db

    def import_examples(self, directory, memory_store):
        imported = []
        for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
            source_key = os.path.splitext(os.path.basename(path))[0]
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    card = json.load(fh)
            except (OSError, ValueError) as exc:
                log.warning("skip %s: %s", path, exc)
                continue
            err = validate_card(card)
            if err:
                log.warning("skip %s: %s", path, err)
                continue
            with self.db.session() as conn:
                row = conn.execute("SELECT character_id, card_json FROM characters WHERE source_key=?",
                                   (source_key,)).fetchone()
                if row:
                    cid = row["character_id"]
                    if json.loads(row["card_json"]).get("edited"):
                        imported.append((cid, card["name"]))     # the player edited it: never overwrite
                        continue
                    conn.execute("UPDATE characters SET card_json=? WHERE character_id=?",
                                 (json.dumps(card, ensure_ascii=False), cid))
                else:
                    cid = "char_" + uuid.uuid4().hex[:12]
                    conn.execute("INSERT INTO characters (character_id, source_key, card_json, created_at) "
                                 "VALUES (?,?,?,?)",
                                 (cid, source_key, json.dumps(card, ensure_ascii=False),
                                  now_iso()))
            try:
                memory_store.replace_canon(cid, card.get("canon_memories", []))
            except Exception as e:
                # Don't crash the whole app if example import hits a disk/DB issue
                print("skip canon import for", card.get("name"), ":", e)
            imported.append((cid, card["name"]))
        return imported

    def get(self, character_id):
        with self.db.session() as conn:
            row = conn.execute("SELECT card_json FROM characters WHERE character_id=?",
                               (character_id,)).fetchone()
        if not row:
            return None
        card = json.loads(row["card_json"])
        card["character_id"] = character_id
        return card

    def list(self):
        with self.db.session() as conn:
            rows = conn.execute("SELECT character_id, card_json FROM characters "
                                "ORDER BY created_at").fetchall()
        return [{"character_id": r["character_id"],
                 "name": json.loads(r["card_json"]).get("name")} for r in rows]

    # -- cards created at runtime (novel extraction, manual) ------------------
    def find_by_source_key(self, source_key):
        with self.db.session() as conn:
            row = conn.execute("SELECT character_id FROM characters WHERE source_key=?", (source_key,)).fetchone()
        return row["character_id"] if row else None

    def save_generated(self, card, source_key, novel_id=None):
        """Insert or replace a card; the id is created here (spec 5.2) and kept on re-generation."""
        cid = self.find_by_source_key(source_key) or "char_" + uuid.uuid4().hex[:12]
        blob = json.dumps(card, ensure_ascii=False)
        with self.db.session() as conn:
            if conn.execute("SELECT 1 FROM characters WHERE character_id=?", (cid,)).fetchone():
                conn.execute("UPDATE characters SET card_json=?, novel_id=? WHERE character_id=?", (blob, novel_id, cid))
            else:
                conn.execute("INSERT INTO characters (character_id, source_key, card_json, created_at, novel_id) "
                             "VALUES (?,?,?,?,?)", (cid, source_key, blob, now_iso(), novel_id))
        return cid

    def update(self, character_id, card):
        with self.db.session() as conn:
            conn.execute("UPDATE characters SET card_json=? WHERE character_id=?",
                         (json.dumps(card, ensure_ascii=False), character_id))

    def delete(self, character_id):
        with self.db.session() as conn:
            conn.execute("DELETE FROM characters WHERE character_id=?", (character_id,))
            conn.execute("DELETE FROM memories WHERE character_id=?", (character_id,))

    def list_all(self):
        with self.db.session() as conn:
            rows = conn.execute("SELECT character_id, card_json, novel_id FROM characters ORDER BY created_at").fetchall()
        out = []
        for r in rows:
            card = json.loads(r["card_json"])
            card["character_id"], card["novel_id"] = r["character_id"], r["novel_id"]
            out.append(card)
        return out
