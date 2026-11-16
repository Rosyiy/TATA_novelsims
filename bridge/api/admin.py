"""Dashboard (admin) API. Reachable only over HTTP, only with the per-run admin token."""
import time
from datetime import datetime, timezone

import json
import os
import uuid

from ..character.edit import apply_edit, blank_card, compute_missing
from ..errors import ApiError
from ..llm import LLMError
from ..llm.presets import BY_ID
from ..novels import catalog as novel_catalog

DISCLOSURE = [
    "联网检索时：书名、作者、人物名会作为搜索词发送给你勾选的搜索服务（必应 / 智谱联网搜索 / Tavily 等）。",
    "小说检索/整理人物时：你填写的书名、作者、人物名、自设剧情文字，以及网页搜索得到的资料摘录（每条最多约 1200 字）。",
    "发送给云端模型的内容：对话双方小人的姓名、本次互动名称。",
    "角色卡关键字段：姓名、身份、性格、说话风格、核心动机、核心规则、禁止行为、当前时间线阶段、与对方的原著关系。",
    "记忆片段：与对方最相关的原著固定记忆和游戏动态记忆（各最多 5 条，每条不超过 200 字）。",
    "不会发送：存档文件、小说全文、你的 API Key 以外的本机信息。",
    "发送内容会经过该服务商的服务器；请遵守对方的使用条款，并自行评估隐私风险。",
]


def _age_seconds(iso):
    try:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds())
    except (TypeError, ValueError):
        return None


class AdminApi(object):
    def __init__(self, app):
        self.app = app

    def handle(self, method, sub, body, query):
        route = (method, sub)
        if route == ("GET", "overview"):
            return self.overview()
        if route == ("GET", "settings"):
            return self.app.settings.public()
        if route == ("PUT", "settings"):
            return self.app.settings.update(body)
        if route == ("POST", "test"):
            return self.test()
        if route == ("GET", "characters"):
            return self.characters()
        if route == ("GET", "character"):
            card = self.app.characters.get((query.get("id") or [""])[0])
            if card is None:
                raise ApiError(404, "character_not_found")
            return card
        if route == ("GET", "logs"):
            return self.logs(query)
        if route == ("DELETE", "logs"):
            with self.app.db.session() as conn:
                conn.execute("DELETE FROM dialogue_log")
                conn.execute("DELETE FROM request_log")
            return {"cleared": True}
        r = self._novel_routes(method, sub, body, query)
        if r is not None:
            return r
        if route == ("GET", "disclosure"):
            return {"items": DISCLOSURE}
        if route == ("GET", "preview"):
            return self.app.dialogue.preview((query.get("actor") or [""])[0],
                                             (query.get("target") or [None])[0])
        raise ApiError(404, "not_found", "admin/" + sub)

    # -- novels / cards -------------------------------------------------------
    def _q(self, query, key):
        return (query.get(key) or [""])[0]

    def _card(self, cid):
        card = self.app.characters.get(cid)
        if card is None:
            raise ApiError(404, "character_not_found")
        return card

    def _save_card(self, cid, card):
        card.pop("character_id", None)
        self.app.characters.update(cid, card)
        self.app.memories.replace_canon(cid, card.get("canon_memories", []))
        self.app.write_character_index()
        card["character_id"] = cid
        return card

    def _novel_routes(self, method, sub, body, query):
        a, nv = self.app, self.app.novels
        body = body if isinstance(body, dict) else {}
        if (method, sub) == ("GET", "jjwxc/rank"):
            try:
                return a.jjwxc.ranking(self._q(query, "period") or "month",
                                       self._q(query, "channel") or "全部")
            except Exception as exc:
                raise ApiError(502, "jjwxc_unavailable", "晋江榜单暂时无法读取：%s" % str(exc)[:240])
        if (method, sub) == ("GET", "jjwxc/search"):
            try:
                return a.jjwxc.search(self._q(query, "q"), 20)
            except Exception as exc:
                raise ApiError(502, "jjwxc_search_failed", "晋江作品搜索暂时不可用：%s" % str(exc)[:240])
        if (method, sub) == ("GET", "jjwxc/covers"):
            try:
                return a.jjwxc.search_covers(self._q(query, "q"), self._q(query, "author"), 12)
            except Exception as exc:
                raise ApiError(502, "jjwxc_cover_search_failed", "封面检索暂时不可用：%s" % str(exc)[:200])
        if (method, sub) == ("POST", "jjwxc/cover"):
            try:
                return a.jjwxc.set_cover(body.get("id"), body.get("cover_url"))
            except Exception as exc:
                raise ApiError(400, "invalid_cover", str(exc)[:200])
        if (method, sub) == ("GET", "jjwxc/book"):
            try:
                return a.jjwxc.book(self._q(query, "id"))
            except Exception as exc:
                raise ApiError(502, "jjwxc_book_unavailable", "作品详情/封面暂时无法读取：%s" % str(exc)[:240])
        if (method, sub) == ("POST", "jjwxc/select"):
            book = body
            title = str(book.get("title", "")).strip()[:160]
            author = str(book.get("author", "")).strip()[:100]
            if not title:
                raise ApiError(400, "invalid_request", "作品名称不能为空")
            characters = book.get("characters") if isinstance(book.get("characters"), list) else []
            characters = [str(x).strip()[:30] for x in characters if str(x).strip()][:12]
            existing = next((n for n in nv.store.list() if n["title"] == title and n["author"] == author), None)
            novel = existing or nv.create({"title": title, "author": author, "version": "晋江文学城原著",
                                           "characters": characters, "mode": "web"})
            task_id = nv.start(novel["novel_id"])
            return {"novel_id": novel["novel_id"], "task_id": task_id, "title": title,
                    "characters": characters, "reused": bool(existing)}
        if (method, sub) == ("GET", "catalog"):
            category = self._q(query, "category") or "全部"
            rank = self._q(query, "rank") or "全部"
            q = self._q(query, "q")
            return {"books": novel_catalog.list_books(category, rank, q),
                    "categories": novel_catalog.CATEGORIES, "ranks": ["全部"] + novel_catalog.RANKS,
                    "count": len(novel_catalog.list_books(category, rank, q)),
                    "ranking_note": "编辑精选与经典榜为内置策展榜单；热门榜为产品内推荐排序，并非实时销量榜。"}
        if (method, sub) == ("GET", "catalog/book"):
            book = novel_catalog.get_book(self._q(query, "id"))
            if not book:
                raise ApiError(404, "book_not_found", "书库中没有这本书")
            return book
        if (method, sub) == ("POST", "catalog/select"):
            book = novel_catalog.get_book(body.get("book_id"))
            if not book:
                raise ApiError(404, "book_not_found", "书库中没有这本书")
            existing = next((n for n in nv.store.list() if n["title"] == book["title"] and n["author"] == book["author"]), None)
            if existing:
                novel = existing
            else:
                novel = nv.create({"title": book["title"], "author": book["author"],
                                   "version": "原著小说", "characters": book["characters"], "mode": "web"})
            task_id = nv.start(novel["novel_id"])
            return {"novel_id": novel["novel_id"], "task_id": task_id,
                    "title": book["title"], "characters": book["characters"], "reused": bool(existing)}
        if (method, sub) == ("GET", "novels"):
            return {"novels": [dict(n, plot_text=None, task=nv.store.task_get(novel_id=n["novel_id"]),
                                    cards=sum(1 for c in a.characters.list_all() if c.get("novel_id") == n["novel_id"]))
                               for n in nv.store.list()]}
        if (method, sub) == ("POST", "novels"):
            return nv.detail(nv.create(body)["novel_id"])
        if (method, sub) == ("GET", "novel"):
            return nv.detail(self._q(query, "id"))
        if (method, sub) == ("PUT", "novel"):
            nid = body.get("novel_id")
            plot = str(body.get("plot_text", ""))[:20000].strip()
            n = nv.store.get(nid)
            if not n:
                raise ApiError(404, "novel_not_found")
            if len(plot) < 30:
                raise ApiError(400, "invalid_request", "自设剧情至少写几句话（30字以上）")
            mode = "manual" if body.get("manual_only") else "both"
            with a.db.session() as conn:
                conn.execute("UPDATE novels SET plot_text=?, mode=? WHERE novel_id=?", (plot, mode, nid))
            return nv.detail(nid)
        if (method, sub) == ("DELETE", "novel"):
            nid = self._q(query, "id")
            for c in a.characters.list_all():
                if c.get("novel_id") == nid and c.get("verification_status") != "confirmed":
                    a.characters.delete(c["character_id"])
            nv.store.delete(nid)
            a.write_character_index()
            return {"deleted": True}
        if (method, sub) == ("POST", "novels/start"):
            return {"task_id": nv.start(body.get("novel_id"))}
        if (method, sub) == ("POST", "novels/extract"):
            return {"task_id": nv.start(body.get("novel_id"), reuse=True)}
        if (method, sub) == ("GET", "task"):
            t = nv.store.task_get(self._q(query, "id"))
            if not t:
                raise ApiError(404, "task_not_found")
            return t
        if (method, sub) == ("POST", "task/cancel"):
            return nv.cancel(body.get("task_id"))
        if (method, sub) == ("GET", "search_settings"):
            return a.settings.search_public()
        if (method, sub) == ("PUT", "search_settings"):
            return a.settings.update_search(body)
        if (method, sub) == ("PUT", "card"):
            cid = body.get("character_id")
            return self._save_card(cid, apply_edit(self._card(cid), body.get("patch")))
        if (method, sub) == ("POST", "card/confirm"):
            cid = body.get("character_id")
            card = self._card(cid)
            card["verification_status"] = "confirmed" if body.get("confirmed", True) else "draft"
            return self._save_card(cid, card)
        if (method, sub) == ("POST", "card/create"):
            name = str(body.get("name", "")).strip()[:30]
            if not name:
                raise ApiError(400, "invalid_request", "角色名不能为空")
            card = apply_edit(blank_card(name), body.get("patch") or {})
            card["verification_status"], card["edited"] = "user_defined", True
            cid = a.characters.save_generated(card, "manual:" + uuid.uuid4().hex[:10])
            return self._save_card(cid, self._card(cid))
        if (method, sub) == ("DELETE", "card"):
            a.characters.delete(self._q(query, "id"))
            a.write_character_index()
            return {"deleted": True}
        path = os.path.join(a.cfg.data_dir, "pending_bind.json")
        if sub == "pending_bind":
            if method == "GET":
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        return json.load(fh)
                except (OSError, ValueError):
                    return {}
            if method == "DELETE":
                try:
                    os.remove(path)
                except OSError:
                    pass
                return {}
            if method == "POST":
                card = self._card(body.get("character_id"))
                if card.get("verification_status") not in ("confirmed", "user_defined", "fixture"):
                    raise ApiError(409, "not_confirmed", "请先校对并“确认”这张身份卡，再绑定到小人")
                info = {"character_id": card["character_id"], "name": card["name"]}
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(info, fh, ensure_ascii=False)
                return info
        return None

    # -- pieces ------------------------------------------------------------
    def overview(self):
        app, cfg = self.app, self.app.cfg
        with app.db.session() as conn:
            by = dict((r[0], r[1]) for r in conn.execute(
                "SELECT outcome, COUNT(*) FROM dialogue_log GROUP BY outcome"))
            avg = conn.execute("SELECT AVG(latency_ms) FROM (SELECT latency_ms FROM dialogue_log "
                               "WHERE outcome='success' ORDER BY id DESC LIMIT 50)").fetchone()[0]
            last = conn.execute("SELECT MAX(created_at) FROM dialogue_log").fetchone()[0]
            recent = [dict(r) for r in conn.execute(
                "SELECT created_at, actor_name, target_name, text, outcome, latency_ms FROM dialogue_log "
                "ORDER BY id DESC LIMIT 24")]
            n_dyn = conn.execute("SELECT COUNT(*) FROM memories WHERE layer='dynamic'").fetchone()[0]
        total = sum(by.values())
        ok = by.get("success", 0)
        rejected = sum(v for k, v in by.items() if k.startswith("rejected"))
        desc = app.provider.describe() if hasattr(app.provider, "describe") else \
            {"id": getattr(app.provider, "name", "?"), "name": getattr(app.provider, "name", "?"),
             "model": getattr(app.provider, "model", ""), "remote": False}
        return {
            "version": __import__("bridge").__version__,
            "uptime_s": int(time.time() - app.started_at), "data_dir": cfg.data_dir,
            "provider": desc, "total": total, "success": ok, "rejected": rejected,
            "errors": total - ok - rejected,
            "success_rate": round(100.0 * ok / total) if total else None,
            "avg_latency_ms": int(avg) if avg else None,
            "last_request_age_s": _age_seconds(last), "recent": recent,
            "characters": len(app.characters.list()), "dynamic_memories": n_dyn,
            "transports": {"http": {"on": cfg.enable_http, "addr": "%s:%d" % (cfg.host, cfg.http_port)},
                           "tcp": {"on": cfg.enable_tcp, "addr": "%s:%d" % (cfg.host, cfg.tcp_port)},
                           "file": {"on": cfg.enable_file_ipc, "addr": cfg.data_dir}},
        }

    def characters(self):
        titles = dict((n["novel_id"], n["title"]) for n in self.app.novels.store.list())
        counts = {}
        with self.app.db.session() as conn:
            for r in conn.execute("SELECT character_id, layer, COUNT(*) FROM memories GROUP BY character_id, layer"):
                counts.setdefault(r[0], {})[r[1]] = r[2]
        out = []
        for c in self.app.characters.list_all():
            n = counts.get(c["character_id"], {})
            out.append({"character_id": c["character_id"], "name": c["name"], "identity": c.get("identity", ""),
                        "tags": (c.get("core_personality") or [])[:4], "status": c.get("verification_status", ""),
                        "low_data": c.get("low_data", False), "origin": c.get("origin", ""),
                        "novel": titles.get(c.get("novel_id")) or c.get("source_novel", ""),
                        "canon": n.get("canon", 0), "dynamic": n.get("dynamic", 0),
                        "missing": len(c.get("missing_fields") or []),
                        "sources": len(c.get("info_sources") or [])})
        return {"characters": out}

    def logs(self, query):
        try:
            n = min(max(int((query.get("limit") or ["100"])[0]), 1), 500)
        except ValueError:
            n = 100
        with self.app.db.session() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, created_at, actor_name, target_name, interaction, text, outcome, "
                "latency_ms, provider, model, detail FROM dialogue_log ORDER BY id DESC LIMIT ?", (n,))]
        return {"logs": rows}

    def test(self):
        t0 = time.time()
        try:
            fn = getattr(self.app.provider, "test", None)
            if fn:
                return fn()
            self.app.provider.generate([{"role": "user", "content": 'Reply with {"ok": true}'}])
            return {"ok": True, "latency_ms": int((time.time() - t0) * 1000)}
        except LLMError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)[:300],
                    "latency_ms": int((time.time() - t0) * 1000)}
