"""SSRF guard: the backend runs on the player's PC, so pages it fetches must never be able to
reach the local machine or LAN (router admin pages, the bridge itself, other local services)."""
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrl(Exception):
    pass


def check_public_url(url, allow_private=False):
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise UnsafeUrl("只允许 http(s) 地址")
    if u.username or u.password:
        raise UnsafeUrl("地址里不能带账号密码")
    if allow_private:                     # tests only
        return
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeUrl("域名解析失败")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise UnsafeUrl("拒绝访问内网/本机地址")
