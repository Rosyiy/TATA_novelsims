"""Deterministic test model. Modes let tests exercise every failure path."""
import json
import time

from .base import LLMError, LLMProvider


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, mode="ok", slow_seconds=2.0):
        self.mode = mode
        self.slow_seconds = slow_seconds

    def _extract(self, meta):
        mode = self.mode
        if mode == "error":
            raise LLMError("llm_unavailable", "mock error")
        if mode == "bad_json":
            return "not json"
        name, ids, text = meta.get("character_name", "某人"), meta.get("source_ids") or [], meta.get("source_text", "")
        sid = ids[0] if ids else None
        out = {"identity": "%s（由资料整理）" % name, "background": text[:80], "core_personality": ["坚韧"],
               "speech_style": {"summary": "语气平静", "address": "", "sample_phrases": []},
               "relationships": [], "canon_memories": [], "timeline": {"stages": {}}, "conflicts": [],
               "missing_fields": []}
        if sid:
            out["relationships"] = [{"name": "同伴", "relation": "同伴", "stage": "", "sources": [sid]}]
            out["canon_memories"] = [{"content": text[:60] or "出场", "importance": 6, "sources": [sid]}]
            out["timeline"] = {"stages": {"original_mid": {"state": "故事中段", "known_info": [], "goal": "", "sources": [sid]}}}
        if mode == "hallucinate":
            out["relationships"].append({"name": "虚构人物", "relation": "恋人", "stage": "", "sources": ["S99"]})
            out["canon_memories"].append({"content": "编造的事件", "importance": 9, "sources": ["S99"]})
            out["speech_style"]["sample_phrases"] = ["这句话资料里根本没有"]
        return json.dumps(out, ensure_ascii=False)

    def generate(self, messages, meta=None):
        meta = meta or {}
        if meta.get("task") == "extract":
            return self._extract(meta)
        mode = self.mode
        if mode == "error":
            raise LLMError("llm_unavailable", "mock error")
        if mode == "slow":
            time.sleep(self.slow_seconds)
        if mode == "bad_json":
            return "this is not json {"
        phrase = (meta.get("sample_phrase") or "嗯。")
        text = "%s，%s" % (meta.get("target_name") or "你", phrase)
        if mode == "ooc" and meta.get("forbidden_terms"):
            text = meta["forbidden_terms"][0]
        out = {
            "character_id": meta.get("character_id"),
            "target_character_id": meta.get("target_character_id"),
            "dialogue": {"text": text, "emotion": "neutral", "tone": "calm"},
            "behavior": {"suggestion": "继续交谈", "priority": 3, "reason": "符合人物性格"},
            "memory_candidate": {"content": "与%s进行了一次简短交谈" % (meta.get("target_name") or "对方"),
                                 "importance": 3},
            "consistency": {"status": "pass", "conflicts": []},
        }
        if mode == "conflict":
            out["consistency"] = {"status": "conflict", "conflicts": ["与核心规则冲突"]}
        if mode == "wrongid":
            out["character_id"] = "char_wrong"
        return "```json\n" + json.dumps(out, ensure_ascii=False) + "\n```"
