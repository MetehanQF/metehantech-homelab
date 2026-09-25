# DNS Center — Phase 10 & Phase 19 design notes

These two phases were explicitly scoped as **discovery / recommendation only**. Nothing
below has been implemented.

---

# Phase 10 — Local DNS namespace

## The proposal on the table

```
home.metehantech.local
status.metehantech.local
cloud.metehantech.local
frigate.metehantech.local
```

## Why `.local` is the wrong choice here — concretely

`.local` is reserved by RFC 6762 for **multicast DNS**, and this network already uses it:

```
avahi-daemon: running [<primary-node>.local]     # active on the Pi
udp  0.0.0.0:5353, <PRIMARY_NODE_IP>:5353, [::]:5353     # mDNS responder, already bound
```

- Android, iOS, macOS and modern Windows resolve `.local` by **multicasting on the LAN**,
  not by asking the configured DNS server. Android in particular has never reliably sent
  `.local` to unicast DNS. So `status.metehantech.local` would be answered by AdGuard for
  some clients and silently fail for others — the worst kind of bug to debug.
- The Pi's own avahi already claims `<primary-node>.local`. Adding a unicast `.local`
  zone creates two authorities for one namespace.
- `.local` can never hold a publicly trusted TLS certificate. Every internal HTTPS service
  would show a browser warning forever.

**Verdict: do not use `.local`.**

## Recommended namespace instead

Use a subdomain of the domain you already own, and simply never publish it in Cloudflare:

```
<HA_INTERNAL_HOST>
<STATUS_INTERNAL_HOST>
<CLOUD_INTERNAL_HOST>
<FRIGATE_INTERNAL_HOST>
```

Why this is strictly better:

| | `.local` | `lan.metehantech.com` |
|---|---|---|
| Resolves on Android/iOS via AdGuard | unreliable | yes |
| Collides with mDNS/avahi | yes | no |
| Publicly trusted TLS possible | never | yes, wildcard `*.lan.metehantech.com` via DNS-01 ACME |
| Leaks to the internet | n/a | no — the records only exist inside AdGuard |
| Off-LAN (Tailscale) clients | no | yes, if they use AdGuard as resolver |

Implementation when you want it (AdGuard → Filters → **DNS rewrites**):

```
<HA_INTERNAL_HOST>    → <PRIMARY_NODE_IP>
<STATUS_INTERNAL_HOST>  → <PRIMARY_NODE_IP>
<CLOUD_INTERNAL_HOST>   → <PRIMARY_NODE_IP>
<FRIGATE_INTERNAL_HOST> → <PRIMARY_NODE_IP>
```

## The hard rule that protects the existing public setup

**Never create a rewrite for `status.metehantech.com` or `cloud.metehantech.com`.**

Those names resolve to Cloudflare's edge, which terminates TLS with a certificate issued
for them and forwards into the tunnel. Rewriting them to <PRIMARY_NODE_IP> would send browsers
straight at the local Apache/Flask origin, which does not hold that certificate — result:
TLS errors on every device in the house, and a very confusing outage. The `lan.` prefix
exists precisely so the internal and external names can never be confused.

## Simpler option you already have

Tailscale MagicDNS already gives stable, working names with **zero** configuration:

```
<primary-node>.tailad2806.ts.net   → the Pi, from anywhere on the tailnet
metehantechpcold.tailad2806.ts.net    → Secondary Node
```

If the goal is "type a name instead of an IP", this is free and already works. The
`lan.metehantech.com` scheme is worth the effort only if you also want trusted internal
TLS.

---

# Phase 19 — Secondary Node as a secondary DNS server

## Is it worth doing?

Partly. It protects against the *wrong* failure. Be clear about what each option buys:

| Failure | Does a second DNS server help? |
|---|---|
| AdGuard container crashes / OOM | **Yes** |
| Primary Node reboots for updates | **Yes** |
| Primary Node hardware or SD/NVMe failure | **Yes** |
| Upstream (Quad9 + Cloudflare) unreachable | No — already handled by `fallback_dns: <ROUTER_IP>` |
| Internet down | No — nothing helps |
| Router down | No — the LAN is down anyway |

Secondary Node is also the NFS target for camera recordings and the backup destination, so it is
already expected to be up whenever the Pi is. That makes it a reasonable candidate.

## The three real problems with two independent AdGuard instances

1. **Clients do not fail over the way people assume.** Handing out two DNS servers over
   DHCP does *not* mean "use the first, fall back to the second". Windows and Android
   query both, often in parallel, and use whichever answers first. So roughly half your
   ad-blocking would silently stop working if the secondary had different filters — and
   you would have no obvious symptom, just ads reappearing.
2. **Configuration drift.** Filter lists, DNS rewrites, per-client names and blocked
   services all live in each instance's own YAML. Within weeks the two diverge, and
   problem 1 turns that divergence into non-deterministic behaviour.
3. **Split observability.** Query log and statistics are per-instance. The DNS Center
   would show only half the traffic unless it merges two APIs.

## Recommended target architecture

```
                    DHCP hands out ONE address: <DNS_VIP_LAN_IP> (VIP)
                                   │
                        keepalived / VRRP floating IP
                          ┌────────┴────────┐
                   MASTER │                 │ BACKUP
              Primary Node <PRIMARY_NODE_IP>        Secondary Node <SECONDARY_NODE_IP>
              AdGuard (primary)       AdGuard (replica)
                    └──── adguardhome-sync (config replication) ────┘
```

- **`keepalived` VRRP virtual IP** solves problem 1 properly: clients only ever know one
  DNS address, and exactly one node answers on it at a time. No ambiguous failover, no
  half-filtered browsing, and the DHCP setting never has to change again.
- **`adguardhome-sync`** (`ghcr.io/bakito/adguardhome-sync`, actively maintained) replicates
  filters, rewrites, clients and settings from primary to replica on a schedule. Solves
  problem 2. Run it on the Pi, pointed at both API endpoints over loopback/Tailscale.
- Problem 3 stays: keep the primary as the reporting source, and label the DNS Center
  panel "primary node" rather than silently under-reporting. A merged view is possible
  later but is not worth the complexity at this size.

### Cheaper alternatives, in order of effort

1. **Do nothing extra.** Set DHCP DNS to `<PRIMARY_NODE_IP>, <ROUTER_IP>`. The router is already
   a working resolver. Cost: zero. Downside: when the Pi is down (or sometimes even when it
   is not), clients get unfiltered answers from the router. For a home network this is a
   perfectly defensible trade.
2. **Plain forwarder on Secondary Node** (`unbound` or `dnsmasq` → Quad9). Survives a Pi outage, but
   with no filtering and no shared config. Slightly better than option 1 only if you do not
   trust the router.
3. **Full VIP + sync** as diagrammed above. Best behaviour, most moving parts.

**Recommendation: start with option 1 when you go whole-home.** Live with it for a few
weeks, see whether the Pi actually goes down, and only then build the VIP + sync pair.
Adding a redundancy layer you have not yet needed is the most common way to make a system
*less* reliable.

## Prerequisites already verified on Secondary Node

- `<SECONDARY_NODE_IP>`, reachable, Debian, Docker + Portainer present.
- **Port 53 is free** — only `udp/5353` (mDNS) is bound; there is no systemd-resolved stub
  listener to work around.
- `/etc/resolv.conf` is written by Tailscale (`nameserver 100.100.100.100`). A DNS server
  installed there must **not** try to manage that file.

## Blocker to be aware of

The SSH account available for automation (`metehanbackup`) has no sudo beyond starting the
backup export service. Deploying anything on Secondary Node — including a container — needs either
your hands on that machine or a wider-privileged account. That is why this phase stops at
a design.
