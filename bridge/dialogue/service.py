"""Dialogue generation: validate request -> assemble context -> model -> validate."""
import json
import logging
import re
import threading
import time
from collections import OrderedDict

from ..errors import ApiError
from ..llm import LLMError
from ..memory.store import check_save_key, now_iso
from ..validation.dialogue import Rejected, parse_model_json, validate_model_output

log = logging.getLogger("novelsims.dialogue")
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

SYSTEM_TEMPLATE = (
    "你是《模拟人生4》里小说人物「{name}」的对话生成器。只输出一个JSON对象，不要解释，不要Markdown。\n"
    "规则：\n"
    "1. 严格遵守角色卡的核心人格、说话风格、核心规则，绝不做出禁止行为。\n"
    "2. 只使用下面提供的已知信息，不得编造原著事实；不确定就不说。\n"
    "3. 台词使用{language}，不超过{max_chars}字，不得包含花括号或尖括号。\n"
    "4. 角色不得知道当前阶段尚未发生的事件。\n"
    "5. 保持角色身份，不得提及自己是AI或语言模型。\n"
    "6. 若资料中有 source_conflicts（来源说法冲突），不要断言其中任何一种说法。\n"
    "输出格式：\n"
    '{{"character_id":"{cid}","target_character_id":{tid},'
    '"dialogue":{{"text":"台词","emotion":"neutral|happy|sad|angry|anxious|affectionate|playful|embarrassed|confident|tense","tone":"语气"}},'
    '"behavior":{{"suggestion":"行为建议","priority":3,"reason":"原因"}},'
    '"memory_candidate":null,"consistency":{{"status":"pass","conflicts":[]}}}}\n'
    "behavior与memory_candidate可为null；memory_candidate形如"
    '{{"content":"一句话记忆","importance":1到10的整数}}。'
)


LEVEL_FIELDS = {
    1: ("name", "identity", "core_personality"),                                              # brief card + basic personality
    2: ("name", "identity", "core_personality", "speech_style"),                              # + speaking style, relations, state
    3: ("name", "identity", "core_personality", "speech_style", "behavioral_tendencies", "core_motivation",
        "core_rules", "background", "variable_personality", "core_trauma"),                  # full card + memories
}
LEVEL_FIELDS[4] = LEVEL_FIELDS[3] + ("forbidden_behaviors",)                                  # + forbidden, timeline, conflicts
LEVEL_FIELDS[5] = LEVEL_FIELDS[4]                                                             # + strict validation
DEFAULT_LEVEL = 4


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def validate_request(body):
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_request", "body must be an object")
    rid = body.get("request_id")
    if not isinstance(rid, str) or not _ID_RE.match(rid):
        raise ApiError(400, "invalid_request", "request_id invalid")
    check_save_key(body.get("save_key"))
    for who in ("actor", "target"):
        p = body.get(who)
        if not isinstance(p, dict) or not _is_int(p.get("sim_id")):
            raise ApiError(400, "invalid_request", who + ".sim_id must be an integer")
        if not isinstance(p.get("name", ""), str):
            raise ApiError(400, "invalid_request", who + ".name must be a string")
        cid = p.get("character_id")
        if cid is not None and (not isinstance(cid, str) or not _ID_RE.match(cid)):
            raise ApiError(400, "invalid_request", who + ".character_id invalid")
    if not body["actor"].get("character_id"):
        raise ApiError(400, "invalid_request", "actor.character_id is required")
    lvl = body["actor"].get("protection_level", DEFAULT_LEVEL)
    if not _is_int(lvl) or not 1 <= lvl <= 5:
        raise ApiError(400, "invalid_request", "actor.protection_level must be 1..5")
    st = body["actor"].get("stage")
    if st is not None and (not isinstance(st, str) or len(st) > 32):
        raise ApiError(400, "invalid_request", "actor.stage invalid")
    inter = body.get("interaction")
    if not isinstance(inter, dict) or not isinstance(inter.get("name"), str):
        raise ApiError(400, "invalid_request", "interaction.name required")
    return body


class DialogueService(object):
    CACHE_SIZE = 256

    def __init__(self, cfg, characters, memories, provider, db):
        self.cfg = cfg
        self.characters = characters
        self.memories = memories
        self.provider = provider
        self.db = db
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    # -- helpers ---------------------------------------------------------
    def _cache_get(self, rid):
        with self._lock:
            return self._cache.get(rid)

    def _cache_put(self, rid, value):
        with self._lock:
            self._cache[rid] = value
            while len(self._cache) > self.CACHE_SIZE:
                self._cache.popitem(last=False)

    def _log(self, rid, actor, target, est, sections, outcome):
        try:
            with self.db.session() as conn:
                conn.execute("INSERT INTO request_log VALUES (?,?,?,?,?,?,?)",
                             (rid, now_iso(), actor, target or "", est,
                              json.dumps(sections, ensure_ascii=False), outcome))
        except Exception:  # logging must never break a request
            log.exception("request_log write failed")

    @staticmethod
    def _level(body):
        return body["actor"].get("protection_level", DEFAULT_LEVEL)

    def _build_context(self, body, card, target_card):
        lvl = self._level(body)
        sections = []   # (name, text) in priority order (spec 10)
        keep = {k: card.get(k) for k in LEVEL_FIELDS[lvl]}
        sections.append(("character_card", json.dumps(keep, ensure_ascii=False)))
        tl = card.get("timeline") or {}
        stages = tl.get("stages") or {}
        want = body["actor"].get("stage")
        key = want if want in stages else tl.get("current_stage")     # the player may switch the story stage in game
        stage = stages.get(key)
        if lvl >= 2 and stage:
            if lvl >= 4:
                sections.append(("timeline", json.dumps({"current_stage": key, "stage": stage}, ensure_ascii=False)))
            else:
                sections.append(("timeline", json.dumps({"current_stage": key, "state": stage.get("state")}, ensure_ascii=False)))
        tname = body["target"].get("name") or ""
        if lvl >= 2:
            rel = [r for r in card.get("relationships", [])
                   if tname and (r.get("name") == tname or (target_card and r.get("name") == target_card.get("name")))]
            if rel:
                sections.append(("relationship_canon", json.dumps(rel, ensure_ascii=False)))
        tkeys = ["sim:%d" % body["target"]["sim_id"]]
        if body["target"].get("character_id"):
            tkeys.append(body["target"]["character_id"])
        mem = self.memories.query(body["save_key"], card["character_id"], tkeys,
                                  [tname, (target_card or {}).get("name")])
        if lvl >= 3 and mem["canon"]:
            sections.append(("canon_memories", json.dumps([m["content"] for m in mem["canon"]], ensure_ascii=False)))
        if lvl >= 3 and mem["dynamic"]:
            sections.append(("dynamic_memories", json.dumps([m["content"] for m in mem["dynamic"]], ensure_ascii=False)))
        if lvl >= 4 and card.get("conflicts"):
            sections.append(("source_conflicts", json.dumps(
                [{"field": c.get("field"), "claims": [k.get("claim") for k in c.get("candidates", [])]}
                 for c in card["conflicts"]], ensure_ascii=False)))
        sections.append(("scene", json.dumps(
            {"interaction": body["interaction"]["name"], "speaking_to": tname or "未知"},
            ensure_ascii=False)))

        included, dropped, used = [], [], 0
        for name, text in sections:
            if used + len(text) <= self.cfg.max_context_chars or not included:
                included.append((name, text))
                used += len(text)
            else:
                dropped.append(name)
        return included, dropped, used

    # -- main ------------------------------------------------------------
    def generate(self, body):
        validate_request(body)
        rid = body["request_id"]
        cached = self._cache_get(rid)
        if cached is not None:          # idempotency (API_SPEC: same request_id => same result)
            return cached
        result = self._generate(body)
        if result[0] != 503:            # do not cache transient model failures
            self._cache_put(rid, result)
        return result

    def _generate(self, body):
        rid = body["request_id"]
        actor_cid = body["actor"]["character_id"]
        target_cid = body["target"].get("character_id")
        card = self.characters.get(actor_cid)
        if card is None:
            raise ApiError(404, "character_not_found", actor_cid)
        target_card = self.characters.get(target_cid) if target_cid else None
        if target_cid and target_card is None:
            raise ApiError(404, "character_not_found", target_cid)

        messages, included, dropped, used = self._messages(body, card, target_card)
        est_tokens = (used + 1) // 2      # rough: ~2 chars/token for Chinese
        sections = {"included": [n for n, _ in included], "dropped": dropped}
        phrases = (card.get("speech_style") or {}).get("sample_phrases", [])
        meta = {"character_id": actor_cid, "target_character_id": target_cid,
                "target_name": body["target"].get("name"),
                "sample_phrase": phrases[0] if phrases else "",
                "forbidden_terms": (card.get("hard_rules") or {}).get("forbidden_terms", [])}
        t0 = time.time()
        try:
            raw = self.provider.generate(messages, meta)
        except LLMError as exc:
            self._log(rid, actor_cid, target_cid, est_tokens, sections, exc.code)
            self._dlog(body, exc.code, "", t0, str(exc))
            return 503, {"request_id": rid, "status": "error", "code": exc.code,
                         "message": str(exc)[:200]}

        try:
            data = parse_model_json(raw)
            strict = self._level(body) >= 5          # level 5: strict rule check, refuse on any reported conflict
            normalized = validate_model_output(data, actor_cid, target_cid, card,
                                               min(self.cfg.max_dialogue_chars, 120) if strict else self.cfg.max_dialogue_chars,
                                               strict=strict)
        except Rejected as exc:
            self._log(rid, actor_cid, target_cid, est_tokens, sections, "rejected:" + exc.reason)
            self._dlog(body, "rejected:" + exc.reason, "", t0, exc.details)
            return 200, {"request_id": rid, "status": "rejected", "reason": exc.reason}
        normalized.update({"request_id": rid, "status": "success"})
        self._log(rid, actor_cid, target_cid, est_tokens, sections, "success")
        self._dlog(body, "success", normalized["dialogue"]["text"], t0)
        return 200, normalized

    # -- helpers shared by generate() and the dashboard preview ------------
    def _messages(self, body, card, target_card):
        included, dropped, used = self._build_context(body, card, target_card)
        system = SYSTEM_TEMPLATE.format(
            name=card["name"], language=card.get("language", "中文"),
            max_chars=self.cfg.max_dialogue_chars, cid=card["character_id"],
            tid=json.dumps(body["target"].get("character_id")))
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": "\n".join("[%s] %s" % (n, t) for n, t in included)}]
        return messages, included, dropped, used

    def _describe(self):
        d = getattr(self.provider, "describe", None)
        if callable(d):
            info = d()
            return info.get("id", ""), info.get("model", "")
        return getattr(self.provider, "name", ""), getattr(self.provider, "model", "")

    def _dlog(self, body, outcome, text, t0, detail=""):
        pid, model = self._describe()
        try:
            with self.db.session() as conn:
                conn.execute(
                    "INSERT INTO dialogue_log (request_id, created_at, actor_name, target_name, "
                    "interaction, text, outcome, latency_ms, provider, model, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (body["request_id"], now_iso(), body["actor"].get("name", ""),
                     body["target"].get("name", ""), body["interaction"].get("name", ""), text,
                     outcome, int((time.time() - t0) * 1000), pid, model, str(detail)[:300]))
        except Exception:
            log.exception("dialogue_log write failed")

    def preview(self, actor_cid, target_cid=None):
        """Exactly what would be sent to the model for a sample request (dashboard disclosure)."""
        card = self.characters.get(actor_cid)
        if card is None:
            raise ApiError(404, "character_not_found", str(actor_cid))
        target_card = self.characters.get(target_cid) if target_cid else None
        body = {"save_key": "preview",
                "actor": {"sim_id": 0, "character_id": actor_cid, "name": card["name"]},
                "target": {"sim_id": 1, "character_id": target_cid if target_card else None,
                           "name": (target_card or {}).get("name", "对方")},
                "interaction": {"name": "Chat"}}
        messages, included, dropped, used = self._messages(body, card, target_card)
        return {"messages": messages, "sections": [n for n, _ in included], "chars": used}
