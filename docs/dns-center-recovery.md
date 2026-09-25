# DNS Center — RECOVERY

Backup root: `$BACKUP_ROOT/20260921T063604Z-dns-center`
(path is also stored in `workspace/dns-center/backup-location`; integrity manifest `SHA256SUMS.txt`)

---

## 0. The single most important fact

**This deployment did not modify the Pi5's own DNS resolution at all.**

`systemd-resolved` was **not** disabled, masked, or reconfigured. `/etc/resolv.conf` still points at
`127.0.0.53`. NetworkManager was not touched. No container's DNS was changed. The router was not touched.

AdGuard Home listens on **<PRIMARY_NODE_IP>:53** and **<PRIMARY_NODE_TAILSCALE_IP>:53** only — addresses that nothing
was using. Nothing on this network queries those addresses unless a client is *explicitly* pointed at
them.

**Consequence: stopping or deleting AdGuard cannot break Primary Node or home-network DNS.** There is no
"restore DNS" step to perform. The sections below exist for completeness.

---

## 1. Emergency: "DNS is broken, undo everything now"

```bash
docker stop metehantech-adguard
```

That is the whole rollback. Port 53 on <PRIMARY_NODE_IP> / <PRIMARY_NODE_TAILSCALE_IP> goes silent again, and every
existing service keeps resolving through 127.0.0.53 exactly as before.

If a **test client** was manually pointed at <PRIMARY_NODE_IP> for DNS, set that one client back to
automatic/DHCP DNS (it will go back to the router, <ROUTER_IP>).

Full removal:

```bash
cd <repo>/dns/adguard
docker compose down                 # stops + removes container and its network
# data/config are preserved on disk in ./conf and ./work; delete only if you mean it:
# trash <repo>/dns/adguard/conf <repo>/dns/adguard/work
```

---

## 2. Verify the Pi's own DNS is healthy (any time)

```bash
resolvectl status | head -5          # expect: resolv.conf mode: stub
dig +short @127.0.0.53 example.com   # expect: an address
docker exec metehantech-homeassistant getent hosts github.com   # expect: an address
```

Expected healthy baseline (captured 2026-09-21, pre-deployment):

```
/etc/resolv.conf -> ../run/systemd/resolve/stub-resolv.conf
nameserver 127.0.0.53
systemd-resolved: active, enabled, resolv.conf mode: stub
link <PRIMARY_WIFI_IFACE> -> <ROUTER_IP>
link tailscale0      -> 100.100.100.100 (suffix tailad2806.ts.net)
```

## 3. Restoring host DNS config from backup (only if someone edits it later)

```bash
B=$BACKUP_ROOT/20260921T063604Z-dns-center
sudo cp "$B/network/resolved.conf" /etc/systemd/resolved.conf
sudo rm -f /etc/systemd/resolved.conf.d/*adguard*          # if any was ever added
sudo ln -sfn ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
sudo systemctl restart systemd-resolved
resolvectl status | head -5
```

NetworkManager reference copies: `$B/network/NetworkManager.conf`, `$B/network/NetworkManager-conf.d/`,
`$B/network/nmcli-<HOME_SSID>.txt`. NetworkManager was not modified, so nothing should need restoring.

## 4. Restoring Control Center code

Phase 12–14 added DNS Center to `<status-repo>`. Pristine pre-change copies:

```bash
B=$BACKUP_ROOT/20260921T063604Z-dns-center/control-center
S=<status-repo>
cp "$B"/app.py "$B"/alerts.py "$B"/control_center.py "$B"/health_model.py "$B"/history.py "$B"/admin.py "$S"/
cp "$B"/templates/admin.html "$B"/templates/index.html "$S"/templates/
cp "$B"/static/control-center.js "$B"/static/control-center.css "$B"/static/admin.js "$B"/static/style.css "$S"/static/
rm -f "$S"/dns_center.py "$S"/dns_alerts.py "$S"/static/dns-center.js "$S"/tests/test_dns_center.py
sudo -n systemctl restart --no-block metehantech-status.service
```

Files **added** by this work (safe to delete on rollback): `dns_center.py`, `dns_alerts.py`,
`static/dns-center.js`, `tests/test_dns_center.py`, `deploy/dns-center/`.

Do **not** SIGHUP the status service — restart it with the allow-listed command above.

## 5. Recovering AdGuard itself

Config and data live on the host:

- `<repo>/dns/adguard/conf/AdGuardHome.yaml` — full configuration
- `<repo>/dns/adguard/work/` — query log + statistics DB
- `<repo>/dns/adguard/credentials.json` (mode 0600) — admin username/password + API secret

A timestamped copy of the first known-good config is kept at
`<repo>/dns/adguard/conf/AdGuardHome.yaml.baseline`.

Restore it with:

```bash
cd <repo>/dns/adguard
docker compose down
cp conf/AdGuardHome.yaml.baseline conf/AdGuardHome.yaml
docker compose up -d
```

Rebuild from scratch (config lost):

```bash
cd <repo>/dns/adguard
trash conf work && mkdir -p conf work
docker compose up -d          # AdGuard restarts in setup-wizard mode on :3000
```

## 6. What was deliberately NOT changed (so nothing needs undoing)

- router / modem DHCP + DNS settings (<ROUTER_IP>)
- router port-forwarding rules
- `/etc/resolv.conf`, `systemd-resolved`, NetworkManager
- Cloudflare Tunnel ingress (AdGuard is **not** published through it)
- Tailscale MagicDNS / split-DNS / `--accept-dns`
- Home Assistant, Frigate, Nextcloud, Mosquitto container configuration
- any host firewall rule (the account cannot write them non-interactively)
