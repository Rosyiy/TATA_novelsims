"""Polite, size-limited, SSRF-guarded fetching. Honors robots.txt for web pages."""
import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .htmltext import decode_bytes
from .netguard import UnsafeUrl, check_public_url

UA = "Mozilla/5.0 (compatible; NovelSimsBot/0.2; personal local tool; honors robots.txt)"
OK_TYPES = ("text/html", "application/xhtml", "text/plain", "application/json")


class FetchError(Exception):
    def __init__(self, code, message=""):
        Exception.__init__(self, message or code)
        self.code = code


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_private):
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            check_public_url(newurl, self.allow_private)
        except UnsafeUrl as exc:
            raise FetchError("unsafe_redirect", str(exc))
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


class Fetcher(object):
    def __init__(self, timeout=10.0, max_bytes=1500000, allow_private=False, respect_robots=True):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.allow_private = allow_private
        self.respect_robots = respect_robots
        self._robots = {}
        self._opener = urllib.request.build_opener(_GuardedRedirect(allow_private))

    def _request(self, url, data=None, headers=None, method=None):
        try:
            check_public_url(url, self.allow_private)
        except UnsafeUrl as exc:
            raise FetchError("unsafe_url", str(exc))
        h = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            return self._opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raise FetchError("http_%d" % exc.code, "HTTP %d" % exc.code)
        except FetchError:
            raise
        except socket.timeout:
            raise FetchError("timeout", "超时")
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), socket.timeout):
                raise FetchError("timeout", "超时")
            raise FetchError("network", str(exc.reason))
        except (OSError, ValueError) as exc:
            raise FetchError("network", str(exc))

    def robots_allowed(self, url):
        if not self.respect_robots:
            return True
        u = urlparse(url)
        base = "%s://%s" % (u.scheme, u.netloc)
        if base not in self._robots:
            rp = RobotFileParser()
            try:
                resp = self._request(base + "/robots.txt")
                rp.parse(decode_bytes(resp.read(200000)).splitlines())
            except FetchError as exc:
                if exc.code in ("http_401", "http_403"):
                    rp.parse(["User-agent: *", "Disallow: /"])
                else:
                    rp.parse([])          # no robots.txt / unreachable => allowed
            self._robots[base] = rp
        return self._robots[base].can_fetch(UA, url)

    def fetch_page(self, url):
        """Return {'url','html'} or raise FetchError ('robots', 'content_type', ...)."""
        if not self.robots_allowed(url):
            raise FetchError("robots", "该站点 robots.txt 不允许抓取")
        resp = self._request(url)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if not any(t in ctype for t in OK_TYPES):
            raise FetchError("content_type", "不是网页内容：" + ctype[:40])
        raw = resp.read(self.max_bytes + 1)[: self.max_bytes]
        return {"url": resp.geturl(), "html": decode_bytes(raw, ctype)}

    def fetch_page_nonrobots(self, url):
        """Search-result pages only (the user explicitly enabled that engine). Never used for content pages."""
        resp = self._request(url)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        raw = resp.read(self.max_bytes + 1)[: self.max_bytes]
        return {"url": resp.geturl(), "html": decode_bytes(raw, ctype)}

    def _json(self, resp):
        try:
            return json.loads(decode_bytes(resp.read(self.max_bytes), resp.headers.get("Content-Type", "")))
        except ValueError:
            raise FetchError("bad_json", "返回的不是 JSON")

    def get_json(self, url, headers=None):
        return self._json(self._request(url, headers=headers))

    def post_json(self, url, payload, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        return self._json(self._request(url, data=json.dumps(payload).encode("utf-8"), headers=h, method="POST"))
