"""SQLite helper. One short-lived connection per session => thread safe."""
import os
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    character_id TEXT PRIMARY KEY,
    source_key   TEXT UNIQUE NOT NULL,
    card_json    TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    memory_id     TEXT PRIMARY KEY,
    save_key      TEXT NOT NULL,
    character_id  TEXT NOT NULL,
    layer         TEXT NOT NULL,
    content       TEXT NOT NULL,
    importance    INTEGER NOT NULL,
    locked        INTEGER NOT NULL,
    source        TEXT NOT NULL,
    involved_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_lookup ON memories (character_id, layer, save_key);
CREATE TABLE IF NOT EXISTS dialogue_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  TEXT,
    created_at  TEXT,
    actor_name  TEXT,
    target_name TEXT,
    interaction TEXT,
    text        TEXT,
    outcome     TEXT,
    latency_ms  INTEGER,
    provider    TEXT,
    model       TEXT
);
CREATE TABLE IF NOT EXISTS novels (
    novel_id        TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    author          TEXT,
    version         TEXT,
    notes           TEXT,
    mode            TEXT,
    characters_json TEXT,
    plot_text       TEXT,
    status          TEXT,
    created_at      TEXT
);
CREATE TABLE IF NOT EXISTS sources (
    novel_id   TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    name       TEXT,
    url        TEXT,
    fetched_at TEXT,
    kind       TEXT,
    edition    TEXT,
    engine     TEXT,
    status     TEXT,
    excerpt    TEXT,
    PRIMARY KEY (novel_id, source_id)
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    novel_id    TEXT,
    state       TEXT,
    progress    INTEGER,
    message     TEXT,
    result_json TEXT,
    created_at  TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS request_log (
    request_id      TEXT,
    created_at      TEXT,
    actor_id        TEXT,
    target_id       TEXT,
    est_tokens      INTEGER,
    context_summary TEXT,
    outcome         TEXT
);
"""


class Database(object):
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self.session() as conn:
            conn.executescript(SCHEMA)
            self._ensure_column(conn, "dialogue_log", "detail", "TEXT")
            self._ensure_column(conn, "characters", "novel_id", "TEXT")

    @staticmethod
    def _ensure_column(conn, table, column, decl):
        cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]
        if column not in cols:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))

    @contextmanager
    def session(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
