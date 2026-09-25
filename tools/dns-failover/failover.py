#!/usr/bin/env python3
"""Phase 7/8 — iki resolver'li bir stub client'i taklit eder.

Gercek bir istemci gibi davranir: once DNS1'e sorar, timeout/SERVFAIL olursa
DNS2'ye duser. Her sorgu icin hangi resolver cevapladi, kac ms surdu,
ve filtreleme hala calisiyor mu kaydeder.
"""
import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment
import argparse
import json
import random
import socket
import struct
import sys
import time

DNS1 = env('PRIMARY_NODE_IP')
DNS2 = env('SECONDARY_NODE_IP')


def build_query(name, qtype=1):
    xid = random.randint(0, 0xFFFF)
    header = struct.pack('!HHHHHH', xid, 0x0100, 1, 0, 0, 0)
    q = b''.join(bytes([len(p)]) + p.encode() for p in name.split('.')) + b'\0'
    return xid, header + q + struct.pack('!HH', qtype, 1)


def parse_rcode(data):
    return data[3] & 0x0F


def first_a(data):
    """Return the first A record address, or None."""
    try:
        qd, an = struct.unpack('!HH', data[4:8])
        i = 12
        for _ in range(qd):
            while data[i] != 0:
                i += 1 + data[i]
            i += 5
        for _ in range(an):
            if data[i] & 0xC0 == 0xC0:
                i += 2
            else:
                while data[i] != 0:
                    i += 1 + data[i]
                i += 1
            rtype, _, _, rdlen = struct.unpack('!HHIH', data[i:i + 10])
            i += 10
            if rtype == 1 and rdlen == 4:
                return socket.inet_ntoa(data[i:i + 4])
            i += rdlen
    except Exception:  # noqa: BLE001
        pass
    return None


def ask(server, name, timeout=2.0, qtype=1):
    xid, pkt = build_query(name, qtype)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    t0 = time.monotonic()
    try:
        s.sendto(pkt, (server, 53))
        while True:
            data, _ = s.recvfrom(4096)
            if struct.unpack('!H', data[:2])[0] == xid:
                break
        ms = (time.monotonic() - t0) * 1000
        return {'ok': True, 'server': server, 'ms': round(ms, 1),
                'rcode': parse_rcode(data), 'a': first_a(data)}
    except socket.timeout:
        return {'ok': False, 'server': server, 'ms': round((time.monotonic() - t0) * 1000, 1),
                'error': 'timeout'}
    except OSError as exc:
        return {'ok': False, 'server': server,
                'ms': round((time.monotonic() - t0) * 1000, 1), 'error': str(exc)}
    finally:
        s.close()


def resolve(name, timeout=2.0):
    """Stub-resolver davranisi: DNS1 -> basarisizsa DNS2."""
    r1 = ask(DNS1, name, timeout)
    if r1['ok'] and r1.get('rcode') in (0, 3):
        return {'answered_by': DNS1, 'fallback': False, **r1}
    r2 = ask(DNS2, name, timeout)
    return {'answered_by': DNS2 if r2['ok'] else None, 'fallback': True,
            'primary_failure': r1.get('error') or f"rcode={r1.get('rcode')}", **r2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--label', default='run')
    ap.add_argument('--count', type=int, default=6)
    ap.add_argument('--interval', type=float, default=1.0)
    ap.add_argument('--timeout', type=float, default=2.0)
    args = ap.parse_args()

    # normal + filtrelenmesi gereken + DNSSEC-gecerli domainler
    probes = ['example.com', 'doubleclick.net', 'cloudflare.com',
              'wikipedia.org', 'doubleclick.net', 'github.com']

    results = []
    print(f'--- {args.label} ---')
    for i in range(args.count):
        name = probes[i % len(probes)]
        r = resolve(name, args.timeout)
        r['query'] = name
        results.append(r)
        who = r['answered_by'] or 'BASARISIZ'
        blocked = ' [BLOCKED]' if r.get('a') == '0.0.0.0' else ''
        fb = '  <- FALLBACK' if r['fallback'] else ''
        print(f'  {name:18} {who:15} {r["ms"]:7.1f}ms  rcode={r.get("rcode")}{blocked}{fb}')
        if i < args.count - 1:
            time.sleep(args.interval)

    ok = sum(1 for r in results if r['answered_by'])
    via2 = sum(1 for r in results if r['answered_by'] == DNS2)
    blocked_ok = sum(1 for r in results if r['query'] == 'doubleclick.net' and r.get('a') == '0.0.0.0')
    blocked_total = sum(1 for r in results if r['query'] == 'doubleclick.net')
    print(f'  => {ok}/{len(results)} cozuldu, {via2} tanesi PcOld uzerinden, '
          f'filtreleme {blocked_ok}/{blocked_total}')

    print(json.dumps({'label': args.label, 'resolved': ok, 'total': len(results),
                      'via_secondary': via2, 'filtering_ok': blocked_ok,
                      'filtering_total': blocked_total, 'results': results},
                     ensure_ascii=False), file=sys.stderr)


if __name__ == '__main__':
    main()
