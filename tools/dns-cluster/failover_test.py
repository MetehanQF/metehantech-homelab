#!/usr/bin/env python3
"""Phase 8/9 — failover behaviour of a two-AdGuard cluster.

Because the two resolvers are now in parity they return identical answers, so the
client's reply cannot tell us which one served it. Attribution therefore comes from
each AdGuard's own query log: we mark every probe with a unique label and then ask
both nodes which labels they saw.

Test clients are throwaway containers. Production config is never modified; the only
production action is stopping/starting the Pi5 AdGuard container for tests D and E,
which is safe today because nothing on the network uses it for DNS yet (DHCP still
hands out the router).
"""
import os
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adguard import Client, AdGuardError
import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment

PRIMARY = env("PRIMARY_NODE_IP")
# Defaults to a throwaway staging instance; override to test the real secondary.
SECONDARY = os.environ.get("FAILOVER_SECONDARY", "172.17.0.2")
DEAD = "192.0.2.99"               # RFC 5737 documentation address: nothing listens
# Wildcard resolver: every unique label still returns a real answer, so a probe
# failure means "no resolver replied", not "that name does not exist".
PROBE_DOMAIN = "10.0.0.1.nip.io"


def run(cmd, timeout=180):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe(dns_servers, count=20, image="debian:bookworm-slim", label=None):
    """Resolve `count` unique names from a throwaway container; return timing + tag."""
    tag = label or secrets.token_hex(4)
    args = []
    for server in dns_servers:
        args += ["--dns", server]
    script = (
        f'ok=0; fail=0; t0=$(date +%s%N); '
        f'for i in $(seq 1 {count}); do '
        f'  if getent ahostsv4 mt-{tag}-$i.{PROBE_DOMAIN} >/dev/null 2>&1; then ok=$((ok+1)); else fail=$((fail+1)); fi; '
        f'done; t1=$(date +%s%N); '
        f'echo "RESULT ok=$ok fail=$fail ms=$(( (t1-t0)/1000000 ))"'
    )
    result = run(["docker", "run", "--rm", "--network", "bridge", *args, image, "sh", "-c", script])
    line = next((l for l in result.stdout.splitlines() if l.startswith("RESULT")), "RESULT ok=0 fail=0 ms=0")
    fields = dict(part.split("=") for part in line.split()[1:])
    total_ms = int(fields["ms"])
    return {"tag": tag, "ok": int(fields["ok"]), "fail": int(fields["fail"]),
            "total_ms": total_ms, "per_lookup_ms": round(total_ms / max(1, count), 1),
            "count": count}


def seen_by(node, tag, limit=500):
    """How many of the tagged probes reached this node, per its own query log."""
    try:
        client = Client(node)
        data = client.call(f"/control/querylog?limit={limit}", timeout=20)
    except AdGuardError:
        return None
    return sum(1 for row in (data.get("data") or [])
               if tag in ((row.get("question") or {}).get("name") or ""))


def attribute(result):
    a = seen_by("primary", result["tag"])
    b = seen_by("secondary", result["tag"])
    return a, b


def container(action, name="metehantech-adguard"):
    run(["docker", action, name], timeout=120)
    time.sleep(6 if action == "start" else 3)


def wait_healthy(name="metehantech-adguard", seconds=90):
    for _ in range(seconds // 2):
        out = run(["docker", "inspect", name, "--format",
                   "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"]).stdout.strip()
        if out == "healthy":
            return True
        time.sleep(2)
    return False


def report(title, result, note=""):
    a, b = attribute(result)
    print(f"  {title}")
    print(f"      resolved {result['ok']}/{result['count']}   failed {result['fail']}   "
          f"{result['per_lookup_ms']} ms per lookup")
    print(f"      served by  primary(Pi5)={a}   secondary={b}")
    if note:
        print(f"      {note}")
    print()
    return {"title": title, **result, "primary_served": a, "secondary_served": b}


def main():
    results = []
    print("=" * 78)
    print("Phase 8/9 — cluster failover behaviour   (glibc client, DNS1=primary DNS2=secondary)")
    print("=" * 78 + "\n")

    print("TEST A — both resolvers healthy")
    results.append(report("A: both up", probe([PRIMARY, SECONDARY], 20),
                          "glibc is sequential: the primary should take essentially all of it"))

    print("TEST B — primary unavailable (silent black hole as DNS1)")
    results.append(report("B: primary silent", probe([DEAD, SECONDARY], 20),
                          "secondary must carry 100% — this is the Pi5-is-off case"))

    print("TEST C — secondary unavailable (silent black hole as DNS2)")
    results.append(report("C: secondary silent", probe([PRIMARY, DEAD], 20),
                          "primary must carry 100%, with no latency penalty"))

    print("TEST D — primary AdGuard container stopped (real outage)")
    container("stop")
    time.sleep(2)
    results.append(report("D: primary container down", probe([PRIMARY, SECONDARY], 20),
                          "connection-refused is faster to detect than a silent host"))
    container("start")
    healthy = wait_healthy()
    print(f"      primary restarted, healthy={healthy}\n")

    print("TEST E — secondary AdGuard container stopped")
    container("stop", "metehantech-adguard-staging")
    time.sleep(2)
    results.append(report("E: secondary container down", probe([PRIMARY, SECONDARY], 20),
                          "primary unaffected"))
    container("start", "metehantech-adguard-staging")
    time.sleep(8)

    print("TEST G/H — secondary's upstreams unreachable (SERVFAIL source)")
    secondary = Client("secondary")
    good = secondary.call("/control/dns_info")
    broken = {k: good[k] for k in ("upstream_dns", "bootstrap_dns", "fallback_dns",
                                   "local_ptr_upstreams", "upstream_mode") if k in good}
    broken["upstream_dns"] = ["192.0.2.53"]      # TEST-NET, unreachable
    broken["fallback_dns"] = []                   # no rescue path: force SERVFAIL
    secondary.call("/control/dns_config", data=broken)
    time.sleep(3)
    direct = run(["dig", "+time=5", "+tries=1", f"@{SECONDARY}", "kernel.org", "A"]).stdout
    status = next((l.split("status: ")[1].split(",")[0] for l in direct.splitlines() if "status:" in l), "?")
    print(f"      secondary queried directly -> {status}  (expected SERVFAIL)")
    results.append(report("G/H: secondary upstream dead, client uses both",
                          probe([PRIMARY, SECONDARY], 20),
                          "primary still healthy, so the client never notices"))
    results.append(report("G/H: secondary ONLY (worst case for a client that picked it)",
                          probe([SECONDARY], 10),
                          "a SERVFAIL resolver does NOT fail over inside the client"))
    restore = {k: good[k] for k in ("upstream_dns", "bootstrap_dns", "fallback_dns",
                                    "local_ptr_upstreams", "upstream_mode") if k in good}
    secondary.call("/control/dns_config", data=restore)
    time.sleep(3)
    direct = run(["dig", "+short", "+time=5", f"@{SECONDARY}", "kernel.org", "A"]).stdout.strip()
    print(f"      secondary restored -> kernel.org = {direct.splitlines()[0] if direct else 'FAILED'}\n")

    print("TEST F — both resolvers down (Phase 9, the accepted trade-off)")
    results.append(report("F: both down", probe([DEAD, "192.0.2.98"], 6),
                          "no third fallback by design — DNS stops, as agreed"))

    Path(os.environ.get("RESULTS_DIR", ".")) / "failover-results.json".write_text(
        json.dumps(results, indent=2))
    print("=" * 78)
    print("summary")
    for r in results:
        print(f"  {r['title']:<48} resolved {r['ok']}/{r['count']:<3} "
              f"{r['per_lookup_ms']:>7} ms/lookup   pri={r['primary_served']} sec={r['secondary_served']}")
    print("=" * 78)


if __name__ == "__main__":
    main()
