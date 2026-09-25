#!/usr/bin/env python3
"""Phase 5/6/11 — hangi istemci hangi resolver'a soruyor?

Her iki AdGuard'in query log'unu okur, gercek client IP'lerini gruplar.
Router proxy'si arkasinda kalsaydik hepsi router adresi gorunurdu; burada
gercek IP gorunmesi client identification'in calistiginin kanitidir.

Kullanim:
    python3 canary.py                 # son 15 dk, her iki resolver
    python3 canary.py --minutes 5
    python3 canary.py --client <istemci-ip>     # tek istemciye odaklan
"""
import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

# The cluster client ships with this repository; no external path is needed.
sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / 'dns-cluster'))

from adguard import Client as AdGuardClient, AdGuardError  # noqa: E402

NODES = ('primary', 'secondary')
LABEL = {'primary': 'Primary ' + env('PRIMARY_NODE_IP'), 'secondary': 'Secondary ' + env('SECONDARY_NODE_IP')}


def parse_time(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None


def collect(node, cutoff, limit=1000):
    client = AdGuardClient(node)
    data = client.call(f'/control/querylog?limit={limit}')
    rows = []
    for entry in (data or {}).get('data', []):
        ts = parse_time(entry.get('time'))
        if ts and ts < cutoff:
            continue
        rows.append({
            'client': entry.get('client', '?'),
            'client_name': entry.get('client_info', {}).get('name') or entry.get('client_id') or '',
            'name': (entry.get('question') or {}).get('name', '?'),
            'reason': entry.get('reason', ''),
            'status': (entry.get('answer') or [{}])[0].get('type', '') if entry.get('answer') else '',
            'time': entry.get('time'),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=int, default=15)
    ap.add_argument('--client')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=args.minutes)
    report = {}

    for node in NODES:
        try:
            rows = collect(node, cutoff)
        except AdGuardError as exc:
            print(f'{LABEL[node]}: HATA {exc}')
            report[node] = {'error': str(exc)}
            continue

        by_client = defaultdict(list)
        for row in rows:
            by_client[row['client']].append(row)

        report[node] = {
            'total_queries': len(rows),
            'clients': {ip: len(v) for ip, v in sorted(by_client.items(),
                                                       key=lambda kv: -len(kv[1]))},
            'names': {ip: next((r['client_name'] for r in v if r['client_name']), '')
                      for ip, v in by_client.items()},
        }

        print(f'\n=== {LABEL[node]} — son {args.minutes} dk: {len(rows)} sorgu ===')
        if not by_client:
            print('  (sorgu yok)')
        for ip, rws in sorted(by_client.items(), key=lambda kv: -len(kv[1])):
            name = next((r['client_name'] for r in rws if r['client_name']), '')
            flag = ''
            if ip == env('ROUTER_IP'):
                flag = '  <-- DIKKAT: router proxy! client identity kaybi'
            print(f'  {ip:16} {len(rws):5} sorgu   {name}{flag}')

        if args.client:
            focus = by_client.get(args.client, [])
            print(f'\n  --- {args.client} detay ({len(focus)} sorgu) ---')
            for row in focus[:25]:
                print(f'    {row["time"][:19]}  {row["reason"]:20} {row["name"]}')
            blocked = Counter(r['reason'] for r in focus)
            print(f'    reason dagilimi: {dict(blocked)}')

    if args.json:
        print('\n' + json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
