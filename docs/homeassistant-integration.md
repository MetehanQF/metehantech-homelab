# MetehanTech integration preparation

## Frigate
- Existing Frigate 0.18.0, bridge network `metehantech-camera_default` (172.18.0.0/16).
- Home Assistant host networking reaches the existing private API at `http://127.0.0.1:5400` (container port 5000). Never publish this unauthenticated API publicly.
- Existing authenticated UI port: LAN <PRIMARY_NODE_IP>:8971 and Tailscale <PRIMARY_NODE_TAILSCALE_IP>:8971.
- Camera `tapo_c211`; stream, detection and recording config unchanged.
- MQTT is disabled in Frigate. No broker container, systemd broker or 1883/8883 listener detected on Pi; this does not exclude a broker elsewhere on LAN.
- Frigate custom integration is NOT installed. Complete HA owner onboarding first; subsequently install the official Frigate integration via HACS and plan an authenticated private MQTT broker shared by HA and Frigate. Event/entity functionality needs MQTT. Do not change Frigate until the next approved integration stage.

## Monitoring (preparation only)
- Prefer built-in Home Assistant REST sensors polling `http://127.0.0.1:5200/api/status` every 60 seconds. It returns `devices` keyed by `id` (pi5/pcold), metrics.temperature, metrics.ram, metrics.disk, metrics.load, checks and services.
- Convert units carefully; UNKNOWN/unreachable must become unavailable, never zero. `load` is load average, NOT CPU percentage.
- Existing Secondary Node source: `http://<SECONDARY_NODE_IP>:8765/status`; Pi aggregates it. Existing metrics.db retains temperature/RAM/disk/load history.
- Secondary Node watchdog API: `http://<SECONDARY_NODE_IP>:8766/incidents`, restricted to allowed source IPs. Prefer the existing Pi incident aggregation rather than changing watchdog ACLs or listening addresses.
- For true Pi CPU percentage, use HA System Monitor CPU sensor after onboarding and compare against host measurements; container disk/process views may not equal host views. For Secondary Node CPU percentage, a later read-only collector extension would be required; current API provides load only.
- No metrics/watchdog changes or new agents deployed. Do not mount Docker socket or grant privileged mode just for monitoring.

## Access and recovery
- LAN: http://<PRIMARY_NODE_IP>:8123
- Tailscale: http://<PRIMARY_NODE_TAILSCALE_IP>:8123 (subject to tailnet ACLs).
- No Cloudflare ingress, public forwarding, firewall or Tailscale config changes.
- Existing protected host firewall/Cloudflare configuration could not be fully read without sudo; no claim of external perimeter audit. No global IPv6 HTTP bind is intended.
- Docker is enabled at boot; restart unless-stopped handles reboot/startup retry. No actual Pi reboot performed, to preserve other services.
- After the next planned reboot: `python3 <repo>/homeassistant/verify.py`.
- Roll back: `docker compose -f <repo>/homeassistant/compose.yaml down`. Keep config for recovery; no volumes/data deletion.
- Before future edits: timestamp-backup compose.yaml and config (including hidden .storage). Backups contain credentials after onboarding; restrict access. For consistent SQLite backup, stop only HA briefly or use SQLite backup API.
- Initial pre-start backup and existing container baseline: `$BACKUP_ROOT/20260920T063018Z-homeassistant`.

Sources: https://www.home-assistant.io/installation/linux ; https://docs.frigate.video/integrations/home-assistant/ ; https://www.home-assistant.io/integrations/systemmonitor/

## HTTP migration detail
Home Assistant 2026.9.3 migrated initial YAML HTTP settings into `.storage/http`. After successful HTTP probes, HA alone was stopped, both files were timestamp-backed up, the tested pending listen configuration was persisted as stable, and the obsolete YAML HTTP block was removed. No user/authentication store was edited. Final verifier checks both stable storage and exact socket bindings. Preserve `.storage` in backups.
