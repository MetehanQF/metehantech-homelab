# DNS Center v2 — Kontrollü Geliştirme Raporu

**Tarih:** 2026-09-22 · **Sunucu:** Raspberry Pi 5 (`<primary-node>`) · **Servis:** `metehantech-status.service`

> ## EN ÖNEMLİ SATIR
> Bu bir **arayüz ve gözlem** geliştirmesidir. AdGuard yapılandırması, Pi5/Secondary Node
> resolver ayarları, upstream/fallback, DHCP/router, filtre kuralları ve kimlik
> doğrulama/CSRF/session/lockout mekanizmalarının **hiçbirine dokunulmadı** —
> `admin.py`, `alerts.py`, `dns_cluster.py`, `dns_alerts.py`, `app.py`, `history.py`
> ve public sayfa **sha256 olarak aynı**. RE305 trafiği yalnızca **ölçüldü**,
> engellenmedi.

---

## 1. Değiştirilen dosyalar

### Yeni (2)
| Dosya | Ne yapar |
|---|---|
| `dns_inventory.py` | İstemci kimlik kanıtı: ARP/NDP MAC, Docker bridge, varsayılan ağ geçidi, host adresleri, AdGuard envanteri. Sınıflandırma ve **birleştirme kararı**. |
| `dns_anomaly.py` | Mevcut query-log örneğinden ölçüm tabanlı anomali tespiti. Hiçbir istemci/domain gömülü değil. |

### Değiştirilen (5)
| Dosya | Değişiklik |
|---|---|
| `dns_center.py` | Kimlik zenginleştirme, anomali, filtre listesi durumu, domain + query-type filtresi, 2 yeni endpoint |
| `templates/admin.html` | DNS sekmesi 6 alt bölüme ayrıldı; diğer 10 sekme **satır satır aynı** |
| `static/dns-center.js` | Sub-navigation, health strip, anomali/event kartları, client filtreleri, domain drawer, LIVE modu, grafik tooltip |
| `static/dns-center.css` | Sub-nav, health strip, anomali, timeline, live feed, semantik renkler, responsive, reduced-motion |
| `static/control-center.js` | **Sadece 2 satır:** hash artık `#dns/clients` gibi ikinci seviye taşıyor (`ccSubView`/`ccNavigate` hook'ları). Diğer sekmeler için davranış aynı. |

### Test (1)
`tests/test_dns_center.py` — 33 yeni test eklendi, mevcut testlerin hiçbiri silinmedi.

### Hash'i değişmeyen kritik dosyalar (doğrulandı)
`admin.py` · `alerts.py` · `dns_cluster.py` · `dns_alerts.py` · `app.py` · `history.py` ·
`static/admin.js` · `static/admin.css` · `static/style.css` · `static/design-system.css` ·
`static/control-center.css` · `templates/index.html` · `templates/admin_login.html`

---

## 2. Backup konumu

```
$BACKUP_ROOT/20260922T071917Z-dns-center-v2/
├── control-center/      değiştirilen her dosyanın değişiklik ÖNCESİ hali
├── AdGuardHome.yaml.readonly-reference   (salt okunur referans; config'e dokunulmadı)
└── SHA256SUMS.txt       23 dosya bütünlük manifesti
```

Geri alma: `workspace/dns-center-v2/RECOVERY.md`. Tek komutluk geri dönüş orada.

---

## 3. Eklenen özellikler

**Sub-navigation** — `Overview | Traffic | Clients | Domains | Resolvers | Query Log`.
Varsayılan Overview. Yatay kaydırılabilir, sticky, ana navbar'ın **altında** başlar
(çakışma 4 viewport'ta ölçüldü: ≤2 px). Seçim URL hash'inde (`#dns/clients`) — refresh
sonrası kaybolmuyor (test edildi).

**DNS Health Strip** — tamamı canlı: genel sağlık, Primary Node ve Secondary Node probe gecikmesi, cache
isabet %, engelleme %, upstream sağlığı, son probe yaşı.

**Topology** — 6 aşama: LAN CLIENTS → GATEWAY → RESOLVERS → CACHE/FILTER → UPSTREAM →
INTERNET. Upstream node'ları artık gerçek config'ten geliyor (Quad9, Cloudflare,
fallback), her biri tıklanınca detay açıyor. Router **gri** kaldı — "not health-probed
by this dashboard" ifadesi korundu.

**Traffic** — `1H | 6H | 24H | 7D`. AdGuard'ın granülaritesi saatlik olduğu için 1H tek
kova; çizgi yerine tek nokta olarak çiziliyor ve bu bilgi ekranda yazıyor. Hover
tooltip: zaman damgası, sorgu, engellenen, engelleme %. Ek gerçek istatistikler: peak
queries/hour, peak blocked/hour, average queries/hour, range total. **Cache tarihsel
serisi uydurulmadı** — AdGuard yayınlamıyor.

**Clients** — arama, kategori filtresi (All/Infrastructure/User devices/IoT/Unknown) ve
kapsam filtresi (All/Client/Infrastructure traffic). Yeni "Category" sütunu. Drawer'da
artık MAC, MAC tipi, known IPs, kimlik kanıtı, kategori kanıtı ve son sorgular var.

**Domains** — satırlar tıklanabilir; yeni domain drawer: örnek boyutu, ilk/son görülme,
engellenen, cached, query type dağılımı, top clients, eşleşen filtre kuralları.
**Güvenli/zararlı yorumu yapılmıyor** ve bu ekranda açıkça yazıyor.

**Resolvers** — cluster, primary resolver detayı, upstream karşılaştırması (fallback
kesikli çerçeveyle ayrı çiziliyor) ve filtre listeleri ayrı kartlarda.

**Query Log** — mevcut client filtresi + **yeni domain filtresi** + **yeni query-type
filtresi**. Server-side pagination korundu.

**LIVE modu** — 5 sn aralık, DOM'da en fazla 30 satır, replace (append değil) → liste
büyüyemez. Sadece Query Log bölümü açıkken, sekme ön plandayken ve LIVE açıkken
poll ediyor. Bölümden çıkınca polling'in durduğu tarayıcıda ölçüldü.

**DNS Events** — mevcut Alert Center kayıtlarından (`source='dns_center'`) raised/resolved
geçişleri + AdGuard'ın kendi filtre `last_updated` damgası. **Yeni kalıcı sistem
kurulmadı, geçmiş olay uydurulmadı.**

---

## 4. Yeni / değiştirilen API endpointleri

| Endpoint | Durum | Not |
|---|---|---|
| `GET /api/admin/dns-center` | genişletildi | +`identity`, +`category`, +`anomalies`, +`anomaly_window`, +`filters[].state` |
| `GET /api/admin/dns-center/client` | genişletildi | +`identity`, +`recent` (en fazla 10 satır) |
| `GET /api/admin/dns-center/recent` | genişletildi | +`domain`, +`type` parametreleri, +`post_filtered`/`fetched` |
| `GET /api/admin/dns-center/domain` | **yeni** | Domain detayı, sunucu tarafında toplanmış |
| `GET /api/admin/dns-center/events` | **yeni** | DNS olay zaman çizelgesi |

Hepsi aynı `@admin_required` dekoratörünü kullanıyor. Anonim erişim **401** (hem testte
hem canlı production'da doğrulandı). Girdi doğrulama sunucu tarafında:
domain allowlist karakter kümesi + ≤253 karakter, query type sabit allowlist, client ≤64.
Kabuk yok, string interpolasyonu yok — `ip` ve `docker` çağrıları sabit argv ve kullanıcı
girdisi hiç oraya ulaşmıyor.

---

## 5. Test sonuçları

| Test | Öncesi | Sonrası |
|---|---|---|
| **Python paketi** | 177 test / 494 subtest | **210 test / 502 subtest — hepsi geçti** |
| **Staging HTTP smoke** (gerçek login, gerçek CSRF) | — | **46/46 geçti** |
| **Tarayıcı regresyonu** (4 viewport, Chromium) | — | **140/140 geçti** |

Staging smoke kapsamı: 5 DNS endpoint'i anonim → 401; gerçek parola ile login; **yanlış
CSRF → 403**; 11 ana sekmenin hepsi sayfada; 6 DNS bölümü; geçerli/geçersiz filtre
kombinasyonları (limit, filter, type, domain, client); `/api/admin/control-center`,
`/api/status`, `/api/history`, `/api/events`, `/api/incidents`, public `/` hepsi 200.

Tarayıcı regresyonu kapsamı (desktop 1440 · tablet 1280×800 · tablet 800×1280 · telefon 390):
11 ana sekmenin hepsi açılıyor · 6 DNS bölümünün hiçbirinde **yatay taşma yok** · hash
kalıcılığı · sub-nav ana navbar'la çakışmıyor · **4 viewport'ta da 0 JS/console hatası** ·
traffic canvas 4 aralıkta da gerçekten piksel boyuyor · tooltip · client filtreleri ·
client ve domain drawer'ları · Escape ile kapanma · filtre listesinde **STOPPED yok**,
DISABLED gri · fallback ayrı çiziliyor · query log 3 filtresi · type filtresi ·
LIVE açık/kapalı + polling'in durması · `prefers-reduced-motion` animasyonu durduruyor.

---

## 6. Production servis durumu

```
metehantech-status.service   active (restart 2026-09-22 10:43:46 +03)
/           200        /admin        302 → login        /api/status  200
/api/admin/dns-center          401 (anonim)    ✔
/api/admin/dns-center/recent   401 (anonim)    ✔
/api/admin/dns-center/events   401 (anonim)    ✔
/api/admin/dns-center/domain   401 (anonim)    ✔
static/dns-center.js?v=subnav-v2   200, 63 234 B  (yeni kod serviste)
journal: 0 error / 0 traceback / 0 exception
```

Container restart sayıları **hepsi 0**: adguard · homeassistant · frigate ·
nextcloud-app · mosquitto. Public `/api/status` → `health: HEALTHY`, ki bu rollup
`dns_center.summary()`'yi de içeriyor → production collector yeni kodla sağlıklı
snapshot üretiyor. Public payload'da query log / domain / client geçmişi **yok**
(otomatik kontrol edildi).

Ölçülen ek maliyet: kimlik toplama **60 saniyede bir 64 ms** (cache'liyken 0.01 ms).
Ekstra AdGuard API çağrısı **yok** — anomali, cache oranı için zaten çekilen örneği
kullanıyor (testle sabitlendi: query-log çağrı sayısı 2, değişmedi).

---

## 7. DNS cluster durumu

```
Primary Node   <PRIMARY_NODE_IP>:53   answering ✔  filtering ✔  37.6 ms   HEALTHY
Secondary Node <SECONDARY_NODE_IP>:53   answering ✔  filtering ✔  36.0 ms   HEALTHY
cluster 2/2 HEALTHY · redundant
upstreams 3/3 healthy (Quad9 DoH · Cloudflare Security DoH · <ROUTER_IP> fallback)
```

Deploy sonrası bağımsız doğrulama: `dig @<PRIMARY_NODE_IP> example.com` → cevap,
`dig @<PRIMARY_NODE_IP> doubleclick.net` → `0.0.0.0`; aynısı Secondary Node için de.

---

## 8. Bulduğum gerçek anomaliler

### 8.1 RE305 **iki ayrı cihaz**, tek cihaz değil — birleştirilmedi
`<EXTENDER_B_LAN_IP>` → MAC `<AP_BSSID>` · `<EXTENDER_A_LAN_IP>` → MAC `<DEVICE_MAC>`.
İkisi de **universally administered** (rastgele değil) ve **farklı**. rDNS ikisine de
"RE305" diyor ama bu tek başına kanıt değil. Dashboard bunları ayrı satırda gösteriyor
ve satırda `DUPLICATE?` rozeti ile "different MAC — different hardware" gerekçesini
veriyor.

### 8.2 A72 iki IP'de — yine birleştirilmedi
`<CLIENT_A_LAN_IP>` → `<CLIENT_A_MAC>` · `<CLIENT_B_LAN_IP>` → `<CLIENT_B_MAC>`. İkisi de
**locally administered / rastgeleleştirilmiş** MAC. Aynı telefon olabilir de olmayabilir
de; rastgele MAC hiçbir şey kanıtlamaz. Gerekçe ekranda yazıyor: "MACs differ and at
least one is randomised, so they prove nothing". **Otomatik birleştirme yapılmadı.**

Birleştirme yalnızca iki durumda yapılıyor: (a) AdGuard'ın **insan tarafından gözden
geçirilmiş** persistent kaydı iki adresi de listeliyorsa (Primary Node ve Secondary Node böyle), (b)
komşu tablosunda **aynı universal MAC** iki adreste görünüyorsa.

### 8.3 `172.19.0.1` = Docker bridge gateway — kesin doğrulandı
`docker network inspect metehantech-dns_default` → `Gateway: 172.19.0.1`, subnet
`172.19.0.0/16`. Artık "Unknown client" değil,
**"Docker bridge gateway (metehantech-dns_default)"**, kanıtı da drawer'da yazıyor.
İsim çalışma zamanında daemon'dan türetiliyor, gömülü değil.

### 8.4 AdAway listesi gerçekten kapalı, hatalı değil
`enabled: false`, `rules_count: 0`, `last_updated: null`. Artık kırmızı **STOPPED**
değil, nötr gri **DISABLED**. Kırmızı `ERROR` yalnızca "açık ama kural yok" durumuna
ayrıldı.

---

## 9. RE305 `a.root-servers.net` trafiği — ölçüm

En yeni **2000 query-log satırı**, gerçek pencere **108.9 dakika** (2026-09-22 ~08:50–10:39 UTC+3):

| İstemci | Sorgu | Oran | Domain payı | Cache | Engellenen |
|---|---|---|---|---|---|
| `<EXTENDER_B_LAN_IP>` (RE305) | 757 | **7.0 sorgu/dk** | %99.9 `a.root-servers.net` | 756/757 | 0 |
| `<EXTENDER_A_LAN_IP>` (RE305) | 746 | **6.9 sorgu/dk** | %99.9 `a.root-servers.net` | 745/746 | 0 |

- `a.root-servers.net` **tüm örneğin %75'i** (1501/2000).
- AdGuard'ın 7 günlük sayacında bu iki cihaz **21 181 sorgunun 10 631'i = %50.2**.
- Yanıtların neredeyse tamamı **cache'ten** dönüyor (TTL 3 537 255 s), yani upstream'e
  gitmiyor ve internet trafiği üretmiyor. Engellenen: **0**.

Bu, TP-Link menzil genişleticilerinin klasik internet-bağlantı kontrolü paterni.
**Hiçbir şey yapılmadı:** engellenmedi, DNS rewrite eklenmedi, RE305 ayarı
değiştirilmedi, AdGuard filtresi eklenmedi. Sadece Overview'da ölçümüyle birlikte
bir ANOMALY kartı olarak gösteriliyor.

**Kart kendiliğinden kaybolur.** Eşikler: ≥30 örnek, ≥120 sn pencere, tek domain payı
≥%80 ve o domain için ≥3 sorgu/dk. Oran bunun altına düşerse backend kartı üretmeyi
bırakır; saklanan hiçbir durum yok (testle sabitlendi).

---

## 10. Bilerek YAPMADIĞIM / değiştirmediğim kritik şeyler

- ❌ AdGuard Home yapılandırması — `AdGuardHome.yaml`'a yazılmadı, hiçbir POST/PUT
  çağrısı yapılmadı. Sadece okuma endpoint'leri + AdGuard'ın kendi upstream testi.
- ❌ Primary Node ve Secondary Node resolver yapılandırması
- ❌ Upstream / fallback / bootstrap ayarları
- ❌ DHCP ve router yapılandırması
- ❌ DNS filtreleme kuralları — AdAway listesi **kapalı bırakıldı**, RE305 için kural
  eklenmedi, DNS rewrite oluşturulmadı
- ❌ RE305 cihazlarının kendi ayarları
- ❌ Authentication / CSRF / session / lockout / rate limit — `admin.py` tek byte
  değişmedi
- ❌ Alert Center çekirdeği ve DNS alarm kuralları — `alerts.py`, `dns_alerts.py`
  değişmedi; yeni alarm türü eklenmedi. Anomali kartı **alarm değil**, sadece görünüm.
- ❌ Cluster probe mantığı — `dns_cluster.py` değişmedi; 2/2 HEALTHY · 1/2 DEGRADED ·
  0/2 CRITICAL aynen duruyor
- ❌ Services, Camera, Nextcloud, Storage, Backups, Network, Alerts, Activity
  sekmelerinin içeriği — `admin.html` içinde ilgili blokların hiçbiri düzenlenmedi,
  `control-center.js` render fonksiyonuna dokunulmadı
- ❌ Public status sayfası ve `templates/index.html`
- ❌ Paylaşılan tasarım sistemi (`design-system.css`) — DNS'e özel geçersiz kılmalar
  `dns-center.css` içinde tutuldu
- ❌ Yeni kalıcı veritabanı / tablo / şema
- ❌ Cihaz sınıflandırmasında tahmin — rDNS ismi kategori belirlemiyor. Bugün
  `infrastructure` yalnızca kanıtla atanıyor (host adresi, ağ geçidi, Docker bridge,
  yapılandırılmış resolver). Kanıtı olmayan her şey dürüstçe **Unknown**.

### Doğrulanmayan tek şey
Fiziksel Samsung Tab S9 FE+ üzerinde **görsel** kontrol yapılmadı — production admin
parolası root-only `admin.env` içinde. Bunun yerine aynı kod, izole bir staging
örneğinde gerçek parola ile gerçek Chromium'da 1280×800 ve 800×1280 dahil dört
viewport'ta çalıştırıldı; ekran görüntüleri `workspace/dns-center-v2/` altında.

---

## 11. Notlar

- `pytest 9.1.1` proje venv'ine kuruldu (test paketini çalıştırmak için gerekiyordu).
  Sadece geliştirme bağımlılığı; gunicorn onu import etmiyor, `requirements.txt`
  değiştirilmedi.
- Playwright Chromium headless shell `~/.cache/ms-playwright` altına indirildi
  (tarayıcı regresyonu için).
- Ekran görüntüleri: `dns-1440.png`, `dns-tablet-12.4-landscape.png`,
  `dns-tablet-12.4-portrait.png`, `dns-phone-390.png`, `topo-1440.png`, `topo-tablet.png`.
- Tarayıcı testi tekrar çalıştırılabilir:
  `STAGE_PASSWORD=... node workspace/dns-center-v2/browser-check.cjs`
  (önce izole staging örneğini ayağa kaldırmak gerekiyor — RECOVERY.md'de anlatıldı).
