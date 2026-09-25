#!/usr/bin/env python3
"""Port-scoped interception proof, without root.

The decisive comparison: send the SAME host the SAME TTL=1 packet on port 53
and on a non-DNS port. If the router forwards normally it must drop both at
TTL=1 and return ICMP Time Exceeded. A DNS answer arriving on port 53 while
the other port yields an ICMP error proves port 53 alone is being answered
locally rather than forwarded.
"""
import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment
import socket, struct, sys, time

IP_RECVTTL = 12
IP_TTL_CMSG = 2          # cmsg_type of a received TTL is IP_TTL, not IP_RECVTTL
IP_RECVERR = 11


def build_query(name="example.com", qid=0x2222, dnssec_ok=False):
    arcount = 1 if dnssec_ok else 0
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, arcount)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    pkt = header + qname + struct.pack(">HH", 1, 1)
    if dnssec_ok:
        pkt += b"\x00" + struct.pack(">HHIH", 41, 4096, 0x00008000, 0)
    return pkt


def parse(data):
    if len(data) < 12:
        return None
    qid, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    return {"id": qid, "rcode": flags & 0x0F, "answers": an, "ad": bool((flags >> 5) & 1)}


RC = {0: "NOERROR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}


def probe(dst, port=53, ttl=None, timeout=3.0, dnssec_ok=False, name="example.com"):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.IPPROTO_IP, IP_RECVTTL, 1)
    s.setsockopt(socket.IPPROTO_IP, IP_RECVERR, 1)   # surface ICMP errors
    if ttl is not None:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
    s.settimeout(timeout)
    start = time.perf_counter()
    try:
        s.connect((dst, port))                        # connected: ICMP -> OSError
        s.send(build_query(name, dnssec_ok=dnssec_ok))
        data, ancdata, _f, _a = s.recvmsg(4096, socket.CMSG_SPACE(64))
        ms = (time.perf_counter() - start) * 1000
        recv_ttl = None
        for level, ctype, cdata in ancdata:
            if level == socket.IPPROTO_IP and ctype in (IP_TTL_CMSG, IP_RECVTTL):
                recv_ttl = cdata[0]
        r = parse(data)
        return {"ok": True, "recv_ttl": recv_ttl, "ms": round(ms, 1),
                "answers": r["answers"] if r else None,
                "rcode": RC.get(r["rcode"], r["rcode"]) if r else None,
                "ad": r["ad"] if r else None}
    except socket.timeout:
        return {"ok": False, "kind": "timeout",
                "ms": round((time.perf_counter() - start) * 1000, 1)}
    except OSError as e:
        return {"ok": False, "kind": f"{e.__class__.__name__}/{e.errno}",
                "err": str(e), "ms": round((time.perf_counter() - start) * 1000, 1)}
    finally:
        s.close()


def line(res):
    if res.get("ok"):
        return (f"DNS ANSWER   ip_ttl={str(res['recv_ttl']):<4} rcode={res['rcode']} "
                f"ans={res['answers']} ad={res['ad']} {res['ms']}ms")
    return f"no answer    {res.get('kind')} {res.get('err','')} {res['ms']}ms"


def main():
    hosts = ["9.9.9.9", "1.1.1.1", "8.8.8.8", "203.0.113.99", env("ROUTER_IP")]

    print("=" * 84)
    print("1) IP TTL OF THE REPLY (normal outgoing TTL)")
    print("   LAN-generated reply arrives ~64/255; real internet resolver ~50-58")
    print("=" * 84)
    for h in hosts:
        print(f"  {h:<16} port53  {line(probe(h))}")

    print()
    print("=" * 84)
    print("2) TTL=1 ON PORT 53 vs A NON-DNS PORT (same host, same TTL)")
    print("=" * 84)
    for h in hosts:
        p53 = probe(h, port=53, ttl=1, timeout=2.5)
        p5353 = probe(h, port=5353, ttl=1, timeout=2.5)
        p443 = probe(h, port=443, ttl=1, timeout=2.5)
        print(f"  --- {h}")
        print(f"      ttl=1 port 53   : {line(p53)}")
        print(f"      ttl=1 port 5353 : {line(p5353)}")
        print(f"      ttl=1 port 443  : {line(p443)}")

    print()
    print("=" * 84)
    print("3) SAME PORTS AT NORMAL TTL (is 5353/443 reachable at all?)")
    print("=" * 84)
    for h in ["9.9.9.9", "203.0.113.99"]:
        print(f"  --- {h}")
        for port in (53, 5353, 443):
            print(f"      ttl=64 port {port:<5}: {line(probe(h, port=port, timeout=2.5))}")

    print()
    print("=" * 84)
    print("4) DNSSEC VIA UDP/53 (dnssec-failed.org, DO bit set)")
    print("   A validating resolver must answer SERVFAIL")
    print("=" * 84)
    for h in hosts:
        r = probe(h, dnssec_ok=True, name="dnssec-failed.org", timeout=4)
        print(f"  {h:<16} {line(r)}")
    print("  --- control: a correctly signed name")
    for h in ["9.9.9.9", "203.0.113.99"]:
        r = probe(h, dnssec_ok=True, name="sigok.verteiltesysteme.net", timeout=4)
        print(f"  {h:<16} {line(r)}")


if __name__ == "__main__":
    main()
