"""Source filtering (spec 5.1): drop pirated/full-text sites, classify sources, tag adaptations."""
import re
from urllib.parse import urlparse

# Well-known full-text / pirate reading sites (host substring match). Not exhaustive: the content
# check in looks_like_fulltext() is a second line of defence.
PIRACY_HOST_PARTS = ("biquge", "biqu", "bqg", "xbiquge", "qb5", "ixdzs", "uukanshu", "zwdu", "shuquge",
                     "wenku8", "ptwxz", "69shu", "xs8", "23us", "25zw", "81zw", "aixs", "kanshu",
                     "txt99", "txtnovel", "novel543", "piaotia", "bookben", "zhuishu")
BLOCKED_EXT = (".txt", ".epub", ".mobi", ".azw3", ".pdf", ".zip", ".rar", ".7z", ".doc", ".docx")

TRUST = [("wikipedia.org", 10, "encyclopedia"), ("baike.baidu.com", 9, "encyclopedia"),
         ("moegirl.org.cn", 8, "encyclopedia"), ("baike.sogou.com", 6, "encyclopedia"),
         ("qidian.com", 8, "platform"), ("jjwxc.net", 8, "platform"), ("fanqienovel.com", 7, "platform"),
         ("zongheng.com", 6, "platform"), ("douban.com", 7, "review"), ("goodreads.com", 6, "review"),
         ("zhihu.com", 4, "community"), ("tieba.baidu.com", 3, "community"), ("bilibili.com", 3, "community")]
ADAPTATION_WORDS = ("电视剧", "电影", "改编", "漫画", "动画", "手游", "游戏", "舞台剧", "广播剧",
                    "网剧", "剧集", "影视", "drama series", "tv series", "film")


def host_of(url):
    return (urlparse(url).hostname or "").lower()


def blocked_reason(url):
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        return "不是网页地址"
    host = host_of(url)
    if any(p in host for p in PIRACY_HOST_PARTS):
        return "疑似盗版/全文站"
    if u.path.lower().endswith(BLOCKED_EXT):
        return "文件下载链接（可能是全文）"
    return None


def trust_of(url):
    host = host_of(url)
    for dom, score, kind in TRUST:
        if host == dom or host.endswith("." + dom):
            return score, kind
    return 3, "other"


def detect_edition(title, snippet, url):
    blob = (title + " " + snippet + " " + url).lower()
    return "adaptation" if any(w in blob for w in ADAPTATION_WORDS) else "unknown"


def looks_like_fulltext(text):
    """Chapter-marker density: reading pages are full of 第N章 headings / navigation."""
    if len(re.findall(r"第[0-9零一二三四五六七八九十百千两]{1,6}[章节回]", text)) >= 8:
        return True
    return text.count("上一章") + text.count("下一章") + text.count("加入书签") >= 2


def canonical_url(url):
    u = urlparse(url)
    q = "&".join(p for p in u.query.split("&")
                 if p and not p.lower().startswith(("utm_", "spm", "from", "ref")))
    return "%s://%s%s%s" % (u.scheme, u.netloc.lower(), u.path.rstrip("/") or "/", ("?" + q) if q else "")
