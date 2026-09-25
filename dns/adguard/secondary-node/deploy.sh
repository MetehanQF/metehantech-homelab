#!/usr/bin/env bash
# Deploy the SECONDARY AdGuard Home resolver on the secondary node..
#
# Run on PcOld as root:   sudo ./deploy.sh
#
# Safe to re-run. It refuses to continue rather than guess, and it never touches
# anything outside its own project directory.
#
# What it does NOT do: change /etc/resolv.conf, touch ufw, stop any existing
# service, alter NFS/Portainer/Uptime Kuma, or modify router settings.

set -euo pipefail

PROJECT_DEFAULT=/opt/metehantech-dns
PROJECT="${PROJECT:-$PROJECT_DEFAULT}"
BUNDLE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="adguard/adguardhome@sha256:aba9e3bf0613be3ba3755e1fc311b126e2c24bec25e18b6483894a88283074f0"
# Bind addresses are required; there is no fallback to a real address, because a
# wrong or missing bind is how a resolver accidentally becomes world-reachable.
LAN_IP="${SECONDARY_NODE_IP:?set SECONDARY_NODE_IP (see config.example.env)}"
TS_IP="${SECONDARY_NODE_TAILSCALE_IP:?set SECONDARY_NODE_TAILSCALE_IP}"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    ok    %s\n' "$*"; }
warn() { printf '    WARN  %s\n' "$*"; }
die()  { printf '\n    ABORT %s\n\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- preflight
say "Preflight"
[ "$(id -u)" -eq 0 ] || die "run as root:  sudo ./deploy.sh"
command -v docker >/dev/null || die "docker not found"
docker compose version >/dev/null 2>&1 || die "docker compose v2 plugin not found"
ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"

# Port 53 must be free. Do NOT stop anything automatically if it is not.
if ss -lntu 2>/dev/null | awk '{print $5}' | grep -qE '(^|:)53$'; then
  echo
  ss -lntup 2>/dev/null | grep -E '(^|:)53\s|:53$' || true
  die "something already listens on port 53 (shown above). Identify it and decide deliberately; this script will not stop services."
fi
ok "tcp/udp 53 free"

for ip in "$LAN_IP" "$TS_IP"; do
  ip -br addr | grep -q "$ip" || die "address $ip is not present on this host — refusing to publish to an address we do not own"
done
ok "bind addresses $LAN_IP and $TS_IP present"

[ -f "$BUNDLE/credentials.json" ] || die "credentials.json missing from the bundle"
AGH_USER="${SUDO_USER:-root}"
AGH_UID="$(id -u "$AGH_USER")"
AGH_GID="$(id -g "$AGH_USER")"
ok "container will run as ${AGH_USER} (${AGH_UID}:${AGH_GID})"

if command -v ufw >/dev/null && ufw status 2>/dev/null | head -1 | grep -qi active; then
  warn "ufw is active. Docker's published-port DNAT bypasses ufw's INPUT chain, so"
  warn "no ufw rule is needed — and none is added. Verified after start-up below."
fi

# ---------------------------------------------------------------- install
say "Installing to $PROJECT"
mkdir -p "$PROJECT"/conf "$PROJECT"/work
install -m 0644 "$BUNDLE/compose.yaml" "$PROJECT/compose.yaml"
install -m 0600 -o "$AGH_UID" -g "$AGH_GID" "$BUNDLE/credentials.json" "$PROJECT/credentials.json"
printf 'AGH_UID=%s\nAGH_GID=%s\n' "$AGH_UID" "$AGH_GID" > "$PROJECT/.env"
chmod 0644 "$PROJECT/.env"
chmod 0700 "$PROJECT"
ok "project files in place"

say "Pulling the pinned image (same digest as Pi5)"
docker pull "$IMAGE" >/dev/null
ARCH="$(docker image inspect "$IMAGE" --format '{{.Architecture}}/{{.Os}}')"
ok "image present ($ARCH)"

# ---------------------------------------------------------------- first launch
# AdGuard refuses its very first start as a non-root user ("you must run it as
# administrator"). Bootstrap the config with a throwaway root container, then hand
# the files to the unprivileged uid and run the real service.
if [ ! -f "$PROJECT/conf/AdGuardHome.yaml" ]; then
  say "First launch bootstrap (throwaway root container)"
  docker rm -f agh-setup >/dev/null 2>&1 || true
  docker run -d --name agh-setup -u 0:0 \
    -v "$PROJECT/conf:/opt/adguardhome/conf" \
    -v "$PROJECT/work:/opt/adguardhome/work" \
    -p 127.0.0.1:3000:3000/tcp "$IMAGE" >/dev/null
  for _ in $(seq 1 30); do
    curl -fsS -o /dev/null "http://127.0.0.1:3000/control/install/get_addresses" && break
    sleep 1
  done
  USERNAME="$(python3 -c 'import json;print(json.load(open("'"$PROJECT"'/credentials.json"))["username"])')"
  PASSWORD="$(python3 -c 'import json;print(json.load(open("'"$PROJECT"'/credentials.json"))["password"])')"
  # --data @- keeps the password off the process list and out of any shell history.
  printf '{"web":{"ip":"0.0.0.0","port":3000},"dns":{"ip":"0.0.0.0","port":3053},"username":"%s","password":"%s"}' \
    "$USERNAME" "$PASSWORD" \
    | curl -fsS -o /dev/null -H 'Content-Type: application/json' --data @- \
        "http://127.0.0.1:3000/control/install/configure" \
    || die "install API call failed"
  unset PASSWORD
  sleep 3
  docker stop agh-setup >/dev/null && docker rm agh-setup >/dev/null
  [ -f "$PROJECT/conf/AdGuardHome.yaml" ] || die "AdGuard did not write its config"
  ok "base config generated"
else
  ok "existing config found — bootstrap skipped"
fi

chown -R "$AGH_UID:$AGH_GID" "$PROJECT/conf" "$PROJECT/work"
chmod 700 "$PROJECT/conf" "$PROJECT/work"
chmod 600 "$PROJECT/conf/AdGuardHome.yaml"
cp -a "$PROJECT/conf/AdGuardHome.yaml" "$PROJECT/conf/AdGuardHome.yaml.pre-sync" 2>/dev/null || true
ok "ownership handed to ${AGH_UID}:${AGH_GID}"

# ---------------------------------------------------------------- start
say "Starting the unprivileged service"
cd "$PROJECT"
docker compose up -d
for _ in $(seq 1 40); do
  state="$(docker inspect metehantech-adguard --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)"
  [ "$state" = "healthy" ] && break
  sleep 2
done
[ "$state" = "healthy" ] || die "container did not become healthy (state=$state). Check: docker logs metehantech-adguard"
ok "container healthy"

# ---------------------------------------------------------------- verify
say "Verification"
docker inspect metehantech-adguard --format \
'    privileged : {{.HostConfig.Privileged}}
    user       : {{.Config.User}}
    cap_add    : {{.HostConfig.CapAdd}}
    cap_drop   : {{.HostConfig.CapDrop}}
    security   : {{.HostConfig.SecurityOpt}}
    network    : {{.HostConfig.NetworkMode}}
    mem_limit  : {{.HostConfig.Memory}}'
echo "    docker socket mounted: $(docker inspect metehantech-adguard --format '{{range .Mounts}}{{.Source}} {{end}}' | grep -c docker.sock)"

echo "    listeners:"
ss -lntu 2>/dev/null | awk '$5 ~ /:53$|:3000$/ {print "      "$1" "$5}'
if ss -lntu 2>/dev/null | awk '{print $5}' | grep -qE '^(0\.0\.0\.0|\[::\]):53$'; then
  die "0.0.0.0:53 is bound — that is not the intended posture. Investigate before continuing."
fi
ok "bound to specific addresses only, never 0.0.0.0"

echo "    live DNS:"
printf '      example.com      -> %s\n' "$(dig +short +time=4 @$LAN_IP example.com | head -1)"
printf '      doubleclick.net  -> %s (0.0.0.0 = filtering active)\n' "$(dig +short +time=4 @$LAN_IP doubleclick.net | head -1)"

say "Done"
cat <<EOF
    Secondary resolver is up at ${LAN_IP}:53 and ${TS_IP}:53.
    Admin UI: http://${LAN_IP}:3000  (credentials in ${PROJECT}/credentials.json, mode 0600)

    NEXT, from Pi5:
        cd <repo>/tools/dns-cluster
        python3 cluster.py health
        python3 cluster.py parity      # expect drift: this node is still at defaults
        python3 cluster.py sync        # pull Pi5's configuration onto this node

    The router's DHCP settings have NOT been touched. Nothing uses this resolver yet.
EOF
