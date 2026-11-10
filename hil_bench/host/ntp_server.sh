#!/usr/bin/env bash
# Turns the host into the time server of the HiL bench (chrony). It keeps synchronising with the public pools and
# also serves the time to the bench subnet (LAN_CIDR). If the Internet link drops it keeps serving its own time
# (local stratum 10), so the Raspberry Pi and the Yún stay aligned with each other.
# Usage (on the host):  sudo bash hil_bench/host/ntp_server.sh
# Undo:  sudo rm /etc/chrony/conf.d/hil_bench.conf && sudo systemctl restart chrony
set -e
source "$(dirname "$0")/../bench.env"
[ -n "${LAN_CIDR:-}" ] || { echo "Set LAN_CIDR in hil_bench/bench.env"; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "Run it with sudo"; exit 1; }
if ! command -v chronyd >/dev/null; then
  echo "== installing chrony (replaces systemd-timesyncd)"
  apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq chrony
fi
mkdir -p /etc/chrony/conf.d
printf '# HiL bench: serve the time to the bench subnet\nallow %s\nlocal stratum 10\n' "$LAN_CIDR" > /etc/chrony/conf.d/hil_bench.conf
grep -q "^confdir /etc/chrony/conf.d" /etc/chrony/chrony.conf || echo "confdir /etc/chrony/conf.d" >> /etc/chrony/chrony.conf
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow from "$LAN_CIDR" to any port 123 proto udp
fi
systemctl restart chrony
sleep 15
echo "== sources of the host"; chronyc -n sources
echo "== status"; chronyc tracking
