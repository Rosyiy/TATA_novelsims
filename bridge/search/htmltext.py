"""HTML -> plain text (stdlib only), including GB18030 pages common on Chinese sites."""
import re
from html import unescape
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe",
        "template", "button", "select"}
BLOCK = {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
         "table", "dd", "dt", "blockquote"}


class _Parser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def decode_bytes(data, content_type=""):
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I) or \
        re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", data[:3000], re.I)
    names = []
    if m:
        g = m.group(1)
        names.append(g.decode("ascii", "ignore") if isinstance(g, bytes) else g)
    names += ["utf-8", "gb18030"]
    for n in names:
        try:
            return data.decode(n)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


def meta_description(html):
    for pat in (r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
                r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']',
                r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']'):
        m = re.search(pat, html, re.I)
        if m and m.group(1).strip():
            return unescape(m.group(1)).strip()
    return ""


def extract_title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", unescape(m.group(1))).strip() if m else ""


def html_to_text(html, max_chars=6000):
    p = _Parser()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    lines = [re.sub(r"[ \t\u3000\xa0]+", " ", ln).strip() for ln in "".join(p.parts).splitlines()]
    text = "\n".join(ln for ln in lines if len(ln) >= 2)
    desc = meta_description(html)
    if desc and desc not in text[:1500]:
        text = desc + "\n" + text
    return text[:max_chars]
