# MetehanTech — Ev Geneli DHCP DNS Cutover — RAPOR

**Durum: TAMAMLANDI ve DOĞRULANDI**
Cutover yazımı: `2026-09-21T16:09:01Z` (19:09 yerel)
Doğrulama penceresi: cutover + ~4.7 saat (2026-09-21 23:50 yerel)

---

## 1. Ne değişti

Archer AX55 router'ın DHCP sunucusunda **yalnızca iki alan**:

| Alan | Önce | Sonra |
|---|---|---|
| `pri_dns` | *(boş → router kendi <ROUTER_IP>'i dağıtıyordu)* | `<PRIMARY_NODE_IP>` (Primary Node AdGuard) |
| `snd_dns` | *(boş)* | `<SECONDARY_NODE_IP>` (Secondary Node AdGuard) |

Korunan ve canlı router'dan okunup **aynen geri yazılan** alanlar:
`enable=on`, `leasetime=120`, `gateway=<ROUTER_IP>`, `ipaddr_start=<DHCP_POOL_START>`,
`ipaddr_end=<DHCP_POOL_END>`, `domain=""`.

Router'da **başka hiçbir şey** değiştirilmedi: DHCP rezervasyonları (<primary-node>
→ .20, Secondary Node → .22), LAN ayarları, port yönlendirme, WiFi — hepsi ellenmedi.
Port forward açılmadı, kamera/hizmet dışarı açılmadı.

Yazım `router.py` ile yapıldı; router parolası gizli prompt ile alındı, argv'ye /
environment'a / shell history'ye / diske / bu rapora **girmedi**. Kaydedilen JSON
dosyaları `redact()` filtresinden geçti ve `0600` izinli.

---

## 2. Kanıtlar

### 2.1 Router write doğrulaması (yazım anı)
`router-cutover-result.json` — yazım sonrası router'dan **geri okundu**:
`pri_dns=<PRIMARY_NODE_IP>`, `snd_dns=<SECONDARY_NODE_IP>`, `verified: true`.
Diğer altı alan before/after **birebir aynı**.

### 2.2 Gerçek istemciler gerçekten yeni resolver'ları kullanıyor (son 60 dk)

`canary.py --minutes 60` çıktısı — AdGuard query log'undan **gerçek client IP'leri**:

**Primary Node (<PRIMARY_NODE_IP>) — 1000 sorgu** *(query log limiti, gerçek sayı daha yüksek)*

| İstemci | Sorgu | Ad |
|---|---|---|
| <EXTENDER_B_LAN_IP> | 301 | RE305 (menzil genişletici) |
| <EXTENDER_A_LAN_IP> | 299 | RE305 |
| <CLIENT_A_LAN_IP> | 291 | <PRIMARY_PHONE> (telefon) |
| <PRIMARY_NODE_IP> | 86 | Primary Node |
| <CLIENT_C_LAN_IP> | 10 | <CLIENT_PHONE> |
| <CLIENT_D_LAN_IP> / <CLIENT_E_LAN_IP> / <CLIENT_F_LAN_IP> / <CLIENT_G_LAN_IP> | 3-4 | L530 ampuller |

**Secondary Node (<SECONDARY_NODE_IP>) — 456 sorgu**

| İstemci | Sorgu | Ad |
|---|---|---|
| <CLIENT_A_LAN_IP> | 336 | telefon |
| <PRIMARY_NODE_IP> | 120 | Primary Node |

**Bu tablonun neden önemli olduğu:** router DNS proxy'si arkasında kalsaydık
*bütün* sorgular tek bir `<ROUTER_IP>` istemcisi olarak görünürdü. Gerçek per-cihaz
IP'lerin ve isimlerin görünmesi, cutover'ın gerçekten uygulandığının ve
**client identification'ın korunduğunun** doğrudan kanıtı. Ayrıca her iki
resolver'ın da canlı trafik aldığı görülüyor — DNS2 yazılıp unutulmuş değil.

**Gözlem:** Android telefon (.130) her iki resolver'a **paralel** soruyor (291 + 336).
Bu beklenen Android davranışı; pratikte failover'ı anlık yapıyor, ama sorgularının
yaklaşık yarısı ikincil sunucuya düşüyor.

### 2.3 Stub-resolver davranışı (`failover.py`, post-cutover 4.7h)

| Sorgu | Yanıtlayan | Süre | Sonuç |
|---|---|---|---|
| example.com | <PRIMARY_NODE_IP> | 0.8 ms | rcode=0 |
| doubleclick.net | <PRIMARY_NODE_IP> | 0.7 ms | **0.0.0.0 — engellendi** |
| cloudflare.com | <PRIMARY_NODE_IP> | 30.3 ms | rcode=0 |
| wikipedia.org | <PRIMARY_NODE_IP> | 60.9 ms | rcode=0 |
| doubleclick.net | <PRIMARY_NODE_IP> | 0.7 ms | **0.0.0.0 — engellendi** |
| github.com | <PRIMARY_NODE_IP> | 16.3 ms | rcode=0 |

**6/6 çözüldü**, 0 fallback gerekmedi, **filtreleme 2/2**. Önbellek isabetleri
sub-millisecond (0.7-0.8 ms).

### 2.4 AdGuard servis durumu (her iki düğüm)

| | Primary Node | Secondary Node |
|---|---|---|
| running / protection | True / True | True / True |
| sürüm | v0.107.79 | v0.107.79 |
| 24s sorgu | 7 526 | 2 796 |
| 24s engellenen | 719 | 510 |
| ort. işlem süresi | 30.74 ms | 21.54 ms |

### 2.5 Hiçbir servis etkilenmedi

8/8 Primary Node container'ı **`restarts=0`** ve healthy — Phase 0 baseline ile birebir aynı:
adguard, mosquitto, homeassistant, frigate, nextcloud-{cron,app,db,redis}.
`metehantech-status`, `cloudflared`, `tailscaled` → **active**.
Control Center canlı sağlık: **HEALTHY**.
Secondary Node: 7 gün 5 saat uptime, load 0.64.

### 2.6 Log taraması (cutover'dan bu yana 4.7 saat)

- `journalctl -p err`, brcmfmac hariç: **0 satır**.
  (brcmfmac WiFi sürücü gürültüsü **pre-existing**: cutover'dan önceki 7 saatte
  2203 kayıt. DNS ile ilgisi yok.)
- AdGuard container log'u: **45 satırda tek 1 error** — Quad9 DoH'a tek bir
  `unexpected EOF`, tek bir domain için (`consumer-downdetector-api.speedtest.net`).
  Geçici upstream gürültüsü, tekrar etmedi.

---

## 3. Doğrulanmamış / kapsam dışı bırakılanlar

- **Router config'inin şu anki canlı hali yeniden okunmadı.** `router.py --read-only`
  parola promptu gerektiriyor ve bu doğrulama oturumunda parola istenmedi.
  Dolaylı kanıt güçlü: lease süresi 120 dk, cutover'ın üzerinden 4.7 saat geçti,
  yani her istemci en az iki kez yeniledi ve hâlâ .20/.22'ye soruyor.
  Kesin teyit isteniyorsa: `python3 router.py --read-only`.
- **Gerçek ev geneli failover testi (Primary Node AdGuard'ı durdurup tüm ev cihazlarını
  ikincile düşürmek) yapılmadı.** Bu tüm haneyi etkileyen bir eylem; ayrı onay ister.
  Not: resolver seviyesinde failover, DHCP cutover'ından önce dns-redundancy
  fazında 6/6 gerçek sorgu ile zaten kanıtlanmıştı.
- Secondary Node container detayları okunamıyor — `metehanbackup` SSH hesabı docker grubunda
  değil (bilinen, kasıtlı kısıt). Secondary Node AdGuard sağlığı API üzerinden doğrulandı.
- Modem'in public IP `<WAN_PUBLIC_IP>` üzerinden DNS yanıtlaması **önceden var olan**
  bir bulgu; bu çalışma onu ne yarattı ne de değiştirdi. Hâlâ hat dışından tek bir
  `dig @<WAN_PUBLIC_IP> example.com` ile netleştirilmeyi bekliyor.

---

## 4. Geri alma

`RECOVERY.md` dosyasına bakın. Özet: `python3 router.py --rollback`, kaydedilmiş
**gerçek** eski değerlere (`pri_dns=""`, `snd_dns=""`) döner; diğer altı alan
yine korunur.
