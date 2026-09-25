#!/usr/bin/env python3
"""Minimal authenticated AdGuard Home API client for the two cluster nodes.

Used for snapshot/patch/verify during the Cloudflare -> Mullvad upstream
migration. Only touches the endpoints it is told to.
"""
import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment
import http.cookiejar, json, urllib.error, urllib.request
from pathlib import Path

NODES = {
    "primary": {"base": "http://127.0.0.1:3000",
            "creds": env("PRIMARY_ADGUARD_CREDENTIALS")},
    "secondary": {"base": "http://" + env("SECONDARY_NODE_IP") + ":3000",
              "creds": env("SECONDARY_ADGUARD_CREDENTIALS")},
}
_openers = {}


def opener(node):
    if node in _openers:
        return _openers[node]
    cfg = NODES[node]
    data = json.loads(Path(cfg["creds"]).read_text())
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.open(urllib.request.Request(
        cfg["base"] + "/control/login",
        data=json.dumps({"name": data["username"], "password": data["password"]}).encode(),
        headers={"Content-Type": "application/json"}), timeout=10)
    _openers[node] = op
    return op


def call(node, path, data=None, timeout=60, method=None):
    op = opener(node)
    req = urllib.request.Request(
        NODES[node]["base"] + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method)
    with op.open(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body) if body else {}


def snapshot(node):
    """Everything we need to prove nothing outside upstream_dns moved."""
    out = {}
    for name, path in (("dns_info", "/control/dns_info"),
                       ("status", "/control/status"),
                       ("filtering", "/control/filtering/status"),
                       ("querylog_config", "/control/querylog/config"),
                       ("stats_config", "/control/stats/config"),
                       ("clients", "/control/clients"),
                       ("access", "/control/access/list"),
                       ("rewrites", "/control/rewrite/list"),
                       ("safebrowsing", "/control/safebrowsing/status"),
                       ("parental", "/control/parental/status")):
        try:
            out[name] = call(node, path, timeout=25)
        except Exception as e:
            out[name] = {"_error": f"{type(e).__name__}: {e}"}
    return out


def test_upstreams(node, cfg=None):
    cfg = cfg or call(node, "/control/dns_info", timeout=20)
    body = {"upstream_dns": cfg.get("upstream_dns") or [],
            "bootstrap_dns": cfg.get("bootstrap_dns") or [],
            "fallback_dns": cfg.get("fallback_dns") or [],
            "private_upstream": cfg.get("local_ptr_upstreams") or []}
    return call(node, "/control/test_upstream_dns", data=body, timeout=90)
