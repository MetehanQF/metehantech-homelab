#!/usr/bin/env python3
"""Read-only DoH evaluation: Mullvad vanilla vs Quad9, over HTTP/2.

Both resolvers reject HTTP/1.1 (Quad9 answers 505, Mullvad speaks raw h2),
so every request here goes through curl with --http2 and full certificate
verification (never -k). Nothing on the host is modified.
"""
import base64, json, os, random, shutil, statistics, struct, subprocess, sys, tempfile, time

RESOLVERS = {"mullvad": "dns.mullvad.net", "quad9": "dns.quad9.net"}
FUNCTIONAL = ["example.com", "google.com", "github.com", "cloudflare.com"]
TIMEOUT = 5
RCODE = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}

WRITEOUT = ("CURLSTAT %{url_effective} code=%{http_code} ver=%{http_version} "
            "conns=%{num_connects} ip=%{remote_ip} appconnect=%{time_appconnect} "
            "connect=%{time_connect} start=%{time_starttransfer} total=%{time_total}\\n")


def build_query(name, qtype=1, dnssec_ok=False):
    arcount = 1 if dnssec_ok else 0
    header = struct.pack(">HHHHHH", 0, 0x0100, 1, 0, 0, arcount)
    qname = b"".join(bytes([len(p)]) + p.encode("ascii")
                     for p in name.rstrip(".").split(".")) + b"\x00"
    packet = header + qname + struct.pack(">HH", qtype, 1)
    if dnssec_ok:
        packet += b"\x00" + struct.pack(">HHIH", 41, 4096, 0x00008000, 0)
    return base64.urlsafe_b64encode(packet).decode().rstrip("=")


def parse(path):
    try:
        data = open(path, "rb").read()
    except OSError:
        return {"ok": False, "error": "no body"}
    if len(data) < 12:
        return {"ok": False, "error": f"short body ({len(data)}B)"}
    _, flags, _, an, _, _ = struct.unpack(">HHHHHH", data[:12])
    return {"ok": True, "rcode": flags & 0x0F, "ad": bool((flags >> 5) & 1),
            "answers": an, "bytes": len(data)}


def run_curl(jobs, workdir):
    """jobs: list of (tag, url). One curl process; connections are pooled and
    reused per host, so interleaved tags exercise true persistent reuse."""
    cfg = os.path.join(workdir, "curl.cfg")
    with open(cfg, "w") as fh:
        for i, (tag, url) in enumerate(jobs):
            fh.write(f'url = "{url}"\noutput = "{workdir}/{i:04d}_{tag}.bin"\n')
    proc = subprocess.run(
        ["curl", "-4", "--http2", "-sS", "--max-time", str(TIMEOUT),
         "-H", "accept: application/dns-message", "-w", WRITEOUT, "-K", cfg],
        capture_output=True, text=True, timeout=TIMEOUT * len(jobs) + 60)
    rows = []
    idx = 0
    for line in proc.stdout.splitlines():
        if not line.startswith("CURLSTAT "):
            continue
        fields = {}
        for part in line[9:].split():
            if "=" in part:
                k, v = part.split("=", 1)
                fields[k] = v
        tag = jobs[idx][0]
        body = parse(os.path.join(workdir, f"{idx:04d}_{tag}.bin"))
        fields["tag"] = tag
        fields["body"] = body
        rows.append(fields)
        idx += 1
    return rows, proc.stderr


def ms(v):
    try:
        return float(v) * 1000
    except (TypeError, ValueError):
        return None


def summarize(samples):
    if not samples:
        return None
    s = sorted(samples)
    return {"n": len(s), "min": round(s[0], 1), "avg": round(statistics.fmean(s), 1),
            "p50": round(statistics.median(s), 1),
            "p95": round(s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))], 1),
            "max": round(s[-1], 1)}


def classify(row):
    """A query counts as successful only with HTTP 200 and a NOERROR body."""
    code = row.get("code")
    body = row.get("body", {})
    if code == "200" and body.get("ok") and body.get("rcode") == 0 and body.get("answers", 0) > 0:
        return "ok", None
    if code == "000":
        return "fail", "transport/timeout"
    if code != "200":
        return "fail", f"HTTP {code}"
    return "fail", f"rcode={RCODE.get(body.get('rcode'), body.get('error'))}"


def functional(report, workdir):
    jobs = [(r, f"https://{h}/dns-query?dns={build_query(d)}")
            for d in FUNCTIONAL for r, h in RESOLVERS.items()]
    rows, err = run_curl(jobs, workdir)
    out = {r: [] for r in RESOLVERS}
    for row, (tag, _) in zip(rows, jobs):
        body = row.get("body", {})
        domain = FUNCTIONAL[jobs.index((tag, _)) // len(RESOLVERS)]
        out[tag].append({"domain": domain, "http": row.get("code"),
                         "http_version": row.get("ver"), "ip": row.get("ip"),
                         "rcode": RCODE.get(body.get("rcode"), body.get("error")),
                         "answers": body.get("answers"),
                         "ms": round(ms(row.get("total")) or 0, 1)})
    report["functional"] = out
    if err.strip():
        report.setdefault("stderr", {})["functional"] = err.strip()[:400]


def warm(report, workdir, count):
    """Interleaved resolvers in one curl run: connection per host is reused."""
    jobs = []
    for i in range(count):
        order = list(RESOLVERS)
        random.shuffle(order)
        for r in order:
            jobs.append((r, f"https://{RESOLVERS[r]}/dns-query?"
                            f"dns={build_query(FUNCTIONAL[i % len(FUNCTIONAL)])}"))
    rows, err = run_curl(jobs, workdir)
    agg = {r: {"lat": [], "ok": 0, "fail": 0, "timeout": 0, "tls": 0,
               "http_err": 0, "reused": 0, "new_conn": 0, "errs": []}
           for r in RESOLVERS}
    for row in rows:
        r = row["tag"]
        a = agg[r]
        verdict, reason = classify(row)
        if row.get("conns") == "0":
            a["reused"] += 1
        else:
            a["new_conn"] += 1
        if verdict == "ok":
            a["ok"] += 1
            a["lat"].append(ms(row.get("start")))
        else:
            a["fail"] += 1
            a["errs"].append(reason)
            if reason == "transport/timeout":
                a["timeout"] += 1
            elif reason and reason.startswith("HTTP"):
                a["http_err"] += 1
    report["warm"] = {
        r: {"attempts": count, "success": a["ok"], "failures": a["fail"],
            "timeouts": a["timeout"], "tls_errors": a["tls"],
            "http_errors": a["http_err"], "reused_conn": a["reused"],
            "new_conn": a["new_conn"],
            "error_samples": a["errs"][:5],
            "latency_ms": summarize([x for x in a["lat"] if x is not None])}
        for r, a in agg.items()}
    if err.strip():
        report.setdefault("stderr", {})["warm"] = err.strip()[:400]


def cold(report, workdir, count):
    """Separate curl process per query: full TCP+TLS handshake every time."""
    agg = {r: {"hs": [], "tot": [], "ok": 0, "fail": 0, "ips": set()} for r in RESOLVERS}
    for i in range(count):
        order = list(RESOLVERS)
        random.shuffle(order)
        for r in order:
            d = os.path.join(workdir, f"cold{i}_{r}")
            os.makedirs(d, exist_ok=True)
            rows, _ = run_curl(
                [(r, f"https://{RESOLVERS[r]}/dns-query?"
                     f"dns={build_query(FUNCTIONAL[i % len(FUNCTIONAL)])}")], d)
            if not rows:
                agg[r]["fail"] += 1
                continue
            row = rows[0]
            agg[r]["ips"].add(row.get("ip", "?"))
            verdict, _ = classify(row)
            if verdict == "ok":
                agg[r]["ok"] += 1
                agg[r]["hs"].append(ms(row.get("appconnect")))
                agg[r]["tot"].append(ms(row.get("total")))
            else:
                agg[r]["fail"] += 1
            time.sleep(0.05)
    report["cold"] = {
        r: {"attempts": count, "success": a["ok"], "failures": a["fail"],
            "ips_seen": sorted(a["ips"]),
            "handshake_ms": summarize([x for x in a["hs"] if x is not None]),
            "total_ms": summarize([x for x in a["tot"] if x is not None])}
        for r, a in agg.items()}


DNSSEC_CASES = [
    ("sigok.verteiltesysteme.net", "valid",
     "Uni Duisburg-Essen DNSSEC testbed - correctly signed"),
    ("sigfail.verteiltesysteme.net", "bogus",
     "Uni Duisburg-Essen DNSSEC testbed - deliberately broken signature"),
    ("dnssec-failed.org", "bogus",
     "Comcast/NANOG DNSSEC testbed - deliberately broken signature"),
    ("internetsociety.org", "valid", "Internet Society - DNSSEC-signed production domain"),
    ("example.com", "valid", "IANA reference domain - DNSSEC-signed"),
]


def dnssec(report, workdir):
    out = {}
    for r, h in RESOLVERS.items():
        d = os.path.join(workdir, f"dnssec_{r}")
        os.makedirs(d, exist_ok=True)
        jobs = [(r, f"https://{h}/dns-query?dns={build_query(dom, dnssec_ok=True)}")
                for dom, _, _ in DNSSEC_CASES]
        rows, _ = run_curl(jobs, d)
        results = []
        for (dom, expect, source), row in zip(DNSSEC_CASES, rows):
            body = row.get("body", {})
            rcode = body.get("rcode")
            if expect == "valid":
                ok = rcode == 0 and body.get("answers", 0) > 0 and body.get("ad")
                detail = "AD set" if body.get("ad") else "AD NOT set"
            else:
                ok = rcode == 2
                detail = "SERVFAIL as expected" if ok else "NOT rejected"
            results.append({"domain": dom, "expect": expect, "source": source,
                            "http": row.get("code"),
                            "rcode": RCODE.get(rcode, body.get("error")),
                            "ad": body.get("ad"), "answers": body.get("answers"),
                            "ms": round(ms(row.get("total")) or 0, 1),
                            "verdict": "PASS" if ok else "FAIL", "detail": detail})
        out[r] = results
    report["dnssec"] = out


def main():
    warm_n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    cold_n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    random.seed()
    workdir = tempfile.mkdtemp(prefix="dohbench-")
    report = {"host": os.uname().nodename,
              "curl": subprocess.run(["curl", "--version"], capture_output=True,
                                     text=True).stdout.splitlines()[0],
              "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        functional(report, workdir)
        warm(report, workdir, warm_n)
        cold(report, workdir, cold_n)
        dnssec(report, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
