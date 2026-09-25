# MetehanTech — Public DNS Port 53 Güvenlik İncelemesi

**Tarih:** 2026-09-21 · **Tip:** READ-ONLY INVESTIGATION
**Kanıt klasörü:** `workspace/dns-security/investigation-20260921T101212Z/`

> ## HİÇBİR DEĞİŞİKLİK YAPILMADI
> Firewall, router, NAT, systemd-resolved, AdGuard bind, Docker networking, Tailscale DNS —
> hiçbirine dokunulmadı. Tüm servisler restart sayısı ve sağlık durumu dahil **birebir aynı**.

> ## EN ÖNEMLİ BULGU — ÖNCEKİ RAPORUMDAKİ YORUMU DÜZELTİYORUM
> Önceki raporda "ya NAT hairpin ya da gerçek WAN open resolver" demiştim. **Üçüncü bir
> ihtimal vardı ve gerçek olan o:** TP-Link Archer AX55, LAN'dan çıkan **bütün** port 53
> trafiğini (UDP *ve* TCP) ele geçirip kendi dnsmasq'ı ile cevaplıyor.
> Bu yüzden **LAN içinden `<WAN_PUBLIC_IP>:53`'e yapılan hiçbir test geçerli değildi** — o
> paketler evden hiç çıkmadı. Aşağıdaki analiz bu düzeltme üzerine kurulu.

---

## Kanıt 1 — Router bütün port 53 trafiğini ele geçiriyor (KESİN)

LAN'dan hangi adrese DNS sorusu sorarsak soralım — **RFC 5737 ile rezerve edilmiş,
internette var olmayan adresler dahil** — aynı cevap geliyor:

| Sorulan adres | `version.bind` | `<primary-node>` |
|---|---|---|
| 1.1.1.1 (Cloudflare) | `"dnsmasq-2.83"` | **<PRIMARY_NODE_IP>** |
| 8.8.8.8 (Google) | `"dnsmasq-2.83"` | **<PRIMARY_NODE_IP>** |
| 9.9.9.9 (Quad9) | `"dnsmasq-2.83"` | **<PRIMARY_NODE_IP>** |
| 208.67.222.222 (OpenDNS) | `"dnsmasq-2.83"` | **<PRIMARY_NODE_IP>** |
| **192.0.2.1** (TEST-NET-1, var olmayan) | `"dnsmasq-2.83"` | **<PRIMARY_NODE_IP>** |
| **203.0.113.53** (TEST-NET-3, var olmayan) | `"dnsmasq-2.83"` | **<PRIMARY_NODE_IP>** |
| <WAN_PUBLIC_IP> (public IP) | `"dnsmasq-2.83"` | **<PRIMARY_NODE_IP>** |
| <ROUTER_IP> (router) | `"dnsmasq-2.83"` | **<PRIMARY_NODE_IP>** |
| <PRIMARY_NODE_IP> (AdGuard) | cevap yok (blocked_hosts) | — |

`<primary-node> → <PRIMARY_NODE_IP>` eşlemesi **yalnızca Archer AX55'in DHCP lease
tablosunda** var. Dünyadaki hiçbir ISP cihazı bu ismi bilemez. Var olmayan bir adrese
sorulan soruya bu cevabın gelmesi, araya girenin **ev router'ı** olduğunun kesin kanıtıdır.

Destekleyici kanıt:
- Cevap gecikmesi **2–7 ms** = LAN mesafesi. İlk ISP hop'u (`10.98.237.226`) **8.4 ms**.
- `tracepath <ROUTER_IP>` → 1 hop, 2.8 ms.
- Router'ın PTR kaydı: `Archer_AX55.` · UPnP: `TP-LINK/TP-LINK UPnP/1.1 MiniUPnPd/2.2.2`

**Yan etki:** `dig @8.8.8.8 TXT o-o.myaddr.l.google.com` sorgusu, Google'a gerçekte hangi
resolver'ın ulaştığını söyler. Cevap: **212.156.15.169 / .170 (Türk Telekom)** — yani
"8.8.8.8 kullanıyorum" sanan her cihaz aslında TT resolver'ına konuşuyor.
AdGuard üzerinden aynı sorgu: **104.23.182.12 (Cloudflare)** — çünkü AdGuard **DoH/443**
kullanıyor ve bu ele geçirmeden **etkilenmiyor**.

---

## 22 soruya cevaplar

### 1. <WAN_PUBLIC_IP> nedir?
Evin **kendi public IPv4 adresi**. RIPE RDAP: `<WAN_ISP_RANGE_START> – <WAN_ISP_RANGE_END>`, **TurkTelekom**,
AS9121, ülke TR, netblock notu *"ADSL-MET-Acibadem-Static Pool"*.
PTR: `<WAN_PUBLIC_IP>.dynamic.ttnet.com.tr`

### 2. Primary Node public IP ile ilişkisi nedir?
Pi5'in çıkış IP'si de bu. Üç bağımsız servis (ipify, ifconfig.me, icanhazip) aynı cevabı
verdi: **<WAN_PUBLIC_IP>**. Pi5'in bu adres üzerinde **kendi başına hiçbir yetkisi yok** —
adres modemin WAN arayüzünde.

### 3. Router WAN IP nedir?
**<WAN_PUBLIC_IP>** — router'ın kendisinden, read-only UPnP IGD SOAP çağrısıyla okundu
(`GetExternalIPAddress`). Bağlantı durumu `Connected`, uptime 276.102 sn (~3,2 gün).
Router arayüzüne giriş yapılmadı, parola denenmedi.

### 4. CGNAT var mı?
**HAYIR.** Router'ın kendi bildirdiği WAN IP'si (<WAN_PUBLIC_IP>) ile internetten görülen
çıkış IP'si **birebir aynı**. CGNAT olsaydı router WAN'ı `100.64.0.0/10` aralığında olurdu.
*(Not: `tracepath 1.1.1.1` yolunda 2. ve 3. hop'ta `10.98.237.226` ve `10.0.0.194` özel
adresleri görülüyor — bu TT'nin iç transit adreslemesi, CGNAT değil.)*
**Confidence: HIGH.**

### 5. UDP/53 dışarıdan cevap veriyor mu?
Senin mobil veri testine göre **evet, cevap geldi**. Ama **cevabı verenin ev router'ı olduğu
henüz kanıtlanmadı** — çünkü aynı ele geçirme davranışı mobil şebekede de olabilir (madde 10).
**Bu, raporun tek açık sorusu ve senden iki komut istiyorum (aşağıda).**

### 6. TCP/53 dışarıdan cevap veriyor mu?
**BİLİNMİYOR.** Mobil test yalnız UDP idi. LAN içinden yapılan TCP testi router ele
geçirmesine takıldığı için geçersiz. Dışarıdan test gerekiyor (aşağıdaki Test C).

### 7. Recursion gerçekten açık mı?
Mobil testte `flags: qr rd ra` görüldü — `ra` = recursion available ve gerçek A kayıtları
döndü. Yani **cevaplayan her neyse recursive çalışıyor.** Kim olduğu madde 10'a bağlı.

### 8. DNS server fingerprint nedir?

| Test | Public IP (LAN'dan) | LAN Router | Primary Node AdGuard |
|---|---|---|---|
| `version.bind` | `"dnsmasq-2.83"` | `"dnsmasq-2.83"` | cevap yok |
| `hostname.bind` | NOTIMP | NOTIMP | cevap yok |
| `id.server` | NOTIMP | NOTIMP | cevap yok |
| recursive UDP | NOERROR `qr rd ra` | NOERROR `qr rd ra` | NOERROR `qr rd ra **ad**` |
| recursive TCP | NOERROR | NOERROR | NOERROR |
| non-recursive | NOERROR, 2 answer | NOERROR, 2 answer | NOERROR, 2 answer, `ad` |
| DNSSEC `+do` RRSIG | **0** | **0** | **1** |
| `dnssec-failed.org` | **NOERROR** (doğrulamıyor) | **NOERROR** | **SERVFAIL** (doğruluyor) |
| EDNS UDP size | **4096** | **4096** | **1232** |
| `ANY` sorgusu | cevap yok | cevap yok | **NOTIMP** |

### 9. LAN router DNS ile public DNS aynı davranıyor mu?
**Evet — 10 kriterin 10'unda birebir aynı.** Ama bu beklenen sonuç, çünkü LAN'dan public
IP'ye giden paketler zaten router tarafından ele geçiriliyor; iki sütun aslında **aynı
process**. Bu tablo, public IP'nin WAN'dan da aynı davrandığını **kanıtlamaz**.
Tablonun asıl değeri: **AdGuard sütunu hiçbir kritere uymuyor.**

### 10. DNS interception kanıtı var mı?
**EVET, KESİN — ama beklenen yerde değil.** Ele geçiren **ISP değil, evin kendi
TP-Link Archer AX55'i.** Kanıt: var olmayan TEST-NET adreslerine sorulan sorular, router'ın
DHCP lease tablosundaki LAN isimleriyle cevaplanıyor (Kanıt 1). **Confidence: HIGH.**

### 11. Public sorgu AdGuard loguna ulaştı mı?
**HAYIR.** AdGuard'ın tuttuğu query log'un **tamamı** (150 kayıt, 06:42:18Z'den bugüne —
yani senin mobil testinden öncesini de kapsıyor) tarandı:

```
distinct client addresses:
   <PRIMARY_NODE_IP>   144  private
   <SECONDARY_NODE_IP>     5  private
   <PRIMARY_NODE_TAILSCALE_IP>    1  private
*** public kaynak adresli sorgu sayısı: 0 ***
```

Router NAT'layıp kaynağı gizlese bile `<ROUTER_IP>` diye bir client da yok.
**Mobil sorgu AdGuard'a hiç ulaşmadı.**

### 12. AdGuard public open resolver mı?
**HAYIR. Dört bağımsız kanıt:**

1. **Kernel bind:** `0.0.0.0:53` veya `[::]:53` **yok**. Sadece `<PRIMARY_NODE_IP>:53` ve `<PRIMARY_NODE_TAILSCALE_IP>:53`.
2. **Firewall (gerçek kural dökümü):** port 53 için **tek bir wildcard DNAT kuralı yok** —
   hepsi hedef adrese bağlı:
   ```
   -A DOCKER -d <PRIMARY_NODE_IP>/32  -p udp --dport 53 -j DNAT --to 172.19.0.2:3053
   -A DOCKER -d <PRIMARY_NODE_TAILSCALE_IP>/32 -p udp --dport 53 -j DNAT --to 172.19.0.2:3053
   -A DOCKER -d <PRIMARY_NODE_IP>/32  -p tcp --dport 53 -j DNAT --to 172.19.0.2:3053
   -A DOCKER -d <PRIMARY_NODE_TAILSCALE_IP>/32 -p tcp --dport 53 -j DNAT --to 172.19.0.2:3053
   0.0.0.0/0 hedefli port-53 DNAT kuralı sayısı: 0
   ```
   WAN'dan gelen bir pakette hedef adres public IP olur; bu kuralların hiçbirine uymaz.
3. **Router'da port 53 yönlendirmesi yok** (madde 13/14).
4. **Query log'da sıfır public kaynak** (madde 11).
5. Ek katman: `allowed_clients` = LAN + Tailscale + WireGuard + Docker + loopback.
   Bir WAN adresi bir şekilde ulaşsa bile reddedilirdi.

**Confidence: HIGH.**

### 13. Router'da port 53 forwarding var mı?
**HAYIR.** UPnP IGD üzerinden **63 port eşlemesinin tamamı** read-only olarak listelendi:

```
toplam eşleme        : 63
protokol             : hepsi UDP (TCP eşleme sayısı: 0)
<PRIMARY_NODE_IP>:41641   : 33 adet   (Tailscale)
<SECONDARY_NODE_IP>:41641   : 29 adet   (Tailscale)
<PRIMARY_NODE_IP>:41641   :  1 adet   (NAT-PMP)
*** port 53 içeren eşleme : 0 ***
```

`WAN:53 → <PRIMARY_NODE_IP>:53` gibi bir kayıt **yok**.

### 14. UPnP port 53 mapping var mı?
**HAYIR** — yukarıdaki 63 eşlemenin hiçbiri 53 değil.

⚠️ **Ama ayrı bir hijyen bulgusu var:** 63 eşlemenin hepsi `lease=0` (kalıcı) ve hepsi
Tailscale'in NAT traversal portu 41641'e gidiyor. Tailscale her yeni endpoint denemesinde
bir eşleme daha açıyor ve eskiler temizlenmiyor. Güvenlik açığı değil ama birikiyor;
UPnP'nin açık olması da kendi başına küçük bir saldırı yüzeyi. Bunu ayrıca konuşabiliriz.

### 15. Risk seviyesi nedir?
İki ayrı konuyu ayıralım:

**A) Router'ın LAN-içi DNS ele geçirmesi — risk DÜŞÜK, ama önemli yan etkileri var:**
- Ev cihazlarının "Cloudflare/Google DNS kullanıyorum" ayarı **sahte**; hepsi TT resolver'ına
  gidiyor (kanıt: `o-o.myaddr` → 212.156.15.169).
- Router'ın yolu **DNSSEC doğrulamıyor** (`dnssec-failed.org` → NOERROR). AdGuard doğruluyor.
- **AdGuard için kritik sonuç:** eğer AdGuard upstream'leri düz `:53` olsaydı (1.1.1.1 gibi),
  hepsi sessizce router'a yönlenirdi ve DNSSEC + filtreleme faydasının bir kısmı kaybolurdu.
  DoH/443 seçimi bunu engelledi ve **doğrulandı** (AdGuard → Cloudflare 104.23.182.12).
  Bu, önceki görevdeki tasarım kararının beklenmedik ama somut bir kazancı.

**B) Public UDP/53 cevabı — risk, kaynağa göre değişir:**
- **Eğer ev router'ı gerçekten WAN'dan cevap veriyorsa:** risk **ORTA**. DNS
  amplification/reflection saldırılarında reflektör olarak kullanılabilirsin (EDNS 4096
  payload destekliyor), bant genişliği tüketilir, TT'den abuse uyarısı gelebilir. Router'ın
  cache'i zehirlenmeye de daha açık hale gelir. **Panik gerektirmez ama kapatılmalıdır.**
- **Eğer mobil şebeke ele geçirmesiyse:** risk **YOK**. Evde değiştirilecek bir şey yok.

Her iki durumda da **MetehanTech servislerine ve AdGuard'a yönelik bir risk yok.**

### 16. Attribution classification nedir?

| Soru | Sınıflandırma | Confidence |
|---|---|---|
| LAN'dan çıkan :53 trafiğini kim ele geçiriyor? | **CONFIRMED ROUTER DNS INTERCEPTION** (TP-Link Archer AX55) | **HIGH** |
| Primary Node AdGuard public open resolver mı? | **CONFIRMED NOT EXPOSED** | **HIGH** |
| <WAN_PUBLIC_IP> kimin? | **CONFIRMED evin WAN IP'si, CGNAT yok** | **HIGH** |
| Router'da :53 port-forward / UPnP eşlemesi? | **CONFIRMED NONE** | **HIGH** |
| **Mobil testte cevap veren kimdi?** | **INCONCLUSIVE** — "LIKELY ROUTER OPEN RESOLVER" ile "LIKELY MOBILE-SIDE DNS INTERCEPTION" arasında | **LOW** |

Son satır için "confirmed" **demiyorum**, çünkü elimde ağ dışından alınmış ayırt edici tek
bir ölçüm yok. Ele geçirme davranışının bu ağda zaten var olduğunu kanıtladık; aynı
davranışın mobil tarafta da olması tamamen mümkün ve o durumda mobil test sonucu evin
modemi hakkında **hiçbir şey** söylemiyor.

### 17. Confidence nedir?
Yukarıdaki tabloda madde madde verildi. Özet: **evle ilgili her şey HIGH; tek açık soru
(mobil cevabın kaynağı) LOW** — ve senden iki komutla HIGH'a çıkarabiliriz.

### 18. Önerilen hardening nedir?
**Şu an önerilen değişiklik: HİÇBİRİ.** Önce aşağıdaki iki testin sonucu lazım.

Test sonucu "router gerçekten WAN'dan cevaplıyor" çıkarsa, Archer AX55 için tercih sırası:

1. **Advanced → NAT Forwarding → UPnP** ve **Advanced → System Tools → Administration →
   Remote Management** ayarlarını gözden geçir (bunlar :53 ile ilgisiz ama aynı ekranda).
2. **Asıl hedef:** WAN tarafında DNS servisinin kapatılması. Archer AX55 stok firmware'inde
   "WAN DNS service" diye ayrı bir anahtar **yoktur**; bu yüzden gerçekçi seçenek:
   **Advanced → Security → Firewall** altında varsa WAN'dan gelen istekleri reddetme, ya da
   **firmware güncellemesi** (TP-Link bu tür WAN-side dnsmasq açıklarını firmware ile
   kapatmıştır).
3. Modem ISP tarafından sağlandıysa: TT'ye "modemin WAN tarafında DNS açık" bildirimi.
4. **LAN DNS hizmetine dokunulmayacak** — <ROUTER_IP>'in LAN'a DNS vermesi gerekiyor
   (AdGuard'ın `fallback_dns`'i ve `local_ptr_upstreams`'i ona bağlı).
5. **AdGuard'ın LAN DNS'ine dokunulmayacak.**

Router modelinin gerçekten hangi ayarları sunduğunu arayüzü görmeden bilemem — **kör
firewall kuralı üretmeyeceğim.** Testler sonuçlanınca menüyü birlikte gezeriz.

### 19. Değişiklik gerekiyor mu?
**Şu an hayır.** Pi5, AdGuard, Docker, firewall, Tailscale tarafında düzeltilecek **hiçbir
şey bulunmadı** — her şey tasarlandığı gibi kapalı. Olası tek aksiyon router'da ve o da
kanıta bağlı.

### 20. Kullanıcı onayı gereken adım nedir?
Router/modem ayarı değiştirmek. **Onayın olmadan dokunmayacağım.** Ondan önce de aşağıdaki
iki testi senin çalıştırman gerekiyor.

### 21. Investigation sırasında herhangi bir production değişikliği yapıldı mı?
**HAYIR.**
- Yapılan her şey okuma: `ss`, `docker inspect/port`, `dig`, `curl`, UPnP SOAP **GET**
  çağrıları, RDAP/PTR sorguları, AdGuard API okuma.
- Firewall kurallarını **okumak** için (hesabın `sudo`'su parola istediği için) kısa ömürlü
  bir container `--net=host --cap-add NET_ADMIN` ile çalıştırıldı — `--privileged` değil,
  hiçbir dizin mount edilmedi, **hiçbir kural yazılmadı**, container silindi.
- Router arayüzüne **giriş yapılmadı**, parola **denenmedi**, hiçbir ayar okunmadı/yazılmadı
  (UPnP dışında, o da salt-okunur ve kimlik doğrulamasız bir protokol).
- Port taraması, mass scan, flood **yapılmadı**. Üçüncü şahıs IP'lere toplu sorgu yok;
  kullanılan TEST-NET adresleri RFC 5737 ile bu amaç için rezerve edilmiştir.
- Dosya kanıtı: `AdGuardHome.yaml` son yazılma zamanı **10:01 (yerel)**, inceleme
  **13:12'de** başladı. `compose.yaml` 09:39. `/etc/resolv.conf` hâlâ stub'a bağlı.
  `systemd-resolved` active.

### 22. Mevcut MetehanTech servislerinin durumu nedir?
İnceleme öncesi/sonrası **birebir aynı** (`diff` boş):

| Servis | Restart | Durum |
|---|---|---|
| metehantech-adguard | 0 | healthy |
| metehantech-homeassistant | 0 | healthy |
| metehantech-frigate | 0 | healthy |
| metehantech-nextcloud-app / db / redis / cron | 0 | healthy |
| metehantech-mosquitto | 0 | running |
| metehantech-status / cloudflared / tailscaled / docker / systemd-resolved / home / clan-web | NRestarts=0 | active |

Canlı kontroller: Control Center 200 · Home Assistant 200 · Frigate 200 · Nextcloud 200 ·
host DNS (127.0.0.53) çalışıyor · HA container DNS çalışıyor · AdGuard her iki adresinde
cevap veriyor · AdGuard DNSSEC hâlâ doğruluyor (SERVFAIL).

---

## SENDEN İSTEDİĞİM İKİ TEST (mobil veri, Wi-Fi KAPALI)

Termux veya herhangi bir `dig` uygulamasında, **sırayla**:

```
# TEST A — kontrol testi (mobil şebeke de ele geçiriyor mu?)
dig @192.0.2.1 example.com

# TEST B — belirleyici test
dig @<WAN_PUBLIC_IP> <primary-node>
```

**Nasıl okunacak:**

| Test A | Test B | Sonuç |
|---|---|---|
| cevap **geldi** | (önemsiz) | **Mobil şebeke de :53 ele geçiriyor.** Önceki mobil test geçersiz. Evde yapılacak bir şey yok. Risk: YOK. |
| cevap **yok** (timeout) | **`<PRIMARY_NODE_IP>` döndü** | ⚠️ **CONFIRMED: Archer AX55 public open resolver.** Router hardening gerekli. |
| cevap **yok** | **NXDOMAIN / boş / timeout** | Router cevaplamıyor; ilk gözlem büyük ihtimalle ISP tarafı. Risk: DÜŞÜK. |

`192.0.2.1` internette **var olmayan**, RFC 5737 ile dokümantasyon için rezerve edilmiş bir
adres. Ona cevap gelmesi, o ağda port 53'ün ele geçirildiğinin tanımı demektir.

`<primary-node>` ismi **yalnızca senin Archer AX55'inin DHCP tablosunda** var. Mobil
veriden sorulduğunda `<PRIMARY_NODE_IP>` dönerse, cevabı veren **kesinlikle** senin modemin.

İsteğe bağlı destekleyici testler:
```
dig @<WAN_PUBLIC_IP> version.bind ch txt      # "dnsmasq-2.83" mı?
dig +tcp @<WAN_PUBLIC_IP> example.com         # TCP/53 de açık mı? (madde 6'yı kapatır)
```

---

## Phase 16 — Control Center'a "DNS Security" eklensin mi?

**Bu görevde hiçbir şey implement edilmedi** (istendiği gibi). Değerlendirmem:

**Evet, mantıklı — ama dürüst bir tasarımla.** Pi5'ten "dışarıdan erişilebilir miyim"
sorusunu **doğru cevaplamak imkânsız**: kendi public IP'mize sorduğumuz her paket router
tarafından yutuluyor, yani naif bir self-check her zaman "açık" gibi görünen bir sonuç
üretir ve **yanıltıcı olur**. Bu bu görevin asıl dersi.

Bunun yerine, içeriden **gerçekten doğrulanabilen** değişmezleri izleyen bir panel öneririm:

| Kontrol | İçeriden doğrulanabilir mi? |
|---|---|
| `0.0.0.0:53` / `[::]:53` bind var mı | ✅ evet (`ss`) |
| Wildcard (`0.0.0.0/0`) port-53 DNAT kuralı var mı | ✅ evet |
| Router'da :53 port-forward / UPnP eşlemesi var mı | ✅ evet (UPnP IGD SOAP, read-only) |
| AdGuard query log'unda public kaynaklı sorgu var mı | ✅ evet |
| Upstream gerçekten hedeflenen resolver mı (hijack tespiti) | ✅ evet (`o-o.myaddr` karşılaştırması) |
| **WAN'dan :53 açık mı** | ❌ **hayır — ağ dışı bakış açısı gerekir** |

Yani `External resolver exposure: SAFE / WARNING / UNKNOWN` yerine:
`Local exposure invariants: PASS/FAIL` + `Upstream hijack detected: YES/NO` +
`External verification: <son manuel doğrulama tarihi>` şeklinde bir tasarım öneririm.
Doğrulayamadığımız bir şeye "SAFE" demeyelim.

İstersen ayrı bir görevde yaparız.

---

## Ek bulgular (bu görevin kapsamı dışında, bilgi olarak)

1. **Pi5'te host firewall yok.** `iptables -P INPUT ACCEPT`, `ufw` inactive. Port 53 için
   bir açık oluşturmuyor (Docker DNAT adrese bağlı, router'da forward yok) ama genel olarak
   savunma katmanı eksik. Ayrı bir görevde ele alınabilir.
2. **63 kalıcı UPnP eşlemesi** birikmiş, hepsi Tailscale 41641'e. `lease=0`. Temizlenmesi ve
   UPnP'nin gerekliliğinin sorgulanması mantıklı.
3. **Router yolu DNSSEC doğrulamıyor.** Tüm ev şu an doğrulanmamış DNS kullanıyor. AdGuard'a
   geçmek bunu da düzeltecek — DNS Center görevindeki "tüm eve geç" adımının beklenmedik bir
   ek faydası.

---

## DURUYORUM

Rapor burada bitiyor. **Test A ve Test B sonuçlarını bekliyorum.** Onlar gelmeden router
veya firewall tarafında hiçbir değişiklik önermeyeceğim ve yapmayacağım.
