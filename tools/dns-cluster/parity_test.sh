#!/usr/bin/env bash
# Phase 4 — behavioural parity battery.
# Asks both resolvers the same questions and reports whether a client would get the
# same answer whichever one it happened to pick.
#
#   ./parity_test.sh <primary-ip> <secondary-ip>
#
# Read-only: it only sends DNS queries.

# Addresses are required. No default points at a real resolver: querying the
# wrong host silently would make the parity report meaningless.
A="${1:-${PRIMARY_NODE_IP:-}}"
B="${2:-${SECONDARY_NODE_IP:-}}"
if [ -z "$A" ] || [ -z "$B" ]; then
  echo "usage: $0 <primary-ip> <secondary-ip>" >&2
  echo "   or: set PRIMARY_NODE_IP and SECONDARY_NODE_IP (see config.example.env)" >&2
  exit 1
fi

pass=0; fail=0

cmp_row() {           # label, dig-args...
  local label="$1"; shift
  local ra rb
  # The server address is stripped from any error text, otherwise two resolvers that
  # behave identically (e.g. both silently drop version.bind) compare as different
  # purely because their own IP appears in dig's message.
  ra="$(dig +time=5 +tries=1 "@$A" "$@" 2>&1 | grep -oP 'status: \K[A-Z]+' | head -1)|$(dig +short +time=5 +tries=1 "@$A" "$@" 2>&1 | sed "s/$A/SERVER/g" | sort | tr '\n' ',' )"
  rb="$(dig +time=5 +tries=1 "@$B" "$@" 2>&1 | grep -oP 'status: \K[A-Z]+' | head -1)|$(dig +short +time=5 +tries=1 "@$B" "$@" 2>&1 | sed "s/$B/SERVER/g" | sort | tr '\n' ',' )"
  if [ "$ra" = "$rb" ]; then
    pass=$((pass+1)); printf "  MATCH     %-34s %s\n" "$label" "${ra:0:66}"
  else
    fail=$((fail+1)); printf "  DIFFER    %-34s\n      primary   : %s\n      secondary : %s\n" "$label" "${ra:0:90}" "${rb:0:90}"
  fi
}

flag_row() {          # label, expected-flag, dig-args...
  local label="$1" want="$2"; shift 2
  local fa fb
  fa="$(dig +dnssec +time=5 +tries=1 "@$A" "$@" 2>&1 | grep -oP '^;; flags: \K[a-z ]+' | head -1 | grep -ow "$want" || echo MISSING)"
  fb="$(dig +dnssec +time=5 +tries=1 "@$B" "$@" 2>&1 | grep -oP '^;; flags: \K[a-z ]+' | head -1 | grep -ow "$want" || echo MISSING)"
  if [ "$fa" = "$fb" ] && [ "$fa" = "$want" ]; then
    pass=$((pass+1)); printf "  MATCH     %-34s both have '%s'\n" "$label" "$want"
  else
    fail=$((fail+1)); printf "  DIFFER    %-34s primary=%s secondary=%s\n" "$label" "$fa" "$fb"
  fi
}

echo "Behavioural parity:  primary $A   vs   secondary $B"
echo
echo "-- resolution"
cmp_row "normal domain (A)"            example.com A
cmp_row "normal domain (AAAA)"         example.com AAAA
cmp_row "CNAME chain"                  www.github.com A
cmp_row "explicit CNAME record"        www.wikipedia.org CNAME
cmp_row "MX"                           gmail.com MX
cmp_row "TXT"                          cloudflare.com TXT
cmp_row "NS"                           iana.org NS
echo
echo "-- filtering"
cmp_row "blocked ad domain"            doubleclick.net A
cmp_row "blocked ad domain (AAAA)"     doubleclick.net AAAA
cmp_row "second blocked domain"        ads.doubleclick.net A
cmp_row "NOT blocked (control)"        github.com A
cmp_row "bank must resolve"            garanti.com.tr A
cmp_row "HA push must resolve"         mobile-apps.home-assistant.io A
echo
echo "-- negative / error handling"
cmp_row "NXDOMAIN"                     this-name-does-not-exist-mt.example A
cmp_row "NXDOMAIN (tld)"               nonexistent-tld-mt.invalid A
echo
echo "-- DNSSEC"
cmp_row "dnssec valid"                 cloudflare.com A
flag_row "dnssec authenticated-data" ad cloudflare.com A
cmp_row "dnssec BROKEN -> SERVFAIL"    dnssec-failed.org A
cmp_row "dnssec signed control"        sigok.verteiltesysteme.net A
echo
echo "-- local / PTR"
cmp_row "PTR of primary"               -x "$A"
cmp_row "PTR of secondary"             -x "$B"
cmp_row "PTR public"                   -x 1.1.1.1
echo
echo "-- server hardening parity"
cmp_row "version.bind refused"         version.bind ch txt
cmp_row "ANY refused"                  isc.org ANY
echo
echo "-- transport"
echo "  (TCP)"
for d in example.com doubleclick.net; do
  ra="$(dig +tcp +short +time=5 +tries=1 "@$A" "$d" A | sort | tr '\n' ',')"
  rb="$(dig +tcp +short +time=5 +tries=1 "@$B" "$d" A | sort | tr '\n' ',')"
  if [ "$ra" = "$rb" ]; then pass=$((pass+1)); printf "  MATCH     %-34s %s\n" "tcp $d" "$ra"
  else fail=$((fail+1)); printf "  DIFFER    %-34s %s vs %s\n" "tcp $d" "$ra" "$rb"; fi
done

echo
echo "=============================================="
printf "  PARITY: %d match, %d differ\n" "$pass" "$fail"
echo "=============================================="
[ "$fail" -eq 0 ]
