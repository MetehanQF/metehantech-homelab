# MetehanTech Homelab

[![CI](https://github.com/MetehanQF/metehantech-homelab/actions/workflows/ci.yml/badge.svg)](https://github.com/MetehanQF/metehantech-homelab/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

The infrastructure side of a two-node home lab: **redundant DNS**, an **MQTT
broker**, and **Home Assistant** — with the deployment scripts, cluster tooling
and incident write-ups that came out of actually running it.

This is not a "copy my dotfiles" repository. Every component here exists because
something broke and needed a designed answer: a single resolver is a single point
of failure, two resolvers drift apart, a resolver that binds to the wrong address
becomes an open resolver, and a client whose identity is guessed from a hostname
gets merged with a different device.

> Companion repositories:
> [metehantech-status](https://github.com/MetehanQF/metehantech-status) — the
> monitoring and backup application · [homelab-toolkit](https://github.com/MetehanQF/homelab-toolkit) — standalone host fixes.

---

## Architecture

```
                         Internet
                             │
                    ┌────────┴────────┐
                    │     Router      │  DHCP: hands out both resolvers
                    │  (DHCP + PTR)   │  Also the last-resort DNS upstream
                    └────┬───────┬────┘
                         │       │
         ┌───────────────┘       └───────────────┐
         │                                       │
┌────────┴──────────┐                  ┌─────────┴─────────┐
│   Primary Node    │                  │  Secondary Node   │
│                   │                  │                   │
│  AdGuard Primary  │◄── parity/sync ──►│ AdGuard Secondary │
│  MQTT Broker      │                  │                   │
│  Home Assistant   │                  │  backup target    │
└───────────────────┘                  └───────────────────┘
         │
         └── MQTT ──► camera / automation integrations
```

Both resolvers are handed out by DHCP, so a client survives losing either one.
They are kept in parity by the cluster tools rather than by hand.

---

## DNS redundancy

Two AdGuard Home instances, deliberately **not** a leader/follower pair at the
protocol level — clients fail over, not the servers.

**What the design has to get right**

- **No recursive loops.** A resolver must never list the other member (or itself)
  as upstream, fallback or PTR target. `tools/dns-cluster` refuses to sync a
  configuration that would create one; the set of cluster addresses is derived
  from configuration, not guessed.
- **No accidental open resolver.** Ports are published on **specific host
  addresses only**, never `0.0.0.0`. The compose files use `${VAR:?}` so a missing
  address is a hard error rather than a silent wildcard bind.
- **Client identity on evidence only.** Two addresses are treated as one device
  only when a persistent record lists both, or when the neighbour table shows the
  same *universally administered* MAC. A matching hostname is never enough —
  reverse DNS happily returns the same name for two different range extenders.
- **Reverse lookups go to the router.** It owns the DHCP leases, so it is the only
  thing that actually knows LAN hostnames.

**Tooling** (`tools/`)

| Directory | What it does |
|---|---|
| `dns-cluster/` | AdGuard API client, parity comparison, configuration sync with loop validation, failover test harness |
| `dns-cutover/` | Router DHCP DNS cutover with rollback, plus a canary that reports which client is actually asking which resolver |
| `dns-failover/` | Simulates a two-resolver stub client: queries the first, measures what happens on timeout/SERVFAIL |
| `dns-eval/` | Upstream benchmarking (DoH), bootstrap matrix, DNS stamps, raw TCP/53 probe |
| `dns-security/` | Unprivileged DNS interception detection — proves whether something on the path is rewriting port 53 |

---

## AdGuard Home

`dns/adguard/` holds the compose file for the primary, `configure.py` which
applies settings idempotently, and a deployment bundle for the secondary node.

`configure.py` touches **only** the keys it manages — upstreams, bootstrap,
fallback, local PTR, the client allowlist and persistent clients. Everything else
AdGuard generated (schema version, the bcrypt admin hash, TLS and DHCP blocks) is
left exactly as written, so the schema stays valid for the running version.

The generated `AdGuardHome.yaml` itself is **runtime state** and is not in this
repository — it carries the admin password hash and your client inventory.

---

## MQTT

`mqtt/` is a Mosquitto broker with anonymous access off and a per-user ACL:
each of the camera, Home Assistant and probe accounts can only touch the topics it
needs. `configure-frigate.py` and `configure-ha.py` wire the integrations up;
`probe.py` verifies the broker answers.

The `passwords` file (bcrypt hashes) is generated on the host and never committed.

---

## Home Assistant

`homeassistant/` contains only the parts that are **authored**, not generated:

```
config/       configuration.yaml, automations.yaml, scenes.yaml, scripts.yaml
packages/     the home + automation packages
dashboards/   two dashboards
themes/       a dark theme
verify.py     read-only post-reboot verification
```

Everything Home Assistant produces itself — `.storage/` (which holds access
tokens), the SQLite recorder database, logs, `deps/`, `www/`, and any HACS or
vendored `custom_components/` — is excluded on purpose. Those are runtime state or
third-party code, not this project's.

---

## The config / example system

**Nothing about a particular installation is in the source.** A single module,
`homelab_config.py`, resolves every environment-dependent value:

```
process environment  →  config file  →  ConfigError
```

The config file is the first match of `$HOMELAB_CONFIG` (exclusive when set),
`<repo>/config.env`, then `~/.config/metehantech-homelab/config.env`. Parsing
follows systemd `EnvironmentFile` semantics, not shell semantics, so
`KEY=two words` is read intact.

```bash
cp config.example.env config.env
chmod 600 config.env
$EDITOR config.env
```

Every address in `config.example.env` comes from the RFC documentation ranges
(`192.0.2.0/24`, `100.64.0.0/10`) and points at nothing.

**There is no fallback to a real value anywhere.** A missing required key raises
`ConfigError`, and compose files use `${VAR:?}`. This is deliberate: for a
resolver, silently binding to the wrong address is a worse outcome than not
starting at all.

| Template | Copy to | Holds |
|---|---|---|
| `config.example.env` | `config.env` | node addresses, credential paths, container names |
| `dns/examples/adguard.env.example` | `dns/adguard/.env` | AdGuard compose bind addresses |
| `dns/examples/credentials.example.json` | outside the repo | AdGuard admin credentials |
| `mqtt/examples/credentials.example.json` | outside the repo | MQTT account passwords |

---

## Deployment

```bash
git clone https://github.com/MetehanQF/metehantech-homelab.git
cd metehantech-homelab
cp config.example.env config.env && chmod 600 config.env && $EDITOR config.env
```

**Primary node**

```bash
cd dns/adguard && cp ../examples/adguard.env.example .env && $EDITOR .env
docker compose config      # verify substitution before applying
docker compose up -d
python3 configure.py       # run with the container stopped, then start it

cd ../../mqtt && docker compose up -d
cd ../homeassistant && docker compose up -d
```

**Secondary node**

```bash
SECONDARY_NODE_IP=... SECONDARY_NODE_TAILSCALE_IP=... \
  bash dns/adguard/secondary-node/deploy.sh
```

**Then bring the pair into parity**

```bash
python3 tools/dns-cluster/cluster.py health
python3 tools/dns-cluster/cluster.py parity
python3 tools/dns-cluster/cluster.py sync
bash    tools/dns-cluster/parity_test.sh "$PRIMARY_NODE_IP" "$SECONDARY_NODE_IP"
```

Only after both resolvers agree should DHCP be pointed at them —
`tools/dns-cutover/router.py` does that and supports `--rollback`.

---

## Security model

| Secret | Where it lives |
|---|---|
| AdGuard admin credentials | JSON files outside the repo, mode `0600`, paths supplied by config |
| AdGuard admin password hash | inside AdGuard's own generated `AdGuardHome.yaml` — excluded |
| MQTT account passwords | `mqtt/config/passwords` (bcrypt), generated on the host — excluded |
| Home Assistant tokens | `config/.storage/` — excluded; tools mint short-lived tokens in-container instead |

Further rules this repository follows:

- **Resolvers bind to named addresses only.** Never `0.0.0.0`; a missing bind
  address aborts the deploy.
- **Hard anti-open-resolver allowlist.** Even if a port-forward were created by
  mistake, a WAN source address is not on the list and is refused.
- **Container hardening.** `cap_drop: ALL` with only `NET_BIND_SERVICE` added
  back, `no-new-privileges`, pinned image digests rather than floating tags.
- **Credentials are read at call time** from `0600` files and never returned,
  printed, logged, or placed in an exception message.

### Deliberately not in this repository

`.env` files · `credentials.json` · the real `AdGuardHome.yaml` · Home Assistant
`.storage/` and `secrets.yaml` · `*.db` · `*.log` · `backups/` · raw investigation
dumps · HACS and vendored `custom_components/` · screenshots · any runtime state.

Templates are provided for each. See `.gitignore` for the full list.

---

## Documentation

`docs/` holds the write-ups produced while building and debugging this: DNS
discovery, architecture design notes, the cutover, failover behaviour, redundancy
status, and a security review of the resolver's exposure.

These are **sanitized** — real addresses, MAC addresses and device names are
replaced by symbolic placeholders (`<PRIMARY_NODE_IP>`, `Primary Node`, …). They
are in Turkish, as written during the work; the English README covers the design.
Purely historical snapshots with nothing reusable in them were not published.

---

## Contributing

Please keep real addresses, hostnames, MAC addresses and credentials out of
patches — including in examples. Use the RFC documentation ranges
(`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `100.64.0.0/10`).

## Licence

[MIT](LICENSE) © 2026 Metehan Öztürk
