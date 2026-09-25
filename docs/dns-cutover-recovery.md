# MetehanTech — DHCP DNS Cutover — GERİ ALMA

Cutover: `2026-09-21T16:09:01Z`. Bu dosya, ev genelindeki DNS'i cutover
öncesindeki haline nasıl döndüreceğini anlatır.

---

## Ne zaman geri al

Aşağıdakilerden biri olursa:

- Birden fazla cihazda ad çözümleme bozulursa ve `<PRIMARY_NODE_IP>` / `<SECONDARY_NODE_IP>`
  doğrudan sorgulandığında da yanıt vermiyorsa,
- Her iki AdGuard aynı anda düşerse ve hızlı ayağa kaldırılamıyorsa
  (**her ikisi birden down = ev geneli DNS kesintisi**),
- Yanlış pozitif engelleme kritik bir hizmeti kesip AdGuard tarafında
  hızlıca allowlist'lenemiyorsa.

**Önce daha ucuz seçenekleri dene** — aşağıdaki "Kısmi çareler"e bak.
Router'ı geri almak en ağır adım.

---

## Tam geri alma (router DHCP)

```bash
cd <workspace>/dns-cutover
python3 router.py --rollback
```

Davranışı:

1. Router'a bağlanır (parola gizli prompt ile; argv/env/history/diske girmez).
2. `router-live-state.json` içindeki **gerçek** cutover-öncesi değerleri okur:
   `pri_dns=""`, `snd_dns=""`.
3. Diğer altı alanı (`enable`, `leasetime`, `gateway`, `ipaddr_start`,
   `ipaddr_end`, `domain`) yine canlı router'dan okuyup aynen geri yazar.
4. Yazmadan önce ekranda diff gösterir ve **`EVET`** yazmanı bekler.
5. Yazdıktan sonra geri okuyup doğrular, sonucu `router-cutover-result.json`'a yazar.

`--rollback` modu `router-live-state.json`'ı **üzerine yazmaz**; orijinal
cutover-öncesi anlık görüntü korunur.

> `router-live-state.json` silinirse rollback **çalışmaz** ve durur —
> gerçek eski değerler bilinmeden router'a yazmaz. Bu dosyayı silme.

### Geri alma sonrası

`leasetime=120` olduğu için cihazlar **en geç 2 saat içinde** eski DNS'e döner.
Hemen dönmesi için cihazın WiFi'ını kapat/aç ya da router'ı yeniden başlat.
Router yine `<ROUTER_IP>`'i (kendi dnsmasq'i) dağıtır — bu cutover öncesi haldi.

---

## Kısmi çareler (router'a dokunmadan)

Çoğu sorun bunlarla çözülür, tüm haneyi etkilemez:

**Tek bir domain yanlışlıkla engellendiyse** — AdGuard'da allowlist kuralı ekle,
her iki düğüme de. Router'a dokunma.

**Sadece birincil (Pi5) sorunluysa** — hiçbir şey yapma. İkincil `<SECONDARY_NODE_IP>`
zaten dağıtılıyor; istemciler kendiliğinden düşer. Primary Node AdGuard'ı düzelt:
```bash
docker restart metehantech-adguard
```

**Sadece ikincil (Secondary Node) sorunluysa** — etki yok, birincil çalışmaya devam eder.

**Tek bir cihazı geçici olarak muaf tutmak** — o cihaza elle DNS gir
(`1.1.1.1` vb.). Ev genelini değiştirmeden tek cihazı izole eder.

**Filtrelemeyi geçici olarak tamamen kapatmak** — AdGuard arayüzünde
protection'ı kapat. DNS çözümleme devam eder, sadece engelleme durur.
Router'ı geri almaktan çok daha hızlı ve geri alınabilir.

---

## Sağlık kontrolü

```bash
cd <workspace>/dns-cutover

# Hangi istemci hangi resolver'a soruyor (gerçek client IP'leriyle)
python3 canary.py --minutes 15

# Stub-resolver davranışı: DNS1 -> gerekirse DNS2, filtreleme dahil
python3 failover.py --label kontrol

# Router'ın canlı DHCP ayarını oku (DEĞİŞİKLİK YAPMAZ, parola ister)
python3 router.py --read-only
```

Beklenen sağlıklı tablo: `failover.py` 6/6 çözer, filtreleme 2/2,
`canary.py` gerçek per-cihaz IP'ler gösterir (hepsi `<ROUTER_IP>` olarak
görünüyorsa client identification kaybolmuş demektir).

---

## Bilinen kısıtlar

- Rollback'in **boş** `pri_dns`/`snd_dns` yazımı canlı router'da henüz test
  edilmedi. Router boş değeri reddederse, alternatif olarak router arayüzünden
  DHCP → DNS alanlarını elle temizle ya da "Otomatik/ISP" seçeneğine dön.
- Rollback router oturumu açar; router aynı anda başka bir yerden yönetiliyorsa
  oturum çakışabilir. Router arayüzünden çıkış yapıp tekrar dene.
- `metehanbackup` SSH hesabının Secondary Node'da genel sudo'su yok; Secondary Node tarafındaki
  container müdahalesi o makinede elle yapılmalı.
