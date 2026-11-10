#!/usr/bin/env bash
# Prepares the Linux side of the Arduino Yún for the HiL bench:
#  1) it takes the time from the host (NTP server of the bench) instead of the public servers;
#  2) it installs /root/hil_clock.py, which answers the system time in milliseconds (used by the sketch to
#     synchronise its clock, see hil_clock.py).
# The Yún must already be on the bench network (Wi-Fi configured through its web panel) and reachable by SSH.
# Usage (on the host, after filling hil_bench/bench.env):  bash hil_bench/yun_actuator/prepare_yun.sh
set -e
source "$(dirname "$0")/../bench.env"
[ -n "${HOST_IP:-}" ] || { echo "Set HOST_IP in hil_bench/bench.env"; exit 1; }
YUN="${YUN_HOST:-root@arduino.local}"
# the OpenWrt of the Yún only supports old SSH algorithms
SSHOPT=(-o ConnectTimeout=10 -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa
        -o KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1)
echo "It will ask for the password of the Yún"
ssh "${SSHOPT[@]}" "$YUN" "cat > /root/hil_clock.py" < "$(dirname "$0")/hil_clock.py"
ssh "${SSHOPT[@]}" "$YUN" "
echo '== 1. NTP: the host as the only server'
uci set system.ntp.server='$HOST_IP'
uci set system.ntp.enable_server=0
uci commit system
ntpd -q -n -p $HOST_IP && echo 'time set with the host'
/etc/init.d/sysntpd restart
sleep 2
ps | grep -v grep | grep ntpd
echo '== 2. /root/hil_clock.py test (two readings):'; printf '\n\n' | python -u /root/hil_clock.py
echo '== 3. tools to upload sketches over the network'
which merge-sketch-with-bootloader.lua run-avrdude kill-bridge 2>&1
echo \"== time on the Yún: \$(date)\"
"
echo "== time on the host: $(date)"
