#!/usr/bin/env bash
# The Raspberry Pi takes the time only from the host (chrony, polling every 16-64 s), so that its clock and the
# clock of the host are aligned and the offset can be measured (hil_bench/measure_clocks.sh).
# Usage (from the host, after filling hil_bench/bench.env):
#   source hil_bench/bench.env && ssh "$RPI_HOST" "sudo bash -s $HOST_IP" < hil_bench/raspberry/ntp_client.sh
# Undo (on the Raspberry Pi):  sudo cp /etc/chrony/chrony.conf.bak-hil /etc/chrony/chrony.conf
#   sudo rm /etc/chrony/sources.d/hil_bench.sources && sudo systemctl restart chrony
set -e
SERVER=${1:?usage: ntp_client.sh <host IP>}
[ "$(id -u)" -eq 0 ] || { echo "Run it with sudo"; exit 1; }
if ! command -v chronyd >/dev/null; then
  echo "== installing chrony (replaces systemd-timesyncd)"
  apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq chrony
fi
[ -f /etc/chrony/chrony.conf.bak-hil ] || cp /etc/chrony/chrony.conf /etc/chrony/chrony.conf.bak-hil
sed -i 's/^\(pool\|server\) /#&/' /etc/chrony/chrony.conf
mkdir -p /etc/chrony/sources.d
echo "server $SERVER iburst minpoll 4 maxpoll 6" > /etc/chrony/sources.d/hil_bench.sources
grep -q "^sourcedir /etc/chrony/sources.d" /etc/chrony/chrony.conf || echo "sourcedir /etc/chrony/sources.d" >> /etc/chrony/chrony.conf
systemctl restart chrony
echo "== waiting for the synchronisation (60 s)"; sleep 60
echo "== sources of the Raspberry Pi"; chronyc -n sources
echo "== status (System time = offset with respect to the host)"; chronyc tracking
