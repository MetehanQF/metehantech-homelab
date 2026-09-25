#!/usr/bin/env python3
"""Parser/behaviour matrix for AdGuard Home bootstrap hardening candidates.

Every probe goes through POST /control/test_upstream_dns, which validates and
exercises the supplied upstreams and returns a per-address verdict WITHOUT
writing anything to the running configuration. Production config is read once at
the end to prove it never moved.

The bootstrap-independence trick: point bootstrap_dns at 127.0.0.1:59999 inside
the AdGuard container, where nothing listens. The TP-Link interceptor cannot
answer loopback, so any upstream that still succeeds provably did not need a
bootstrap lookup, and any upstream that fails provably did.
"""
import os
import json
import agh
import stamp

DEAD_BOOTSTRAP = ["127.0.0.1:59999"]          # nothing listens here; not interceptable
REAL_BOOTSTRAP = ["9.9.9.9", "149.112.112.112", "1.1.1.1", "1.0.0.1"]

Q9_STAMP   = stamp.encode_doh("9.9.9.9", "dns.quad9.net", "/dns-query")
Q9_STAMP2  = stamp.encode_doh("149.112.112.112", "dns.quad9.net", "/dns-query")
MV_STAMP   = stamp.encode_doh("194.242.2.2", "dns.mullvad.net", "/dns-query")
# deliberately mismatched: Mullvad's IP but Quad9's TLS hostname
MISMATCH   = stamp.encode_doh("194.242.2.2", "dns.quad9.net", "/dns-query")
# unroutable addr, correct hostname: proves `addr` is what gets dialled
TESTNET    = stamp.encode_doh("203.0.113.99", "dns.quad9.net", "/dns-query")

CASES = [
    # (label, upstream, bootstrap, what a PASS proves)
    ("baseline: hostname DoH + real bootstrap",
     "https://dns.quad9.net/dns-query", REAL_BOOTSTRAP,
     "current production shape works"),

    ("CONTROL: hostname DoH + DEAD bootstrap",
     "https://dns.quad9.net/dns-query", DEAD_BOOTSTRAP,
     "must FAIL - proves the dead-bootstrap probe is meaningful"),

    ("B1: bare-IP DoH https://9.9.9.9/dns-query + dead bootstrap",
     "https://9.9.9.9/dns-query", DEAD_BOOTSTRAP,
     "IP upstream needs no bootstrap (cert then verified against the IP)"),

    ("B2: bare-IP DoH https://149.112.112.112/dns-query + dead bootstrap",
     "https://149.112.112.112/dns-query", DEAD_BOOTSTRAP, ""),

    ("B3: bare-IP DoH Mullvad https://194.242.2.2/dns-query + dead bootstrap",
     "https://194.242.2.2/dns-query", DEAD_BOOTSTRAP, ""),

    ("C1: Quad9 STAMP addr=9.9.9.9 host=dns.quad9.net + dead bootstrap",
     Q9_STAMP, DEAD_BOOTSTRAP,
     "stamp dials addr, verifies hostname, no bootstrap needed"),

    ("C2: Quad9 STAMP addr=149.112.112.112 + dead bootstrap",
     Q9_STAMP2, DEAD_BOOTSTRAP, ""),

    ("C3: Mullvad STAMP addr=194.242.2.2 host=dns.mullvad.net + dead bootstrap",
     MV_STAMP, DEAD_BOOTSTRAP, ""),

    ("C4: MISMATCH STAMP addr=194.242.2.2(Mullvad) host=dns.quad9.net",
     MISMATCH, DEAD_BOOTSTRAP,
     "must FAIL on certificate - proves TLS is verified against hostname"),

    ("C5: TEST-NET STAMP addr=203.0.113.99 host=dns.quad9.net",
     TESTNET, DEAD_BOOTSTRAP,
     "must FAIL - proves the stamp really dials addr"),

    ("D1: encrypted bootstrap  bootstrap_dns=[https://dns.quad9.net/dns-query]",
     "https://dns.mullvad.net/dns-query", ["https://dns.quad9.net/dns-query"],
     "does bootstrap_dns accept a DoH URL?"),

    ("D2: encrypted bootstrap  bootstrap_dns=[tls://dns.quad9.net]",
     "https://dns.mullvad.net/dns-query", ["tls://dns.quad9.net"],
     "does bootstrap_dns accept DoT?"),

    ("D3: encrypted bootstrap  bootstrap_dns=[quic://dns.adguard-dns.com]",
     "https://dns.mullvad.net/dns-query", ["quic://dns.adguard-dns.com"], ""),

    ("D4: encrypted bootstrap  bootstrap_dns=[sdns://...quad9]",
     "https://dns.mullvad.net/dns-query", [Q9_STAMP], ""),

    ("D5: bootstrap_dns = IP:port form 9.9.9.9:53",
     "https://dns.mullvad.net/dns-query", ["9.9.9.9:53"], ""),

    ("E1: stamp upstream + EMPTY bootstrap list",
     Q9_STAMP, [],
     "no bootstrap configured at all"),

    ("E2: bare-IP upstream + EMPTY bootstrap list",
     "https://9.9.9.9/dns-query", [], ""),

    ("F1: DoT bare IP tls://9.9.9.9 + dead bootstrap",
     "tls://9.9.9.9", DEAD_BOOTSTRAP, "DoT with IP - cert hostname?"),

    ("F2: DoQ Mullvad quic://dns.mullvad.net + dead bootstrap",
     "quic://dns.mullvad.net", DEAD_BOOTSTRAP, ""),
]


def probe(node, upstream, bootstrap):
    body = {"upstream_dns": [upstream], "bootstrap_dns": bootstrap,
            "fallback_dns": [], "private_upstream": []}
    try:
        res = agh.call(node, "/control/test_upstream_dns", data=body, timeout=90)
    except Exception as e:
        return {"_transport_error": f"{type(e).__name__}: {e}"}
    return res


def main():
    node = "primary"
    print("#" * 100)
    print("AdGuard Home v0.107.79 — bootstrap/upstream parser & behaviour matrix")
    print("All probes via POST /control/test_upstream_dns (read-only: never writes config)")
    print("#" * 100)
    print(f"\nQuad9 stamp   : {Q9_STAMP}")
    print(f"Quad9 stamp 2 : {Q9_STAMP2}")
    print(f"Mullvad stamp : {MV_STAMP}")
    print(f"Mismatch stamp: {MISMATCH}")
    print(f"TEST-NET stamp: {TESTNET}\n")

    results = {}
    for label, upstream, bootstrap, note in CASES:
        res = probe(node, upstream, bootstrap)
        results[label] = res
        print("-" * 100)
        print(f"{label}")
        if note:
            print(f"   beklenti: {note}")
        print(f"   upstream : {upstream[:78]}")
        print(f"   bootstrap: {bootstrap}")
        if "_transport_error" in res:
            print(f"   >>> API HATASI: {res['_transport_error'][:150]}")
            continue
        for addr, verdict in res.items():
            mark = "OK  " if verdict == "OK" else "FAIL"
            print(f"   [{mark}] {addr[:60]}")
            if verdict != "OK":
                print(f"          {str(verdict)[:200]}")
    print("-" * 100)

    print("\n### PRODUCTION CONFIG DEGISMEDI MI? ###")
    for n in ("primary", "secondary"):
        cfg = agh.call(n, "/control/dns_info", timeout=20)
        print(f"  {n}: upstream_dns={cfg.get('upstream_dns')}")
        print(f"       bootstrap_dns={cfg.get('bootstrap_dns')}")
        print(f"       fallback_dns={cfg.get('fallback_dns')}")

    Path = __import__("pathlib").Path
    # Written next to where you run the tool unless RESULTS_DIR says otherwise.
    _out = Path(os.environ.get("RESULTS_DIR", ".")) / "matrix-results.json"
    _out.write_text(json.dumps(results, indent=1))
    print(f"  results -> {_out}")


if __name__ == "__main__":
    main()
