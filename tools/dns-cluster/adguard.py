"""Minimal AdGuard Home API client for a two-node DNS cluster.

Deliberately stdlib-only so it runs under the system python without adding a
dependency.

Credentials are read from 0600 files at call time and are never returned, printed,
logged or placed in an exception message.

Addresses and credential paths come from configuration (see config.example.env);
nothing about a particular installation is hard-coded here.
"""
import http.cookiejar
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment

# The two cluster members. `key` is what the tools and reports use.
NODES = {
    "primary": {
        "label": "AdGuard Primary",
        # Administered over loopback: the primary runs on this host.
        "api": "http://127.0.0.1:3000",
        "dns": env("PRIMARY_NODE_IP"),
        "credentials": Path(env("PRIMARY_ADGUARD_CREDENTIALS")),
        "role": "primary",
    },
    "secondary": {
        "label": "AdGuard Secondary",
        "api": "http://" + env("SECONDARY_NODE_IP") + ":3000",
        "dns": env("SECONDARY_NODE_IP"),
        "credentials": Path(env("SECONDARY_ADGUARD_CREDENTIALS")),
        "role": "secondary",
    },
}

# Any address that must never appear as an upstream/fallback/PTR resolver of a
# cluster member. A member pointing at the other member (or at itself) is how a
# recursive DNS loop gets built, so the sync validator refuses such a config.
CLUSTER_ADDRESSES = {
    env("PRIMARY_NODE_IP"), env("SECONDARY_NODE_IP"),
    env("PRIMARY_NODE_TAILSCALE_IP"), env("SECONDARY_NODE_TAILSCALE_IP"),
    "127.0.0.1", "localhost", "::1",
}

# Redirect a node at a different endpoint without editing this file. Used to validate
# the whole pipeline against a throwaway staging instance before touching PcOld, and
# useful again if a node's address ever changes.
for _node, _spec in NODES.items():
    _api = os.environ.get(f"HOMELAB_DNS_{_node.upper()}_API")
    _dns = os.environ.get(f"HOMELAB_DNS_{_node.upper()}_DNS")
    _cred = os.environ.get(f"HOMELAB_DNS_{_node.upper()}_CREDENTIALS")
    if _api:
        _spec["api"] = _api
    if _dns:
        _spec["dns"] = _dns
    if _cred:
        _spec["credentials"] = Path(_cred)


class AdGuardError(RuntimeError):
    """Raised with a message that never contains a credential."""


class Client:
    def __init__(self, node, timeout=8):
        if node not in NODES:
            raise AdGuardError(f"unknown node {node!r}")
        self.node = node
        self.spec = NODES[node]
        self.timeout = timeout
        self._opener = None

    # ----------------------------------------------------------------- transport
    def _login(self):
        path = self.spec["credentials"]
        if not path.exists():
            raise AdGuardError(f"{self.node}: credential file missing at {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        payload = json.dumps({"name": data["username"], "password": data["password"]}).encode()
        request = urllib.request.Request(self.spec["api"] + "/control/login", data=payload,
                                         headers={"Content-Type": "application/json"})
        try:
            with opener.open(request, timeout=self.timeout) as response:
                response.read()
        except urllib.error.HTTPError as error:
            raise AdGuardError(f"{self.node}: authentication rejected (HTTP {error.code})") from None
        except (urllib.error.URLError, OSError) as error:
            raise AdGuardError(f"{self.node}: API unreachable at {self.spec['api']} ({error.reason})") from None
        return opener

    def call(self, path, *, data=None, method=None, timeout=None):
        for attempt in (1, 2):
            if self._opener is None:
                self._opener = self._login()
            body = None if data is None else json.dumps(data).encode()
            headers = {"Content-Type": "application/json"} if body is not None else {}
            request = urllib.request.Request(self.spec["api"] + path, data=body,
                                             headers=headers, method=method)
            try:
                with self._opener.open(request, timeout=timeout or self.timeout) as response:
                    raw = response.read()
                return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as error:
                if error.code in (401, 403) and attempt == 1:
                    self._opener = None
                    continue
                detail = error.read()[:200].decode(errors="replace")
                raise AdGuardError(f"{self.node}: {path} -> HTTP {error.code} {detail}") from None
            except (urllib.error.URLError, OSError) as error:
                raise AdGuardError(f"{self.node}: {path} unreachable ({error})") from None
        raise AdGuardError(f"{self.node}: authentication loop on {path}")

    # ------------------------------------------------------------------- reading
    def snapshot(self):
        """Everything that defines DNS behaviour, in one comparable dict."""
        dns = self.call("/control/dns_info")
        filtering = self.call("/control/filtering/status")
        clients = self.call("/control/clients")
        querylog = self.call("/control/querylog/config")
        stats = self.call("/control/stats/config")
        access = self.call("/control/access/list")
        safebrowsing = self.call("/control/safebrowsing/status")
        parental = self.call("/control/parental/status")
        status = self.call("/control/status")
        return {
            "version": status.get("version"),
            "running": status.get("running"),
            "protection_enabled": status.get("protection_enabled"),
            "dns": dns,
            "filtering": filtering,
            "clients": clients,
            "querylog": querylog,
            "stats": stats,
            "access": access,
            "safebrowsing": safebrowsing,
            "parental": parental,
        }


# --------------------------------------------------------------- parity contract
# Exactly the values that must be identical on both resolvers for a client to get
# the same answer whichever one it happens to pick.
DNS_PARITY_KEYS = (
    "upstream_dns", "bootstrap_dns", "fallback_dns", "local_ptr_upstreams",
    "upstream_mode", "use_private_ptr_resolvers", "resolve_clients",
    "dnssec_enabled", "cache_enabled", "cache_size", "cache_ttl_min", "cache_ttl_max",
    "cache_optimistic", "ratelimit", "refuse_any", "blocking_mode",
    "blocking_ipv4", "blocking_ipv6", "edns_cs_enabled", "disable_ipv6",
    "upstream_timeout", "blocked_response_ttl",
)
# Host-specific by design; a difference here is expected and is NOT drift.
DNS_HOST_KEYS = ("bind_hosts", "port", "protection_enabled")


def parity_view(snapshot):
    """Reduce a snapshot to the comparable parity surface."""
    dns = snapshot.get("dns") or {}
    filtering = snapshot.get("filtering") or {}
    clients = snapshot.get("clients") or {}
    view = {f"dns.{k}": dns.get(k) for k in DNS_PARITY_KEYS}
    view["filtering.enabled"] = filtering.get("enabled")
    view["filtering.interval"] = filtering.get("interval")
    view["filtering.user_rules"] = list(filtering.get("user_rules") or [])
    view["filtering.filters"] = sorted(
        [(f.get("url"), bool(f.get("enabled")), f.get("name")) for f in (filtering.get("filters") or [])])
    view["filtering.whitelist_filters"] = sorted(
        [(f.get("url"), bool(f.get("enabled"))) for f in (filtering.get("whitelist_filters") or [])])
    view["clients.persistent"] = sorted(
        [(c.get("name"), tuple(sorted(c.get("ids") or []))) for c in (clients.get("clients") or [])])
    view["querylog.enabled"] = (snapshot.get("querylog") or {}).get("enabled")
    view["querylog.interval"] = (snapshot.get("querylog") or {}).get("interval")
    view["querylog.anonymize_client_ip"] = (snapshot.get("querylog") or {}).get("anonymize_client_ip")
    view["stats.enabled"] = (snapshot.get("stats") or {}).get("enabled")
    view["stats.interval"] = (snapshot.get("stats") or {}).get("interval")
    view["access.allowed_clients"] = sorted((snapshot.get("access") or {}).get("allowed_clients") or [])
    view["access.disallowed_clients"] = sorted((snapshot.get("access") or {}).get("disallowed_clients") or [])
    view["safebrowsing.enabled"] = (snapshot.get("safebrowsing") or {}).get("enabled")
    view["parental.enabled"] = (snapshot.get("parental") or {}).get("enabled")
    return view


def diff(source_view, target_view):
    """Ordered list of (key, source_value, target_value) for every mismatch."""
    out = []
    for key in sorted(set(source_view) | set(target_view)):
        a, b = source_view.get(key), target_view.get(key)
        if a != b:
            out.append((key, a, b))
    return out


# ------------------------------------------------------------------- loop guard
def loop_risks(dns_config):
    """Return the reasons a DNS config would build a resolver loop. Empty == safe.

    A cluster member must resolve the internet directly over DoH. If it ever points
    its upstream, fallback or local-PTR resolver at another cluster member, queries
    can bounce between the two resolvers forever.
    """
    problems = []
    for field in ("upstream_dns", "fallback_dns", "local_ptr_upstreams", "bootstrap_dns"):
        for entry in dns_config.get(field) or []:
            text = str(entry)
            # strip AdGuard's optional "[/domain/]server" prefix syntax
            server = text.split("]")[-1] if text.startswith("[/") else text
            host = server.split("://")[-1].split("/")[0].rsplit(":", 1)[0].strip("[]")
            if host in CLUSTER_ADDRESSES:
                problems.append(f"{field} contains cluster member {host!r} — recursive loop risk")
    if not (dns_config.get("upstream_dns") or []):
        problems.append("upstream_dns is empty")
    if not any(str(u).startswith(("https://", "tls://", "quic://", "h3://"))
               for u in dns_config.get("upstream_dns") or []):
        problems.append("no encrypted upstream: plain :53 upstreams are hijacked by the router")
    return problems
