"""Validation of model output (spec 6.1, 9). Failure => result is discarded."""
import json
import re

from ..memory.store import sanitize_text

ALLOWED_EMOTIONS = {"neutral", "happy", "sad", "angry", "anxious", "affectionate",
                    "playful", "embarrassed", "confident", "tense"}


class Rejected(Exception):
    def __init__(self, reason, details=""):
        Exception.__init__(self, reason)
        self.reason = reason
        self.details = details


def parse_model_json(raw):
    if not isinstance(raw, str):
        raise Rejected("invalid_json", "model output is not text")
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise Rejected("invalid_json", "no JSON object found")
    body = text[start:end + 1]
    try:
        data = json.loads(body)
    except ValueError as exc:
        try:                                    # models often leave trailing commas; that is safe to repair
            data = json.loads(re.sub(r",\s*([}\]])", r"\1", body))
        except ValueError:
            raise Rejected("invalid_json", str(exc))
    if not isinstance(data, dict):
        raise Rejected("invalid_json", "top level is not an object")
    return data


def validate_model_output(data, expected_character_id, expected_target_id, card,
                          max_dialogue_chars=200, strict=False):
    """Return a normalized dict (without request_id/status) or raise Rejected."""
    # 1-3. required fields and id matching
    for key in ("character_id", "dialogue"):
        if key not in data:
            raise Rejected("missing_field", key)
    if data["character_id"] != expected_character_id:
        raise Rejected("character_mismatch", "character_id differs from request")
    got_target = data.get("target_character_id")
    if got_target != expected_target_id:
        raise Rejected("target_mismatch", "target_character_id differs from request")

    dlg = data["dialogue"]
    if not isinstance(dlg, dict) or not isinstance(dlg.get("text"), str):
        raise Rejected("missing_field", "dialogue.text")
    text = sanitize_text(dlg["text"])
    if not text:
        raise Rejected("empty_dialogue")
    if len(text) > max_dialogue_chars:
        raise Rejected("dialogue_too_long", "%d > %d" % (len(text), max_dialogue_chars))

    if strict:                                   # protection level 5
        cons = data.get("consistency")
        if isinstance(cons, dict) and (cons.get("status") not in (None, "pass") or cons.get("conflicts")):
            raise Rejected("consistency_conflict", "model reported a consistency problem")
    # 6. hard rules (substring match on the card's forbidden_terms)
    lowered = text.lower()
    for term in (card.get("hard_rules") or {}).get("forbidden_terms", []):
        if term and term.lower() in lowered:
            raise Rejected("consistency_conflict", "forbidden term: %s" % term)

    emotion = dlg.get("emotion") if dlg.get("emotion") in ALLOWED_EMOTIONS else "neutral"
    tone = sanitize_text(str(dlg.get("tone", "")))[:40]

    behavior = None
    b = data.get("behavior")
    if isinstance(b, dict) and isinstance(b.get("suggestion"), str):
        prio = b.get("priority")
        prio = prio if isinstance(prio, int) and not isinstance(prio, bool) and 1 <= prio <= 5 else 3
        behavior = {"suggestion": sanitize_text(b["suggestion"])[:100],
                    "target_id": expected_target_id, "priority": prio,
                    "reason": sanitize_text(str(b.get("reason", "")))[:200]}

    # memory candidates are only candidates: invalid ones are dropped, not fatal
    candidate = None
    m = data.get("memory_candidate")
    if isinstance(m, dict) and isinstance(m.get("content"), str):
        content = sanitize_text(m["content"])
        imp = m.get("importance")
        if content and len(content) <= 200 and isinstance(imp, int) \
                and not isinstance(imp, bool) and 1 <= imp <= 10:
            candidate = {"content": content, "importance": imp}

    return {"character_id": expected_character_id,
            "target_character_id": expected_target_id,
            "dialogue": {"text": text, "emotion": emotion, "tone": tone},
            "behavior": behavior, "memory_candidate": candidate,
            "consistency": {"status": "pass", "conflicts": []}}
