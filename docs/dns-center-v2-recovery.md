# DNS Center v2 — Geri Alma

**Backup:** `$BACKUP_ROOT/20260922T071917Z-dns-center-v2/`
(yol ayrıca `workspace/dns-center-v2-backup-path.txt` içinde)

Bu geliştirme **sadece Control Center dosyalarını** değiştirdi. AdGuard, resolver,
DHCP/router ve filtre yapılandırmasına dokunulmadı — dolayısıyla "DNS'i geri al" diye
bir adım **yok**. Geri alma yalnızca dashboard kodunu eski haline döndürür.

## Tam geri alma (tek blok)

```bash
BK=$BACKUP_ROOT/20260922T071917Z-dns-center-v2/control-center
cd <status-repo>

# değiştirilen 5 dosyayı geri yükle
cp -a "$BK/dns_center.py"              dns_center.py
cp -a "$BK/control_center.py"          control_center.py
cp -a "$BK/templates/admin.html"       templates/admin.html
cp -a "$BK/static/dns-center.js"       static/dns-center.js
cp -a "$BK/static/dns-center.css"      static/dns-center.css
cp -a "$BK/static/control-center.js"   static/control-center.js
cp -a "$BK/tests/test_dns_center.py"   tests/test_dns_center.py

# eklenen 2 modülü kaldır (eski dns_center.py bunları import etmiyor)
rm -f dns_inventory.py dns_anomaly.py
rm -rf __pycache__ tests/__pycache__

sudo -n systemctl restart --no-block metehantech-status.service
```

Doğrulama:

```bash
systemctl is-active metehantech-status.service          # active
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5200/          # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5200/api/admin/dns-center   # 401
dig +short @<PRIMARY_NODE_IP> example.com                    # cevap dönmeli
dig +short @<PRIMARY_NODE_IP> doubleclick.net                # 0.0.0.0
```

## Kısmi geri alma

Sadece görünümü eski haline döndürmek (backend yeni kalsın) mümkün **değil** —
`admin.html` ve `dns-center.js` birlikte çalışıyor. İkisini birlikte geri yükleyin.

Sadece backend'i geri alırsanız (`dns_center.py` + iki modülü silmek) arayüz
`identity`, `anomalies`, `filters[].state` alanlarını bulamaz; kartlar "Not available"
gösterir ama sayfa çökmez. Yine de ikisini birlikte geri almak doğru olanıdır.

## Bütünlük kontrolü

```bash
cd $BACKUP_ROOT/20260922T071917Z-dns-center-v2
sha256sum -c SHA256SUMS.txt
```

## Testleri yeniden çalıştırma

```bash
cd <status-repo>
.venv/bin/python -m pytest tests/ -q        # beklenen: 210 passed (geri alma sonrası 177)
```

## İzole staging örneği (tarayıcı testi için)

Production'a dokunmadan aynı kodu 5299 portunda çalıştırır; kendi geçici admin
parolasını üretir, production `admin.env`'i okumaz:

```bash
PW=$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')
cd <status-repo>
ADMIN_SESSION_SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))') \
ADMIN_COOKIE_SECURE=0 \
ADMIN_PASSWORD_HASH=$(.venv/bin/python -c "from werkzeug.security import generate_password_hash as g;print(g('$PW'))") \
.venv/bin/python -c "
from app import app; import dns_center, threading, time
def warm():
    while True:
        try: dns_center.collect([])
        except Exception: pass
        time.sleep(60)
threading.Thread(target=warm, daemon=True).start(); time.sleep(4)
app.run(host='127.0.0.1', port=5299, threaded=True)" &

PLAYWRIGHT_BROWSERS_PATH=<home>/.cache/ms-playwright \
STAGE_PASSWORD="$PW" node <workspace>/dns-center-v2/browser-check.cjs
```

Staging örneği production veritabanlarını **okur** ama collector kilidi (`collector.lock`)
yüzünden ikinci bir toplayıcı başlatmaz; `dns_center.collect()` yalnızca AdGuard'dan
okur ve hiçbir tabloya yazmaz.
