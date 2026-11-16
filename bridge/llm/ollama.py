"""Ollama provider (/api/chat, non-streaming, JSON mode). stdlib only."""
import json
import socket
import urllib.error
import urllib.request

from .base import LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url, model, timeout_s=25.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    def generate(self, messages, meta=None):
        meta = meta or {}
        opts = {"temperature": meta.get("temperature", 0.7)}
        if meta.get("max_tokens"):
            opts["num_predict"] = int(meta["max_tokens"])
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "format": "json", "options": opts}
        req = urllib.request.Request(
            self.base_url + "/api/chat", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except socket.timeout:
            raise LLMError("llm_timeout", "ollama timed out")
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), socket.timeout):
                raise LLMError("llm_timeout", "ollama timed out")
            raise LLMError("llm_unavailable", "ollama unreachable: %s" % exc.reason)
        except (OSError, ValueError) as exc:
            raise LLMError("llm_unavailable", str(exc))
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMError("llm_bad_response", "empty ollama response")
        return content
