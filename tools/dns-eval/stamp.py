#!/usr/bin/env python3
"""DNS Stamp (dnscrypt.info/stamps) encoder/decoder for the DoH protocol.

Only the DoH stamp type (0x02) is needed here. The point of interest is that a
DoH stamp carries BOTH an `addr` (an IP, optionally with port) and a `hostname`.
dnsproxy dials `addr` but performs TLS SNI and certificate verification against
`hostname` — which is exactly a fixed-IP upstream that keeps full hostname-based
certificate validation and needs no bootstrap lookup.
"""
import base64, struct, sys

PROTO = {0x00: "Plain DNS", 0x01: "DNSCrypt", 0x02: "DoH", 0x03: "DoT",
         0x04: "DoQ", 0x05: "Oblivious DoH target", 0x81: "Anonymized DNSCrypt relay"}


def b64d(s):
    s = s[len("sdns://"):] if s.startswith("sdns://") else s
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def b64e(b):
    return "sdns://" + base64.urlsafe_b64encode(b).decode().rstrip("=")


def _lp(data, off):
    """length-prefixed field"""
    n = data[off]
    return data[off + 1:off + 1 + n], off + 1 + n


def _vlp(data, off):
    """vector of length-prefixed fields; high bit of the length continues the vector"""
    out = []
    while True:
        n = data[off]
        more = n & 0x80
        n &= 0x7F
        out.append(data[off + 1:off + 1 + n])
        off += 1 + n
        if not more:
            return out, off


def decode(stamp):
    d = b64d(stamp)
    proto = d[0]
    off = 1
    props = struct.unpack("<Q", d[off:off + 8])[0]
    off += 8
    info = {"protocol": PROTO.get(proto, hex(proto)), "protocol_id": proto,
            "props": {"dnssec": bool(props & 1), "no_logs": bool(props & 2),
                      "no_filter": bool(props & 4)}}
    if proto in (0x02, 0x03, 0x04, 0x05):
        addr, off = _lp(d, off)
        info["addr"] = addr.decode()
        hashes, off = _vlp(d, off)
        info["hashes"] = [h.hex() for h in hashes if h]
        hostname, off = _lp(d, off)
        info["hostname"] = hostname.decode()
        if proto in (0x02, 0x05):
            path, off = _lp(d, off)
            info["path"] = path.decode()
        if off < len(d):
            boot, off = _vlp(d, off)
            info["bootstrap_ips"] = [b.decode() for b in boot if b]
    elif proto == 0x00:
        addr, off = _lp(d, off)
        info["addr"] = addr.decode()
    return info


def encode_doh(addr, hostname, path="/dns-query", dnssec=True, no_logs=True,
               no_filter=False, hashes=None, bootstrap_ips=None):
    """addr: 'IP' or 'IP:port' (may be empty to force hostname resolution)."""
    props = (1 if dnssec else 0) | (2 if no_logs else 0) | (4 if no_filter else 0)
    out = bytes([0x02]) + struct.pack("<Q", props)
    out += bytes([len(addr)]) + addr.encode()
    hashes = hashes or [b""]
    for i, h in enumerate(hashes):
        last = i == len(hashes) - 1
        out += bytes([len(h) | (0 if last else 0x80)]) + h
    out += bytes([len(hostname)]) + hostname.encode()
    out += bytes([len(path)]) + path.encode()
    if bootstrap_ips:
        for i, b in enumerate(bootstrap_ips):
            last = i == len(bootstrap_ips) - 1
            eb = b.encode()
            out += bytes([len(eb) | (0 if last else 0x80)]) + eb
    return b64e(out)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "decode":
        import json
        print(json.dumps(decode(sys.argv[2]), indent=1))
    else:
        print(encode_doh(sys.argv[1], sys.argv[2],
                         sys.argv[3] if len(sys.argv) > 3 else "/dns-query"))
