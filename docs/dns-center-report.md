# MetehanTech DNS Center — Final Report (TR)

**Tarih:** 2026-09-21 · **Sunucu:** Raspberry Pi 5 (`<primary-node>`, Ubuntu 24.04.4, arm64)

> ## EN ÖNEMLİ SATIR
> AdGuard Home **kuruldu, yapılandırıldı ve test edildi.**
> **Ev ağının DNS'i hâlâ AdGuard'a bağlı DEĞİL.** Modem/router DHCP DNS ayarına
> dokunulmadı. Pi5'in kendi DNS'i de değiştirilmedi. Bir cihaz elle <PRIMARY_NODE_IP>'yi DNS
> olarak yazmadıkça hiçbir şey AdGuard üzerinden çözülmüyor.
> Geri alma tek komut: `docker stop metehantech-adguard`.

---

## 1. Başlangıç DNS mimarisi

```
container (bridge)   ─► 127.0.0.11 (Docker embedded) ─┐
Home Assistant (host)─► 127.0.0.53 ───────────────────┤
Primary Node host süreçleri   ─► 127.0.0.53 ───────────────────┴─► systemd-resolved
                                                            ├─ <PRIMARY_WIFI_IFACE> ─► <ROUTER_IP> (router, dnsmasq 2.83)
                                                            └─ tailscale0 ─────► 100.100.100.100 (MagicDNS)
Secondary Node (<SECONDARY_NODE_IP>) ─► 100.100.100.100 (resolv.conf'u Tailscale yazıyor)
```

- `/etc/resolv.conf` → `stub-resolv.conf` sembolik bağı, `nameserver 127.0.0.53`.
- `/etc/systemd/resolved.conf` boştu (`[Resolve]`), `resolved.conf.d/` hiç yoktu.
- NetworkManager 1.46.0 aktif, `conf.d/` içinde DNS ile ilgili hiçbir override yok.
- Upstream: evdeki modem (dnsmasq 2.83), ölçülen gecikme **20 ms**.

## 2. Primary Node DNS / port discovery sonucu

**Kritik bulgu:** `systemd-resolved` yalnızca **loopback**'e bağlanıyor:

```
udp/tcp  127.0.0.53%lo:53      (stub)
udp/tcp  127.0.0.54:53         (legacy)
```

`0.0.0.0:53` **bağlı değil.** Yani `<PRIMARY_NODE_IP>:53` ve `<PRIMARY_NODE_TAILSCALE_IP>:53` tamamen boş.

**Sonuç:** AdGuard'ı kurmak için systemd-resolved'i durdurmaya / maskelemeye /
yeniden yapılandırmaya **gerek yok** — ve kesinlikle yapılmamalı. Home Assistant `host`
network modunda çalışıyor ve `127.0.0.53`'ü kullanıyor; Frigate / Nextcloud / Mosquitto ise
`127.0.0.11` üzerinden yine aynı stub'a çıkıyor (`ExtServers: [host(127.0.0.53)]`).
İnternetteki yaygın "port 53'ü boşaltmak için systemd-resolved'i kapat" tarifi bu makinede
Home Assistant, Frigate, Nextcloud ve Mosquitto'nun DNS'ini **aynı anda** koparırdı.

Dağıtımdan önce alınan negatif referans: Secondary Node'dan `dig @<PRIMARY_NODE_IP> example.com` →
`;; no servers could be reached` ✔

Diğer boş portlar: tcp/3000, tcp/8053, tcp/784. `udp/5353` **avahi-daemon (mDNS)** tarafından
kullanılıyor — Faz 10 için önemli.

Ayrıca keşfedilen kısıt: hesabın `sudo`'su parola istiyor; sadece 5 adet `systemctl`
komutu NOPASSWD. Bu yüzden **firewall kuralları okunamadı ve değiştirilemedi**; güvenlik
host firewall'ı yerine **arayüze özel port bağlama** üzerine kuruldu (bkz. madde 12).

## 3. Kurulan AdGuard sürümü

**AdGuard Home v0.107.79** (linux/arm64), digest ile sabitlendi:

```
adguard/adguardhome@sha256:aba9e3bf0613be3ba3755e1fc311b126e2c24bec25e18b6483894a88283074f0
```

## 4. Container mimarisi

Proje: `<repo>/dns/adguard/` (mevcut `metehantech-mqtt` düzeniyle aynı stil)

| Ayar | Değer |
|---|---|
| Container | `metehantech-adguard` |
| Kullanıcı | `1000:1000` — **root değil** |
| Yetkiler | `cap_drop: ALL` + `cap_add: NET_BIND_SERVICE` (tek yetki) |
| | `security_opt: no-new-privileges:true` |
| Privileged | `false` |
| Docker socket | **yok** |
| Host network | **yok** — kendi bridge ağı `metehantech-dns_default` |
| Host dosya erişimi | sadece `./conf` ve `./work` |
| Restart policy | `unless-stopped` |
| Healthcheck | web arayüzü + DNS portu TCP kontrolü, 30 sn |
| Log | json-file, 10 MB × 3 |

İki teknik ayrıntı (ikisi de gerçek hata olarak yaşandı ve çözüldü):

1. **İlk açılış root istiyor.** AdGuard, config dosyası yokken `root` değilse
   `this is the first launch … you must run it as administrator` verip crash-loop'a giriyor.
   Bu yüzden ilk config tek kullanımlık bir root container ile install API'si üzerinden
   üretildi, dosyalar `1000:1000`'e devredildi, kalıcı servis yetkisiz olarak açıldı.
2. **`cap_drop: ALL` tek başına çalışmıyor.** İmajdaki `AdGuardHome` binary'si
   `cap_net_bind_service`'i **dosya capability'si** olarak taşıyor; bounding set tamamen boş
   olduğunda `execve()`'nin kendisi `operation not permitted` ile düşüyor. Bu yüzden
   `NET_BIND_SERVICE` geri eklendi — verilen tek yetki bu.

DNS container içinde **3053** (yetkisiz port) dinliyor; ayrıcalıklı host tarafı `:53`
bağlamayı dockerd'nin DNAT'ı yapıyor.

## 5. Kullanılan upstream DNS

```yaml
upstream_dns:
  - https://dns.quad9.net/dns-query              # Quad9 secured (DoH)
  - https://security.cloudflare-dns.com/dns-query # Cloudflare 1.1.1.2 (DoH)
upstream_mode: load_balance
bootstrap_dns: [9.9.9.9, 149.112.112.112, 1.1.1.1, 1.0.0.1]
fallback_dns:  [<ROUTER_IP>]                     # tüm upstream'ler düşerse modem
local_ptr_upstreams: [<ROUTER_IP>]               # LAN PTR → modemin dnsmasq'ı
upstream_timeout: 5s
```

Neden bu ikisi: **ikisi de DNSSEC doğruluyor ve ikisi de bilinen zararlı/phishing
domainleri engelliyor.** load_balance hangi upstream'i seçerse seçsin güvenlik davranışı
aynı kalıyor — karışık (biri filtreli, biri filtresiz) bir kurulumda olmayacak bir tutarlılık.
DoH seçildi, böylece sorgular modeme/ISP'ye açık gitmiyor.

`fallback_dns` doğrudan Faz 8'in istediği şey: internet tarafındaki resolver'lar
çökse bile isim çözümleme modem üzerinden devam ediyor.

## 6. Kullanılan filter listeleri

**Tek liste: "AdGuard DNS filter"** (~181.411 kural), varsayılan olarak etkin.
"AdAway Default Blocklist" kurulu ama **kapalı**.

İstendiği gibi 10–20 agresif community listesi eklenmedi. Zararlı/phishing koruması
liste yığmak yerine **upstream seviyesinde** (Quad9 secured + Cloudflare security)
sağlanıyor — false-positive riski community listelerine göre çok daha düşük.

AdGuard'ın kendi SafeBrowsing/Parental özellikleri **kapalı** tutuldu: bunlar domain
hash'lerini AdGuard sunucularına gönderiyor, gizlilik açısından gereksiz.

### Kritik servis testi (filtreleme AÇIKKEN)

24 domain test edildi, **23'ü sorunsuz çözüldü**: Google (google/www/accounts),
Microsoft (login.microsoftonline.com, outlook.office365.com), Samsung (samsung.com,
account.samsung.com), Tapo (tapo.com, wap.tplinkcloud.com), Home Assistant
(home-assistant.io, mobile-apps.home-assistant.io), Nextcloud, Cloudflare, Tailscale
(login + controlplane), GitHub, ve bankalar: İş Bankası, Ziraat, Garanti, Akbank,
Yapı Kredi, e-Devlet.

Tek "boş dönen" isim `n-eu-wap.tplinkcloud.com` idi. **Filtreleme kapatılmadan nedeni
bulundu:** AdGuard'ın kendi `check_host` kararı `NotFilteredNotFound` (yani engellenmemiş),
ve aynı isim **modemin dnsmasq'ında da, doğrudan Quad9'da da NXDOMAIN** dönüyor. Yani o
hostname gerçekten yok — benim tahmin ettiğim Tapo bulut adresi yanlıştı; gerçek adres
`wap.tplinkcloud.com` ve o sorunsuz çözülüyor. **False positive yok.**

## 7. DNSSEC durumu

**Etkin** (`enable_dnssec: true`) ve gerçekten doğruluyor:

| Test | Sonuç |
|---|---|
| `cloudflare.com` | `NOERROR`, **`ad` flag'i var** (authenticated data) ✔ |
| `dnssec-failed.org` (kasıtlı bozuk imza) | **`SERVFAIL`** ✔ — doğrulama çalışıyor |
| `sigok.verteiltesysteme.net` (geçerli imza kontrolü) | `NOERROR` ✔ |

## 8. Cache durumu

Etkin. `cache_size: 16 MiB`, `cache_ttl_min: 60` (çok kısa TTL'li reklam/CDN kayıtları da
yeniden kullanılsın diye), `cache_optimistic: false` (v1'de asla bayat cevap verilmez).

Ölçüm: aynı sorgu 8 ms → 1 ms. Canlı örneklemde cache isabet oranı **%32** (ölçüm penceresi
küçük, zamanla yükselir).

## 9. Query log retention

- Query log: **açık, 72 saat** (3 gün)
- İstatistikler: **7 gün** (sadece toplu sayaçlar)
- `size_memory: 1000`

Gizlilik gereği kasıtlı olarak kısa tutuldu. Şu anki disk kullanımı `work/` = **4.3 MB**.

## 10. Admin UI erişim adresi

| Yol | Adres |
|---|---|
| LAN | `http://<PRIMARY_NODE_IP>:3000` |
| Tailscale | `http://<PRIMARY_NODE_TAILSCALE_IP>:3000` |
| Loopback (Control Center bunu kullanıyor) | `http://127.0.0.1:3000` |

**Public internete açık değil.** Cloudflare Tunnel'a hiçbir şey eklenmedi, router'da
port-forward oluşturulmadı.

Kullanıcı adı / parola: `<repo>/dns/adguard/credentials.json` (mod **0600**).
Parola 28 karakter, rastgele üretildi. **Bu dosyanın dışında hiçbir yerde düz metin olarak
yok** — config'de bcrypt hash olarak duruyor, container loglarında 0 kez geçiyor,
Control Center hiçbir yanıtında göndermiyor.

## 11. DNS server IP adresi

```
<PRIMARY_NODE_IP> : 53   (LAN,       UDP + TCP)
<PRIMARY_NODE_TAILSCALE_IP>: 53   (Tailscale, UDP + TCP)
```

## 12. Public / open-resolver güvenlik testi

| Kontrol | Sonuç |
|---|---|
| `0.0.0.0:53` bağlı mı? | **HAYIR** — sadece iki spesifik adres |
| `0.0.0.0:3000` bağlı mı? | **HAYIR** — 127.0.0.1 + LAN + Tailscale |
| Docker port map | `3053 → <PRIMARY_NODE_IP>:53`, `3053 → <PRIMARY_NODE_TAILSCALE_IP>:53` (wildcard yok) |
| ANY sorgusu (amplifikasyon) | **`NOTIMP`** — `refuse_any: true` ✔ |
| `version.bind` / `hostname.bind` / `id.server` | cevapsız (parmak izi alınamıyor) ✔ |
| Rate limit | 20 sorgu/sn/client ✔ |
| `allowed_clients` | LAN + Tailscale + WireGuard + Docker + loopback |
| allowlist gerçekten uyguluyor mu? | **Kanıtlandı** — Secondary Node geçici olarak listeden çıkarıldı → `no servers could be reached`; geri alındı → `NOERROR` ✔ |
| Container privileged / docker.sock | `false` / **yok** ✔ |

**WAN tarafı:** Public IP `<WAN_PUBLIC_IP>:53`'e sorgu cevap veriyor **ama cevabı veren
AdGuard değil, modemin kendi dnsmasq'ı** — `version.bind` sorgusu `"dnsmasq-2.83"` dönüyor,
AdGuard ise bu sorguya hiç cevap vermiyor. Yani AdGuard WAN'dan erişilebilir değil.

⚠️ **Bu işle ilgisi olmayan, önceden var olan bir bulgu:** modem public IP üzerinde
`ra` (recursion available) flag'i ile DNS cevaplıyor. Bu ya NAT hairpin'dir (zararsız) ya da
modem gerçekten WAN'dan özyinelemeli DNS kabul ediyordur (**o durumda açık resolver ve DNS
amplifikasyon riski**). Ağın içinden ayırt edilemiyor; kesin cevap için ağ dışından tek bir
sorgu gerekiyor (ör. telefonun mobil verisinden `dig @<WAN_PUBLIC_IP> example.com`).
Bu modemin kendi resolver'ı — AdGuard bunu ne yarattı ne de kötüleştirdi, ama bilmelisin.

## 13. Test sonuçları

| Test | Sonuç |
|---|---|
| DNS UDP | ✔ `example.com` → NOERROR |
| DNS TCP | ✔ |
| Tailscale adresinden sorgu | ✔ |
| Gerçek LAN istemcisi (Secondary Node <SECONDARY_NODE_IP>) | ✔ UDP + TCP, kaynak IP doğru görünüyor |
| Engellenen domain | ✔ `doubleclick.net` → `0.0.0.0`, kural `||doubleclick.net^` |
| DNSSEC geçerli / bozuk / kontrol | ✔ `ad` / `SERVFAIL` / `NOERROR` |
| Cache | ✔ 8 ms → 1 ms |
| Upstream sağlığı | ✔ 3/3 OK (Quad9, Cloudflare, fallback modem) |
| **Upstream tamamen çökerse** | ✔ Her iki upstream kara deliğe çevrildi → **fallback (modem) cevapladı**, sonra geri alındı ve normale döndü |
| **AdGuard tamamen kapalıyken** | ✔ Primary Node host DNS, Home Assistant, Frigate, Nextcloud container DNS'i, Control Center (HTTP 200), HA API, Frigate API, Nextcloud, cloudflared — **hepsi çalışmaya devam etti**, container restart sayıları **0 → 0** |
| Container health | ✔ `healthy` |
| Admin UI | ✔ LAN / Tailscale / loopback; public değil |
| Query logging | ✔ 72 saat |
| Filtering | ✔ 181.411 kural aktif |
| Control Center DNS sayfası | ✔ (madde 16) |
| Control Center auth | ✔ anonim `/api/admin/dns-center` → **401** |
| Alert Center entegrasyonu | ✔ (madde 17) |
| **Negatif test: WAN'dan recursive DNS** | ✔ AdGuard erişilemiyor (madde 12) |
| Regresyon: mevcut test paketi | ✔ **155 test + 349 subtest geçti** (öncesi 130) |

## 14. Ölçülen DNS latency

50 benzersiz cache-miss + 50 sıcak sorgu, AdGuard ve modem karşılaştırmalı:

| Resolver | Cache-MISS ort. | medyan | p95 | Sıcak medyan |
|---|---|---|---|---|
| **AdGuard <PRIMARY_NODE_IP>** | 110.2 ms | 112.7 ms | 173.9 ms | **38.2 ms** |
| modem <ROUTER_IP> | 120.7 ms | 98.4 ms | 217.3 ms | 52.1 ms |

Yorum: DoH'un TLS maliyetine rağmen AdGuard cache-miss'te modemle **aynı sınıfta**, sıcak
sorgularda ise **daha hızlı**. AdGuard'ın kendi raporladığı ortalama işlem süresi: **61 ms**.

## 15. CPU / RAM etkisi

| | CPU ort. | CPU p95 | RAM kullanılan | Boşta |
|---|---|---|---|---|
| Dağıtım **öncesi** (30 sn) | %38.21 | %43.50 | 5.35 GiB | 9.65 GiB |
| Dağıtım **sonrası** (60 sn) | %40.77 | %50.00 | 5.40 GiB | 9.60 GiB |

**Container'ın kendisi: CPU %0.02, RAM 46.9 MiB.** Aradaki ~2 puanlık fark ölçüm sırasında
çalıştırdığım test yükünden kaynaklanıyor, AdGuard'dan değil — container'ın kendi tüketimi
ölçüm gürültüsünün altında.

Disk: query log + istatistik = **4.3 MB**. 72 saatlik retention ve 168 GB boş alan ile
kontrolsüz büyüme riski yok.

## 16. Control Center DNS Center özellikleri

Mevcut Control Center V2'ye **yeni bir dashboard açılmadan**, aynı tema ve navigasyonla
`Network` ile `Alerts` arasına **DNS** sekmesi eklendi (`/admin#dns`). Tamamı
**admin auth** arkasında.

**Overview kartları:** AdGuard durumu · sürüm · filtreleme açık/kapalı · **DNSSEC** ·
DNS sunucu adresleri · container restart sayısı · toplam sorgu · engellenen · **engelleme
yüzdesi** · aktif istemci · **ortalama işlem süresi** · collector API gecikmesi ·
**cache isabet oranı** · cache boyutu · **upstream sağlığı** · son probe zamanı ·
**freshness / last update**.

**Clients:** isim · IP · sorgu sayısı · engellenen sayısı · **isim kaynağı**.
İsimler ya gözden geçirilmiş MetehanTech envanterinden ya da AdGuard'ın kendi
rDNS/ARP/DHCP gözleminden geliyor. Eşleşmeyen adres **"Unknown client"** olarak kalıyor —
uydurma isim yok. WHOIS kapatıldı (istemci adresleri hakkında dışarıya sorgu gitmesin diye).

Envantere sabitlenen cihazlar — **yalnızca kanıtı olanlar**:
`Primary Node (<PRIMARY_NODE_IP>, <PRIMARY_NODE_TAILSCALE_IP>)`, `Secondary Node (<SECONDARY_NODE_IP>, <SECONDARY_NODE_TAILSCALE_IP>)`,
`Tapo C211 (<CAMERA_IP>)`, `<PRIMARY_PHONE> (<PHONE_TAILSCALE_IP>)`, `<CLIENT_PHONE> (<CLIENT_TAILSCALE_IP>)`.
Telefon/tabletlerin **LAN** adresleri kasıtlı olarak sabitlenmedi: DHCP ile değişebilirler,
yanlış etiketlemektense rDNS'e bırakmak doğru. Tailscale adresleri cihaza kalıcı atandığı
için güvenli.

**Domains:** Top Queried Domains + Top Blocked Domains, **sunucu tarafında 15 kayıtla
sınırlı**. Admin-only.

**Recent Activity:** `ALL / BLOCKED / ALLOWED` filtresi, client filtresi, 25/50/100 limiti,
imleç tabanlı "Load older" sayfalama. **Filtreleme ve sayfalama sunucu tarafında** —
tarayıcıya asla toplu ham query log yüklenmiyor. Ayrıca bu görünüm sadece DNS sekmesi
açıkken yenileniyor; arka planda query log çekilmiyor.

**Gizlilik (Faz 11):** Public status sayfası AdGuard hakkında **yalnızca "çalışıyor mu"**
bilgisini gösteriyor. Domain geçmişi, client geçmişi, query log — hiçbiri public endpoint'e
girmiyor; bu bir testle sabitlendi (`test_public_status_never_exposes_dns_history`).
AdGuard kimlik bilgisi sunucu tarafında kalıyor, tarayıcıya gönderilmiyor.

## 17. Alert Center entegrasyonu

Mevcut Alert Center'a (yeni sistem kurulmadan, aynı `alerts`/`alert_states` tabloları)
5 kural eklendi. **Hepsi debounce'lu — tek başarısız sorgu/probe asla alarm üretmiyor:**

| Alarm | Eşik | Şiddet |
|---|---|---|
| `adguard_unavailable` | 2 ardışık döngü → warning, 5 → critical | WARNING / CRITICAL |
| `dns_upstream_all_down` | 2 ardışık döngü | CRITICAL |
| `dns_upstream_degraded` | 2 ardışık döngü | WARNING |
| `dns_latency_high` | >250 ms, 3 ardışık döngü | WARNING |
| `dns_protection_disabled` | 2 ardışık döngü | WARNING |
| `dns_collector_stale` | mevcut ortak `STALE_WARNING/CRITICAL` modeli | WARNING / CRITICAL |

Çözülme de simetrik: alarm ancak koşul 2 döngü boyunca temiz kaldıktan sonra kapanıyor.

### Canlı uçtan uca alarm testi (gerçek kesinti, gerçek alarm, gerçek çözülme)

AdGuard 4 dakika boyunca gerçekten durduruldu ve production Alert Center izlendi:

```
T0            → alarm yok
stop 06:56:57Z
+1 dk         → alarm yok            ← debounce çalışıyor: tek kaçırılan probe alarm üretmiyor
+2 dk         → WARNING  active  "unreachable"
+3 dk         → WARNING  active
+4 dk         → CRITICAL active      ← 5 döngüde kritiğe yükseldi
start 07:01:18Z
recovery +1dk → CRITICAL active      ← hemen kapanmıyor (simetrik debounce)
recovery +2dk → CRITICAL resolved "reachable"   ← otomatik çözüldü
```

Aynı kesinti sırasında: `metehantech-homeassistant`, `metehantech-frigate`,
`metehantech-nextcloud-app` → **restart sayısı 0, hepsi `healthy`**. Kesinti sonrası
`dig @<PRIMARY_NODE_IP> example.com` normal cevap verdi.

**Faz 14 (Systems / Services):** AdGuard Home artık Services görünümünde
`RUNNING / DEGRADED / UNKNOWN` olarak, Docker kartlarında **restart sayacıyla** ve Network
görünümünde DNS adresleriyle listeleniyor. Yeni bir otomatik restart mekanizması
**kurulmadı** — mevcut Docker `unless-stopped` politikası yeterli.

## 18. Değiştirilen dosyalar

**Yeni proje** — `<repo>/dns/adguard/`
`compose.yaml` · `configure.py` · `README.md` · `credentials.json` (0600) ·
`conf/AdGuardHome.yaml` (+ `.baseline`, `.pre-configure`) · `work/`

**Control Center — eklenen 4 dosya** (`<status-repo>/`)
`dns_center.py` · `dns_alerts.py` · `static/dns-center.js` · `tests/test_dns_center.py`

**Control Center — değiştirilen 5 dosya**
`app.py` (+5 satır) · `control_center.py` (+15) · `history.py` (+6) ·
`templates/admin.html` (DNS sekmesi + görünüm) · `static/control-center.css` (tablo stili)

**Hash'i değişmeyen kritik dosyalar (doğrulandı):**
`alerts.py`, `admin.py`, `health_model.py`, `static/admin.js`, `static/style.css`,
`static/control-center.js`, `templates/index.html`.
Yani Alert Center çekirdeği, kimlik doğrulama, CSRF/lockout, audit log, backup akışı ve
public sayfa **hiç ellenmedi**.

**Dokümanlar** — `workspace/dns-center/`
`DISCOVERY.md` · `RECOVERY.md` · `DESIGN-NOTES.md` · `REPORT.md` · `backup-location`

Sistem servisi sadece izin verilen komutla yeniden başlatıldı
(`sudo -n systemctl restart --no-block metehantech-status.service`), SIGHUP kullanılmadı.

## 19. Rollback konumu

```
$BACKUP_ROOT/20260921T063604Z-dns-center/
├── network/          resolved.conf, resolv.conf sembolik bağ, NetworkManager, resolvectl, ss, hosts
├── tailscale/        status + dns status
├── docker/           ps, networks, tüm container inspect JSON
├── control-center/   değiştirilen her dosyanın değişiklik öncesi hali
└── SHA256SUMS.txt    34 dosya, bütünlük manifesti
```

Adım adım kurtarma: `workspace/dns-center/RECOVERY.md`.

**Acil geri alma tek satır:** `docker stop metehantech-adguard`
Host DNS'i hiç değişmediği için "DNS'i geri al" diye bir adım **yok**.

## 20. Bilerek yapılmayan işlemler

- ❌ Modem/router DHCP DNS ayarı — **senin onayını bekliyor**
- ❌ Router port-forward — hiç oluşturulmadı
- ❌ Cloudflare Tunnel'a AdGuard admin paneli eklenmedi
- ❌ `/etc/resolv.conf`, `systemd-resolved`, NetworkManager — **hiç dokunulmadı**
- ❌ Tailscale MagicDNS / split-DNS / `--accept-dns` — değiştirilmedi
- ❌ Home Assistant / Frigate / Nextcloud / Mosquitto config — değiştirilmedi
- ❌ Ev cihazlarının DNS'i — tek bir cihaz bile değiştirilmedi
- ❌ AdGuard DHCP sunucusu — kapalı, DHCP modemde kalıyor
- ❌ İkinci AdGuard instance'ı (Secondary Node) — sadece tasarım önerisi (madde 22)
- ❌ `.local` local DNS kayıtları — bilinçli olarak uygulanmadı (madde 21 altı)
- ❌ Agresif community blocklist'leri
- ❌ Host firewall kuralları — hesabın yetkisi yok; güvenlik arayüze özel bağlama ile sağlandı

**Doğrulanamayanlar (dürüstlük notu):**
- Production admin oturumuyla tarayıcıdan gerçek giriş yapılıp DNS sekmesinin **görsel**
  kontrolü yapılmadı — admin parolası root-only `admin.env` içinde. Bunun yerine aynı Flask
  app nesnesi üzerinde gerçek oturumla API'ler uçtan uca test edildi (401 → 200, tüm
  filtreler, sayfalama, geçersiz girdi reddi).
- Modemin WAN tarafında gerçekten açık resolver olup olmadığı ağ dışından test edilemedi.
- Telefon/tablet gibi gerçek istemcilerde test yapılmadı (bilinçli — Faz 7 gereği).

## 21. Router'da tüm eve geçirmek için senin yapman gerekenler

> **Bunu sen onaylamadan yapmayacağım.** Hazır olduğunda:

1. Modem arayüzüne gir: `http://<ROUTER_IP>`
2. **LAN / DHCP** ayarlarına git.
3. **DNS Server** alanını `<PRIMARY_NODE_IP>` yap. (Mümkünse birincil `<PRIMARY_NODE_IP>`,
   ikincil `<ROUTER_IP>` bırak — Pi kapandığında ev internetsiz kalmasın.)
4. Kaydet, sonra cihazlarda Wi-Fi'ı kapat/aç veya DHCP lease'i yenile.
5. Doğrula: bir telefonda `nslookup doubleclick.net` → `0.0.0.0` dönmeli.

**Önce yapılması önerilen:** modemde Primary Node için **<PRIMARY_NODE_IP> DHCP rezervasyonu** tanımla.
Şu an bu adres dinamik; ev DNS'i tamamen Pi'ye bağlıyken Pi'nin IP'si değişirse bütün ev
isim çözemez hale gelir.

**Geri alma:** DNS alanını `Otomatik` / `<ROUTER_IP>` yap. Modeme fiziksel erişebildiğin
bir zamanda yap.

## 22. Secondary Node secondary DNS önerisi

Kısa cevap: **mantıklı ama şimdi değil, ve "iki bağımsız AdGuard" şeklinde değil.**

İkinci bir DNS sunucusu şunlara karşı korur: AdGuard container'ı çökerse, Primary Node güncelleme
için yeniden başlarsa, Primary Node donanımı bozulursa. Şunlara karşı **korumaz**: upstream
erişilemezse (zaten `fallback_dns` ile çözüldü), internet giderse, modem giderse.

**İki bağımsız AdGuard'ın üç gerçek problemi:**
1. **İstemciler beklendiği gibi failover yapmaz.** DHCP ile iki DNS vermek "birincisini
   kullan, düşerse ikincisine geç" demek değildir — Windows ve Android ikisini de,
   çoğu zaman paralel sorgular. İki instance'ın filtreleri farklıysa reklam engelleme
   sessizce yarı yarıya çalışmaya başlar ve hiçbir belirti vermez.
2. **Configuration drift.** Filtre listeleri, DNS rewrite'lar, istemci isimleri her
   instance'ın kendi YAML'ında; haftalar içinde ayrışır ve 1. problemi tetikler.
3. **Bölünmüş gözlem.** Query log ve istatistik instance başına; DNS Center trafiğin
   yarısını görür.

**Önerilen hedef mimari:**

```
        DHCP tek adres dağıtır: <DNS_VIP_LAN_IP> (VIP)
                     │
           keepalived / VRRP floating IP
            ┌────────┴────────┐
     MASTER │                 │ BACKUP
  Primary Node <PRIMARY_NODE_IP>     Secondary Node <SECONDARY_NODE_IP>
  AdGuard (primary)    AdGuard (replica)
        └──── adguardhome-sync (config replikasyonu) ────┘
```

- **keepalived VRRP** 1. problemi kökten çözer: istemciler tek DNS adresi bilir, o adreste
  aynı anda tek düğüm cevap verir. Belirsiz failover yok, yarı filtreli gezinme yok.
- **`adguardhome-sync`** (`ghcr.io/bakito/adguardhome-sync`, aktif bakımda) filtreleri,
  rewrite'ları ve istemci ayarlarını primary'den replica'ya kopyalar — 2. problemi çözer.
- 3. problem kalır; DNS Center'ı "primary node" olarak etiketlemek en dürüst çözüm.

**Efor sırasına göre alternatifler:**
1. **Hiçbir şey yapma.** DHCP DNS'i `<PRIMARY_NODE_IP>, <ROUTER_IP>` yap. Modem zaten çalışan
   bir resolver. Maliyet sıfır. Dezavantajı: Pi kapalıyken (bazen açıkken de) bazı sorgular
   modemden filtresiz cevap alır. Ev ağı için gayet savunulabilir bir takas.
2. **Secondary Node'a düz forwarder** (`unbound`/`dnsmasq` → Quad9). Pi çökmesini atlatır ama
   filtreleme ve ortak config yok.
3. **VIP + sync** (yukarıdaki diyagram). En doğru davranış, en çok hareketli parça.

**Tavsiyem: eve geçerken 1. seçenekle başla.** Birkaç hafta yaşa, Pi gerçekten düşüyor mu
gör, sonra gerekirse VIP + sync çiftini kur. Henüz ihtiyaç duymadığın bir yedeklilik
katmanı eklemek, sistemi *daha az* güvenilir yapmanın en yaygın yoludur.

**Secondary Node ön koşulları (doğrulandı):** port 53 boş (sadece udp/5353 mDNS var), systemd-resolved
stub'ı yok, Docker + Portainer mevcut. `/etc/resolv.conf`'u Tailscale yazıyor — oraya
kurulacak DNS sunucusu bu dosyayı yönetmeye **çalışmamalı**.

**Engel:** otomasyon için kullanılan `metehanbackup` SSH hesabının backup servisini
başlatmak dışında sudo yetkisi yok. Secondary Node'a bir şey kurmak için ya senin elin ya da daha
geniş yetkili bir hesap gerekiyor. Bu yüzden bu faz tasarımda kaldı.

---

## Faz 10 — Local DNS (discovery / öneri)

**`.local` KULLANMA.** Nedeni somut: `.local` RFC 6762 ile **mDNS'e** ayrılmış ve bu ağ zaten
kullanıyor — Pi'de `avahi-daemon` çalışıyor, `<primary-node>.local` adını üstlenmiş ve
`udp/5353`'ü bağlamış durumda. Android, iOS, macOS ve modern Windows `.local` isimlerini
**LAN'a multicast ederek** çözer, yapılandırılmış DNS sunucusuna sormaz. Sonuç:
`status.metehantech.local` bazı cihazlarda AdGuard'dan cevap alır, bazılarında sessizce
başarısız olur. Ayrıca `.local` için asla güvenilir TLS sertifikası alınamaz.

**Önerilen namespace:** zaten sahip olduğun domainin bir alt alanı — Cloudflare'de hiç
yayınlamadan:

```
<HA_INTERNAL_HOST>    → <PRIMARY_NODE_IP>
<STATUS_INTERNAL_HOST>  → <PRIMARY_NODE_IP>
<CLOUD_INTERNAL_HOST>   → <PRIMARY_NODE_IP>
<FRIGATE_INTERNAL_HOST> → <PRIMARY_NODE_IP>
```

mDNS ile çakışmaz, Android/iOS'ta çalışır, ve istersen DNS-01 ACME ile
`*.lan.metehantech.com` wildcard sertifikası alıp **iç ağda gerçek HTTPS** kullanabilirsin —
`.local` ile imkânsız olan şey. Uygulaması: AdGuard → Filters → **DNS rewrites**.

**Değişmez kural:** `status.metehantech.com` ve `cloud.metehantech.com` için **asla** rewrite
oluşturma. Bu isimler Cloudflare edge'ine çözülüyor, TLS'i orada sonlanıyor ve tünele
giriyor. Onları <PRIMARY_NODE_IP>'ye yönlendirirsen tarayıcılar sertifikası olmayan yerel
origin'e çarpar ve evdeki her cihazda TLS hatası alırsın. `lan.` öneki tam olarak bu
karışıklığı imkânsız kılmak için var.

**Zaten elinde olan basit seçenek:** Tailscale MagicDNS hiçbir yapılandırma olmadan
`<primary-node>.tailad2806.ts.net` ve `metehantechpcold.tailad2806.ts.net` isimlerini
çalıştırıyor. Amaç sadece "IP yerine isim yazmak" ise bu bedava ve hazır.

Detaylı karşılaştırma: `workspace/dns-center/DESIGN-NOTES.md`.
