"""Search engines. Official APIs (Wikipedia, Tavily) are the reliable ones; the Bing/DuckDuckGo
HTML parsers are best-effort because those pages change and may rate-limit or ask for a captcha."""
import base64
import re
from html import unescape
from urllib.parse import parse_qs, quote, unquote, urlparse


class SearchResult(object):
    def __init__(self, title, url, snippet="", engine="", rank=0):
        self.title, self.url, self.snippet, self.engine, self.rank = title, url, snippet, engine, rank
        self.content_is_text = False


def strip_tags(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _attr(tag, name):
    m = re.search(r'\b%s\s*=\s*"([^"]*)"' % name, tag) or re.search(r"\b%s\s*=\s*'([^']*)'" % name, tag)
    return unescape(m.group(1)) if m else ""


class EngineError(Exception):
    pass


class WikipediaEngine(object):
    def __init__(self, fetcher, lang="zh", api_base=None):
        self.name = "wikipedia"
        self.f, self.lang = fetcher, lang
        self.api = api_base or "https://%s.wikipedia.org/w/api.php" % lang

    def search(self, query, limit=6):
        data = self.f.get_json("%s?action=query&list=search&srsearch=%s&srlimit=%d&format=json&utf8=1"
                               % (self.api, quote(query), limit))
        out = []
        base = self.api.rsplit("/w/api.php", 1)[0]
        for i, it in enumerate((data.get("query") or {}).get("search", [])):
            title = it.get("title", "")
            out.append(SearchResult(title, "%s/wiki/%s" % (base, quote(title.replace(" ", "_"))),
                                    strip_tags(it.get("snippet", "")), self.name, i))
        return out


def _bing_unwrap(url):
    if "bing.com/ck/a" in url:
        u = parse_qs(urlparse(url).query).get("u", [""])[0]
        if u.startswith("a1"):
            b = u[2:]
            try:
                return base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode("utf-8")
            except Exception:
                return url
    return url


class BingEngine(object):
    def __init__(self, fetcher, host="cn.bing.com"):
        self.name = "bing"
        self.f, self.host = fetcher, host

    @staticmethod
    def parse(html):
        out = []
        for i, block in enumerate(re.findall(r'<li[^>]+class="[^"]*\bb_algo\b[^"]*"[^>]*>.*?</li>', html, re.S)):
            m = re.search(r"<h2[^>]*>\s*(<a\b[^>]*>)(.*?)</a>", block, re.S)
            if not m:
                continue
            url = _bing_unwrap(_attr(m.group(1), "href"))
            sn = re.search(r"<p[^>]*>(.*?)</p>", block, re.S) or \
                re.search(r'<div[^>]+class="[^"]*b_caption[^"]*"[^>]*>(.*?)</div>', block, re.S)
            if url.startswith("http"):
                out.append(SearchResult(strip_tags(m.group(2)), url, strip_tags(sn.group(1)) if sn else "", "bing", i))
        return out

    def search(self, query, limit=6):
        html = self.f.fetch_page_nonrobots("https://%s/search?q=%s&setlang=zh-Hans&count=%d"
                                           % (self.host, quote(query), limit))["html"]
        res = self.parse(html)
        if not res and re.search(r"captcha|验证码|unusual traffic", html, re.I):
            raise EngineError("被限流或需要人机验证，稍后再试或换用其他搜索源")
        return res[:limit]


class DuckDuckGoEngine(object):
    def __init__(self, fetcher):
        self.name = "duckduckgo"
        self.f = fetcher

    @staticmethod
    def parse(html):
        out = []
        for i, m in enumerate(re.finditer(r"(<a\b[^>]*class=\"[^\"]*result__a[^\"]*\"[^>]*>)(.*?)</a>", html, re.S)):
            url = _attr(m.group(1), "href")
            q = parse_qs(urlparse(url).query).get("uddg")
            if q:
                url = unquote(q[0])
            if url.startswith("//"):
                url = "https:" + url
            tail = html[m.end(): m.end() + 2500]
            sn = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', tail, re.S)
            if url.startswith("http"):
                out.append(SearchResult(strip_tags(m.group(2)), url, strip_tags(sn.group(1)) if sn else "", "duckduckgo", i))
        return out

    def search(self, query, limit=6):
        page = self.f.fetch_page_nonrobots("https://html.duckduckgo.com/html/?q=%s" % quote(query))
        return self.parse(page["html"])[:limit]



class BaiduEngine(object):
    """Baidu web search HTML adapter; best-effort parser, no CAPTCHA bypass."""
    name = "baidu"
    def __init__(self, fetcher): self.f = fetcher
    @staticmethod
    def parse(html):
        out=[]
        blocks=re.findall(r'<div[^>]+class=["\'][^"\']*(?:result|c-container)[^"\']*["\'][^>]*>.*?</div>\s*</div>', html, re.S|re.I)
        for i,b in enumerate(blocks):
            m=re.search(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',b,re.S|re.I)
            if m and m.group(1).startswith('http'):
                sn=re.search(r'<(?:div|span)[^>]+class=["\'][^"\']*(?:content-right|c-abstract|content)[^"\']*["\'][^>]*>(.*?)</(?:div|span)>',b,re.S|re.I)
                out.append(SearchResult(strip_tags(m.group(2)),unescape(m.group(1)),strip_tags(sn.group(1)) if sn else '', 'baidu',i))
        return out
    def search(self,query,limit=8):
        h=self.f.fetch_page_nonrobots('https://www.baidu.com/s?wd='+quote(query)+'&rn='+str(min(limit,20)))['html']
        return self.parse(h)[:limit]


class QuarkEngine(object):
    """Quark mobile search HTML adapter; markup can change and may return no results."""
    name = "quark"
    def __init__(self,fetcher): self.f=fetcher
    @staticmethod
    def parse(html):
        out=[]; seen=set()
        for i,m in enumerate(re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',html,re.S|re.I)):
            url=unescape(m.group(1)); title=strip_tags(m.group(2))
            if url.startswith('//'): url='https:'+url
            host=urlparse(url).hostname or ''
            if url.startswith('http') and title and len(title)>2 and host not in ('quark.sm.cn','m.sm.cn') and url not in seen:
                seen.add(url); out.append(SearchResult(title,url,'','quark',i))
        return out
    def search(self,query,limit=8):
        h=self.f.fetch_page_nonrobots('https://quark.sm.cn/s?q='+quote(query))['html']
        return self.parse(h)[:limit]


class SogouEngine(object):
    name = "sogou"
    def __init__(self,fetcher): self.f=fetcher
    @staticmethod
    def parse(html):
        out=[]
        blocks=re.findall(r'<(?:div|li)[^>]+class=["\'][^"\']*(?:vrwrap|rb|results)[^"\']*["\'][^>]*>.*?</(?:div|li)>',html,re.S|re.I)
        for i,b in enumerate(blocks):
            m=re.search(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',b,re.S|re.I)
            if m and m.group(1).startswith('http'):
                sn=re.search(r'<(?:p|div)[^>]+class=["\'][^"\']*(?:str_info|ft)[^"\']*["\'][^>]*>(.*?)</(?:p|div)>',b,re.S|re.I)
                out.append(SearchResult(strip_tags(m.group(2)),unescape(m.group(1)),strip_tags(sn.group(1)) if sn else '', 'sogou',i))
        return out
    def search(self,query,limit=8):
        h=self.f.fetch_page_nonrobots('https://www.sogou.com/web?query='+quote(query))['html']
        return self.parse(h)[:limit]


class ZhipuSearchEngine(object):
    """Zhipu Web Search API (POST /paas/v4/web_search, Bearer key). Reuses the player's Zhipu key.
    The API returns page summaries (not raw pages), so results are marked content_is_text and the
    pipeline never fetches those pages itself (no robots/anti-bot problems, and no page copies)."""

    def __init__(self, fetcher, api_key, base="https://open.bigmodel.cn/api/paas/v4/web_search",
                 search_engine="search_std"):
        self.name = "zhipu"
        self.f, self.key, self.base, self.engine = fetcher, api_key, base, search_engine

    def search(self, query, limit=6):
        data = self.f.post_json(self.base, {"search_query": query[:70], "search_engine": self.engine,
                                            "search_intent": False, "count": max(1, min(int(limit), 20))},
                                {"Authorization": "Bearer " + self.key})
        out = []
        for i, r in enumerate(data.get("search_result") or []):
            if not isinstance(r, dict):
                continue
            url = r.get("link") or r.get("url") or ""
            text = r.get("content") or r.get("summary") or r.get("snippet") or ""
            if url.startswith("http"):
                res = SearchResult(strip_tags(r.get("title", "")), url, strip_tags(text)[:1500], self.name, i)
                res.content_is_text = True
                out.append(res)
        return out


class TavilyEngine(object):
    def __init__(self, fetcher, api_key, base="https://api.tavily.com/search"):
        self.name = "tavily"
        self.f, self.key, self.base = fetcher, api_key, base

    def search(self, query, limit=6):
        data = self.f.post_json(self.base, {"query": query, "max_results": limit, "search_depth": "basic"},
                                {"Authorization": "Bearer " + self.key})
        return [SearchResult(r.get("title", ""), r.get("url", ""), strip_tags(r.get("content", "")), self.name, i)
                for i, r in enumerate(data.get("results", [])) if r.get("url")]


ENGINE_INFO = [
    {"id": "zhipu", "name": "智谱联网搜索 API（复用“智谱 GLM”的 Key，国内稳定，推荐）", "needs_key": True, "key_of": "智谱"},
    {"id": "baidu", "name": "百度网页搜索（中文资料）", "needs_key": False},
    {"id": "quark", "name": "夸克搜索（中文网页，页面结构可能变化）", "needs_key": False},
    {"id": "sogou", "name": "搜狗网页搜索", "needs_key": False},
    {"id": "bing", "name": "必应网页搜索（解析网页，可能被限流）", "needs_key": False},
    {"id": "wikipedia", "name": "维基百科（官方 API，国内通常连不上）", "needs_key": False},
    {"id": "duckduckgo", "name": "DuckDuckGo（解析网页，大陆通常不可用）", "needs_key": False},
    {"id": "tavily", "name": "Tavily 搜索 API（需要单独的 Key，最稳）", "needs_key": True, "key_of": "Tavily"},
]


def build_engines(ids, fetcher, keys):
    out = []
    for i in ids:
        if i == "wikipedia":
            out.append(WikipediaEngine(fetcher))
        elif i == "baidu":
            out.append(BaiduEngine(fetcher))
        elif i == "quark":
            out.append(QuarkEngine(fetcher))
        elif i == "sogou":
            out.append(SogouEngine(fetcher))
        elif i == "bing":
            out.append(BingEngine(fetcher))
        elif i == "duckduckgo":
            out.append(DuckDuckGoEngine(fetcher))
        elif i == "tavily" and keys.get("tavily"):
            out.append(TavilyEngine(fetcher, keys["tavily"]))
        elif i == "zhipu" and keys.get("zhipu"):
            out.append(ZhipuSearchEngine(fetcher, keys["zhipu"]))
    return out
