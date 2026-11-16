# -*- coding: utf-8 -*-
"""Read-only discovery adapter for public Jinjiang ranking and work pages.

Only public metadata is collected. The adapter does not fetch chapter text or bypass
robots.txt, login, CAPTCHA, or access controls.
"""
import html
import json
import os
import re
import time
from urllib.parse import quote, urljoin, urlparse

from ..search.engines import BingEngine, SearchResult
from ..search.fetch import FetchError, Fetcher

BASE = "https://m.jjwxc.com"
RANKS = {
    "month": ("月榜", "/rank/naturalmore/5"),
    "quarter": ("季度榜", "/rank/naturalmore/6"),
    "halfyear": ("半年榜", "/rank/naturalmore/30"),
    "total": ("总分榜", "/rank/naturalmore/64"),
}
CHANNELS = ["全部", "言情", "纯爱", "原创", "衍生/轻小说", "无CP+", "百合"]


def _attr(tag, name):
    m = re.search(r"\b%s\s*=\s*\"([^\"]*)\"" % re.escape(name), tag, re.I)
    if not m:
        m = re.search(r"\b%s\s*=\s*'([^']*)'" % re.escape(name), tag, re.I)
    return html.unescape(m.group(1)) if m else ""


def _plain(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _safe_cover(url):
    if not url:
        return ""
    url = urljoin(BASE, html.unescape(url).replace("\\/", "/"))
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return ""
    if re.search(r"(logo|heart|hitcount|avatar|head|rank|loading|blank|default)", p.path, re.I):
        return ""
    return url


class JinjiangService(object):
    def __init__(self, data_dir=None):
        self.fetcher = Fetcher(timeout=12.0, max_bytes=1800000, respect_robots=True)
        self.bing = BingEngine(self.fetcher)
        self.data_dir = data_dir or os.getcwd()
        self.cover_file = os.path.join(self.data_dir, "jjwxc_cover_overrides.json")
        self.book_cache_file = os.path.join(self.data_dir, "jjwxc_book_cache.json")

    def _cover_overrides(self):
        try:
            with open(self.cover_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_cover(self, book_id, cover_url):
        bid = re.sub(r"\D", "", str(book_id or ""))[:12]
        url = str(cover_url or "").strip()
        parsed = urlparse(url)
        if not bid or parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("封面地址无效")
        if any(x in parsed.hostname.lower() for x in ("localhost", "127.0.0.1", "0.0.0.0")):
            raise ValueError("不允许使用本机地址作为封面")
        data = self._cover_overrides()
        data[bid] = url[:2000]
        os.makedirs(self.data_dir, exist_ok=True)
        tmp = self.cover_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.cover_file)
        return {"id": bid, "cover_url": data[bid]}

    def search_covers(self, title, author="", limit=12):
        q = (str(title or "").strip() + " " + str(author or "").strip() + " 晋江 小说封面").strip()[:120]
        if not q:
            return {"covers": []}
        page = self.fetcher.fetch_page_nonrobots("https://www.bing.com/images/search?q=" + quote(q))
        raw = page.get("html", "")
        covers, seen = [], set()
        # Bing image result metadata contains original image URLs as JSON-escaped murl values.
        for m in re.finditer(r'"murl"\s*:\s*"((?:\\.|[^"\\])+)"', raw):
            try:
                url = json.loads('"' + m.group(1) + '"')
            except ValueError:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or url in seen:
                continue
            if any(x in parsed.hostname.lower() for x in ("localhost", "127.0.0.1")):
                continue
            seen.add(url)
            covers.append({"url": url[:2000], "source": parsed.hostname})
            if len(covers) >= min(max(int(limit), 1), 20):
                break
        return {"query": q, "covers": covers, "count": len(covers)}

    @staticmethod
    def _book_id(url):
        m = re.search(r"/book2/(\d+)", url or "")
        return m.group(1) if m else ""

    def _parse_rank(self, page, period, channel):
        html_text = page.get("html", "")
        found = []
        seen = set()
        # The mobile ranking pages group works under visible channel headings.
        for m in re.finditer(r"<a\b[^>]*href\s*=\s*(['\"])([^'\"]*/book2/\d+[^'\"]*)\1[^>]*>(.*?)</a>", html_text, re.I | re.S):
            url = urljoin(BASE, html.unescape(m.group(2)))
            book_id = self._book_id(url)
            title = _plain(m.group(3))
            if not book_id or not title or book_id in seen:
                continue
            before = html_text[:m.start()]
            headings = re.findall(r"[〖【]([^〖〗【】]{1,24}?)(?:排行|榜)[〗】]", before)
            group = headings[-1] if headings else "晋江榜单"
            group = group.replace("排行", "").replace("榜", "").strip()
            if channel and channel != "全部" and channel not in group:
                continue
            seen.add(book_id)
            found.append({"id": book_id, "title": title, "author": "", "channel": group,
                          "rank": len(found) + 1, "source": "晋江文学城", "url": url,
                          "cover_url": "", "description": ""})
        return found[:60]

    def ranking(self, period="month", channel="全部"):
        if period not in RANKS:
            period = "month"
        label, path = RANKS[period]
        url = urljoin(BASE, path)
        try:
            page = self.fetcher.fetch_page(url)  # respects the site's robots.txt
        except FetchError as first_error:
            # Alternate official desktop host; do not bypass robots, CAPTCHA, or access controls.
            fallback = urljoin("https://www.jjwxc.net", path)
            try:
                page = self.fetcher.fetch_page(fallback)
            except FetchError as second_error:
                if first_error.code.startswith("http_5") or second_error.code.startswith("http_5"):
                    raise FetchError("jjwxc_upstream", "晋江服务器暂时返回错误（502/5xx）。已尝试官方备用域名，仍不可用；请稍后重试或打开晋江原站。")
                raise second_error
        books = self._parse_rank(page, period, channel)
        return {"source": "晋江文学城", "period": period, "period_label": label,
                "channel": channel or "全部", "books": books, "count": len(books),
                "source_url": page.get("url", url), "channels": CHANNELS,
                "periods": [{"id": k, "name": v[0]} for k, v in RANKS.items()],
                "note": "榜单来自晋江文学城公开榜单页；排名随站点更新。若站点限制访问，稍后重试或打开原站。"}

    def search(self, query, limit=20):
        q = str(query or "").strip()[:80]
        if not q:
            return {"query": q, "books": [], "count": 0}
        results = self.bing.search("site:m.jjwxc.com/book2 " + q, limit=min(max(int(limit), 1), 20))
        books, seen = [], set()
        for item in results:
            bid = self._book_id(item.url)
            if not bid or bid in seen:
                continue
            seen.add(bid)
            books.append({"id": bid, "title": _plain(item.title), "author": "", "channel": "搜索结果",
                          "rank": len(books) + 1, "source": "晋江文学城", "url": urljoin(BASE, "/book2/" + bid),
                          "cover_url": "", "description": _plain(item.snippet)[:240]})
        return {"query": q, "books": books, "count": len(books), "source": "必应检索晋江公开作品页"}

    def _book_cache(self):
        try:
            with open(self.book_cache_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def book(self, book_id):
        bid = re.sub(r"\D", "", str(book_id or ""))[:12]
        if not bid:
            raise ValueError("晋江作品 ID 无效")
        cache = self._book_cache()
        cached = cache.get(bid)
        if isinstance(cached, dict) and time.time() - cached.get("saved_at", 0) < 7 * 86400:
            result = dict(cached.get("book") or {})
            if result:
                result["cover_url"] = self._cover_overrides().get(bid, result.get("cover_url", ""))
                return result
        url = urljoin(BASE, "/book2/" + bid)
        try:
            page = self.fetcher.fetch_page(url)  # public work metadata only; obey robots.txt
        except FetchError as first_error:
            fallback = urljoin("https://www.jjwxc.net", "/book2/" + bid)
            try:
                page = self.fetcher.fetch_page(fallback)
            except FetchError as second_error:
                if first_error.code.startswith("http_5") or second_error.code.startswith("http_5"):
                    raise FetchError("jjwxc_upstream", "晋江作品页暂时返回 502/5xx；官方备用域名也未能读取，请稍后重试。")
                raise second_error
        raw = page.get("html", "")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        title = _plain(title_match.group(1)) if title_match else ""
        title = re.sub(r"^《|》.*$", "", title) if title.startswith("《") else title.split("_", 1)[0].strip()
        author = self._field(raw, "作者")
        category = self._field(raw, "类型")
        tags = self._field(raw, "标签")
        protagonists = self._field(raw, "主角")
        synopsis = self._field(raw, "简介")
        # Prefer declared social preview image, then an actual cover-like image on the work page.
        candidates = []
        for m in re.finditer(r"<meta\b[^>]*(?:property|name)\s*=\s*(['\"])(?:og:image|twitter:image)\1[^>]*>", raw, re.I):
            candidates.append(_attr(m.group(0), "content"))
        for m in re.finditer(r"<img\b[^>]*>", raw, re.I):
            tag = m.group(0)
            candidates.extend([_attr(tag, "data-src"), _attr(tag, "data-original"), _attr(tag, "data-lazy-src"), _attr(tag, "data-echo"), _attr(tag, "src"), _attr(tag, "srcset").split(",")[0].strip().split(" ")[0]])
        cover = ""
        for candidate in candidates:
            cover = _safe_cover(candidate)
            if cover:
                break
        names = [x.strip() for x in re.split(r"[,，、/；;]", protagonists) if x.strip()][:12]
        cover = self._cover_overrides().get(bid, cover)
        result = {"id": bid, "title": title or ("晋江作品 " + bid), "author": author,
                  "category": category, "tags": tags, "characters": names,
                  "description": synopsis[:1200], "cover_url": cover,
                  "url": page.get("url", url), "source": "晋江文学城"}
        cache[bid] = {"saved_at": time.time(), "book": result}
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            tmp = self.book_cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(cache, fh, ensure_ascii=False)
            os.replace(tmp, self.book_cache_file)
        except OSError:
            pass
        return result

    @staticmethod
    def _field(raw, label):
        # Convert markup to a single text stream so values wrapped in <a>/<span> are retained.
        text = re.sub(r"<[^>]+>", " ", raw or "")
        text = re.sub(r"\s+", " ", html.unescape(text)).strip()
        labels = r"作者|类型|标签|主角|配角|一句话简介|立意|状态|简介|收藏|章节列表|作者公告"
        m = re.search(re.escape(label) + r"\s*[:：]\s*(.*?)(?=\s*(?:" + labels + r")(?:\s*[:：]|\s*[（(])|$)",
                      text, re.I | re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip()[:1200] if m else ""
