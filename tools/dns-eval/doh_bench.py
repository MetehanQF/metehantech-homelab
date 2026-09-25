#!/usr/bin/env python3
"""Read-only DoH evaluation: Mullvad vanilla vs Quad9.

Sends real RFC 8484 DNS-over-HTTPS queries. Changes nothing on the host:
no config writes, no service calls, no trust-store access beyond normal
certificate verification.
"""
import base64, http.client, json, random, socket, ssl, statistics, struct, sys, time

TIMEOUT = 5.0

RESOLVERS = {
    "mullvad": {"host": "dns.mullvad.net", "path": "/dns-query"},
    "quad9":   {"host": "dns.quad9.net",   "path": "/dns-query"},
}

FUNCTIONAL = ["example.com", "google.com", "github.com", "cloudflare.com"]


# ---------------------------------------------------------------- wireformat
def build_query(name, qtype=1, dnssec_ok=False, qid=0):
    arcount = 1 if dnssec_ok else 0
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, arcount)
    qname = b"".join(
        bytes([len(p)]) + p.encode("ascii") for p in name.rstrip(".").split(".")
    ) + b"\x00"
    packet = header + qname + struct.pack(">HH", qtype, 1)
    if dnssec_ok:
        # root name, TYPE=OPT(41), UDP size 4096, DO bit set in the TTL field
        packet += b"\x00" + struct.pack(">HHIH", 41, 4096, 0x00008000, 0)
    return packet


def parse_response(data):
    if len(data) < 12:
        return {"ok": False, "error": "short response"}
    qid, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    return {
        "ok": True,
        "rcode": flags & 0x0F,
        "ad": bool((flags >> 5) & 1),
        "answers": an,
    }


RCODE = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}


# ---------------------------------------------------------------- transport
def peer_cn(conn):
    try:
        cert = conn.sock.getpeercert()
        for rdn in cert.get("subject", ()):
            for key, value in rdn:
                if key == "commonName":
                    return value
    except Exception:
        pass
    return "?"


def open_conn(resolver):
    ctx = ssl.create_default_context()          # full verification, no bypass
    conn = http.client.HTTPSConnection(
        RESOLVERS[resolver]["host"], 443, timeout=TIMEOUT, context=ctx)
    conn.connect()
    return conn


def doh_query(conn, resolver, name, qtype=1, dnssec_ok=False):
    """One query on an already-open connection. Returns (elapsed_ms, result)."""
    q = build_query(name, qtype, dnssec_ok)
    b64 = base64.urlsafe_b64encode(q).decode().rstrip("=")
    path = f"{RESOLVERS[resolver]['path']}?dns={b64}"
    start = time.perf_counter()
    try:
        conn.request("GET", path, headers={
            "accept": "application/dns-message",
            "host": RESOLVERS[resolver]["host"],
        })
        resp = conn.getresponse()
        body = resp.read()
        elapsed = (time.perf_counter() - start) * 1000
        if resp.status != 200:
            return elapsed, {"ok": False, "error": f"HTTP {resp.status}"}
        out = parse_response(body)
        out["http"] = resp.status
        return elapsed, out
    except socket.timeout:
        return (time.perf_counter() - start) * 1000, {"ok": False, "error": "timeout"}
    except ssl.SSLError as e:
        return (time.perf_counter() - start) * 1000, {"ok": False, "error": f"tls: {e}"}
    except Exception as e:
        return (time.perf_counter() - start) * 1000, {
            "ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- statistics
def summarize(samples):
    if not samples:
        return None
    s = sorted(samples)
    return {
        "n": len(s),
        "min": round(s[0], 2),
        "avg": round(statistics.fmean(s), 2),
        "p50": round(statistics.median(s), 2),
        "p95": round(s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))], 2),
        "max": round(s[-1], 2),
    }


# ---------------------------------------------------------------- test phases
def functional(report):
    out = {}
    for r in RESOLVERS:
        rows = []
        try:
            conn = open_conn(r)
            pop = peer_cn(conn)
            for d in FUNCTIONAL:
                ms, res = doh_query(conn, r, d)
                rows.append({
                    "domain": d, "ms": round(ms, 1),
                    "rcode": RCODE.get(res.get("rcode"), res.get("error")),
                    "answers": res.get("answers"),
                })
            conn.close()
        except Exception as e:
            rows.append({"error": f"{type(e).__name__}: {e}"})
            pop = "?"
        out[r] = {"pop": pop, "rows": rows}
    report["functional"] = out


def warm_benchmark(report, count=50):
    """Persistent/reused connection, resolvers alternated query by query."""
    conns, pops, lat, fail, tmo, errs = {}, {}, {}, {}, {}, {}
    for r in RESOLVERS:
        lat[r], fail[r], tmo[r], errs[r] = [], 0, 0, []
        try:
            conns[r] = open_conn(r)
            pops[r] = peer_cn(conns[r])
        except Exception as e:
            conns[r] = None
            pops[r] = "?"
            errs[r].append(f"connect: {type(e).__name__}: {e}")

    order = list(RESOLVERS)
    for i in range(count):
        random.shuffle(order)               # alternate, and de-bias ordering
        for r in order:
            if conns[r] is None:
                fail[r] += 1
                continue
            domain = FUNCTIONAL[i % len(FUNCTIONAL)]
            ms, res = doh_query(conns[r], r, domain)
            if res.get("ok") and res.get("rcode") == 0:
                lat[r].append(ms)
            else:
                fail[r] += 1
                err = res.get("error", f"rcode={res.get('rcode')}")
                errs[r].append(err)
                if "timeout" in str(err):
                    tmo[r] += 1
                try:                          # reconnect so one error is not fatal
                    conns[r].close()
                    conns[r] = open_conn(r)
                except Exception as e2:
                    conns[r] = None
                    errs[r].append(f"reconnect: {type(e2).__name__}: {e2}")
            time.sleep(0.03)

    for r in RESOLVERS:
        if conns.get(r):
            try:
                conns[r].close()
            except Exception:
                pass

    report["warm"] = {
        r: {
            "pop": pops.get(r),
            "attempts": count,
            "success": len(lat[r]),
            "failures": fail[r],
            "timeouts": tmo[r],
            "tls_errors": sum(1 for e in errs[r] if e.startswith("tls:")),
            "http_errors": sum(1 for e in errs[r] if e.startswith("HTTP ")),
            "error_samples": errs[r][:5],
            "latency": summarize(lat[r]),
        } for r in RESOLVERS
    }


def cold_benchmark(report, count=12):
    """Fresh TCP+TLS handshake per query: connection-setup cost included."""
    lat, hs, fail, pops = {}, {}, {}, {}
    for r in RESOLVERS:
        lat[r], hs[r], fail[r], pops[r] = [], [], 0, set()

    order = list(RESOLVERS)
    for i in range(count):
        random.shuffle(order)
        for r in order:
            t0 = time.perf_counter()
            try:
                conn = open_conn(r)
                handshake = (time.perf_counter() - t0) * 1000
                pops[r].add(peer_cn(conn))
                ms, res = doh_query(conn, r, FUNCTIONAL[i % len(FUNCTIONAL)])
                conn.close()
                if res.get("ok") and res.get("rcode") == 0:
                    hs[r].append(handshake)
                    lat[r].append(handshake + ms)
                else:
                    fail[r] += 1
            except Exception:
                fail[r] += 1
            time.sleep(0.05)

    report["cold"] = {
        r: {
            "attempts": count,
            "success": len(lat[r]),
            "failures": fail[r],
            "pops_seen": sorted(pops[r]),
            "handshake_ms": summarize(hs[r]),
            "total_ms": summarize(lat[r]),
        } for r in RESOLVERS
    }


DNSSEC_CASES = [
    ("sigok.verteiltesysteme.net",   "valid",  "Uni Duisburg-Essen DNSSEC test (signed, valid)"),
    ("dnssec-failed.org",            "bogus",  "Comcast/NANOG DNSSEC test (deliberately broken signature)"),
    ("sigfail.verteiltesysteme.net", "bogus",  "Uni Duisburg-Essen DNSSEC test (deliberately broken signature)"),
    ("example.com",                  "valid",  "IANA reference domain (signed)"),
]


def dnssec(report):
    out = {}
    for r in RESOLVERS:
        rows = []
        for domain, expect, source in DNSSEC_CASES:
            try:
                conn = open_conn(r)
                ms, res = doh_query(conn, r, domain, dnssec_ok=True)
                conn.close()
            except Exception as e:
                rows.append({"domain": domain, "expect": expect,
                             "error": f"{type(e).__name__}: {e}"})
                continue
            rcode = res.get("rcode")
            name = RCODE.get(rcode, str(rcode))
            if expect == "valid":
                verdict = "PASS" if rcode == 0 and res.get("answers", 0) > 0 else "FAIL"
                verdict += " (AD set)" if res.get("ad") else " (AD NOT set)"
            else:
                verdict = "PASS" if rcode == 2 else "FAIL"
            rows.append({"domain": domain, "expect": expect, "source": source,
                         "rcode": name, "ad": res.get("ad"),
                         "answers": res.get("answers"), "ms": round(ms, 1),
                         "verdict": verdict})
        out[r] = rows
    report["dnssec"] = out


def main():
    random.seed()
    report = {"host": socket.gethostname(), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    functional(report)
    warm_benchmark(report, count=int(sys.argv[1]) if len(sys.argv) > 1 else 50)
    cold_benchmark(report, count=int(sys.argv[2]) if len(sys.argv) > 2 else 12)
    dnssec(report)
    report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
