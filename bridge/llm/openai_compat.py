"""OpenAI-compatible /chat/completions client (DeepSeek, Qwen, GLM, Kimi, Doubao, GPT, relays...).

Vendors disagree on optional parameters, so on an HTTP 400 that names a parameter we adapt and
retry (max 3 times): drop response_format / temperature / extra_body, or swap max_tokens for
max_completion_tokens. The API key never appears in logs or error messages.
"""
import json
import re
import socket
import time
import urllib.error
import urllib.request

from .base import LLMError, LLMProvider


class OpenAICompatProvider(LLMProvider):
    name = "openai_compat"

    def __init__(self, base_url, model, api_key, timeout_s=25.0, temperature=0.7, max_tokens=600,
                 extra_body=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._key = api_key
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = dict(extra_body or {})

    def _redact(self, text):
        text = str(text)
        return text.replace(self._key, "***") if self._key else text

    def _post(self, payload):
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._key},
            method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _error_text(exc):
        try:
            body = exc.read().decode("utf-8", "replace")
            data = json.loads(body)
            err = data.get("error", data)
            return (err.get("message") if isinstance(err, dict) else str(err)) or body
        except Exception:
            return ""

    def generate(self, messages, meta=None):
        meta = meta or {}
        # per-call overrides: card extraction needs a much larger output budget than a one-line dialogue
        payload = {"model": self.model, "messages": messages,
                   "temperature": meta.get("temperature", self.temperature),
                   "max_tokens": min(int(meta.get("max_tokens", self.max_tokens)), 8000), "stream": False,
                   "response_format": {"type": "json_object"}}
        payload.update(self.extra_body)
        for attempt in range(4):
            try:
                data = self._post(payload)
                break
            except urllib.error.HTTPError as exc:
                msg = self._redact(self._error_text(exc))[:300]
                low = msg.lower()
                if exc.code == 400 and attempt < 3:
                    if "response_format" in low and payload.pop("response_format", None):
                        continue
                    if "max_completion_tokens" in low and "max_tokens" in payload:
                        payload["max_completion_tokens"] = payload.pop("max_tokens")
                        continue
                    if "temperature" in low and payload.pop("temperature", None) is not None:
                        continue
                    dropped = [k for k in self.extra_body if k in low and payload.pop(k, None) is not None]
                    if dropped:
                        continue
                raise LLMError(self._code_for(exc.code), "HTTP %d %s" % (exc.code, msg))
            except socket.timeout:
                raise LLMError("llm_timeout", "timeout after %.0fs" % self.timeout_s)
            except urllib.error.URLError as exc:
                if isinstance(getattr(exc, "reason", None), socket.timeout):
                    raise LLMError("llm_timeout", "timeout after %.0fs" % self.timeout_s)
                raise LLMError("llm_unavailable", self._redact("cannot reach server: %s" % exc.reason))
            except (OSError, ValueError) as exc:
                raise LLMError("llm_unavailable", self._redact(str(exc)))
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("llm_bad_response", "unexpected response shape")
        if not content and (choice["message"].get("reasoning_content") or choice.get("finish_reason") == "length"):
            raise LLMError("llm_truncated",
                           "模型把输出额度/时间用在“思考”上，没有给出正文。请换成非推理模型（如 air / flash），或关闭思考。")
        if choice.get("finish_reason") == "length" and content:
            raise LLMError("llm_truncated", "输出在中途被截断（达到长度上限），得到的 JSON 不完整。"
                           "请换用非推理模型，或在设置里调大“最大输出”。")
        if isinstance(content, list):         # some vendors return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            raise LLMError("llm_bad_response", "empty model output")
        return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()

    @staticmethod
    def _code_for(status):
        if status in (401, 403):
            return "llm_auth"
        if status == 402:
            return "llm_billing"
        if status == 404:
            return "llm_not_found"
        if status == 408:
            return "llm_timeout"
        if status == 429:
            return "llm_rate_limited"
        return "llm_unavailable" if status >= 500 else "llm_bad_request"
