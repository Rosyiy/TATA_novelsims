"""Builds the active provider from the saved settings on every call (so UI changes apply at once)."""
import time

from .base import LLMError, LLMProvider
from .mock import MockProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider
from .presets import BY_ID


class ProviderManager(LLMProvider):
    def __init__(self, cfg, settings):
        self.cfg = cfg
        self.settings = settings

    @property
    def name(self):
        return self.settings.current()["id"]

    def describe(self):
        cur = self.settings.current()
        preset = BY_ID[cur["id"]]
        return {"id": cur["id"], "name": preset["name"], "model": cur["model"],
                "remote": preset["remote"], "base_url": cur["base_url"]}

    def _build(self):
        cur = self.settings.current()
        pid, preset = cur["id"], BY_ID[cur["id"]]
        if pid == "mock":
            return MockProvider(self.cfg.mock_mode)
        if pid == "ollama":
            return OllamaProvider(cur["base_url"], cur["model"] or self.cfg.ollama_model,
                                  self.cfg.llm_timeout_s)
        if not cur["model"]:
            raise LLMError("not_configured", "请先填写模型名")
        if not self.settings.has_consent(pid, cur["base_url"]):
            raise LLMError("consent_required", "尚未确认向该云端服务发送角色资料")
        key, _ = self.settings.get_key(pid)
        if not key:
            raise LLMError("no_key", "尚未填写 API Key")
        return OpenAICompatProvider(cur["base_url"], cur["model"], key, self.cfg.llm_timeout_s,
                                    cur["temperature"], cur["max_tokens"], preset.get("extra_body"))

    def generate(self, messages, meta=None):
        return self._build().generate(messages, meta)

    def test(self):
        """Tiny round trip used by the dashboard's 'test connection' button."""
        t0 = time.time()
        raw = self.generate([{"role": "user", "content": 'Reply with the JSON object {"ok": true}'}])
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000), "sample": raw[:120],
                **{k: v for k, v in self.describe().items() if k in ("id", "model")}}
