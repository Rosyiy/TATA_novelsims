class LLMError(Exception):
    """code: llm_unavailable | llm_timeout | llm_bad_response"""

    def __init__(self, code, message=""):
        Exception.__init__(self, message or code)
        self.code = code


class LLMProvider(object):
    name = "base"

    def generate(self, messages, meta=None):
        """Return the raw model text. `meta` is only for the mock provider."""
        raise NotImplementedError
