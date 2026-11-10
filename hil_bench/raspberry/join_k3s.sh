#!/usr/bin/env bash
# Joins the k3s-agent of the Raspberry Pi to the K3s server of the host: server address, own IP on the wired
# interface and access to the local registry of the host (HTTP). K3s must already be installed on the Raspberry Pi
# as an agent (https://docs.k3s.io/quick-start, with the token of the server). The node must be named "raspberrypi",
# which is the hostname expected by DeployV2/k8s/closedloopsensor.raspberry.manifest.yaml.
# Usage (from the host, after filling hil_bench/bench.env):
#   source hil_bench/bench.env && ssh "$RPI_HOST" "sudo bash -s $HOST_IP $RPI_IP $RPI_IFACE" < hil_bench/raspberry/join_k3s.sh
# A copy of the agent environment file is kept before changing it (k3s-agent.service.env.bak.<date>).
set -e
SERVER=${1:?usage: join_k3s.sh <host IP> <Raspberry IP> [interface]}
IP=${2:?usage: join_k3s.sh <host IP> <Raspberry IP> [interface]}
IFACE=${3:-eth0}
REG="$SERVER:5000"
ENVF=/etc/systemd/system/k3s-agent.service.env
[ "$(id -u)" -eq 0 ] || { echo "Run it with sudo"; exit 1; }
ip -4 addr show "$IFACE" | grep -q "inet $IP/" || { echo "Interface $IFACE does not have the IP $IP: nothing changed"; exit 1; }
cp "$ENVF" "$ENVF.bak.$(date +%Y%m%d%H%M%S)"
echo "== K3S_URL before: $(grep '^K3S_URL' "$ENVF" || echo '(not in the env file)')"
if grep -q '^K3S_URL=' "$ENVF"; then
  sed -i "s#^K3S_URL=.*#K3S_URL='https://$SERVER:6443'#" "$ENVF"
else
  echo "K3S_URL='https://$SERVER:6443'" >> "$ENVF"
fi
echo "== K3S_URL now: $(grep '^K3S_URL' "$ENVF")"
mkdir -p /etc/rancher/k3s
printf 'node-ip: %s\nflannel-iface: %s\n' "$IP" "$IFACE" > /etc/rancher/k3s/config.yaml
printf 'mirrors:\n  "%s":\n    endpoint:\n      - "http://%s"\nconfigs:\n  "%s":\n    tls:\n      insecure_skip_verify: true\n' "$REG" "$REG" "$REG" > /etc/rancher/k3s/registries.yaml
echo "== /etc/rancher/k3s/config.yaml"; cat /etc/rancher/k3s/config.yaml
echo "== /etc/rancher/k3s/registries.yaml"; cat /etc/rancher/k3s/registries.yaml
systemctl daemon-reload
systemctl restart k3s-agent || true
echo "== waiting for the agent (30 s)..."; sleep 30
echo "== k3s-agent: $(systemctl is-active k3s-agent || true)"
journalctl -u k3s-agent --no-pager -n 15 | cut -c1-250
echo "== power supply: $(vcgencmd get_throttled 2>&1)   (0x0 = no under-voltage; power the Yún from its own adapter, not from the Raspberry Pi USB)"
echo "== disk"; df -h / | tail -1
