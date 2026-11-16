"""Turn source excerpts into a character card (spec 5.2) WITHOUT letting the model invent facts.

The model only proposes; this module enforces: every relationship / timeline stage / canon memory
must cite a source id that really was supplied, quoted speech must occur verbatim in a source,
and missing information stays missing (low_data) instead of being filled in.
"""
import re

from ..memory.store import sanitize_text
from ..validation.dialogue import Rejected, parse_model_json  # noqa: F401  (re-exported for callers)

STAGE_KEYS = ("original_early", "original_mid", "original_late", "original_ending", "extra")
KEY_FIELDS = ("identity", "background", "core_personality")
DEFAULT_FORBIDDEN_TERMS = ["我是AI", "语言模型", "人工智能"]

SYSTEM = (
    "你是小说人物资料整理员。只根据下面【资料】里的文字整理人物身份卡，只输出一个JSON对象。\n"
    "硬性规则：\n"
    "1. 资料没写的内容，字符串留空\"\"，列表留[]，并把字段名写进 missing_fields。绝不补全、绝不凭你对这部小说的记忆回答。\n"
    "2. relationships、timeline.stages、canon_memories 的每一条，必须在 sources 里写出依据的资料编号（如\"S2\"）；写不出依据就不要写这一条。\n"
    "3. 资料之间说法冲突时，不要二选一：写进 conflicts，列出各自说法和编号。\n"
    "4. speech_style.sample_phrases 只能是资料里逐字出现的人物原话（每句不超过30字），没有就留[]。\n"
    "5. 资料标注 edition=adaptation 的来自影视/漫画等改编版，不要把改编内容当作原著事实；不确定就放进 conflicts。\n"
    "6. 时间阶段 key 只能是 original_early / original_mid / original_late / original_ending / extra。\n"
    "输出格式（字段齐全，可为空）：\n"
    '{"identity":"","background":"","core_personality":[],"variable_personality":[],'
    '"speech_style":{"summary":"","address":"","sample_phrases":[]},"behavioral_tendencies":[],'
    '"core_trauma":"","core_motivation":"","core_rules":[],"forbidden_behaviors":[],'
    '"relationships":[{"name":"","relation":"","stage":"","sources":["S1"]}],'
    '"timeline":{"stages":{"original_mid":{"state":"","known_info":[],"goal":"","sources":["S1"]}}},'
    '"canon_memories":[{"content":"","importance":5,"sources":["S1"]}],'
    '"conflicts":[{"field":"","candidates":[{"claim":"","sources":["S1"]}]}],"missing_fields":[]}'
)


def build_messages(novel, name, aliases, ctx_sources):
    head = "[小说] 书名：%s；作者：%s；版本：%s\n[人物] %s%s\n[资料]\n" % (
        novel["title"], novel.get("author") or "未知", novel.get("version") or "未注明", name,
        ("（别名：%s）" % "、".join(aliases)) if aliases else "")
    body = "\n".join('<%s kind=%s edition=%s>\n%s\n</%s>' % (s["id"], s["kind"], s["edition"], s["text"], s["id"])
                     for s in ctx_sources)
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": head + body}]


def _s(v, n):
    return sanitize_text(str(v))[:n] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _list(v, n, m):
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        t = _s(x, m)
        if t and t not in out:
            out.append(t)
        if len(out) >= n:
            break
    return out


def _cites(v, valid):
    return [x for x in dict.fromkeys(v if isinstance(v, list) else []) if isinstance(x, str) and x in valid]


def _norm(t):
    return re.sub(r"\s+", "", t)


def validate_card(data, name, aliases, novel, sources, origin, novel_id=None):
    """Return (card, warnings). `sources` = [{id,name,url,kind,edition,text}] actually given to the model."""
    if not isinstance(data, dict):
        raise Rejected("invalid_json", "top level is not an object")
    valid = {s["id"] for s in sources}
    blob = _norm("\n".join(s["text"] for s in sources))
    warnings, dropped = [], 0

    ss = data.get("speech_style") if isinstance(data.get("speech_style"), dict) else {}
    phrases = []
    for p in _list(ss.get("sample_phrases"), 5, 60):
        if _norm(p) in blob:
            phrases.append(p)
        else:
            dropped += 1                   # not verbatim in any source => treated as invented
    rels = []
    for r in (data.get("relationships") if isinstance(data.get("relationships"), list) else [])[:12]:
        if not isinstance(r, dict):
            continue
        src = _cites(r.get("sources"), valid)
        if _s(r.get("name"), 30) and src:
            rels.append({"name": _s(r["name"], 30), "relation": _s(r.get("relation"), 60),
                         "stage": _s(r.get("stage"), 80), "sources": src})
        else:
            dropped += 1
    stages = {}
    tl = data.get("timeline") if isinstance(data.get("timeline"), dict) else {}
    for key, st in (tl.get("stages") if isinstance(tl.get("stages"), dict) else {}).items():
        src = _cites((st or {}).get("sources") if isinstance(st, dict) else None, valid)
        if key in STAGE_KEYS and src and _s(st.get("state"), 200):
            stages[key] = {"state": _s(st["state"], 200), "known_info": _list(st.get("known_info"), 6, 100),
                           "goal": _s(st.get("goal"), 120), "sources": src}
        else:
            dropped += 1
    mems = []
    for m in (data.get("canon_memories") if isinstance(data.get("canon_memories"), list) else [])[:12]:
        if not isinstance(m, dict):
            continue
        src, content, imp = _cites(m.get("sources"), valid), _s(m.get("content"), 200), m.get("importance")
        if content and src:
            mems.append({"content": content, "sources": src,
                         "importance": imp if isinstance(imp, int) and not isinstance(imp, bool) and 1 <= imp <= 10 else 5})
        else:
            dropped += 1
    conflicts = []
    for c in (data.get("conflicts") if isinstance(data.get("conflicts"), list) else [])[:6]:
        cands = []
        for cd in (c.get("candidates") if isinstance(c, dict) and isinstance(c.get("candidates"), list) else [])[:4]:
            src = _cites(cd.get("sources") if isinstance(cd, dict) else None, valid)
            if isinstance(cd, dict) and _s(cd.get("claim"), 150) and src:
                cands.append({"claim": _s(cd["claim"], 150), "sources": src})
        if len(cands) >= 2:
            conflicts.append({"field": _s(c.get("field"), 40), "candidates": cands})
    if dropped:
        warnings.append("丢弃了 %d 条没有有效来源或无法在资料中核实的内容" % dropped)

    card = {
        "name": name, "alias": aliases, "source_novel": novel["title"], "source_author": novel.get("author", ""),
        "source_version": novel.get("version", ""), "language": "中文",
        "identity": _s(data.get("identity"), 120), "background": _s(data.get("background"), 600),
        "core_personality": _list(data.get("core_personality"), 8, 60),
        "variable_personality": _list(data.get("variable_personality"), 8, 60),
        "speech_style": {"summary": _s(ss.get("summary"), 200), "address": _s(ss.get("address"), 100),
                         "sample_phrases": phrases},
        "behavioral_tendencies": _list(data.get("behavioral_tendencies"), 8, 100),
        "core_trauma": _s(data.get("core_trauma"), 200), "core_motivation": _s(data.get("core_motivation"), 200),
        "core_rules": _list(data.get("core_rules"), 8, 100),
        "forbidden_behaviors": _list(data.get("forbidden_behaviors"), 8, 100),
        "hard_rules": {"forbidden_terms": list(DEFAULT_FORBIDDEN_TERMS)},
        "relationships": rels, "canon_memories": mems, "conflicts": conflicts,
        "timeline": {"current_stage": next((k for k in STAGE_KEYS if k in stages), None), "stages": stages},
        "info_sources": [{"id": s["id"], "name": s.get("name", ""), "url": s.get("url", ""), "kind": s["kind"],
                          "edition": s["edition"]} for s in sources],
        "origin": origin, "novel_id": novel_id}

    missing = [f for f in ("identity", "background", "core_personality", "core_motivation") if not card[f]]
    if not card["speech_style"]["summary"]:
        missing.append("speech_style")
    for f, v in (("relationships", rels), ("canon_memories", mems), ("timeline", stages)):
        if not v:
            missing.append(f)
    card["missing_fields"] = missing
    total = sum(len(s["text"]) for s in sources)
    low = len(sources) < 2 or total < 500 or sum(1 for f in KEY_FIELDS if not card[f]) >= 2
    if origin == "user_text" and len(sources) >= 1 and total >= 150:
        low = sum(1 for f in KEY_FIELDS if not card[f]) >= 2     # the user's own text is a single source
    card["low_data"] = bool(low)
    card["verification_status"] = "low_data" if low else "draft"
    return card, warnings


def empty_card(name, aliases, novel, sources, origin, novel_id=None):
    """No usable text mentions this character: do not ask the model, do not guess."""
    card, _ = validate_card({}, name, aliases, novel, sources, origin, novel_id)
    card["missing_fields"] = ["identity", "background", "core_personality", "core_motivation",
                              "speech_style", "relationships", "canon_memories", "timeline"]
    card["low_data"], card["verification_status"] = True, "low_data"
    return card
