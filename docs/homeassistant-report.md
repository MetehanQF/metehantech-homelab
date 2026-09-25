# Home Assistant installation report

- Installed: 2026-09-20, Raspberry Pi 5 / Ubuntu / ARM64.
- Project/config: <repo>/homeassistant ; persistent ./config mounted at /config.
- Container: metehantech-homeassistant; official stable image version 2026.9.3.
- Image digest: ghcr.io/home-assistant/home-assistant@sha256:d8922685169707fd91e8b9729902d975f06157d005e422874d201e0261dda196
- Host networking; HTTP bound only to 127.0.0.1, <PRIMARY_NODE_IP> and <PRIMARY_NODE_TAILSCALE_IP>, port 8123. No wildcard/IPv6 HTTP listener.
- TZ Europe/Istanbul; restart unless-stopped; Docker boot enabled; healthcheck and bounded Docker logs.
- No privileged mode, Docker socket, new broker, public proxy/port forwarding or firewall changes.
- New compose.yaml, configuration.yaml, automations.yaml, scripts.yaml, scenes.yaml; generated .storage HTTP settings finalized after backup. Existing services/configs unchanged.
- Configuration validation passed; healthy after HA-only stop/start; all three HTTP addresses returned 200 from Pi. Remote-device/browser test and actual Pi reboot not performed.
- Frigate API reachable from HA at http://127.0.0.1:5400; custom integration and MQTT pending. Existing camera unchanged.
- No ERROR/CRITICAL log entries; one upstream rich/Python SyntaxWarning during config check, not a startup failure.
- Approximate idle HA memory: 233 MiB.
- Existing Frigate and four Nextcloud containers retained original IDs/start times and remained healthy. Status API operational=true.
- Initial available RAM ~10 GiB, free NVMe ~171 GiB. Docker 29.1.3, Compose 2.40.3.
- Next: create owner account at http://<PRIMARY_NODE_IP>:8123 ; then prepare MQTT + Frigate integration and REST monitoring sensors.

## Existing container/network inventory

metehantech-homeassistant | ghcr.io/home-assistant/home-assistant:stable | 
metehantech-frigate | ghcr.io/blakeblackshear/frigate | <PRIMARY_NODE_TAILSCALE_IP>:8555->8555/tcp, <PRIMARY_NODE_IP>:8555->8555/tcp, 8554/tcp, <PRIMARY_NODE_TAILSCALE_IP>:8971->8971/tcp, <PRIMARY_NODE_TAILSCALE_IP>:8555->8555/udp, <PRIMARY_NODE_IP>:8971->8971/tcp, <PRIMARY_NODE_IP>:8555->8555/udp, 127.0.0.1:5400->5000/tcp
metehantech-nextcloud-cron | nextcloud | 80/tcp
metehantech-nextcloud-app | nextcloud | 127.0.0.1:5300->80/tcp
metehantech-nextcloud-db | postgres | 5432/tcp
metehantech-nextcloud-redis | redis | 6379/tcp

bridge internal=false [{"Subnet":"172.17.0.0/16","IPRange":"","Gateway":"172.17.0.1"}]
host internal=false null
metehantech-camera_default internal=false [{"Subnet":"172.18.0.0/16","IPRange":"","Gateway":"172.18.0.1"}]
metehantech-cloud_backend internal=true [{"Subnet":"172.30.54.0/24","IPRange":"","Gateway":"172.30.54.1"}]
metehantech-cloud_frontend internal=false [{"Subnet":"172.30.53.0/24","IPRange":"","Gateway":"172.30.53.1"}]
