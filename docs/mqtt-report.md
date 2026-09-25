# MetehanTech Frigate / Home Assistant phase 2 — 2026-09-20

## Deployment
- Mosquitto project: <repo>/mqtt; persistent config/, data/, log/.
- Container: metehantech-mosquitto; image eclipse-mosquitto:2, ARM64; restart unless-stopped; unprivileged UID 1000.
- Immutable image reference: eclipse-mosquitto@sha256:38c0da4f2ef84284d47b3b3eeea1cb3bdeabe81ee10caf0cd5c5ff61ee3ea408.
- Host publish: 127.0.0.1:1883 only. Existing camera Docker network attached; no LAN/public listener, firewall/proxy/Tailscale changes.
- Anonymous denied; separate random credentials for frigate/homeassistant/probe and topic ACLs. Credentials remain in mode-600 credentials.json within mode-700 project directory; never print them into chat. Password file contains hashes.
- Frigate MQTT: metehantech-mosquitto:1883 on existing bridge, client metehantech-frigate, prefix frigate.
- Only Frigate config.yml MQTT section changed; all stream/detection/recording values preserved. Config file mode restricted to 600.
- Home Assistant MQTT: 127.0.0.1:1883, distinct homeassistant account.
- Official blakeblackshear/frigate-hass-integration v5.15.6 installed manually into HA config/custom_components/frigate (not via HACS). Future upgrades are manual unless HACS is installed later.
- HA was stopped; core.config_entries was backed up then MQTT/Frigate entries added using installed entry schema. Existing entries and auth/user storage untouched. Configuration.yaml backed up; media_source and stream enabled.
- Frigate URL: http://127.0.0.1:5400.
- Live RTSP template: rtsp://172.18.0.2:8554/{{ name }}_main, uses current Frigate bridge IP and existing tapo_c211_main stream. No new 8554 host mapping. If Frigate is recreated and its bridge IP changes, update this integration option; test after network recreation. HA camera is camera.tapo_c211.

## Evidence
- Mosquitto running; authenticated Frigate and Home Assistant client connections seen in broker logs.
- Actual topics: frigate/available=online; homeassistant/status=online; frigate/tapo_c211/recordings/state=ON; motion/state=ON; detect/state=OFF.
- Anonymous MQTT connection rejected with Not authorized.
- HA and Frigate healthy. HA entity registry contains 37 Frigate entities including camera, sensors, switches and motion binary sensor.
- HA Container -> Frigate API HTTP 200.
- HA Container decoded RTSP main-stream frame at 2304x1296. Browser visual rendering not manually inspected.
- Camera FPS 5, excellent connection; new recording file verified on disk (~1.36 MB), newest segment ~13 seconds old at sample.
- Frigate restart caused a measured ~38.03-second segment gap. Recording resumed; existing recordings were not removed.
- Object/person detection was already disabled and remains disabled; therefore no claim of live object detection test. Motion and recording are ON.
- Four Nextcloud containers unchanged IDs/start times, all healthy; Nextcloud status installed=true, maintenance=false, needsDbUpgrade=false. Home/Clan HTTP 200; Status operational=true.
- HA logs have expected custom integration warning; no HA integration ERROR observed during checks.

## User action
No required setup step remains. Open Settings > Devices & Services > Frigate to see the device/entities; add camera.tapo_c211 to a dashboard if desired. Detection is intentionally left off.

## Backups and rollback
Timestamp backup directory: $BACKUP_ROOT/20260920T064138Z-frigate-mqtt
Includes original Frigate config.yml, HA configuration.yaml and core.config_entries, plus container baseline/stats.
Before any rollback, back up current files again. Stop HA, restore its two backed-up files, then restart HA. Restore Frigate config via docker cp and restart ONLY Frigate. Finally docker compose -f <repo>/mqtt/compose.yaml down; keep data directories. Do not restore old HA entries blindly after subsequent user changes.
New component files can remain inert after removing its entry; archive them if rolling back fully.

Sources:
https://docs.frigate.video/integrations/home-assistant/
https://github.com/blakeblackshear/frigate-hass-integration/releases/tag/v5.15.6
https://mosquitto.org/documentation/authentication-methods/
