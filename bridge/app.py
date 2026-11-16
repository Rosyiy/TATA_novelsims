"""Wiring: build all services from a Config. Used by main.py and by tests."""
import os
import secrets
import time

from .api.admin import AdminApi
from .api.router import Router
from .character.store import CharacterStore
from .db import Database
from .dialogue.service import DialogueService
from .llm.manager import ProviderManager
from .settings import SettingsStore
from .memory.store import MemoryStore
from .novels.service import NovelService
from .novels.jjwxc import JinjiangService


class App(object):
    def __init__(self, cfg, provider=None):
        self.cfg = cfg
        os.makedirs(cfg.data_dir, exist_ok=True)
        self.db = Database(os.path.join(cfg.data_dir, "novelsims.db"))
        self.memories = MemoryStore(self.db)
        self.characters = CharacterStore(self.db)
        try:
            self.imported = self.characters.import_examples(cfg.examples_dir, self.memories)
        except Exception as e:
            print("example import failed, continuing without examples:", e)
            self.imported = []
        self.started_at = time.time()
        self.settings = SettingsStore(cfg.data_dir, cfg.llm_provider)
        # a provider passed in (tests) is used as-is; otherwise follow the dashboard settings
        self.provider = provider or ProviderManager(cfg, self.settings)
        self.dialogue = DialogueService(cfg, self.characters, self.memories, self.provider, self.db)
        self.novels = NovelService(self)
        self.jjwxc = JinjiangService(cfg.data_dir)
        self.write_character_index()
        self.admin_token = secrets.token_urlsafe(24)       # new on every start, embedded in the page
        self.admin = AdminApi(self)
        self.router = Router(cfg, self.characters, self.memories, self.dialogue,
                             self.admin, self.admin_token)

    def write_character_index(self):
        """characters_index.txt: '<id>\t<name>' per card. The game's pie menu reads it."""
        import json
        try:
            with open(os.path.join(self.cfg.data_dir, "characters_index.txt"), "w", encoding="utf-8") as fh:
                for c in self.characters.list():
                    fh.write("%s\t%s\n" % (c["character_id"], c["name"]))
            menu = []
            for c in self.characters.list_all():
                tl = c.get("timeline") or {}
                menu.append({"character_id": c["character_id"], "name": c["name"], "identity": c.get("identity", ""),
                             "status": c.get("verification_status", ""),
                             "bindable": c.get("verification_status") in ("confirmed", "user_defined", "fixture"),
                             "traits": (c.get("core_personality") or [])[:4], "aspiration": c.get("core_motivation", ""),
                             "novel": c.get("source_novel", ""), "stages": list((tl.get("stages") or {}).keys()),
                             "current_stage": tl.get("current_stage"), "low_data": c.get("low_data", False)})
            tmp = os.path.join(self.cfg.data_dir, "characters_menu.json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(menu, fh, ensure_ascii=False)
            os.replace(tmp, os.path.join(self.cfg.data_dir, "characters_menu.json"))
        except OSError:
            pass

    def dashboard_html(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "dashboard.html")
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().replace("__ADMIN_TOKEN__", self.admin_token)
