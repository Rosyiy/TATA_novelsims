"""User settings (settings.json) and API keys (secrets.json), plus remote-data consent.

* Keys are stored apart from settings and are never returned by any API (only 'has_key' + last 4).
* Optional override: environment variable NOVELSIMS_KEY_<PROVIDER_ID> (e.g. NOVELSIMS_KEY_DEEPSEEK).
* Sending data to a remote provider needs an explicit consent that is bound to the provider id AND host.
* NOTE: secrets.json is plain text (file permissions 600 on POSIX only). Prefer the env variable if
  the PC is shared.
"""
import json
import os
import re
import threading
from urllib.parse import urlparse

from .errors import ApiError
from .llm.presets import BY_ID
from .memory.store import now_iso

_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\-]{0,80}$")
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def host_of(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def validate_base_url(provider_id, url):
    preset = BY_ID[provider_id]
    if provider_id == "mock":
        return ""
    if not isinstance(url, str) or len(url) > 300:
        raise ApiError(400, "invalid_request", "base_url invalid")
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ApiError(400, "invalid_request", "base_url must be http(s)://host/...")
    if u.scheme == "http" and u.hostname.lower() not in LOOPBACK:
        raise ApiError(400, "invalid_request", "非本机地址必须使用 https，避免密钥明文传输")
    if preset["remote"] and u.hostname.lower() in LOOPBACK and provider_id != "custom":
        raise ApiError(400, "invalid_request", "云端模型不能指向本机地址")
    return url.strip().rstrip("/")


class SettingsStore(object):
    def __init__(self, data_dir, default_provider="mock"):
        self.dir = data_dir
        self.path = os.path.join(data_dir, "settings.json")
        self.secrets_path = os.path.join(data_dir, "secrets.json")
        self._lock = threading.Lock()
        self._data = {"provider": default_provider if default_provider in BY_ID else "mock",
                      "providers": {}, "temperature": 0.7, "max_tokens": 800, "consent": {},
                      "search": {"engines": ["baidu", "quark", "sogou", "bing", "zhipu"], "max_pages": 30}}
        self._secrets = {}
        self._load()

    # -- persistence -----------------------------------------------------
    def _load(self):
        for attr, path in (("_data", self.path), ("_secrets", self.secrets_path)):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    getattr(self, attr).update(loaded)
            except (OSError, ValueError):
                pass                     # missing/damaged file => defaults, never a crash
        if self._data.get("provider") not in BY_ID:
            self._data["provider"] = "mock"
        sc = self._data.setdefault("search", {"engines": ["bing", "zhipu"], "max_pages": 10})
        if sc.get("engines") in (["wikipedia", "bing"], ["bing", "zhipu"]):
            sc["engines"] = ["baidu", "quark", "sogou", "bing", "zhipu"]
            sc["max_pages"] = max(30, int(sc.get("max_pages", 30)))

    @staticmethod
    def _atomic(path, obj, private=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        if private:
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
        os.replace(tmp, path)

    # -- read ------------------------------------------------------------
    def provider_config(self, provider_id):
        preset = BY_ID[provider_id]
        saved = (self._data.get("providers") or {}).get(provider_id, {})
        return {"base_url": saved.get("base_url") or preset["base_url"],
                "model": saved.get("model") if saved.get("model") is not None else preset["model"]}

    def current(self):
        pid = self._data["provider"]
        cfg = self.provider_config(pid)
        return {"id": pid, "base_url": cfg["base_url"], "model": cfg["model"],
                "temperature": float(self._data.get("temperature", 0.7)),
                "max_tokens": int(self._data.get("max_tokens", 600))}

    def get_key(self, provider_id):
        env = os.environ.get("NOVELSIMS_KEY_" + provider_id.upper().replace(":", "_"))
        if env:
            return env, "env"
        key = self._secrets.get(provider_id)
        return (key, "file") if key else (None, None)

    def key_status(self, provider_id):
        key, source = self.get_key(provider_id)
        return {"has_key": bool(key), "source": source, "hint": ("…" + key[-4:]) if key else ""}

    def has_consent(self, provider_id, base_url):
        c = (self._data.get("consent") or {}).get(provider_id)
        return bool(c) and c.get("host") == host_of(base_url)

    def public(self):
        cur = self.current()
        providers = []
        for p in BY_ID.values():
            cfg = self.provider_config(p["id"])
            providers.append({
                "id": p["id"], "name": p["name"], "remote": p["remote"], "note": p["note"],
                "models": p["models"], "base_url": cfg["base_url"], "model": cfg["model"],
                "key": self.key_status(p["id"]) if p["remote"] else None,
                "consent": self.has_consent(p["id"], cfg["base_url"]) if p["remote"] else None})
        return {"provider": cur["id"], "temperature": cur["temperature"],
                "max_tokens": cur["max_tokens"], "providers": providers}

    # -- web search settings ---------------------------------------------
    def search_public(self):
        from .search.engines import ENGINE_INFO
        cfg = self._data.get("search") or {}
        on = cfg.get("engines") or []
        return {"max_pages": int(cfg.get("max_pages", 16)),
                "engines": [dict(e, enabled=e["id"] in on,
                                 has_key=bool(self.search_keys().get(e["id"])) if e["needs_key"] else None)
                            for e in ENGINE_INFO]}

    def search_keys(self):
        return {"tavily": self.get_key("search:tavily")[0], "zhipu": self.get_key("zhipu")[0]}

    def search_engines(self):
        return list((self._data.get("search") or {}).get("engines") or [])

    def update_search(self, patch):
        from .search.engines import ENGINE_INFO
        if not isinstance(patch, dict):
            raise ApiError(400, "invalid_request", "body must be an object")
        ids = {e["id"] for e in ENGINE_INFO}
        with self._lock:
            sc = self._data.setdefault("search", {})
            if "engines" in patch:
                eng = patch["engines"]
                if not isinstance(eng, list) or any(e not in ids for e in eng):
                    raise ApiError(400, "invalid_request", "unknown engine")
                sc["engines"] = list(dict.fromkeys(eng))
            if "max_pages" in patch:
                mp = patch["max_pages"]
                if isinstance(mp, bool) or not isinstance(mp, int) or not 3 <= mp <= 30:
                    raise ApiError(400, "invalid_request", "max_pages must be 3..30")
                sc["max_pages"] = mp
            key = patch.get("tavily_key")
            if patch.get("clear_tavily_key"):
                self._secrets.pop("search:tavily", None)
            elif isinstance(key, str) and key.strip():
                k = key.strip()
                if len(k) > 200 or any(c.isspace() for c in k):
                    raise ApiError(400, "invalid_request", "key 格式不正确")
                self._secrets["search:tavily"] = k
            self._atomic(self.path, self._data)
            self._atomic(self.secrets_path, self._secrets, private=True)
        return self.search_public()

    # -- write -----------------------------------------------------------
    def update(self, patch):
        if not isinstance(patch, dict):
            raise ApiError(400, "invalid_request", "body must be an object")
        pid = patch.get("provider")
        if pid not in BY_ID:
            raise ApiError(400, "invalid_request", "unknown provider")
        preset = BY_ID[pid]
        with self._lock:
            entry = dict(self._data.setdefault("providers", {}).get(pid, {}))
            if "base_url" in patch:
                entry["base_url"] = validate_base_url(pid, patch["base_url"])
            if "model" in patch:
                m = patch["model"]
                if not isinstance(m, str) or not _MODEL_RE.match(m.strip()):
                    raise ApiError(400, "invalid_request", "model 只能包含字母数字和 . _ : / -")
                entry["model"] = m.strip()
            if "temperature" in patch:
                t = patch["temperature"]
                if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t <= 2:
                    raise ApiError(400, "invalid_request", "temperature must be 0..2")
                self._data["temperature"] = float(t)
            if "max_tokens" in patch:
                mt = patch["max_tokens"]
                if isinstance(mt, bool) or not isinstance(mt, int) or not 64 <= mt <= 4000:
                    raise ApiError(400, "invalid_request", "max_tokens must be 64..4000")
                self._data["max_tokens"] = mt
            self._data["providers"][pid] = entry
            self._data["provider"] = pid

            if preset["remote"]:
                key = patch.get("api_key")
                if patch.get("clear_key"):
                    self._secrets.pop(pid, None)
                elif isinstance(key, str) and key.strip():
                    k = key.strip()
                    if len(k) > 400 or any(c.isspace() for c in k):
                        raise ApiError(400, "invalid_request", "api_key 格式不正确")
                    self._secrets[pid] = k
                base = entry.get("base_url") or preset["base_url"]
                consent = self._data.setdefault("consent", {})
                if patch.get("consent") is True:
                    consent[pid] = {"at": now_iso(), "host": host_of(base)}
                elif patch.get("consent") is False or \
                        (consent.get(pid) and consent[pid].get("host") != host_of(base)):
                    consent.pop(pid, None)       # revoked, or the destination host changed
            self._atomic(self.path, self._data)
            self._atomic(self.secrets_path, self._secrets, private=True)
        return self.public()
