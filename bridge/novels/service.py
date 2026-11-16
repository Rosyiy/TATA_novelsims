"""Novel library + the search -> extract pipeline (V0.2).

Legal/ethical boundaries (spec 5.1): only short excerpts are kept in memory while a task runs, the
database stores <=300 char evidence snippets, pirate/full-text sites are filtered, robots.txt is
honored, and nothing is invented when information is missing.
"""
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import uuid
from urllib.parse import quote

from ..errors import ApiError
from ..extraction.card import Rejected, build_messages, empty_card, parse_model_json, validate_card
from ..llm import LLMError
from ..memory.store import now_iso, sanitize_text
from ..search import filters
from ..search.engines import SearchResult, build_engines
from ..search.fetch import FetchError, Fetcher
from ..search.htmltext import extract_title, html_to_text

log = logging.getLogger("novelsims.novels")
REASONING_RE = re.compile(r"(glm-4\.7|glm-5|reasoner|thinking|deepseek-r1|(^|[^a-z])o[13]([^a-z]|$)|qwq)", re.I)
FATAL_LLM = ("consent_required", "no_key", "not_configured", "llm_auth", "llm_billing")
KIND_LABEL = {"encyclopedia": "百科", "platform": "平台介绍", "review": "书评", "community": "社区", "other": "网页",
              "user": "用户自设"}


def split_names(value):
    """'许星纯 付雪梨' / '甲，乙、丙' / ['甲','乙 丙'] -> ['许星纯','付雪梨'] ... Spaces split names only when every part is
    short (so 'Harry Potter' stays one name only when it is the sole, longer item)."""
    items = value if isinstance(value, list) else re.split(r"[,，、;；/\n]+", str(value))
    out = []
    for it in items:
        it = sanitize_text(str(it)).strip()
        parts = it.split()
        if len(parts) > 1 and all(len(p) <= 8 for p in parts) and not all(re.match(r"^[A-Za-z.\-']+$", p) for p in parts):
            out += parts
        elif it:
            out.append(it)
    return [n[:30] for n in dict.fromkeys(out)][:12]


def _norm(t):
    return re.sub(r"[\s《》〈〉\"“”'’·・:：\-—_]", "", t).lower()


def author_status(text, author):
    """ok | unverified | mismatch. Only an explicit label naming someone else counts as a mismatch,
    because most pages and search snippets simply do not mention the author."""
    if not author or _norm(author) in _norm(text):
        return "ok"
    labels = re.findall(r"(?:作者|著者|文\s*/)\s*[:：]?\s*([^\s，。,;；、《》()（）]{1,12})", text)
    if labels and not any(_norm(l) in _norm(author) or _norm(author) in _norm(l) for l in labels):
        return "mismatch:" + labels[0]
    return "unverified"


def _short(s, n):
    return re.sub(r"\s+", " ", s).strip()[:n]


class NovelStore(object):
    def __init__(self, db):
        self.db = db

    def create(self, d):
        nid = "nov_" + uuid.uuid4().hex[:10]
        with self.db.session() as conn:
            conn.execute("INSERT INTO novels VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (nid, d["title"], d["author"], d["version"], d["notes"], d["mode"],
                          json.dumps(d["characters"], ensure_ascii=False), d["plot_text"], "new", now_iso()))
        return nid

    def get(self, nid):
        with self.db.session() as conn:
            r = conn.execute("SELECT * FROM novels WHERE novel_id=?", (nid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["characters"] = json.loads(d.pop("characters_json") or "[]")
        return d

    def list(self):
        with self.db.session() as conn:
            rows = conn.execute("SELECT novel_id FROM novels ORDER BY created_at DESC").fetchall()
        return [self.get(r["novel_id"]) for r in rows]

    def set_status(self, nid, status):
        with self.db.session() as conn:
            conn.execute("UPDATE novels SET status=? WHERE novel_id=?", (status, nid))

    def set_characters(self, nid, names):
        with self.db.session() as conn:
            conn.execute("UPDATE novels SET characters_json=? WHERE novel_id=?",
                         (json.dumps(names, ensure_ascii=False), nid))

    def reset_sources(self, nid):
        with self.db.session() as conn:
            conn.execute("DELETE FROM sources WHERE novel_id=?", (nid,))

    def add_source(self, nid, **f):
        with self.db.session() as conn:
            n = conn.execute("SELECT COUNT(*) FROM sources WHERE novel_id=?", (nid,)).fetchone()[0]
            sid = "S%d" % (n + 1)
            conn.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (nid, sid, f.get("name", ""), f.get("url", ""), now_iso(), f.get("kind", "other"),
                          f.get("edition", "unknown"), f.get("engine", ""), f.get("status", ""),
                          _short(f.get("excerpt", ""), 300)))
        return sid

    def sources(self, nid):
        with self.db.session() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM sources WHERE novel_id=? ORDER BY CAST(SUBSTR(source_id,2) AS INTEGER)", (nid,))]

    def delete(self, nid):
        with self.db.session() as conn:
            for t in ("sources", "tasks", "novels"):
                conn.execute("DELETE FROM %s WHERE novel_id=?" % t, (nid,))

    # tasks
    def task_new(self, nid):
        tid = "task_" + uuid.uuid4().hex[:10]
        with self.db.session() as conn:
            conn.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)",
                         (tid, nid, "running", 0, "准备中", "{}", now_iso(), now_iso()))
        return tid

    def task_update(self, tid, **f):
        sets, vals = [], []
        for k in ("state", "progress", "message"):
            if k in f:
                sets.append(k + "=?")
                vals.append(f[k])
        if "result" in f:
            sets.append("result_json=?")
            vals.append(json.dumps(f["result"], ensure_ascii=False))
        sets.append("updated_at=?")
        vals += [now_iso(), tid]
        with self.db.session() as conn:
            conn.execute("UPDATE tasks SET %s WHERE task_id=?" % ",".join(sets), vals)

    def task_get(self, tid=None, novel_id=None):
        with self.db.session() as conn:
            if tid:
                r = conn.execute("SELECT * FROM tasks WHERE task_id=?", (tid,)).fetchone()
            else:
                r = conn.execute("SELECT * FROM tasks WHERE novel_id=? ORDER BY created_at DESC LIMIT 1",
                                 (novel_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["result"] = json.loads(d.pop("result_json") or "{}")
        return d


class NovelService(object):
    def __init__(self, app, fetcher=None, engine_factory=None, delay=0.08, direct_urls=True):
        self.direct_urls = direct_urls
        self.app = app
        self.store = NovelStore(app.db)
        self.fetcher = fetcher or Fetcher()
        # Novel discovery defaults to public HTML search providers. No paid search API/key is
        # called in the automatic identity-card workflow.
        self.engine_factory = engine_factory or (lambda: build_engines(
            ["baidu", "quark", "sogou", "bing", "duckduckgo"], self.fetcher, {}))
        self.delay = delay
        self._cancel = set()
        self._last_used = {}                     # in-memory only (never persisted): lets "re-extract" skip the search
        self._lock = threading.Lock()
        self._running = None
        self.threads = []

    # -- create ---------------------------------------------------------------
    def create(self, body):
        if not isinstance(body, dict):
            raise ApiError(400, "invalid_request", "body must be an object")
        title = sanitize_text(str(body.get("title", "")))[:100]
        if not title:
            raise ApiError(400, "invalid_request", "书名不能为空")
        chars = split_names(body.get("characters") or [])
        mode = body.get("mode", "web")
        if not chars and mode == "manual":
            # Even manual text can be scanned locally for character names; no name list is required.
            pass
        if mode not in ("web", "manual", "both"):
            raise ApiError(400, "invalid_request", "mode 必须是 web / manual / both")
        plot = str(body.get("plot_text", ""))[:20000].strip()
        if mode in ("manual", "both") and len(plot) < 30:
            raise ApiError(400, "invalid_request", "自设剧情至少写几句话（30字以上）")
        nid = self.store.create({"title": title, "author": sanitize_text(str(body.get("author", "")))[:60],
                                 "version": sanitize_text(str(body.get("version", "")))[:60],
                                 "notes": sanitize_text(str(body.get("notes", "")))[:500],
                                 "mode": mode, "characters": chars, "plot_text": plot})
        return self.store.get(nid)

    def detail(self, nid):
        n = self.store.get(nid)
        if not n:
            raise ApiError(404, "novel_not_found")
        n["sources"] = self.store.sources(nid)
        n["task"] = self.store.task_get(novel_id=nid)
        n["cards"] = [{"character_id": c["character_id"], "name": c["name"],
                       "status": c.get("verification_status"), "low_data": c.get("low_data", False)}
                      for c in self.app.characters.list_all() if c.get("novel_id") == nid]
        n.pop("plot_text", None)
        n["has_plot"] = bool(self.store.get(nid)["plot_text"])
        return n

    # -- run --------------------------------------------------------------------
    def start(self, nid, reuse=False):
        novel = self.store.get(nid)
        if not novel:
            raise ApiError(404, "novel_not_found")
        if reuse and nid not in self._last_used:
            raise ApiError(409, "no_cache", "没有可复用的检索结果（后端重启过）。请点“重新检索”。")
        with self._lock:
            if self._running:
                raise ApiError(409, "task_running", "已有一个检索任务在运行，请等它结束或先取消")
            tid = self.store.task_new(nid)
            self._running = tid
        t = threading.Thread(target=self._run, args=(tid, novel, reuse), name="ns-novel", daemon=True)
        self.threads.append(t)
        t.start()
        return tid

    def cancel(self, tid):
        self._cancel.add(tid)
        return {"cancelled": True}

    def _progress(self, tid, pct, msg):
        self.store.task_update(tid, progress=int(pct), message=msg)
        if tid in self._cancel:
            raise _Cancelled()

    def _run(self, tid, novel, reuse=False):
        nid, result = novel["novel_id"], {"characters": [], "warnings": [], "engine_report": {}, "raw_samples": {}}
        try:
            if reuse:
                used = list(self._last_used[nid])
                result["summary"] = "沿用上次检索到的 %d 条资料，只重新整理人物。" % len(used)
            else:
                self.store.reset_sources(nid)
                used = []
                if novel["mode"] in ("web", "both"):
                    used += self._collect_web(tid, novel, result)
                if novel["mode"] in ("manual", "both") and novel["plot_text"]:
                    sid = self.store.add_source(nid, name="用户自设剧情", url="", kind="user", edition="original",
                                                engine="user", status="used", excerpt=novel["plot_text"])
                    used.append({"id": sid, "name": "用户自设剧情", "url": "", "kind": "user", "edition": "original",
                                 "text": novel["plot_text"]})
                if not novel.get("characters"):
                    novel["characters"] = self._discover_character_names(novel, used)
                    if novel["characters"]:
                        self.store.set_characters(nid, novel["characters"])
                        result["warnings"].append("已从公开资料中自动识别人物：" + "、".join(novel["characters"]))
                    else:
                        result["warnings"].append("未能可靠识别人物姓名。为避免把普通词语误当角色，未自动创建身份卡；可在小说资料中补充人物名单后重新检索。")
                result["summary"] = self._summary(nid, result)
            self._last_used[nid] = used
            if not used or not novel.get("characters"):
                self.store.task_update(tid, state="needs_manual", progress=100, result=result,
                                       message="没有足够可靠的资料或人物姓名，暂未生成身份卡。你可以补充人物名单后重新检索；身份卡整理本身不调用 AI。")
                self.store.set_status(nid, "needs_manual")
                return
            self._extract_all(tid, novel, used, result)
            n_ok = len(result["characters"])
            result["can_reextract"] = True
            if n_ok == 0 and not any("已确认" in w for w in result["warnings"]):
                self.store.task_update(tid, state="error", progress=100, result=dict(result, error_code="extraction_failed"),
                                       message="资料已经找到，但规则提取器没有给出可用结果，所以没有生成身份卡。原因见下方；修好模型设置后可点“重新整理人物”（不用重新搜索）。")
                self.store.set_status(nid, "error")
                return
            self.store.task_update(tid, state="done", progress=100, result=result,
                                   message="完成：生成 %d 张身份卡（请逐张校对后确认）" % n_ok)
            self.store.set_status(nid, "done")
            self.app.write_character_index()
        except _Cancelled:
            self.store.task_update(tid, state="cancelled", result=result, message="已取消")
        except _Fatal as exc:
            self.store.task_update(tid, state="error", result=dict(result, error_code=exc.code), message=str(exc))
        except Exception as exc:                   # a task must never take the backend down
            log.exception("novel task failed")
            self.store.task_update(tid, state="error", result=result, message="内部错误：%s" % exc)
        finally:
            with self._lock:
                self._running = None
            self._cancel.discard(tid)

    # -- web collection -------------------------------------------------------
    def _queries(self, novel):
        t, a = novel["title"], novel["author"]
        qs = [
            '"%s" %s 人物介绍 角色介绍' % (t, a or ""),
            '"%s" 主要人物 主角 配角 人物关系' % t,
            '"%s" 角色列表 人物设定 人物百科' % t,
            'site:baike.baidu.com "%s" 人物' % t,
            'site:moegirl.org.cn "%s"' % t,
            '"%s" 百度百科 角色' % t,
            '"%s" 作品角色 性格 经历 背景' % t,
            '"%s" 小说 人物分析 人物关系图' % t,
            '"%s" 主角 配角 名单' % t,
        ]
        # More targeted per-character queries for higher hit rate
        templates = [
            '"%s" "%s" 人物介绍',
            '"%s" "%s" 性格 经历 背景',
            '"%s" "%s" 人物关系 结局',
            '"%s" "%s" 角色设定',
            'site:baike.baidu.com "%s" "%s"',
        ]
        for c in novel["characters"][:18]:
            for template in templates:
                qs.append(template % (t, c))
        # Keep a useful but bounded query set; 18 total per run, with every character represented where possible.
        if len(qs) > 28:
            base, targeted = qs[:6], qs[6:]
            qs = base + targeted[:20]
        return list(dict.fromkeys(q.replace("  ", " ").strip() for q in qs))

    def _collect_web(self, tid, novel, result):
        nid, title, author = novel["novel_id"], novel["title"], novel["author"]
        engines = self.engine_factory()
        report = {e.name: {"queries": 0, "results": 0, "error": None} for e in engines}
        pool, dead = {}, set()
        queries = self._queries(novel)
        # Run independent provider/query pairs concurrently. A slow engine no longer blocks every other source.
        jobs = [(e, q) for q in queries for e in engines]
        completed = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_map = {executor.submit(e.search, q, 10): (e, q) for e, q in jobs}
            for future in as_completed(future_map):
                e, q = future_map[future]
                completed += 1
                self._progress(tid, 2 + 23.0 * completed / max(1, len(jobs)),
                               "多源并行搜索：%s（%s，%d/%d）" % (q[:24], e.name, completed, len(jobs)))
                try:
                    res = future.result()
                    report[e.name]["queries"] += 1
                    report[e.name]["results"] += len(res)
                    for r in res:
                        if r.url.startswith(("http://", "https://")):
                            pool.setdefault(filters.canonical_url(r.url), r)
                except Exception as exc:
                    report[e.name]["error"] = report[e.name]["error"] or str(exc)[:120]
        for url in (("https://zh.wikipedia.org/wiki/" + quote(title.replace(" ", "_")),
                     "https://baike.baidu.com/item/" + quote(title)) if self.direct_urls else ()):
            pool.setdefault(filters.canonical_url(url), SearchResult(title, url, "", "direct", 0))
        result["engine_report"] = report
        result["found"] = len(pool)

        names = [title] + novel["characters"]
        ranked = []
        for url, r in pool.items():
            score, kind = filters.trust_of(url)
            score += 3 if title in (r.title + r.snippet) else 0
            score += sum(1 for c in novel["characters"] if c in (r.title + r.snippet))
            ranked.append((score - r.rank * 0.1, url, r, kind))
        ranked.sort(key=lambda t: -t[0])
        max_pages = int(self.app.settings.search_public()["max_pages"])
        used, fetched = [], 0
        for i, (score, url, r, kind) in enumerate(ranked):
            if fetched >= max_pages + 4 or len(used) >= max_pages:
                break
            self._progress(tid, 25 + 35.0 * i / max(1, len(ranked)), "读取：%s" % _short(r.title or url, 40))
            base = {"name": _short(r.title or filters.host_of(url), 80), "url": url, "kind": kind,
                    "edition": filters.detect_edition(r.title, r.snippet, url), "engine": r.engine}
            why = filters.blocked_reason(url)
            if why:
                self.store.add_source(nid, status="blocked:" + why, excerpt=r.snippet, **base)
                continue
            text, status = "", "used"
            if getattr(r, "content_is_text", False) and len(r.snippet) >= 30:
                text, status = r.snippet, "used_snippet"          # search API summary: never fetch the page
            else:
                try:
                    page = self.fetcher.fetch_page(url)
                    fetched += 1
                    raw_text = html_to_text(page["html"], 12000)
                    if filters.looks_like_fulltext(raw_text):
                        self.store.add_source(nid, status="blocked:疑似小说正文/全文页", excerpt="", **base)
                        continue
                    text = raw_text[:6000]
                    base["name"] = _short(extract_title(page["html"]) or base["name"], 80)
                except FetchError as exc:
                    if len(r.snippet) >= 30:
                        text, status = r.snippet, "used_snippet"     # engine snippet only
                    else:
                        self.store.add_source(nid, status="skipped:%s" % ("robots.txt 不允许" if exc.code == "robots" else "抓取失败 " + exc.code),
                                              excerpt="", **base)
                        continue
            combined = _norm(text + " " + r.title + " " + r.snippet)
            title_hit = _norm(title) in combined
            character_hits = [c for c in novel["characters"] if _norm(c) in combined]
            # Character encyclopedias and profile pages often omit the novel title in the
            # body while naming the character; accept them only when a supplied character
            # name is explicitly present, then retain the URL and evidence for review.
            if not title_hit and not character_hits:
                self.store.add_source(nid, status="skipped:与书名及已知人物无关", excerpt=text, **base)
                continue
            au = author_status(text, author)
            if au.startswith("mismatch"):
                self.store.add_source(nid, status="skipped:作者不符（页面写的是“%s”，可能是同名的另一本书）" % au.split(":", 1)[1],
                                      excerpt=text, **base)
                continue
            if au == "unverified":
                status += "+unverified"
            sid = self.store.add_source(nid, status=status, excerpt=text, **base)
            used.append({"id": sid, "name": base["name"], "url": url, "kind": kind, "edition": base["edition"],
                         "text": text})
        return used

    @staticmethod
    def _discover_character_names(novel, used):
        """Conservative Chinese-name discovery from public snippets/pages; no NLP/LLM API."""
        if novel.get("characters"):
            return novel["characters"]
        surnames = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦林尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳唐罗薛伍余米贝姚孟顾尹江钟徐邱骆高夏蔡田樊胡凌霍虞万支柯管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑裴陆荣翁荀羊於惠甄曲封芮储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东殴殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公")
        stop = set("主要人物人物角色小说故事作者作品主角配角简介关系背景经历身份设定第一章第二章第三章第四章第五章第六章第七章第八章第九章第十章结局番外章节人物介绍")
        counts, sources = {}, {}
        for src in used:
            blob = (src.get("name", "") + "\n" + src.get("text", ""))
            local = set()
            for m in re.finditer(r"[\u4e00-\u9fff]{2,3}", blob):
                raw_name = m.group(0)
                if raw_name[0] not in surnames:
                    continue
                # The 2-character candidate handles names followed immediately by grammar;
                # the 3-character candidate preserves common three-character names.
                names_here = [raw_name]
                if len(raw_name) == 3:
                    names_here.append(raw_name[:2])
                for name in names_here:
                    if name[-1] in "是曾与在为的等和并将把又也就而从向对被让给到着过很更最都还":
                        continue
                    if name in stop or name.startswith(("第", "一个", "这个", "那个", "因此", "但是", "因为", "所以")):
                        continue
                    # Exclude words likely to be generic titles or common terms.
                    if any(x in name for x in ("小说", "人物", "作者", "故事", "主角", "角色", "简介", "结局", "章节", "公司", "集团", "世界")):
                        continue
                    local.add(name)
            for name in local:
                counts[name] = counts.get(name, 0) + 1
                sources.setdefault(name, set()).add(src.get("id", ""))
        ranked = sorted(counts, key=lambda n: (len(sources.get(n, ())), counts[n]), reverse=True)
        # Require repeat evidence across at least two separate documents where possible.
        strong = [n for n in ranked if len(sources.get(n, ())) >= 2 and counts[n] >= 2]
        candidates = strong or [n for n in ranked if counts[n] >= 2]
        excluded = {novel.get("title", ""), novel.get("author", "")}
        candidates = [n for n in candidates if n not in excluded and not any(x and x in n for x in excluded)]
        # If a three-character candidate is repeatedly found, drop its two-character prefix.
        candidates = [n for n in candidates if not any(len(other) == len(n) + 1 and other.startswith(n)
                                                        and counts.get(other, 0) >= counts.get(n, 0)
                                                        for other in candidates)]
        # A maximum keeps unrelated entities from flooding the user's game.
        return candidates[:12]

    def _summary(self, nid, result):
        """Plain-language breakdown of what happened to every search hit."""
        c = {}
        for src in self.store.sources(nid):
            st = src["status"] or ""
            k = ("采用" if st.startswith("used") else "盗版/全文站" if "盗版" in st or "全文" in st else
                 "robots不允许" if "robots" in st else "作者不符" if "作者不符" in st else
                 "与书名无关" if "书名无关" in st else "抓取失败" if "抓取失败" in st else "其他")
            c[k] = c.get(k, 0) + 1
        rep = result.get("engine_report") or {}
        bad = [k for k, v in rep.items() if v.get("error") and not v.get("results")]
        head = "共找到 %d 条搜索结果" % result.get("found", 0)
        parts = "、".join("%s %d" % (k, v) for k, v in c.items())
        hint = ("；搜索源 %s 不可用" % "、".join(bad)) if bad else ""
        return "%s（%s）%s。" % (head, parts or "无", hint)

    # -- extraction -------------------------------------------------------------
    @staticmethod
    def _context_for(names, used, limit=4000):
        ctx, total = [], 0
        for s in used:
            paras = []
            for p in (x.strip() for x in s["text"].splitlines() if x.strip()):
                if len(p) <= 300:
                    paras.append(p)
                else:                                   # long summaries: cut at sentence ends
                    buf = ""
                    for sent in re.split(r"(?<=[。！？!?])", p):
                        if len(buf) + len(sent) > 300 and buf:
                            paras.append(buf)
                            buf = ""
                        buf += sent
                    if buf:
                        paras.append(buf)
            hit = [_short(p, 320) for p in paras if any(n in p for n in names)][:5]
            if not hit and s["kind"] == "user":
                hit = [_short(s["text"], 1200)]
            if not hit:
                continue
            text = "\n".join(hit)[:1400]
            if total + len(text) > limit:
                break
            ctx.append({"id": s["id"], "name": s["name"], "url": s["url"], "kind": s["kind"],
                        "edition": s["edition"], "text": text})
            total += len(text)
        return ctx

    @staticmethod
    def _sentences(text):
        text = re.sub(r"[\t\r]+", " ", text or "")
        parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
        out = []
        for part in parts:
            part = re.sub(r"\s+", " ", part).strip(" ·•|—-\t")
            if 8 <= len(part) <= 420 and part not in out:
                out.append(part)
        return out

    @staticmethod
    def _deterministic_card(name, novel, used, origin, novel_id):
        """Build a source-grounded card using rules only. No LLM/provider/API is invoked."""
        import re
        evidence = []
        for src in used:
            text = src.get("text", "")
            if name not in text:
                continue
            for sentence in NovelService._sentences(text):
                if name in sentence:
                    evidence.append((src, sentence))
        # De-duplicate near-identical snippets while retaining their source ids.
        unique = []
        seen = set()
        for src, sentence in evidence:
            key = re.sub(r"[\W_]", "", sentence).lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append((src, sentence))
        source_ids = list(dict.fromkeys(src["id"] for src, _ in unique))
        def refs(src): return [src["id"]]
        all_text = "。".join(x[1] for x in unique)
        traits_map = [
            (("冷漠", "冷淡", "疏离", "寡言", "沉默"), "冷静克制"),
            (("温柔", "善良", "体贴", "温和", "柔软"), "温柔体贴"),
            (("骄傲", "高傲", "自负", "傲慢"), "自尊心强"),
            (("聪明", "机敏", "敏锐", "聪慧", "智谋"), "聪慧敏锐"),
            (("偏执", "执着", "固执", "执拗"), "执着坚定"),
            (("狡猾", "心机", "算计", "腹黑"), "心思深沉"),
            (("勇敢", "果断", "无畏", "坚韧"), "勇敢坚韧"),
            (("善于交际", "圆滑", "八面玲珑"), "擅长交际"),
            (("敏感", "多疑", "戒备", "警惕"), "敏感戒备"),
            (("活泼", "开朗", "天真", "乐观"), "开朗乐观"),
            (("嫉妒", "占有欲", "控制欲"), "情感占有欲强"),
        ]
        traits = [label for words, label in traits_map if any(w in all_text for w in words)]
        identity = ""
        for _, sentence in unique:
            m = re.search(r"(?:是|身为|作为|身份为|担任)([^，。；]{2,48})", sentence)
            if m:
                identity = m.group(1).strip(" ，。；")
                break
        background = "\n".join(x[1] for x in unique[:8])[:600]
        motivation = ""
        for _, sentence in unique:
            if any(k in sentence for k in ("为了", "希望", "渴望", "目标", "想要", "复仇", "寻找", "守护")):
                motivation = sentence[:200]
                break
        trauma = ""
        for _, sentence in unique:
            if any(k in sentence for k in ("创伤", "失去", "背叛", "伤害", "死亡", "离世", "抛弃", "灭门")):
                trauma = sentence[:200]
                break
        # Relationship facts are extracted only where another declared character is named.
        relations = []
        for src, sentence in unique:
            for other in novel.get("characters", []):
                if other == name or other not in sentence:
                    continue
                relation = next((k for k in ("父亲", "母亲", "兄弟", "姐妹", "夫妻", "恋人", "未婚夫", "未婚妻", "师徒", "主仆", "旧友", "朋友", "敌人", "仇人") if k in sentence), "关联人物")
                item = {"name": other, "relation": relation, "stage": "", "sources": refs(src)}
                if not any(x["name"] == other for x in relations): relations.append(item)
        # Exact source quotes only.
        phrases = []
        for src, sentence in unique:
            for q in re.findall(r'[“\"]([^”\"]{2,30})[”\"]', sentence):
                if q not in phrases: phrases.append(q)
                if len(phrases) >= 5: break
            if len(phrases) >= 5: break
        speech_cues = [("寡言", "话少寡言"), ("沉默", "表达克制"), ("直言不讳", "表达直接"),
                       ("温声", "语气温和"), ("讥讽", "常带讽刺意味"), ("冷冷地说", "语气冷淡"),
                       ("命令", "表达偏命令式")]
        speech = "、".join(label for cue, label in speech_cues if cue in all_text)
        behavior = []
        for words, label in [(("保护", "守护"), "倾向于保护重要之人"), (("隐瞒", "秘密", "伪装"), "会隐瞒关键信息"),
                             (("调查", "追查", "寻找"), "主动调查并追寻线索"), (("牺牲", "承担", "独自"), "倾向独自承担责任"),
                             (("谈判", "交易", "利用"), "善于通过谈判或交易达成目的")]:
            if any(w in all_text for w in words): behavior.append(label)
        memories = []
        for src, sentence in unique:
            if any(k in sentence for k in ("相遇", "重逢", "离开", "死亡", "杀死", "救下", "背叛", "婚", "订婚", "继承", "战败", "获救")):
                memories.append({"content": sentence[:200], "importance": 7, "sources": refs(src)})
            if len(memories) >= 10: break
        stages = {}
        stage_words = [("original_early", ("幼年", "童年", "年少", "小时候", "早年")),
                       ("original_mid", ("后来", "此后", "之后", "逐渐", "中期")),
                       ("original_late", ("最终", "最后", "末期", "结局前")),
                       ("original_ending", ("结局", "最终结局", "尾声"))]
        for key, words in stage_words:
            for src, sentence in unique:
                if any(w in sentence for w in words):
                    stages[key] = {"state": sentence[:200], "known_info": [], "goal": "", "sources": refs(src)}
                    break
        missing = []
        for field, val in (("identity", identity), ("background", background), ("core_personality", traits),
                           ("core_motivation", motivation), ("speech_style", speech), ("relationships", relations),
                           ("canon_memories", memories), ("timeline", stages)):
            if not val: missing.append(field)
        card = {
            "name": name, "alias": [], "source_novel": novel["title"], "source_author": novel.get("author", ""),
            "source_version": novel.get("version", ""), "language": "中文", "identity": identity,
            "background": background, "core_personality": traits, "variable_personality": [],
            "speech_style": {"summary": speech, "address": "", "sample_phrases": phrases},
            "behavioral_tendencies": behavior, "core_trauma": trauma, "core_motivation": motivation,
            "core_rules": [], "forbidden_behaviors": [], "hard_rules": {"forbidden_terms": ["我是AI", "语言模型", "人工智能"]},
            "relationships": relations, "canon_memories": memories,
            "conflicts": [], "timeline": {"current_stage": next((k for k in ("original_early", "original_mid", "original_late", "original_ending") if k in stages), None), "stages": stages},
            "info_sources": [{"id": src["id"], "name": src.get("name", ""), "url": src.get("url", ""), "kind": src["kind"], "edition": src["edition"]} for src in used if src["id"] in source_ids],
            "origin": origin, "novel_id": novel_id, "missing_fields": missing,
            "low_data": len(source_ids) < 2 or len(unique) < 3 or not background,
            "verification_status": "low_data" if (len(source_ids) < 2 or len(unique) < 3 or not background) else "draft",
            "extraction_method": "deterministic_no_ai"
        }
        return card

    def _extract_all(self, tid, novel, used, result):
        nid, chars = novel["novel_id"], novel["characters"]
        origin = "mixed" if len({u["kind"] == "user" for u in used}) == 2 else ("user_text" if used[0]["kind"] == "user" else "web")
        result["extraction_method"] = "deterministic_no_ai"
        result["summary"] = (result.get("summary", "") + "；身份卡由规则引擎生成，未调用大模型/LLM API").strip("；")
        for i, name in enumerate(chars):
            self._progress(tid, 60 + 38.0 * i / max(1, len(chars)), "规则提取人物：%s（%d/%d）" % (name, i + 1, len(chars)))
            key = "novel:%s:%s" % (nid, name)
            existing = self.app.characters.find_by_source_key(key)
            if existing and (self.app.characters.get(existing) or {}).get("verification_status") == "confirmed":
                result["warnings"].append("「%s」的身份卡已确认，重新检索不会覆盖它" % name)
                continue
            card = self._deterministic_card(name, novel, used, origin, nid)
            if not card["background"]:
                result["warnings"].append("「%s」没有检索到包含该人物名的有效段落，已保留信息缺口" % name)
            cid = self.app.characters.save_generated(card, key, nid)
            self.app.memories.replace_canon(cid, card["canon_memories"])
            result["characters"].append({"name": name, "character_id": cid, "low_data": card["low_data"],
                                         "missing": card["missing_fields"]})


class _Cancelled(Exception):
    pass


class _Fatal(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code
