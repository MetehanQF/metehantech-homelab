#!/usr/bin/env python3
"""MetehanTech DNS cluster: health, parity/drift, and safe one-way config sync.

    ./cluster.py health          real DNS queries against both resolvers
    ./cluster.py parity          report configuration drift (read-only)
    ./cluster.py sync            Pi5 -> PcOld, validated + backed up (asks first)
    ./cluster.py sync --yes      same, unattended
    ./cluster.py parity --json   machine-readable, for the Control Center

Design rules this file obeys:
  * Pi5 is the single source of truth. Nothing is ever written back to Pi5.
  * A sync refuses to run if the SOURCE looks unhealthy, so a broken Pi5 can never
    propagate its breakage to the secondary.
  * A sync refuses to push a config that would create a resolver loop.
  * Every sync writes a timestamped backup of the target's previous state first.
  * Host-specific values (bind address, port, admin credentials, TLS, DHCP) are
    never copied.
  * Credentials never appear in output, logs, or exceptions.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adguard
from adguard import Client, AdGuardError, NODES, diff, loop_risks, parity_view
import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment

# Backup location comes from configuration; no machine path is baked in.
BACKUP_ROOT = Path(env("CLUSTER_BACKUP_ROOT"))

# --------------------------------------------------------------- health probing
# A resolver is only "healthy" if it actually resolves AND actually filters.
# Port-open is not health.
HEALTH_PROBES = (
    ("resolve", "example.com", "A", "must return at least one address"),
    ("filter", "doubleclick.net", "A", "must be blocked -> 0.0.0.0"),
    ("dnssec_ok", "cloudflare.com", "A", "must validate -> NOERROR + ad flag"),
    ("dnssec_bad", "dnssec-failed.org", "A", "must reject -> SERVFAIL"),
)


def dig(server, name, rrtype="A", tcp=False, timeout=4, dnssec=False):
    cmd = ["dig", f"+time={timeout}", "+tries=1", f"@{server}", name, rrtype]
    if tcp:
        cmd.insert(1, "+tcp")
    if dnssec:
        cmd.insert(1, "+dnssec")
    started = time.perf_counter()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 4)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": None, "answers": [], "flags": "", "ms": None}
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    out = result.stdout
    status = None
    flags = ""
    answers = []
    for line in out.splitlines():
        if "status:" in line:
            status = line.split("status: ")[1].split(",")[0]
        if line.startswith(";; flags:"):
            flags = line.split("flags:")[1].split(";")[0].strip()
        if line.startswith(name + ".") and f"\t{rrtype}\t" in line:
            answers.append(line.split()[-1])
    return {"status": status, "answers": answers, "flags": flags, "ms": elapsed}


def health(node):
    """Real query health for one resolver. Returns a dict the Control Center can render."""
    spec = NODES[node]
    server = spec["dns"]
    checks = {}

    probe = dig(server, "example.com")
    checks["resolve"] = {"ok": probe["status"] == "NOERROR" and bool(probe["answers"]),
                         "detail": probe["status"], "ms": probe["ms"]}

    probe = dig(server, "doubleclick.net")
    checks["filter"] = {"ok": probe["answers"] == ["0.0.0.0"],
                        "detail": ",".join(probe["answers"]) or probe["status"], "ms": probe["ms"]}

    probe = dig(server, "cloudflare.com", dnssec=True)
    checks["dnssec_valid"] = {"ok": probe["status"] == "NOERROR" and "ad" in probe["flags"].split(),
                              "detail": f"{probe['status']} [{probe['flags']}]", "ms": probe["ms"]}

    probe = dig(server, "dnssec-failed.org")
    checks["dnssec_invalid_rejected"] = {"ok": probe["status"] == "SERVFAIL",
                                         "detail": probe["status"], "ms": probe["ms"]}

    probe = dig(server, "example.com", tcp=True)
    checks["tcp"] = {"ok": probe["status"] == "NOERROR", "detail": probe["status"], "ms": probe["ms"]}

    latencies = [c["ms"] for c in checks.values() if c["ms"] is not None]
    passed = sum(1 for c in checks.values() if c["ok"])
    return {
        "node": node, "label": spec["label"], "role": spec["role"], "address": f"{server}:53",
        "checks": checks,
        "passed": passed, "total": len(checks),
        "healthy": passed == len(checks),
        "degraded": 0 < passed < len(checks),
        "latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
    }


def cluster_health():
    """2/2 HEALTHY · 1/2 DEGRADED (service continues) · 0/2 CRITICAL."""
    members = {node: health(node) for node in NODES}
    up = sum(1 for m in members.values() if m["healthy"])
    partial = sum(1 for m in members.values() if m["degraded"])
    if up == len(NODES):
        state = "HEALTHY"
    elif up >= 1:
        state = "DEGRADED"
    elif partial:
        state = "DEGRADED"
    else:
        state = "CRITICAL"
    return {"state": state, "healthy_members": up, "total_members": len(NODES),
            "members": members, "checked_at": datetime.now(timezone.utc).isoformat()}


# ------------------------------------------------------------- parity and drift
def parity():
    result = {"source": "primary", "target": "secondary", "checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        source = Client("primary").snapshot()
        result["source_reachable"] = True
    except AdGuardError as error:
        result["source_reachable"] = False
        result["error"] = str(error)
        return result
    try:
        target = Client("secondary").snapshot()
        result["target_reachable"] = True
    except AdGuardError as error:
        result["target_reachable"] = False
        result["error"] = str(error)
        result["in_sync"] = None
        return result
    differences = diff(parity_view(source), parity_view(target))
    result["in_sync"] = not differences
    result["drift_count"] = len(differences)
    result["drift"] = [{"key": k, "primary": a, "secondary": b} for k, a, b in differences]
    result["versions"] = {"primary": source.get("version"), "secondary": target.get("version")}
    result["loop_risks"] = {"primary": loop_risks(source["dns"]), "secondary": loop_risks(target["dns"])}
    return result


# ------------------------------------------------------------------- safe sync
def _source_is_trustworthy(source_snapshot, source_health):
    """Never propagate from a source we cannot vouch for."""
    reasons = []
    if not source_snapshot.get("running"):
        reasons.append("Pi5 AdGuard reports running=false")
    if source_snapshot.get("protection_enabled") is False:
        reasons.append("Pi5 protection is disabled — refusing to copy an unprotected config")
    if not source_health["healthy"]:
        failed = [k for k, v in source_health["checks"].items() if not v["ok"]]
        reasons.append("Pi5 failed its own health probes: " + ", ".join(failed))
    filters = (source_snapshot.get("filtering") or {}).get("filters") or []
    if not any(f.get("enabled") for f in filters):
        reasons.append("Pi5 has no enabled filter list")
    risks = loop_risks(source_snapshot["dns"])
    if risks:
        reasons.extend("Pi5 config: " + r for r in risks)
    return reasons


def sync(assume_yes=False, dry_run=False):
    print("MetehanTech DNS cluster — safe one-way sync  (Pi5 → PcOld)\n")
    try:
        source_client, target_client = Client("primary"), Client("secondary")
        source = source_client.snapshot()
    except AdGuardError as error:
        print(f"  ABORT: {error}")
        return 2
    source_health = health("primary")

    print(f"  source   Pi5   {source.get('version')}  health "
          f"{source_health['passed']}/{source_health['total']}")
    blockers = _source_is_trustworthy(source, source_health)
    if blockers:
        print("\n  ABORT — the source is not in a state worth propagating:")
        for reason in blockers:
            print(f"    · {reason}")
        print("\n  Fix Pi5 first. The secondary has been left exactly as it was.")
        return 3

    try:
        target = target_client.snapshot()
    except AdGuardError as error:
        print(f"  ABORT: {error}")
        return 2
    target_health = health("secondary")
    print(f"  target   PcOld {target.get('version')}  health "
          f"{target_health['passed']}/{target_health['total']}")

    differences = diff(parity_view(source), parity_view(target))
    if not differences:
        print("\n  Already in sync — nothing to do.")
        return 0

    print(f"\n  {len(differences)} setting(s) differ:")
    for key, a, b in differences:
        print(f"    {key}")
        print(f"        Pi5   : {_short(a)}")
        print(f"        PcOld : {_short(b)}")

    # What we are about to write, with host-specific values preserved from the target.
    payload = _build_payload(source, target)
    risks = loop_risks(payload["dns_config"])
    if risks:
        print("\n  ABORT — the resulting config would create a resolver loop:")
        for risk in risks:
            print(f"    · {risk}")
        return 4

    if dry_run:
        print("\n  --dry-run: nothing written.")
        return 0
    if not assume_yes:
        answer = input("\n  Apply these to PcOld? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("  Cancelled. PcOld unchanged.")
            return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = BACKUP_ROOT / f"{stamp}-dns-sync-pcold"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "pcold-before.json"
    backup.write_text(json.dumps(target, indent=2, sort_keys=True))
    backup.chmod(0o600)
    print(f"\n  backup written: {backup}")

    applied, failed = [], []
    for label, path, body, method in _apply_plan(payload):
        try:
            target_client.call(path, data=body, method=method, timeout=20)
            applied.append(label)
            print(f"    ok      {label}")
        except AdGuardError as error:
            failed.append((label, str(error)))
            print(f"    FAILED  {label}: {error}")

    print(f"\n  applied {len(applied)}, failed {len(failed)}")
    after = Client("secondary").snapshot()
    remaining = diff(parity_view(source), parity_view(after))
    post_health = health("secondary")
    print(f"  post-sync drift : {len(remaining)}")
    print(f"  post-sync health: {post_health['passed']}/{post_health['total']}"
          f"  ({'HEALTHY' if post_health['healthy'] else 'CHECK THIS'})")
    if remaining:
        for key, a, b in remaining:
            print(f"    still differs: {key}  Pi5={_short(a)}  PcOld={_short(b)}")
    if failed or not post_health["healthy"]:
        print(f"\n  Restore the previous state from {backup} if needed.")
        return 5
    return 0


def _short(value, width=90):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= width else text[:width - 1] + "…"


def _build_payload(source, target):
    """Source values for everything syncable; target values for host-specific ones."""
    source_dns = dict(source["dns"])
    target_dns = target["dns"]
    dns_config = {k: source_dns[k] for k in adguard.DNS_PARITY_KEYS if k in source_dns}
    # never move the secondary's listener or its protection switch
    for key in adguard.DNS_HOST_KEYS:
        if key in target_dns:
            dns_config[key] = target_dns[key]
    return {
        "dns_config": dns_config,
        "filters": source["filtering"],
        "clients": source["clients"],
        "querylog": source["querylog"],
        "stats": source["stats"],
        "access": source["access"],
        "safebrowsing": source["safebrowsing"],
        "parental": source["parental"],
        "target_clients": target["clients"],
        "target_filters": target["filtering"],
    }


def _apply_plan(payload):
    """(label, api_path, body, method) tuples, ordered so a partial failure stays coherent.

    Everything here is driven by what the target already has, so a re-run is a no-op
    rather than a pile of 400s. AdGuard's own API quirks that this works around:
      * add_url rejects a URL the node already carries (HTTP 400)
      * querylog/stats config are PUT, not POST
    """
    plan = [("dns settings", "/control/dns_config", payload["dns_config"], None)]

    filtering = payload["filters"]
    plan.append(("filtering on/off + update interval", "/control/filtering/config",
                 {"enabled": filtering.get("enabled", True),
                  "interval": filtering.get("interval", 24)}, None))
    plan.append(("user rules", "/control/filtering/set_rules",
                 {"rules": list(filtering.get("user_rules") or [])}, None))

    target_filtering = payload["target_filters"]
    for whitelist, key in ((False, "filters"), (True, "whitelist_filters")):
        kind = "allowlist" if whitelist else "blocklist"
        present = {f.get("url"): f for f in (target_filtering.get(key) or [])}
        wanted = {f.get("url"): f for f in (filtering.get(key) or [])}
        for url, entry in wanted.items():
            if url not in present:
                plan.append((f"{kind} + {entry.get('name')}", "/control/filtering/add_url",
                             {"name": entry.get("name"), "url": url, "whitelist": whitelist}, None))
            plan.append((f"{kind} {entry.get('name')} enabled={bool(entry.get('enabled'))}",
                         "/control/filtering/set_url",
                         {"url": url, "whitelist": whitelist,
                          "data": {"name": entry.get("name"), "url": url,
                                   "enabled": bool(entry.get("enabled"))}}, None))
        # True parity means the secondary must not carry lists the primary dropped.
        for url, entry in present.items():
            if url not in wanted:
                plan.append((f"{kind} - {entry.get('name')}", "/control/filtering/remove_url",
                             {"url": url, "whitelist": whitelist}, None))

    plan.append(("query log settings", "/control/querylog/config/update",
                 payload["querylog"], "PUT"))
    plan.append(("statistics settings", "/control/stats/config/update",
                 payload["stats"], "PUT"))
    plan.append(("access list", "/control/access/set",
                 {"allowed_clients": payload["access"].get("allowed_clients") or [],
                  "disallowed_clients": payload["access"].get("disallowed_clients") or [],
                  "blocked_hosts": payload["access"].get("blocked_hosts") or []}, None))
    plan.append(("safebrowsing", "/control/safebrowsing/"
                 + ("enable" if payload["safebrowsing"].get("enabled") else "disable"), {}, None))
    plan.append(("parental", "/control/parental/"
                 + ("enable" if payload["parental"].get("enabled") else "disable"), {}, None))

    existing = {c.get("name") for c in (payload["target_clients"].get("clients") or [])}
    for client in payload["clients"].get("clients") or []:
        name = client.get("name")
        body = {"name": name, "data": client} if name in existing else client
        path = "/control/clients/update" if name in existing else "/control/clients/add"
        plan.append((f"client {name}", path, body, None))
    return plan


# ------------------------------------------------------------------------- cli
def main():
    parser = argparse.ArgumentParser(description="MetehanTech DNS cluster tooling")
    parser.add_argument("command", choices=("health", "parity", "sync"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--yes", action="store_true", help="unattended sync")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.command == "health":
        data = cluster_health()
        if args.json:
            print(json.dumps(data, indent=2))
            return 0
        print(f"DNS Cluster: {data['state']}  ({data['healthy_members']}/{data['total_members']} healthy)\n")
        for member in data["members"].values():
            mark = "HEALTHY" if member["healthy"] else "DEGRADED" if member["degraded"] else "DOWN"
            print(f"  {member['label']:<16} {member['address']:<20} {mark:<9} "
                  f"{member['passed']}/{member['total']} checks  avg {member['latency_ms']} ms")
            for name, check in member["checks"].items():
                print(f"      {'PASS' if check['ok'] else 'FAIL'}  {name:<26} {check['detail']}  {check['ms']} ms")
        return 0 if data["state"] != "CRITICAL" else 1

    if args.command == "parity":
        data = parity()
        if args.json:
            print(json.dumps(data, indent=2, default=str))
            return 0
        if not data.get("source_reachable"):
            print("Pi5 unreachable:", data.get("error"))
            return 2
        if not data.get("target_reachable"):
            print("PcOld unreachable:", data.get("error"))
            print("(expected until the secondary is deployed)")
            return 2
        print(f"versions  Pi5 {data['versions']['primary']}   PcOld {data['versions']['secondary']}")
        for node, risks in data["loop_risks"].items():
            print(f"loop risk {node}: {risks or 'none'}")
        if data["in_sync"]:
            print("\nCONFIG PARITY: IN SYNC")
            return 0
        print(f"\nCONFIG DRIFT: {data['drift_count']} setting(s) differ")
        for row in data["drift"]:
            print(f"  {row['key']}\n      Pi5   : {_short(row['primary'])}\n      PcOld : {_short(row['secondary'])}")
        return 1

    return sync(assume_yes=args.yes, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
