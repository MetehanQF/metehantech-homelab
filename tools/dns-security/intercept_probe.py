#!/usr/bin/env python3
"""Localize DNS interception without root.

Two unprivileged kernel features do the work that tcpdump would normally do:

  IP_TTL      - set the outgoing hop limit. A query sent with TTL=1 can only
                ever be answered by something one hop away (the gateway). If a
                "9.9.9.9" query with TTL=1 still returns a DNS answer, the
                answer cannot have come from Quad9.
  IP_RECVTTL  - read the IP TTL of the *received* packet. A reply generated on
                the LAN arrives with the sender's initial TTL almost intact
                (64/255); a reply from a real internet resolver arrives visibly
                decremented (~50-58).

Sends nothing but ordinary DNS queries. Changes no configuration.
"""
import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment
import socket, struct, sys, time

IP_RECVTTL = 12
TARGETS = ["9.9.9.9", "149.112.112.112", "1.1.1.1", "1.0.0.1", "8.8.8.8",
           "192.0.2.53", "198.51.100.53", "203.0.113.53", "203.0.113.99",
           env("ROUTER_IP")]


def build_query(name="example.com", qid=0x1234):
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    return header + qname + struct.pack(">HH", 1, 1)


def parse(data):
    if len(data) < 12:
        return None
    qid, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    return {"id": qid, "rcode": flags & 0x0F, "answers": an,
            "ra": bool((flags >> 7) & 1)}


def query(dst, ttl=None, timeout=3.0, name="example.com", qid=0x1234):
    """Returns dict with reply info, the source IP that answered, and the
    IP TTL that reply arrived with."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.IPPROTO_IP, IP_RECVTTL, 1)
    if ttl is not None:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
    s.settimeout(timeout)
    start = time.perf_counter()
    try:
        s.sendto(build_query(name, qid), (dst, 53))
        data, ancdata, _flags, addr = s.recvmsg(4096, socket.CMSG_SPACE(64))
        elapsed = (time.perf_counter() - start) * 1000
        recv_ttl = None
        for level, ctype, cdata in ancdata:
            if level == socket.IPPROTO_IP and ctype == IP_RECVTTL:
                recv_ttl = cdata[0]
        r = parse(data)
        return {"ok": True, "src": addr[0], "recv_ttl": recv_ttl,
                "ms": round(elapsed, 1), "answers": r["answers"] if r else None,
                "rcode": r["rcode"] if r else None,
                "id_match": (r["id"] == qid) if r else None}
    except socket.timeout:
        return {"ok": False, "error": "timeout",
                "ms": round((time.perf_counter() - start) * 1000, 1)}
    except OSError as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "ms": round((time.perf_counter() - start) * 1000, 1)}
    finally:
        s.close()


def fmt(res):
    if not res.get("ok"):
        return f"NO REPLY ({res.get('error')}) {res.get('ms')}ms"
    return (f"reply from {res['src']:<16} ip_ttl={str(res['recv_ttl']):<4} "
            f"ans={res['answers']} rcode={res['rcode']} "
            f"id_ok={res['id_match']} {res['ms']}ms")


def main():
    print("=" * 78)
    print("A) NORMAL TTL (64) - kim yanitliyor ve yanit kac hop uzaktan geliyor?")
    print("=" * 78)
    for t in TARGETS:
        print(f"  {t:<17} {fmt(query(t))}")

    print()
    print("=" * 78)
    print("B) TTL MERDIVENI - TTL=n ile gonderilen sorguya yanit gelen ilk n")
    print("   TTL=1 -> yalnizca 1 hop otedeki cihaz (gateway) yanitlayabilir")
    print("=" * 78)
    for t in ["9.9.9.9", "1.1.1.1", "8.8.8.8", "203.0.113.99", env("ROUTER_IP")]:
        print(f"  --- {t}")
        for ttl in (1, 2, 3, 4, 5, 8, 64):
            res = query(t, ttl=ttl, timeout=2.5)
            mark = "  <== YANIT" if res.get("ok") else ""
            print(f"      ttl={ttl:<3} {fmt(res)}{mark}")
            if res.get("ok"):
                break

    print()
    print("=" * 78)
    print("C) CACHE PAYLASIMI - ayni domain, farkli hedefler, TTL sayaci")
    print("   Ayni cache yanitliyorsa DNS TTL'leri senkron azalir")
    print("=" * 78)
    name = "example.com"
    for t in ["9.9.9.9", "1.1.1.1", "8.8.8.8", "203.0.113.99", env("ROUTER_IP")]:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(3)
        try:
            s.sendto(build_query(name), (t, 53))
            data, _ = s.recvfrom(4096)
            # walk to the first answer RR and read its TTL
            off = 12
            while data[off] != 0:
                off += data[off] + 1
            off += 5
            while off < len(data) and (data[off] & 0xC0) != 0xC0:
                off += 1
            off += 2
            rtype, rclass, rttl = struct.unpack(">HHI", data[off:off + 8])
            print(f"  {t:<17} answer_rr_ttl={rttl}")
        except Exception as e:
            print(f"  {t:<17} {type(e).__name__}: {e}")
        finally:
            s.close()


if __name__ == "__main__":
    main()
