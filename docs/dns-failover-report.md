# MetehanTech — Safe DNS Failover Discovery & Design

**Tarih:** 2026-09-21 · **Tip:** DISCOVERY + DESIGN. **Hiçbir şey deploy edilmedi.**
**Kanıt:** `workspace/dns-failover/`

> ## HİÇBİR DEĞİŞİKLİK YAPILMADI
> Router DHCP/DNS, AdGuard, systemd-resolved, NetworkManager, firewall, Secondary Node — hiçbirine
> dokunulmadı. Hiçbir container restart edilmedi. Ölçümler, production'a hiç değmeyen
> tek kullanımlık test container'larında yapıldı.

> ## ÖNCE ACI GERÇEK
> İstediğin dört şeyin **hepsini aynı anda** Archer AX55 + tek Primary Node ile sağlayan bir
> yapılandırma **yok**. "Primary Node çalışırken hiç bypass olmasın" ile "Primary Node ölünce internet
> devam etsin" bu donanımda birbiriyle çelişiyor — ve bunu tahmin ederek değil,
> **bu ağda ölçerek** söylüyorum. Aşağıda ölçümler, sebebi ve en iyi pratik denge var.

---

## 1. Ölçülen gerçekler (tahmin değil)

### 1.1 Router şu anda ne dağıtıyor?

Pi5'in kendi DHCP lease'inden okundu:

```
domain_name_servers = <ROUTER_IP>        <- TEK DNS sunucusu, secondary yok
routers             = <ROUTER_IP>
dhcp_server_identifier = <ROUTER_IP>
dhcp_lease_time     = 4294967295         <- sonsuz (DHCP rezervasyonu olduğu için)
```

⚠️ **Operasyonel uyarı:** rezervasyonlu cihazların lease'i sonsuz. DHCP DNS'i
değiştirdiğinde bu cihazlar **kendiliğinden yeni ayarı almaz** — Wi-Fi kapat/aç veya
yeniden bağlanma gerekir. Bu hem deployment hem de **rollback** hızını etkiler.
Deployment öncesi router'da *Address Lease Time* değerine bakmalıyız.

### 1.2 Router LAN→LAN :53 trafiğini ele geçiriyor mu? **HAYIR** (kritik)

Secondary Node'dan (<SECONDARY_NODE_IP>) doğrudan Pi5'e soruldu:

| Sorgu | @<PRIMARY_NODE_IP> (AdGuard) | @<ROUTER_IP> (Router) |
|---|---|---|
| `dnssec-failed.org` | **SERVFAIL** | NOERROR |
| `doubleclick.net` | **0.0.0.0** | 172.217.16.142 |

AdGuard'ın parmak izi (DNSSEC doğrulama + filtreleme) net şekilde geliyor. Yani
**bir istemci <PRIMARY_NODE_IP>'yi DNS olarak kullandığında gerçekten AdGuard'a ulaşıyor**,
router araya girmiyor. Sebep: aynı subnet'teki trafik L2'de köprüleniyor, router'ın
L3 PREROUTING kuralına hiç uğramıyor.

Bu, Mimari A ve C'nin temel ön koşulu ve **doğrulandı.**

### 1.3 İki DNS verirsek istemciler ne yapıyor? **ÖLÇÜLDÜ**

Tek kullanımlık container'larda, `DNS1=<PRIMARY_NODE_IP> (AdGuard)`, `DNS2=<ROUTER_IP> (Router)`,
**ikisi de sağlıklıyken**. Ayırt edici: `doubleclick.net` → `0.0.0.0` ise AdGuard cevapladı,
gerçek IP ise router cevapladı (= bypass).

| İstemci resolver'ı | AdGuard | Router (bypass) | Bypass oranı |
|---|---|---|---|
| **glibc** (Debian — çoğu Linux, muhtemelen Windows'a yakın) | 29/30 | 1/30 | **%3** |
| **musl** (Alpine — birçok IoT, gömülü cihaz) | 11/30 | 19/30 | **%63** |
| Sıra ters çevrilince (DNS1=Router) | 0/20 | 20/20 | %100 |

**Sebep:** glibc **sıralı** sorar (önce 1., timeout olursa 2.). musl **ikisine aynı anda**
sorar ve **ilk gelen cevabı** alır. Her iki sunucu da ~2 ms olduğu için bu bir yazı-tura;
AdGuard Docker DNAT üzerinden geçtiği için yarışı sık kaybediyor. **AdGuard'ı hızlandırarak
bu düzelmez** — engellenen alan adında bile AdGuard zaten anında cevap veriyor.

Bağımsız doğrulama: AdGuard'ın kendi query log'u bu testler sırasında 172.19.0.1'den
134 `doubleclick.net` sorgusu kaydetti — container'ların gördüğüyle tutarlı.

> **Not:** Android, Windows ve evdeki IoT cihazları **ölçülmedi**. Onları tahmin etmiyorum;
> Faz 9 test planı tam olarak bunu ölçmek için var.

### 1.4 Failover ne kadar sürer? **ÖLÇÜLDÜ**

Primary'yi karartarak (AdGuard'a hiç dokunulmadan):

| Senaryo | glibc | musl |
|---|---|---|
| Primary sessiz (host yok) — *"Primary Node tamamen kapalı"* | **her sorguda 3,1 sn** | **0 ms** |
| Primary connection-refused — *"Primary Node açık, AdGuard container down"* | **her sorguda 5,0 sn** | **0 ms** |
| **Tek DNS sunucusu var ve o ölü** | **12,3 sn sonra BAŞARISIZ** | başarısız |

İki önemli sonuç:
- glibc **her sorguda** yeniden primary'yi deniyor — "yapışkan" davranmıyor. Yani Pi5
  kapalıyken internet çalışır ama **her isim çözümlemesi 3–5 sn gecikir**. Kullanılabilir
  ama belirgin şekilde yavaş. Bu, `options timeout:1 attempts:1` ile düzeltilebilir ama
  DHCP bu seçeneği dağıtamaz — istemci başına ayar gerekir.
- **Tek DNS sunucusu dağıtmak felakettir**: Primary Node ölürse isim çözümleme tamamen durur.

### 1.5 Router upstream seçimi — strict priority var mı? **DOĞRULANAMADI**

6 örnek, hepsi farklı çıkış IP'si:
`212.156.15.130 / .131 / .133 / .144 / .162 / .174` (Türk Telekom resolver çiftliği).

Karşılaştırma — AdGuard aynı sürede sadece 3 IP kullandı (74.63.25.233 = Quad9,
104.23.182.12/13 = Cloudflare), yani kendi iki DoH upstream'ine sadık.

Bu **kanıtlamıyor** ki router iki upstream arasında geziniyor — bu değişkenlik tamamen
TT'nin kendi anycast altyapısından da geliyor olabilir. **Ayırt edemiyorum.** Bu yüzden
"router strict primary/secondary yapar" **diyemem** → Mimari B için belirleyici bir bilinmez.

---

## 2. 14 soruya cevaplar

### 1. Archer AX55 gerçek upstream DNS failover destekliyor mu?
**HAYIR / UNSUPPORTED.**
Aradığın davranış — *"<PRIMARY_NODE_IP>:53 sağlıklı mı diye aktif health-check yap, sağlıklıysa
oraya yolla, değilse ISP'ye düş"* — bir CPE DNS relay'inde bulunan bir özellik değil.
Archer AX55 stok firmware'i dnsmasq 2.83 çalıştırıyor; dnsmasq'ta **upstream health-check
diye bir kavram yoktur**. Birden çok upstream verilirse dnsmasq bunları yanıt süresine göre
dener/yayar, ama "öncelikli + sağlık kontrollü" semantiği yoktur.
Router arayüzüne giriş yapmadım (parola denemedim), dolayısıyla menüde gizli bir özellik
olmadığını **%100 kanıtlayamam** — ama bu sınıf cihazda bu özelliğin bulunması gerçekçi değil.
**Confidence: HIGH.**

### 2. DNS1=Primary Node + DNS2=Router yaparsak Primary Node çalışırken secondary kullanılır mı?
**EVET — ve bu bir ihtimal değil, ölçülmüş bir gerçek.**
glibc'de **%3**, musl'de **%63**. Ayrıntı için 1.3.
Bu bir "arıza" değil, resolver kütüphanelerinin tasarımı. RFC'de "primary/secondary" diye
bir kavram yok; işletim sistemleri listeyi istedikleri gibi kullanmakta serbest.

### 3. Router yalnız kendisini DHCP DNS olarak dağıtıp AdGuard'ı upstream yapabiliyor mu?
**DOĞRULANAMADI — ve doğrulansa bile önermem.** Üç ayrı sebep:

1. Archer'ın WAN/upstream DNS alanına bir **LAN adresi** (<PRIMARY_NODE_IP>) kabul edip etmediği
   bilinmiyor; birçok TP-Link firmware'i bunu reddeder. Arayüze girmeden doğrulanamaz.
2. Kabul etse bile (Soru 1) **sağlık kontrollü öncelik yok** — router AdGuard ile ISP
   resolver'ı arasında yayılım yaparsa AdGuard yine bypass edilir, üstelik bu sefer
   **görünmez** şekilde.
3. 🔴 **En ağır sebep — DNS Center'ı yok eder.** Bu mimaride AdGuard'a gelen her sorgunun
   kaynağı `<ROUTER_IP>` olur. Az önce kurduğumuz **client identification, Top Clients,
   per-device istatistik ve client filtresi tamamen anlamsızlaşır** — tüm ev tek bir
   istemci gibi görünür.

**Öneri: kullanma.**

### 4. Bu yapıda AdGuard ölürse router otomatik ISP DNS'e geçebiliyor mu?
**BİLİNMİYOR, muhtemelen hayır — en azından istediğin anlamda değil.**
dnsmasq ölü bir upstream'e sorguyu gönderir, timeout bekler, sonra diğerini dener. Bu
"failover" değil, "her sorguda gecikme". Sağlık kontrolü yok, hızlı geçiş yok, otomatik
geri dönüş garantisi yok. Kanıtlanmamış davranışa mimari kurmam.

### 5. Router'ın mevcut DNS interception özelliği burada işe yarayabilir mi?
**HAYIR — ve bu, en çok umut bağlanabilecek fikrin neden çalışmadığının açıklaması.**

Interception **yalnızca LAN'dan çıkmaya çalışan** trafiği yakalıyor (L3 PREROUTING).
`<PRIMARY_NODE_IP>:53`'e giden bir paket **aynı subnet içinde** kalıyor, router'ın IP katmanına
hiç uğramıyor (1.2'de ölçüldü). Dolayısıyla Primary Node kapandığında router o paketleri
"yakalayıp kurtaramaz" — istemci sadece ARP cevabı alamaz ve timeout'a düşer.

Yan bulgu, faydalı: bu ağda secondary olarak `1.1.1.1` yazmak ile `<ROUTER_IP>` yazmak
**tamamen aynı şeydir** — 1.1.1.1'e giden paket zaten router tarafından yakalanıp kendi
dnsmasq'ıyla cevaplanıyor. "Güvenlik için public DNS yazayım" diye düşünme, bir faydası yok.

Tek gerçek faydası: DNS'i **elle 8.8.8.8'e sabitlenmiş** cihazlar (birçok akıllı TV, IoT)
zaten AdGuard'ı bypass ederdi; interception sayesinde en azından router'ın cache'ine
düşüyorlar. AdGuard'a yönlendirmiyor ama tamamen kontrolsüz de bırakmıyor.

### 6. DNS loop riski var mı?
**Mimari A ve C'de YOK. Mimari B'de VAR — ve somut.**

Mevcut AdGuard config'inde iki alan doğrudan router'ı gösteriyor:
```yaml
fallback_dns:        [<ROUTER_IP>]     # router
local_ptr_upstreams: [<ROUTER_IP>]     # router
upstream_dns:        DoH/443           # router'a uğramıyor
```

Mimari B'de (router'ın upstream'i = AdGuard) oluşan döngüler:

```
LOOP 1 (fallback):  DoH upstream'leri düşer
                    → AdGuard fallback_dns=<ROUTER_IP>'e sorar
                    → router upstream'i AdGuard'dır, geri gönderir
                    → AdGuard → router → AdGuard → ...  ♾️
                    En kötüsü: tam olarak internet kesintisi anında tetiklenir.

LOOP 2 (PTR):       AdGuard, lease'i olmayan bir 192.168.0.x için PTR sorar
                    → local_ptr_upstreams=<ROUTER_IP>
                    → router → AdGuard → ...  ♾️
                    Hafifletici: router bu PTR'lere yerel NXDOMAIN veriyor (ölçüldü),
                    yani bu döngü muhtemelen tetiklenmez — ama garanti değil.

LOOP 3 (düz :53):   fallback'i 1.1.1.1 gibi bir public IP yapsak bile,
                    router o paketi intercept eder → kendi dnsmasq'ı → AdGuard → ...  ♾️
                    Yani "fallback'i public yaparım" çözüm DEĞİL.
```

Mimari B'ye geçilecek olsaydı AdGuard config'i **zorunlu olarak** değişmeliydi
(fallback'i ikinci bir DoH/DoT endpoint'i yapmak, local_ptr'ı kaldırmak — ki bu da
client identification'ı bozar). Bir sebep daha: **kullanma.**

**Önerilen mimarideki resolver yolu (döngüsüz):**
```
istemci ──► <PRIMARY_NODE_IP>  AdGuard ──► DoH/443 ──► Quad9 / Cloudflare ──► internet
                                 └──► fallback <ROUTER_IP> ──► TT resolver   (router geri göndermiyor: döngü yok)
istemci ──► <ROUTER_IP>   Router  ──► TT resolver ──► internet                (AdGuard'a hiç uğramıyor: döngü yok)
```

### 7. Primary Node tamamen kapanırsa internet nasıl devam eder?
Sadece istemcinin **ikinci bir DNS sunucusu** varsa devam eder. Ölçülen:
- glibc: devam eder, ama **her sorgu 3,1 sn** gecikir.
- musl: devam eder, **gecikme yok** (paralel sorduğu için).
- Tek DNS sunucusu dağıtılmışsa: **devam etmez** — 12,3 sn timeout, sonra hata.

Router'ın interception'ı bu durumda **yardım edemez** (Soru 5).

### 8. Primary Node geri gelince AdGuard otomatik tekrar kullanılabilir mi?
**EVET, otomatik.** İstemciler durum tutmaz; her sorguda listeyi baştan uygular. glibc
zaten her sorguda primary'yi önce deniyor (1.4'te görülen 3,1 sn'nin sebebi de bu) —
AdGuard cevap verir vermez gecikme kaybolur ve trafiğin tamamı geri döner.
Ek işlem, DHCP yenileme, reboot **gerekmez**. Toparlanma süresi ≈ bir sorgu.

### 9. Secondary Node secondary AdGuard gerçekten gerekli mi?
**Senin istediğin davranışı eksiksiz sağlamak için: evet, tek yolu o.**

Ölçümlerin gösterdiği şey aslında tam olarak Secondary Node'un çözdüğü problem: secondary DNS
**filtresiz** olduğu için bypass bir soruna dönüşüyor. Secondary de AdGuard olsaydı
bypass diye bir kavram kalmazdı — istemci hangisine giderse gitsin filtrelenmiş cevap alırdı,
ve Primary Node ölünce internet de sorunsuz devam ederdi. Dört gereksinimin dördü birden karşılanırdı.

**Ama bu görevde istemedin, o yüzden önermiyorum — sadece kaydediyorum:** ileride
"hem bypass olmasın hem Primary Node ölünce çalışsın" dersen, cevap Secondary Node'dur. Öncesinde
`adguardhome-sync` ile config drift'i çözmek şart (DNS Center görevindeki Faz 19 notları).

### 10. İstediğin davranışı sağlayan en basit güvenilir mimari hangisi?

**Mimari karşılaştırması:**

| | **A: DNS1=Pi5, DNS2=Router** | **B: Router proxy, upstream=AdGuard** | **C: Sadece Pi5** | **D: Pi5+Secondary Node** |
|---|---|---|---|---|
| Gerçek failover | ✅ otomatik (glibc 3,1 sn/sorgu, musl 0 ms) | ❓ doğrulanamadı | ❌ **yok** — 12,3 sn sonra internet biter | ✅ |
| AdGuard bypass | ⚠️ ölçüldü: glibc %3, musl %63 | ⚠️ görünmez bypass | ✅ %0 | ✅ %0 |
| Tek hata noktası | ✅ yok | ❌ router | ❌ **Pi5** | ✅ yok |
| Karmaşıklık | ✅ tek ayar | ❌ yüksek + AdGuard config değişikliği | ✅ tek ayar | ❌ yüksek |
| Router desteği | ✅ standart DHCP alanı | ❓ **doğrulanamadı** | ✅ | ✅ |
| DNS loop | ✅ yok | 🔴 **3 ayrı döngü yolu** | ✅ yok | ✅ yok |
| DNS Center istatistiği | ⚠️ bypass kadar eksik | 🔴 **yok olur** (tüm ev = <ROUTER_IP>) | ✅ tam | ⚠️ iki instance'a bölünür |
| **Verdict** | **ÖNERİLEN** | **KULLANMA** | fail req#2 | sonraya |

> **ÖNERİM: Mimari A** — `DHCP Primary DNS = <PRIMARY_NODE_IP>`, `Secondary DNS = <ROUTER_IP>`.
>
> Senin öncelik sıranla: #2 (internet devam etsin), #3 (otomatik), #4 (otomatik geri dönüş),
> #5 (Secondary Node yok), #6 (desteklenmeyen hack yok), #7 (loop yok) — **altısını da tam karşılıyor.**
> Sadece #1 (hiç bypass olmasın) kısmen karşılanıyor, ve bu donanımda başka türlü mümkün değil.

**Bypass'ı azaltmak için, deployment'tan sonra, cihaz bazında:**
Faz 9 testiyle hangi cihazın ne kadar bypass ettiğini ölçeriz. Çok bypass eden **ve senin
için önemli olan** cihazlarda (ör. telefon, tablet) o cihazın Wi-Fi ayarını elle
**yalnız <PRIMARY_NODE_IP>** yaparız. Bedeli: Primary Node ölürse *o cihaz* internetsiz kalır — ama bu
bilinçli, cihaz başına verilen bir karar olur. Ev geneli güvenli kalır.

Önemli bir nüans: bypass bir **güvenlik açığı değil**, bir **filtreleme sızıntısı**.
Bypass edilen sorgular yine doğru çözülüyor; sadece reklam engellenmiyor ve DNS Center
istatistiğine girmiyor.

### 11. Kontrollü deployment/test planı nedir?
Aşağıda, Bölüm 3'te. **Bu görevde uygulanmadı, sadece planlandı.**

### 12. Hangi router ayarlarının değiştirilmesi gerekecek?
**Tek bir ekran, tek bir değişiklik:**

```
Advanced → Network → DHCP Server
    Primary DNS   : <ROUTER_IP>   →   <PRIMARY_NODE_IP>
    Secondary DNS : (boş)         →   <ROUTER_IP>
```

Değiştirilmeyecekler (açıkça): WAN DNS, DNS proxy/relay ayarları, firewall, port
forwarding, UPnP, DHCP aralığı, rezervasyonlar, lease time (önce sadece **okunacak**).

⚠️ Değişiklikten **önce** *Address Lease Time* değerini okumalıyız (Bölüm 1.1) — rollback
hızını belirleyen şey o.

### 13. Rollback nasıl yapılacak?
```
Advanced → Network → DHCP Server
    Primary DNS   : <PRIMARY_NODE_IP>  →  <ROUTER_IP>
    Secondary DNS : <ROUTER_IP>   →  (boş)
```
Sonra cihazlarda Wi-Fi kapat/aç (veya `dhclient -r && dhclient` / `ipconfig /renew`).

⚠️ **Rollback anında değildir.** Rezervasyonlu cihazlarda lease sonsuz; yeni DNS ayarını
almaları için yeniden bağlanmaları gerekir. Bu yüzden deployment'ı **evde olduğun ve
router'a fiziksel erişebildiğin bir zamanda** yapmalıyız.

Acil durum kısa yolu — router'a hiç dokunmadan: `docker start metehantech-adguard`
(AdGuard geri gelir gelmez her şey normale döner) veya etkilenen cihazda DNS'i elle
`<ROUTER_IP>` yap.

### 14. Investigation sırasında herhangi bir production değişikliği yapıldı mı?
**HAYIR.**
- Okunanlar: DHCP lease (NetworkManager), `ss`, `docker inspect/port`, UPnP IGD **read-only**
  SOAP, AdGuard API **read-only**, `dig`.
- Ölçümler **tek kullanımlık container'larda** yapıldı (`docker run --rm --network bridge
  --dns ...`). Production container'ların hiçbiri durdurulmadı/yeniden başlatılmadı.
  Failover simülasyonu için AdGuard **hiç durdurulmadı** — bunun yerine primary olarak
  var olmayan bir adres (<UNUSED_TEST_LAN_IP>) ve boş bir port (<SECONDARY_NODE_IP>:53) kullanıldı.
- Router arayüzüne **girilmedi**, parola **denenmedi**, hiçbir ayar yazılmadı.
- Tek yan etki: AdGuard'ın query log'una test container'larından gelen ~134 `doubleclick.net`
  kaydı düştü. Veri, config değil; 72 saat içinde kendiliğinden düşecek.

---

## 3. Faz 9 — Kontrollü test planı (PLAN; uygulanmadı)

### Aşama 0 — Deployment öncesi (router'a dokunmadan)
1. Router'da *Address Lease Time* değerini **oku** (yaz, değiştirme).
2. Mevcut DHCP Primary/Secondary DNS değerlerinin ekran görüntüsünü al (rollback referansı).
3. AdGuard sağlık teyidi: `dig @<PRIMARY_NODE_IP> example.com`, `dnssec-failed.org` → SERVFAIL,
   `doubleclick.net` → 0.0.0.0, DoH upstream'leri OK, Control Center DNS sekmesi HEALTHY.
4. Baseline al: query sayısı, top clients, CPU/RAM.

### Aşama 1 — TEK test istemcisi (DHCP'ye hâlâ dokunulmuyor)
Telefonda (A72) Wi-Fi → ağ ayarları → **Static IP**, DNS1 = `<PRIMARY_NODE_IP>`, DNS2 = `<ROUTER_IP>`.
*(Yalnız o cihaz etkilenir; ev geneli değişmez.)*

Ölç:
- Normal gezinme çalışıyor mu?
- AdGuard query log'unda telefonun IP'si görünüyor mu, kaç sorgu?
- **Bypass oranı:** telefondan aynı engelli alan adını 30 kez çözdür; kaçı `0.0.0.0` döndü?
  Bu, Android'in gerçek davranışını verir — şu an **bilmediğimiz** tek büyük parça.
- Filtreleme, DNSSEC, banka/Google/Microsoft/Tapo erişimi.

### Aşama 2 — Failover ölçümü (yine tek istemci)
AdGuard'ı durdur (`docker stop metehantech-adguard`) ve **kronometre tut**:
- Telefonda internet ne kadar sürede tekrar çalıştı?
- Gezinme gözle görülür yavaşladı mı?
- Control Center Alert Center'da `adguard_unavailable` alarmı geldi mi (önceki görevde
  ölçüldü: +2 dk WARNING, +4 dk CRITICAL)?

Sonra `docker start metehantech-adguard` → **recovery süresi** ve AdGuard log'unda
sorguların geri gelmesi.

### Aşama 3 — İkinci istemci
Aynı testi bir bilgisayarda tekrarla (farklı resolver ailesi → farklı davranış).

### Aşama 4 — Ancak bundan sonra ev geneli
Aşama 1–3 temizse `DHCP Primary=<PRIMARY_NODE_IP>, Secondary=<ROUTER_IP>`.
İlk 24 saat izle: DNS Center sorgu hacmi, blocked %, query log disk büyümesi
(72 saat retention), CPU/RAM, alarm yok.

### Aşama 5 — Bypass'ı kapat (opsiyonel, cihaz bazında)
Aşama 1'de yüksek bypass ölçülen ve senin için önemli cihazlarda DNS'i elle sadece
`<PRIMARY_NODE_IP>` yap. Bedelini bilerek kabul et.

**Her aşamada geri dönüş:** `docker start metehantech-adguard` veya cihazda DNS'i
`<ROUTER_IP>` yap. Aşama 4'ten sonra: Soru 13'teki rollback.

---

## 4. Faz 5 — Arıza senaryoları (Mimari A ile)

| # | Senaryo | DNS ne olur | İnternet | Failover süresi |
|---|---|---|---|---|
| 1 | AdGuard container down | Primary Node `:53` connection-refused → istemci secondary'ye düşer | ✅ devam | glibc **5,0 sn/sorgu**, musl **0 ms** |
| 2 | Docker down | aynı (1) | ✅ devam | aynı |
| 3 | Primary Node reboot | ~60–90 sn boyunca sessiz | ✅ devam | glibc **3,1 sn/sorgu**, musl 0 ms |
| 4 | Primary Node tamamen kapalı | kalıcı sessiz | ✅ devam (yavaş) | aynı — ve düzelene kadar sürer |
| 5 | Primary Node ağdan kopuk | (4) ile aynı | ✅ devam | aynı |
| 6 | AdGuard çalışıyor, DoH upstream'leri erişilemiyor | AdGuard `fallback_dns=<ROUTER_IP>`'e düşer — **önceki görevde canlı doğrulandı** | ✅ devam, **filtreleme korunur** | ~1–2 sn, istemci hiç fark etmez |
| 7 | Router reboot | secondary yok olur; AdGuard çalışır ama DoH için internet de yok | ❌ zaten internet yok | n/a |
| 8 | ISP DNS problemi | AdGuard DoH ile **etkilenmez**; router yolu etkilenir | ✅ AdGuard kullanan cihazlar sorunsuz | — |

Senaryo 6 ve 8 dikkat çekici: **AdGuard DoH kullandığı için, ISP DNS'i bozulduğunda
AdGuard'ı kullanan cihazlar çalışmaya devam eder, router'ı kullananlar etmez.** Yani
AdGuard sadece filtreleme değil, dayanıklılık da katıyor.

---

## 5. Bu görevde bilerek yapılmayanlar

- ❌ Router DHCP/DNS değişikliği — **senin onayını bekliyor**
- ❌ AdGuard config değişikliği
- ❌ systemd-resolved / NetworkManager / firewall değişikliği
- ❌ Secondary Node'a DNS kurulumu
- ❌ Container restart (AdGuard dahil — failover simülasyonu sahte primary ile yapıldı)
- ❌ Router arayüzüne giriş / parola denemesi
- ❌ Mimari B için config üretimi (desteklendiği doğrulanamadığı için)

---

## DURUYORUM

Önerim: **Mimari A** — `DHCP Primary = <PRIMARY_NODE_IP>`, `Secondary = <ROUTER_IP>`,
Bölüm 3'teki aşamalı planla.

Onay verirsen whole-home DNS deployment'ını ayrı görev olarak, Aşama 0'dan başlayarak
yaparız. Onay vermeden router'da hiçbir şeye dokunmayacağım.
