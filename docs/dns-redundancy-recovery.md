# Redundant DNS — rollback and recovery

## Current gate

The router DHCP DNS settings have **not** been changed. Until the explicit whole-home
deployment approval, removing or stopping the Secondary Node secondary cannot affect clients.

The current observed router-issued values are DNS `<ROUTER_IP>`, gateway
`<ROUTER_IP>`, and effective Primary Node lease time `4294967295`. Re-read the live router
values immediately before any cutover; do not rely on this historical observation.

## Secondary Node secondary rollback (before whole-home activation)

Run on Secondary Node as an administrator:

```bash
cd /opt/metehantech-dns
sudo docker compose down
```

This removes only the `metehantech-adguard` container and its dedicated Docker
network. Persistent configuration remains in `/opt/metehantech-dns/conf` and
`/opt/metehantech-dns/work`, so the operation is reversible with:

```bash
cd /opt/metehantech-dns
sudo docker compose up -d
```

Do not delete `/opt/metehantech-dns` during incident recovery. Preserve it for
forensics and rollback.

The pre-parity Secondary Node API snapshot is stored mode 0600 at:

`$BACKUP_ROOT/20260921T153412Z-dns-sync-pcold/pcold-before.json`

Normal drift detection is read-only:

```bash
cd <repo>/tools/dns-cluster
python3 cluster.py parity
```

The on-demand sync command validates Primary Node health and loop safety, backs up Secondary Node,
applies the parity contract, then validates health and zero drift:

```bash
cd <repo>/tools/dns-cluster
python3 cluster.py sync
```

## Control Center rollback

The pre-change files are in:

`$BACKUP_ROOT/20260921T104904Z-dns-redundancy/control-center/`

Restore only the files listed in that directory, then restart
`metehantech-status.service`. Do not replace the whole application tree.

## Future router rollback (not executed in this task)

Immediately before whole-home activation, read and save the router's actual DHCP
DNS values again. The currently observed state is primary `<ROUTER_IP>`, secondary
blank/default, but the live pre-change value—not this note—must be used as rollback.
Clients with long leases may need DHCP renew, Wi-Fi reconnect, or reboot after both
deployment and rollback.
