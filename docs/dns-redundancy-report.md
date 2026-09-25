# MetehanTech Redundant AdGuard — final report

Date: 2026-09-21 · Time zone: Europe/Istanbul

## Sonuç özeti

İkincil AdGuard Home Secondary Node üzerinde kuruldu ve doğrulandı. İki gerçek resolver da
sağlıklı, filtreli, DNSSEC doğruluyor ve config drift değeri sıfır. Control Center
DNS cluster'ı 2/2 sağlıklı gösteriyor. **Router DHCP değiştirilmedi ve whole-home
DNS henüz aktif değil.**

```text
Client -> Primary Node <PRIMARY_NODE_IP>:53   -> Quad9 / Cloudflare Security over DoH
       -> Secondary Node <SECONDARY_NODE_IP>:53 -> Quad9 / Cloudflare Security over DoH
```

Neither resolver points to the other. Router `<ROUTER_IP>` remains only the matching
fallback/PTR path; because the router is not configured to forward to either
AdGuard, it does not currently close a recursive loop.

## İstenen 27 cevap

1. **Secondary Node AdGuard kuruldu mu?** Evet. `metehantech-adguard` çalışıyor; LAN ve
   Tailscale UDP/TCP DNS ile özel admin UI doğrulandı.
2. **Version/image digest:** AdGuard Home `v0.107.79`;
   `sha256:aba9e3bf0613be3ba3755e1fc311b126e2c24bec25e18b6483894a88283074f0`
   (linux/amd64 on Secondary Node; same multi-arch digest as Pi5).
3. **Config parity:** `CONFIG PARITY: IN SYNC`; post-sync drift **0**.
4. **Senkron alanlar:** DoH upstreams, bootstrap/fallback/PTR policy, DNSSEC,
   cache, timeout/rate-limit/blocking mode, filters and user rules, allow/disallow
   lists, persistent clients, query-log 72h, statistics 7d, safe-browsing and
   parental settings.
5. **Host-specific alanlar:** bind IPs, API/admin credential, filesystem paths,
   UID/GID, Docker port publications, persistent volumes and host architecture.
6. **DNS loop:** Bulunmadı. Loop guard Pi5/Secondary Node LAN, Tailscale, loopback and
   cross-member addresses as upstream/fallback/PTR/bootstrap targets rejects.
7. **Primary Node latency:** Post-sync five-query health mean **35.2 ms**; this includes the
   deliberately invalid DNSSEC probe. Control Center's live resolve+filter sample
   was **43.0 ms**.
8. **Secondary Node latency:** Post-sync five-query health mean **39.1 ms**; Control Center
   live resolve+filter sample **34.6 ms**.
9. **Filtering parity:** **26/26 behavioural checks matched**; blocked A=`0.0.0.0`,
   blocked AAAA=`::`, allowed/control domains resolve on both.
10. **DNSSEC:** Valid signed domains return `ad`; `dnssec-failed.org` returns
    `SERVFAIL` on both.
11. **Primary Node down:** A real Primary Node AdGuard container stop was performed. With DNS1=Pi5,
    DNS2=Secondary Node, **6/6** lookups succeeded through Secondary Node in 610 ms total; Primary Node was
    restored healthy, restart count stayed 0.
12. **Secondary Node down:** An unreachable secondary address simulation with healthy Pi5
    returned **6/6** in 570 ms total. Secondary Node's real container was not stopped because
    the unattended SSH account intentionally cannot manage Docker; this boundary
    was not weakened.
13. **Both down:** **0/2** lookups succeeded; glibc gave up after 49.165 s total.
    This is the accepted no-unfiltered-third-resolver trade-off.
14. **Client identification:** Yes. A direct Secondary Node query appeared as client
    `<PRIMARY_NODE_IP>`, inventory name `Primary Node (Raspberry Pi 5)`; router proxy is absent.
15. **Drift detection:** `python3 cluster.py parity`; read-only normalized parity
    contract, secrets and host-specific settings excluded.
16. **Sync:** Manual/on-demand Primary Node → Secondary Node only. It validates source health,
    filtering and loop safety, backs up Secondary Node, applies adapted fields, and requires
    post-sync health plus zero drift. It never blindly mirrors a broken primary.
17. **Secondary Node resources:** AdGuard process ~**1.0% CPU**, **87,172 KiB RSS** (~85 MiB).
    Host: 2,973 MiB RAM total / 1,333 MiB available, 204 GiB free disk, load
    0.48/0.59/0.62. The 512 MiB container limit is a guardrail, not a reservation.
18. **Security:** Non-root `1000:1000`, `privileged=false`, `cap_drop=ALL`, only
    `NET_BIND_SERVICE`, `no-new-privileges`, no Docker socket/host network. DNS/UI
    bind only to `<SECONDARY_NODE_IP>`, `<SECONDARY_NODE_TAILSCALE_IP>`, and UI loopback—never
    `0.0.0.0:53`/`[::]:53`. The prior router read-only inventory found zero port-53
    forward/UPnP mappings; router config remained unchanged. No WAN open resolver
    path was created.
19. **Control Center:** Live DNS Cluster = **HEALTHY**, Primary Node = HEALTHY, Secondary Node =
    HEALTHY, 2/2 redundant. One-member loss becomes debounced WARNING/DEGRADED;
    zero members becomes debounced CRITICAL. Anonymous DNS API is 401 and public
    status has no client/domain/query history. **160 tests + 402 subtests passed.**
20. **Router current DHCP/DNS:** Still gateway/DNS `<ROUTER_IP>`; no router setting
    was changed.
21. **DHCP lease:** Pi5's live lease reports `4294967295` (effective infinite).
    This proves current client behaviour; the global router UI lease field was not
    changed or authenticated to. Existing clients therefore need explicit renew,
    Wi-Fi reconnect, or reboot after cutover and rollback.
22. **Whole-home setting to change after approval:** Archer AX55 DHCP Server:
    Primary DNS `<PRIMARY_NODE_IP>`; Secondary DNS `<SECONDARY_NODE_IP>`. WAN DNS, firewall,
    NAT, UPnP, reservations and router DNS proxy stay untouched.
23. **Rollback:** Immediately before cutover capture live values again. Current
    observed rollback target is Primary `<ROUTER_IP>`, Secondary blank/default;
    restore those captured live values, then renew/reconnect/reboot clients.
24. **Backups:** Initial rollout
    `$BACKUP_ROOT/20260921T104904Z-dns-redundancy`;
    pre-sync Secondary Node snapshot
    `$BACKUP_ROOT/20260921T153412Z-dns-sync-pcold`;
    deploy helper backup
    `<repo>/tools/dns-cluster/deploy-pcold-from-pi.sh.backup-20260921T153037Z`.
25. **Changes:** Secondary Node `/opt/metehantech-dns/{compose.yaml,.env,credentials.json,
    conf/,work/}`, container `metehantech-adguard`, network
    `metehantech-dns_default`; Pi-side cluster tools under
    `<repo>/tools/dns-cluster`; Control Center `dns_cluster.py`,
    `dns_center.py`, `dns_alerts.py`, `history.py`, `static/dns-center.js`,
    `templates/admin.html`, and DNS tests. `metehantech-status.service` was restarted
    once after the full suite passed.
26. **Actual tests:** 2/2 health; 26/26 parity; UDP/TCP; A/AAAA/CNAME/MX/TXT/NS;
    NXDOMAIN; filtered and allowed domains; DNSSEC valid/invalid; PTR; ANY refused;
    real Primary Node container outage; silent primary/secondary; Secondary Node forced upstream
    SERVFAIL and restoration; both-down; client-IP logging; LAN/Tailscale DNS/UI;
    service/auth/regression checks. Primary Node containers remain running with restart count
    0; Secondary Node agent reports Docker/SMART OK; Control Center, HA, Nextcloud, Portainer,
    Uptime Kuma and Frigate container health are good.
27. **Open risks:** Both hosts down means DNS outage; client failover timing is OS
    dependent (glibc silent-primary measured ~3.3 s/query); a SERVFAIL primary also
    caused ~3.3 s/query before fallback; effective infinite DHCP leases make cutover
    and rollback non-instant; the real Secondary Node container-stop path was simulated rather
    than stopped remotely. Configuration sync remains intentionally manual.

## Onay kapısı

Resolver çifti kontrollü whole-home deployment için hazır; ancak **router'da hiçbir
değişiklik yapılmadı**. Onay verilirse sonraki görev önce router'ın canlı DNS/lease
değerlerini yeniden okuyup yedeklemeli, ardından DHCP DNS1=`<PRIMARY_NODE_IP>` ve
DNS2=`<SECONDARY_NODE_IP>` yapmalı, tek test istemcisinde renew uygulayıp iki resolver'ın
log ve failover davranışını doğrulamalı ve ancak sonra diğer istemcilere yaymalıdır.
