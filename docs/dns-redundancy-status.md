# Redundant AdGuard rollout — current status

Updated: 2026-09-21 18:45 Europe/Istanbul

## Deployed and validated

- Primary Node primary: `<PRIMARY_NODE_IP>:53`; Secondary Node secondary: `<SECONDARY_NODE_IP>:53`.
- Both run AdGuard Home v0.107.79 from the same pinned OCI digest.
- Secondary Node is unprivileged, persistent, health-checked, address-scoped, and has no
  Docker socket or host network access.
- Safe one-way Primary Node → Secondary Node sync completed. Post-sync drift: **0**.
- Behavioural parity: **26/26 match**. DNSSEC, filtering, TCP/UDP, NXDOMAIN,
  PTR, A/AAAA/CNAME and hardening behaviour match.
- Real Pi5-container outage: 6/6 test lookups continued through Secondary Node.
- Silent primary and secondary failures, SERVFAIL/upstream failure, recovery,
  and both-down behaviour were measured without changing router DHCP.
- Secondary Node query log preserved the real source `<PRIMARY_NODE_IP>` and inventory name.
- Control Center cluster monitoring is live: **HEALTHY, 2/2**. Test suite:
  **160 tests + 402 subtests passed**. Anonymous DNS API returns 401.

## Deliberately not done

- Router DHCP is unchanged and still advertises only `<ROUTER_IP>`.
- Whole-home DNS is not active.
- Secondary Node's real container was not stopped remotely because the available unattended
  account is intentionally not allowed to manage Docker. Its loss was exercised as
  an unreachable secondary; the real Primary Node container outage proved the opposite path.
- No router, firewall, system resolver, Tailscale DNS, or Primary Node AdGuard configuration
  was changed as part of the cutover.

## Approval gate

Before cutover, re-read and back up the router's live DHCP DNS and lease settings.
Then, only with explicit approval, set:

- Primary DNS: `<PRIMARY_NODE_IP>`
- Secondary DNS: `<SECONDARY_NODE_IP>`

The effective lease observed on Primary Node is `4294967295` (infinite), so existing clients
will require DHCP renew, Wi-Fi reconnect, or reboot. See `REPORT.md` and `RECOVERY.md`.
