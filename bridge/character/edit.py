"""Player edits of a character card (spec 5.2 / 5.6): validated, bounded, markup-free."""
from ..errors import ApiError
from ..extraction.card import DEFAULT_FORBIDDEN_TERMS, STAGE_KEYS, _list, _s

LIST_FIELDS = {"alias": (6, 30), "core_personality": (8, 60), "variable_personality": (8, 60),
               "behavioral_tendencies": (12, 100), "core_rules": (12, 100), "forbidden_behaviors": (12, 100)}
STR_FIELDS = {"identity": 120, "background": 600, "core_motivation": 200, "core_trauma": 200}


def compute_missing(card):
    miss = [f for f in ("identity", "background", "core_personality", "core_motivation") if not card.get(f)]
    if not (card.get("speech_style") or {}).get("summary"):
        miss.append("speech_style")
    for f in ("relationships", "canon_memories"):
        if not card.get(f):
            miss.append(f)
    if not (card.get("timeline") or {}).get("stages"):
        miss.append("timeline")
    return miss


def blank_card(name):
    return {"name": name, "alias": [], "source_novel": "", "source_author": "", "source_version": "",
            "language": "中文", "identity": "", "background": "", "core_personality": [],
            "variable_personality": [], "speech_style": {"summary": "", "address": "", "sample_phrases": []},
            "behavioral_tendencies": [], "core_trauma": "", "core_motivation": "", "core_rules": [],
            "forbidden_behaviors": [], "hard_rules": {"forbidden_terms": list(DEFAULT_FORBIDDEN_TERMS)},
            "relationships": [], "canon_memories": [], "conflicts": [], "info_sources": [],
            "timeline": {"current_stage": None, "stages": {}}, "origin": "user_defined", "low_data": False,
            "missing_fields": [], "verification_status": "user_defined"}


def apply_edit(card, patch):
    if not isinstance(patch, dict):
        raise ApiError(400, "invalid_request", "body must be an object")
    for k, n in STR_FIELDS.items():
        if k in patch:
            card[k] = _s(patch[k], n)
    for k, (n, m) in LIST_FIELDS.items():
        if k in patch:
            card[k] = _list(patch[k], n, m)
    if isinstance(patch.get("speech_style"), dict):
        ss = patch["speech_style"]
        cur = card.setdefault("speech_style", {})
        if "summary" in ss:
            cur["summary"] = _s(ss["summary"], 200)
        if "address" in ss:
            cur["address"] = _s(ss["address"], 100)
        if "sample_phrases" in ss:
            cur["sample_phrases"] = _list(ss["sample_phrases"], 5, 60)
    if isinstance(patch.get("relationships"), list):
        card["relationships"] = [{"name": _s(r.get("name"), 30), "relation": _s(r.get("relation"), 60),
                                  "stage": _s(r.get("stage"), 80), "sources": ["user"]}
                                 for r in patch["relationships"][:12] if isinstance(r, dict) and _s(r.get("name"), 30)]
    if isinstance(patch.get("canon_memories"), list):
        mems = []
        for m in patch["canon_memories"][:20]:
            if isinstance(m, dict) and _s(m.get("content"), 200):
                imp = m.get("importance")
                mems.append({"content": _s(m["content"], 200), "sources": ["user"],
                             "importance": imp if isinstance(imp, int) and not isinstance(imp, bool) and 1 <= imp <= 10 else 5})
        card["canon_memories"] = mems
    if isinstance(patch.get("hard_rules"), dict) and "forbidden_terms" in patch["hard_rules"]:
        card["hard_rules"] = {"forbidden_terms": _list(patch["hard_rules"]["forbidden_terms"], 12, 30)}
    tl = card.setdefault("timeline", {"current_stage": None, "stages": {}})
    if isinstance(patch.get("timeline"), dict) and "current_stage" in patch["timeline"]:
        cs = patch["timeline"]["current_stage"]
        if cs is not None and cs not in (tl.get("stages") or {}) or (cs is not None and cs not in STAGE_KEYS):
            raise ApiError(400, "invalid_request", "current_stage 必须是已有的时间阶段")
        tl["current_stage"] = cs
    card["missing_fields"] = compute_missing(card)
    card["edited"] = True
    if card.get("verification_status") == "confirmed":
        card["verification_status"] = "draft"        # changed after confirmation: needs a new check
    return card
