# DNS Center — Phase 1 Discovery (read-only)

Date: 2026-09-21 · Host: <primary-node> (Raspberry Pi 5, Ubuntu 24.04.4 LTS, arm64, kernel 6.8.0-1064-raspi)
**Nothing was changed in this phase.** Every command below was read-only.

---

## 1. Primary Node network addressing

| Interface | Address | Role |
|---|---|---|
| `<PRIMARY_WIFI_IFACE>` | **<PRIMARY_NODE_IP>/24** | Primary LAN (USB WiFi adapter, NM connection name `<HOME_SSID>`) |
| `tailscale0` | **<PRIMARY_NODE_TAILSCALE_IP>/32**, `<PRIMARY_NODE_TAILSCALE_IPV6>` | Tailscale |
| `wg0` | 10.66.66.1/24 | WireGuard server |
| `br-5d47e31e433c` | 172.18.0.1/16 | Docker `metehantech-camera_default` |
| `br-2c337764c4f2` | 172.30.53.1/24 | Docker `metehantech-cloud_frontend` |
| `br-50a91b04648b` | 172.30.54.1/24 | Docker `metehantech-cloud_backend` |
| `docker0` | 172.17.0.1/16 | default bridge (DOWN / unused) |
| `eth0`, `wlan0` | — | DOWN (onboard NICs unused) |

Default route: `default via <ROUTER_IP> dev <PRIMARY_WIFI_IFACE> proto dhcp metric 601`
Public IP (observed): `<WAN_PUBLIC_IP>`

## 2. Current DNS architecture (before any change)

```
container (bridge net) ─► 127.0.0.11 (Docker embedded)
                             └─ ExtServers: host(127.0.0.53)
Home Assistant (host net) ─► 127.0.0.53
Primary Node host processes       ─► 127.0.0.53  (/etc/resolv.conf → stub-resolv.conf)
                             └─ systemd-resolved
                                  ├─ link <PRIMARY_WIFI_IFACE> (+DefaultRoute) ─► <ROUTER_IP>  (router, dnsmasq-2.83)
                                  └─ link tailscale0 ─► 100.100.100.100 (MagicDNS, suffix tailad2806.ts.net)
Secondary Node (<SECONDARY_NODE_IP>)     ─► 100.100.100.100 (resolv.conf written by Tailscale)
```

- `systemd-resolved`: **active + enabled**, `resolv.conf mode: stub`, `DNSSEC=no/unsupported`, `-DNSOverTLS`, `-mDNS`, `-LLMNR`.
- `/etc/systemd/resolved.conf` is empty (`[Resolve]` only). `/etc/systemd/resolved.conf.d/` does **not** exist.
- `/etc/resolv.conf` is a symlink → `../run/systemd/resolve/stub-resolv.conf`.
- NetworkManager 1.46.0 is active and owns `<HOME_SSID>`; `conf.d/` contains only `10-ubuntu-fan.conf` and `default-wifi-powersave-on.conf` — **no `dns=` override**, so NM uses its default `dns=systemd-resolved` integration.
- Upstream today is the **router at <ROUTER_IP> running dnsmasq 2.83** (confirmed via `version.bind CH TXT`).

## 3. Port 53 — the decisive finding

```
udp UNCONN 127.0.0.54:53      tcp LISTEN 127.0.0.54:53
udp UNCONN 127.0.0.53%lo:53   tcp LISTEN 127.0.0.53%lo:53
```

`systemd-resolved` binds **loopback only** (127.0.0.53 stub + 127.0.0.54 legacy). It does **not** bind `0.0.0.0:53`.

**Therefore TCP/UDP 53 on <PRIMARY_NODE_IP> and on <PRIMARY_NODE_TAILSCALE_IP> is free**, and AdGuard Home can bind those two addresses with **zero conflict and no need to disable, mask, or reconfigure systemd-resolved**. This is the safe path: the whole existing resolution chain above stays byte-for-byte intact.

Negative baseline confirmed from Secondary Node before deployment:
`dig @<PRIMARY_NODE_IP> example.com` → `;; no servers could be reached` ✔

Other ports verified free on the host: tcp/3000, tcp/5353, tcp/8053, tcp/784, udp/3000.
`udp/5353` is **occupied by avahi-daemon** (mDNS, `<primary-node>.local`) — relevant to Phase 10.

## 4. Why systemd-resolved must NOT be disabled

`metehantech-homeassistant` runs with `NetworkMode=host` and its `/etc/resolv.conf` contains `nameserver 127.0.0.53`. Docker bridge containers resolve via `127.0.0.11`, whose upstream is explicitly reported as `ExtServers: [host(127.0.0.53)]`.

So **every container and every host process on this Pi depends on the 127.0.0.53 stub.** The common "free port 53 by disabling systemd-resolved" recipe would take DNS away from Home Assistant, Frigate, Nextcloud, Mosquitto and cloudflared at once. It is not needed here and will not be done.

## 5. Service DNS dependencies

| Service | Network | Resolver | Notes |
|---|---|---|---|
| Home Assistant | `host` | 127.0.0.53 | direct stub dependency |
| Frigate | `metehantech-camera_default` | 127.0.0.11 → host stub | camera is a literal IP (<CAMERA_IP>), so recording survives DNS loss |
| Nextcloud app/db/redis/cron | cloud_frontend/backend | 127.0.0.11 | inter-container names resolved by Docker embedded DNS, **not** by upstream |
| Mosquitto | camera net | 127.0.0.11 | |
| cloudflared | host, systemd | 127.0.0.53 | outbound QUIC to `*.argotunnel.com`; **no inbound DNS dependency** |
| Tailscale | own | 100.100.100.100 | MagicDNS, split route `ts.net.` → 199.247.155.53 |

Docker inter-container name resolution (`127.0.0.11`) is handled inside Docker and is **not** affected by anything AdGuard does.

## 6. Cloudflare Tunnel

`cloudflared.service` active (24h), `tunnel run --token-file /etc/cloudflared/token`, outbound-only QUIC to Cloudflare edge (ist08). Public hostnames (status/cloud.metehantech.com) are published through the tunnel, **not** through any router port-forward. Adding AdGuard does not touch this, and the AdGuard admin UI will **not** be added to the tunnel.

## 7. Privilege constraints discovered

`sudo -n -l`: the account has `(ALL:ALL) ALL` but **requires a password**; only five specific `systemctl` invocations are NOPASSWD:

```
systemctl start  --no-block metehantech-backup-{cloud,pi,pcold}.service
systemctl restart --no-block metehantech-status.service
systemctl restart --no-block metehantech-home.service
systemctl restart --no-block clan-web.service
```

The user **is** in the `docker` group, so container deployment needs no sudo.
Consequence: firewall rules (`iptables -L`, `nft list ruleset`, `ufw status`) could **not** be read, and no host firewall change can be made autonomously. Security therefore relies on **interface-scoped binding** rather than on host firewall rules — see Phase 16.

## 8. Pre-deployment baselines (for Phase 15 comparison)

30-second sample, 2026-09-21:

```
cpu_mean=38.21%  cpu_p95=43.50%  cpu_max=49.50%
ram_used=5.35 GiB  ram_percent=38.1%  available=9.65 GiB
load 1/5/15 = 2.54 / 3.10 / 3.74
```

DNS latency baseline:
- via current stub `127.0.0.53` (cached/warm): ~0.03–0.04 s wall per lookup
- upstream router `<ROUTER_IP>`, forced cache-miss (random subdomain): **20 ms** × 3 samples

Disk: `/dev/nvme0n1p2` 229 G total, 53 G used, **168 G available** (24%).
Memory: 15 GiB total, 9.65 GiB available. Ample headroom for AdGuard (~50–80 MB RSS expected).

## 9. Router / modem

- <ROUTER_IP>, HTTP 200 on the admin page, **dnsmasq 2.83** serving DHCP + DNS for the LAN.
- DHCP hands out <ROUTER_IP> as DNS today.
- ⚠️ **Pre-existing finding, not caused by this work:** a query to `<WAN_PUBLIC_IP>:53` (the public IP) from inside the LAN is answered by the *same* `dnsmasq-2.83`, with the `ra` (recursion available) flag set. This is either NAT hairpin (benign) or the modem genuinely answering recursive DNS on its WAN side (**that would be an open resolver and a DNS-amplification risk**). It cannot be distinguished from inside the network; it needs one query from an off-net vantage point. **This is the modem's own resolver — it is unrelated to AdGuard, and AdGuard will not make it worse.** Flagged for the user in the final report.

## 10. Conflict verdict

| Risk | Verdict |
|---|---|
| systemd-resolved port conflict | **None** — resolved is loopback-only; publish AdGuard on <PRIMARY_NODE_IP>:53 + <PRIMARY_NODE_TAILSCALE_IP>:53 |
| Docker container DNS breakage | **None** — containers use 127.0.0.11, untouched |
| Home Assistant DNS breakage | **None** — 127.0.0.53 stub untouched |
| Tailscale MagicDNS breakage | **None** — tailscale0 link config untouched |
| Cloudflare Tunnel | **None** — outbound-only, no DNS serving role |
| mDNS `.local` collision | **Real** — avahi owns `.local` on this host; see Phase 10 recommendation |
| Router DHCP change | **Not performed** — explicitly out of scope per instruction |

**Recommended deployment:** Docker container, non-privileged, no Docker socket, explicit digest pin, published on
`<PRIMARY_NODE_IP>:53` (udp+tcp), `<PRIMARY_NODE_TAILSCALE_IP>:53` (udp+tcp), admin UI on `<PRIMARY_NODE_IP>:3000` + `<PRIMARY_NODE_TAILSCALE_IP>:3000` + `127.0.0.1:3000`.
**Never `0.0.0.0`.**
