from .base import LLMError, LLMProvider  # noqa: F401
from .mock import MockProvider
from .ollama import OllamaProvider


def create_provider(cfg):
    if cfg.llm_provider == "ollama":
        return OllamaProvider(cfg.ollama_url, cfg.ollama_model, cfg.llm_timeout_s)
    return MockProvider(cfg.mock_mode)
