#!/usr/bin/env python3
"""MetehanTech — Archer AX55 DHCP DNS cutover (Phase 1-4).

Yalnız iki alanı degistirir: pri_dns ve snd_dns.
Diger TUM DHCP alanlari canli router'dan okunup aynen geri yazilir.

Parola: sadece bu terminalde, gizli prompt ile alinir.
  - argv'ye girmez, environment'a girmez, shell history'ye girmez,
  - ekrana yazilmaz, dosyaya yazilmaz, rapora girmez.

Kullanim:
    python3 router.py            # oku -> yedekle -> onayla -> yaz -> dogrula
    python3 router.py --read-only   # sadece oku ve yedekle, DEGISIKLIK YAPMAZ
    python3 router.py --rollback    # kaydedilmis gercek eski degerlere don
"""
import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment
import json
import os
import sys
from datetime import datetime, timezone
from getpass import getpass
from urllib.parse import urlencode

# tplinkrouterc6u is a third-party dependency and is deliberately not vendored.
# Point ROUTER_VENV at a virtualenv's site-packages if it is not importable from
# the interpreter you run this with.
_venv = os.environ.get('ROUTER_VENV', '').strip()
if _venv:
    sys.path.insert(0, _venv)

try:
    from tplinkrouterc6u import TplinkRouterProvider
except ImportError:
    sys.exit(
        'ERROR: tplinkrouterc6u is not importable.\n'
        '  pip install tplinkrouterc6u\n'
        '  or: ROUTER_VENV=/path/to/venv/lib/pythonX.Y/site-packages python3 router.py'
    )

HOST = os.environ.get('ROUTER_HOST', 'http://' + env('ROUTER_IP'))
TARGET_PRI = env('PRIMARY_NODE_IP')
TARGET_SND = env('SECONDARY_NODE_IP')

# Bu alanlar canli router'dan okunup DEGISTIRILMEDEN geri yazilir.
PRESERVE = ('enable', 'leasetime', 'gateway', 'ipaddr_start', 'ipaddr_end', 'domain')

OUTDIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(OUTDIR, 'router-live-state.json')
RESULT_FILE = os.path.join(OUTDIR, 'router-cutover-result.json')

SECRET_KEYS = ('password', 'passwd', 'pwd', 'key', 'psk', 'secret', 'token')


def redact(obj):
    """Recursively drop anything that could carry a credential."""
    if isinstance(obj, dict):
        return {k: ('<redacted>' if any(s in k.lower() for s in SECRET_KEYS) else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def save(path, data):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(redact(data), fh, indent=2, ensure_ascii=False)
    os.chmod(path, 0o600)
    print(f'  -> kaydedildi: {path}')


def connect():
    print(f'Router: {HOST}')
    pwd = getpass('Archer AX55 admin parolasi (ekrana yazilmaz): ')
    if not pwd:
        sys.exit('Parola bos, cikiliyor.')
    router = TplinkRouterProvider.get_client(HOST, pwd)
    if router is None:
        sys.exit('HATA: uyumlu TP-Link istemcisi bulunamadi.')
    print(f'Istemci: {type(router).__name__}')
    router.authorize()
    del pwd
    print('Giris basarili.\n')
    return router


def read_all(router):
    setting = router.request('admin/dhcps?form=setting&operation=read', 'operation=read')
    out = {'captured_utc': datetime.now(timezone.utc).isoformat(), 'dhcp_setting': setting}
    for name, path in (
        ('reservations', 'admin/dhcps?form=reservation&operation=load'),
        ('leases', 'admin/dhcps?form=client&operation=load'),
        ('lan', 'admin/network?form=lan&operation=read'),
    ):
        try:
            out[name] = router.request(path, 'operation=' + ('load' if name != 'lan' else 'read'))
        except Exception as exc:  # noqa: BLE001
            out[name] = {'error': str(exc)}
    return out


def show(setting):
    print('--- CANLI ROUTER DHCP DURUMU ---')
    for k in ('enable', 'ipaddr_start', 'ipaddr_end', 'leasetime',
              'gateway', 'pri_dns', 'snd_dns', 'domain'):
        print(f'  {k:14} = {setting.get(k, "")!r}')
    print()


def build_payload(setting, pri, snd):
    payload = {'operation': 'write', 'pri_dns': pri, 'snd_dns': snd}
    for key in PRESERVE:
        value = setting.get(key, '')
        if value != '':
            payload[key] = value
    return payload


def apply(router, setting, pri, snd, label):
    payload = build_payload(setting, pri, snd)

    print(f'--- YAPILACAK DEGISIKLIK ({label}) ---')
    print(f'  pri_dns : {setting.get("pri_dns","")!r}  ->  {pri!r}')
    print(f'  snd_dns : {setting.get("snd_dns","")!r}  ->  {snd!r}')
    print('  Aynen korunan alanlar:')
    for key in PRESERVE:
        if key in payload:
            print(f'    {key:14} = {payload[key]!r}')
    print('\n  DEGISMEYEN: WAN DNS, firewall, UPnP, port forwarding, NAT, rezervasyonlar.\n')

    if input('Uygulamak icin EVET yaz: ').strip() != 'EVET':
        print('Iptal edildi. Router\'a hicbir sey yazilmadi.')
        return None

    router.request('admin/dhcps?form=setting&operation=write', urlencode(payload))
    print('\nYazildi. Dogrulama icin tekrar okunuyor...\n')

    after = router.request('admin/dhcps?form=setting&operation=read', 'operation=read')
    show(after)
    ok = after.get('pri_dns') == pri and after.get('snd_dns') == snd
    print('DOGRULAMA: ' + ('BASARILI' if ok else 'BASARISIZ — degerler eslesmedi!'))
    return {'before': setting, 'payload': payload, 'after': after, 'verified': ok}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    router = connect()
    try:
        live = read_all(router)
        setting = live['dhcp_setting']
        show(setting)

        if mode != '--rollback':
            # Gercek eski degerleri HER ZAMAN yazmadan once yedekle (Phase 1/2).
            save(STATE_FILE, live)
            print()

        if mode == '--read-only':
            print('Sadece okuma modu. Router degistirilmedi.')
            return

        if mode == '--rollback':
            if not os.path.exists(STATE_FILE):
                sys.exit(f'HATA: {STATE_FILE} yok. Gercek eski degerler bilinmiyor, rollback yapilmaz.')
            with open(STATE_FILE, encoding='utf-8') as fh:
                saved = json.load(fh)['dhcp_setting']
            pri, snd = saved.get('pri_dns', ''), saved.get('snd_dns', '')
            print(f'Kaydedilmis GERCEK eski degerler: pri_dns={pri!r} snd_dns={snd!r}')
            result = apply(router, setting, pri, snd, 'ROLLBACK')
        else:
            result = apply(router, setting, TARGET_PRI, TARGET_SND, 'CUTOVER')

        if result:
            result['mode'] = 'rollback' if mode == '--rollback' else 'cutover'
            result['completed_utc'] = datetime.now(timezone.utc).isoformat()
            save(RESULT_FILE, result)
    finally:
        try:
            router.logout()
            print('\nRouter oturumu kapatildi.')
        except Exception:  # noqa: BLE001
            pass


if __name__ == '__main__':
    main()
