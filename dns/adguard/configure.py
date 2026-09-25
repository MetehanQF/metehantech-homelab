#!/usr/bin/env python3
"""Apply MetehanTech production settings to a freshly generated AdGuardHome.yaml.

Idempotent: safe to re-run. Only the keys listed below are touched; everything else
AdGuard generated (schema_version, bcrypt user hash, TLS block, DHCP block …) is kept
exactly as written by AdGuard itself, so the schema always stays valid for the running
version. Run with the container STOPPED, then start it.
"""
import os
import shutil
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent
# AdGuard's own generated config. It is RUNTIME STATE (it holds the bcrypt admin
# hash and the client inventory) and is deliberately not in this repository.
CONF = Path(os.environ.get("ADGUARD_CONFIG")
            or (PROJECT_ROOT / "conf" / "AdGuardHome.yaml"))

# --- ortam bagimli degerler -------------------------------------------------------
# Adresler ve cihaz adlari repoda DEGILDIR; repo kokundeki config.env dosyasindan
# gelir (Git disi). Sablon: config.example.env
import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env

# --- Phase 5: upstreams -----------------------------------------------------------
# Both upstreams validate DNSSEC and both filter known-malicious domains, so the
# malware posture does not depend on which one load_balance happens to pick.
UPSTREAMS = [
    "https://dns.quad9.net/dns-query",             # Quad9 secured
    "https://security.cloudflare-dns.com/dns-query",  # Cloudflare 1.1.1.2
]
BOOTSTRAP = ["9.9.9.9", "149.112.112.112", "1.1.1.1", "1.0.0.1"]
# Phase 8: if every upstream is unreachable, fall back to the router that serves this
# LAN today. DNS keeps working even with no internet-side resolver.
FALLBACK = [env("ROUTER_IP")]
# Phase 9: PTR for the home LAN must go to the router's dnsmasq, which owns the
# DHCP leases and is the only thing that knows LAN hostnames.
LOCAL_PTR = [env("ROUTER_IP")]

# --- Phase 16: hard anti-open-resolver allowlist ----------------------------------
# Defence in depth on top of interface-scoped port publishing. Even if a port-forward
# were ever created by mistake, a WAN source address is not in this list and is refused.
ALLOWED_CLIENTS = [
    "127.0.0.0/8",        # loopback
    "::1/128",
    env("LAN_SUBNET"),    # home LAN
    "100.64.0.0/10",      # Tailscale CGNAT range
    "fd7a:115c:a1e0::/48",  # Tailscale ULA
    "10.66.66.0/24",      # WireGuard
    "172.16.0.0/12",      # Docker bridges (host-originated queries are SNATed to these)
]

# --- Phase 9: only devices whose address is backed by real evidence ---------------
# Tailscale addresses are permanently assigned per device, so they are safe to pin.
# Phone/tablet LAN addresses come from DHCP and are deliberately NOT pinned — AdGuard's
# rDNS runtime source names them from the router's own lease data, or they stay Unknown.
PERSISTENT_CLIENTS = [
    {"name": "Primary Node",
     "ids": [env("PRIMARY_NODE_IP"), env("PRIMARY_NODE_TAILSCALE_IP")]},
    {"name": "Secondary Node",
     "ids": [env("SECONDARY_NODE_IP"), env("SECONDARY_NODE_TAILSCALE_IP")]},
    {"name": "IP Camera",
     "ids": [env("CAMERA_IP")]},
    {"name": env("PRIMARY_PHONE_NAME"),
     "ids": [env("PRIMARY_PHONE_TAILSCALE_IP")]},
    {"name": env("CLIENT_PHONE_NAME"),
     "ids": [env("CLIENT_PHONE_TAILSCALE_IP")]},
]

CLIENT_DEFAULTS = {
    "tags": [], "use_global_settings": True, "filtering_enabled": False,
    "parental_enabled": False, "safebrowsing_enabled": False,
    "use_global_blocked_services": True,
    "blocked_services": {"schedule": {"time_zone": "Local"}, "ids": []},
    "upstreams": [], "upstreams_cache_enabled": False, "upstreams_cache_size": 0,
    "safe_search": {"enabled": False, "bing": False, "duckduckgo": False, "ecosia": False,
                    "google": False, "pixabay": False, "yandex": False, "youtube": False},
    "ignore_querylog": False, "ignore_statistics": False,
}


def main():
    if not CONF.exists():
        sys.exit(f"missing {CONF} — run the first-launch setup first")
    cfg = yaml.safe_load(CONF.read_text())

    dns = cfg["dns"]
    dns["upstream_dns"] = list(UPSTREAMS)
    dns["bootstrap_dns"] = list(BOOTSTRAP)
    dns["fallback_dns"] = list(FALLBACK)
    dns["local_ptr_upstreams"] = list(LOCAL_PTR)
    dns["use_private_ptr_resolvers"] = True
    dns["upstream_mode"] = "load_balance"
    dns["upstream_timeout"] = "5s"
    dns["allowed_clients"] = list(ALLOWED_CLIENTS)

    # Phase 5: cache on, with a floor so short-TTL ad/CDN records still get reused.
    dns["cache_enabled"] = True
    dns["cache_size"] = 16777216          # 16 MiB
    dns["cache_ttl_min"] = 60
    dns["cache_optimistic"] = False       # never serve a stale answer in v1

    # Phase 16: anti-amplification / privacy. These are AdGuard defaults; pinned so a
    # later UI edit that loosens them shows up as a diff against this file.
    dns["ratelimit"] = 20
    dns["refuse_any"] = True
    dns["enable_dnssec"] = True
    dns["anonymize_client_ip"] = False    # private, admin-only UI; needed for Phase 9
    dns["edns_client_subnet"] = {"custom_ip": "", "enabled": False, "use_custom": False}
    dns["blocked_hosts"] = ["version.bind", "id.server", "hostname.bind"]

    # Phase 11: bounded retention. Query log = 3 days (sensitive, per-client).
    # Statistics = 7 days (aggregate counters only).
    cfg["querylog"].update({"enabled": True, "file_enabled": True,
                            "interval": "72h", "size_memory": 1000})
    cfg["statistics"].update({"enabled": True, "interval": "168h"})

    # Phase 6: start conservative — the default AdGuard DNS filter only. Malware and
    # phishing are covered upstream by Quad9-secured + Cloudflare-security, which have a
    # much lower false-positive rate than community blocklists.
    for f in cfg.get("filters", []):
        f["enabled"] = (f.get("id") == 1)
    cfg["filtering"]["filtering_enabled"] = True
    cfg["filtering"]["protection_enabled"] = True
    cfg["filtering"]["filters_update_interval"] = 24
    # AdGuard's own SafeBrowsing/Parental send domain hashes to AdGuard servers. Off.
    cfg["filtering"]["safebrowsing_enabled"] = False
    cfg["filtering"]["parental_enabled"] = False

    # Phase 9: identify clients from local evidence only. whois() would query public
    # WHOIS servers about client addresses — disabled.
    cfg["clients"]["runtime_sources"] = {"whois": False, "arp": True, "rdns": True,
                                         "dhcp": True, "hosts": True}
    existing = {c["name"]: c for c in cfg["clients"].get("persistent") or []}
    merged = []
    for entry in PERSISTENT_CLIENTS:
        client = dict(CLIENT_DEFAULTS)
        client.update(existing.get(entry["name"], {}))
        client["name"] = entry["name"]
        client["ids"] = entry["ids"]
        merged.append(client)
    cfg["clients"]["persistent"] = merged

    # DHCP server stays off: the router keeps owning DHCP.
    cfg["dhcp"]["enabled"] = False

    backup = CONF.with_suffix(".yaml.pre-configure")
    if not backup.exists():
        shutil.copy2(CONF, backup)
    tmp = CONF.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=120))
    tmp.chmod(0o600)
    tmp.replace(CONF)
    print(f"patched {CONF} (schema_version={cfg['schema_version']})")


if __name__ == "__main__":
    main()
