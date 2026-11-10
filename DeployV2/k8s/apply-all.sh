#!/usr/bin/env bash
set -euo pipefail

NS="simulateiot"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Namespace: ${NS}"
kubectl get ns "${NS}" >/dev/null 2>&1 || kubectl create ns "${NS}"

echo "==> Applying Mosquitto (per fog) and waiting rollouts"
kubectl -n "${NS}" apply -f "${DIR}/fogfoga0-mosquitto.manifest.yaml"
kubectl -n "${NS}" apply -f "${DIR}/fogfoga0-mosquitto.nodeport.yaml"
kubectl -n "${NS}" rollout status deploy/fogfoga0-mosquitto

echo "==> Applying MongoDB (per fog, internal only) and waiting rollouts"
kubectl -n "${NS}" apply -f "${DIR}/fogfoga0-mongo.manifest.yaml"
kubectl -n "${NS}" rollout status deploy/fogfoga0-mongo

echo "==> Applying Fog services and waiting rollouts"
kubectl -n "${NS}" apply -f "${DIR}/fogfoga0-fog.manifest.yaml"
kubectl -n "${NS}" rollout status deploy/fogfoga0-fog

# CEP_CPU=50m|100m|... deliberately limits the CPU of the CEP container (requests = limits) to emulate a CEP
# deployed on a resource-constrained device (the paper uses CEP_CPU=100m). Without CEP_CPU the CEP has no limits.
# CEP_W_MS, CEP_H_MS and CEP_MAX set the lateness window W, the reorder hold H and the buffer capacity MAX of the CEP
# ingress (environment variables CEP_LATENESS_W_MS, CEP_REORDER_HOLD_MS and CEP_REORDER_MAX_EVENTS of the CEP).
# Without them the defaults of the code apply: W = 5000 ms, H = 50 ms, MAX = 2000 events per topic.
if [ -n "${CEP_CPU:-}${CEP_W_MS:-}${CEP_H_MS:-}${CEP_MAX:-}" ]; then
  echo "==> Applying Esper (CEP) with CPU=${CEP_CPU:-unlimited} W=${CEP_W_MS:-5000} H=${CEP_H_MS:-50} MAX=${CEP_MAX:-2000} and waiting rollouts"
  python3 - "${DIR}/fogfoga0-cep-esper.manifest.yaml" "${CEP_CPU:-}" "${CEP_W_MS:-}" "${CEP_H_MS:-}" "${CEP_MAX:-}" <<'PY' | kubectl -n "${NS}" apply -f -
import sys
src, cpu, w, h, mx = sys.argv[1:6]
extra = [(k, v) for k, v in (("CEP_LATENESS_W_MS", w), ("CEP_REORDER_HOLD_MS", h), ("CEP_REORDER_MAX_EVENTS", mx)) if v]
out = []
in_esper = False
for line in open(src):
    out.append(line)
    s = line.strip()
    if s == "- name: esper":
        in_esper = True
        ind = line[:len(line) - len(line.lstrip())] + "  "
        if cpu:
            out.append(f'{ind}resources:\n{ind}  requests:\n{ind}    cpu: "{cpu}"\n{ind}  limits:\n{ind}    cpu: "{cpu}"\n')
    elif in_esper and s == "env:":
        ind = line[:len(line) - len(line.lstrip())] + "  "
        for k, v in extra:
            out.append(f'{ind}- name: {k}\n{ind}  value: "{v}"\n')
sys.stdout.write("".join(out))
PY
else
  echo "==> Applying Esper (CEP) and waiting rollouts"
  kubectl -n "${NS}" apply -f "${DIR}/fogfoga0-cep-esper.manifest.yaml"
fi
kubectl -n "${NS}" rollout status deploy/fogfoga0-cep-esper

# Wait until the CEP has initialised Esper and created its Receiver (line CEP_STATS_MS= in its log) before
# deploying the sensors, so that the start of the JVM does not overlap with the load. With a limited CPU
# (CEP_CPU) the start can take minutes. Maximum 600 s.
echo "==> Waiting for the CEP to be ready..."
T0=$(date +%s)
# grep -c instead of grep -q: with pipefail, grep -q closes the pipe and kubectl would end with SIGPIPE
until kubectl -n "${NS}" logs deploy/fogfoga0-cep-esper 2>/dev/null | grep -c "CEP_STATS_MS=" >/dev/null; do
  if [ $(( $(date +%s) - T0 )) -ge 600 ]; then echo "    the CEP did not start within 600 s"; exit 1; fi
  sleep 2
done
echo "    CEP ready after $(( $(date +%s) - T0 )) s"

# NODOS=5|100|250|... sets the total number of sensor nodes without editing the manifest
# (SENSOR_QUANTITY = NODOS - 1 background sensors, plus the ClosedLoopSensor). Without NODOS the manifest value is used.
if [ -n "${NODOS:-}" ]; then
  echo "==> Applying Sensors (NODOS=${NODOS}: SENSOR_QUANTITY=$((NODOS - 1))) and waiting rollouts"
  sed "/name: SENSOR_QUANTITY/{n;s/value: \"[0-9]*\"/value: \"$((NODOS - 1))\"/;}" "${DIR}/fogfoga0-sensor-sensthread1.manifest.yaml" \
    | kubectl -n "${NS}" apply -f -
else
  echo "==> Applying Sensors and waiting rollouts"
  kubectl -n "${NS}" apply -f "${DIR}/fogfoga0-sensor-sensthread1.manifest.yaml"
fi
kubectl -n "${NS}" rollout status deploy/fogfoga0-sensor-sensthread1

# SENSOR_NODE=raspberry deploys the thermal sensor on the Raspberry Pi of the HiL bench
# (closedloopsensor.raspberry.manifest.yaml, nodeSelector kubernetes.io/hostname: raspberrypi) instead of the host node.
CLS_MANIFEST="closedloopsensor.manifest.yaml"
[ "${SENSOR_NODE:-}" = "raspberry" ] && CLS_MANIFEST="closedloopsensor.raspberry.manifest.yaml"
echo "==> Applying ClosedLoopSensor (reactor batch thermal model, ${CLS_MANIFEST})"
if [ -f "${DIR}/${CLS_MANIFEST}" ]; then
  kubectl -n "${NS}" apply -f "${DIR}/${CLS_MANIFEST}"
  kubectl -n "${NS}" rollout status deploy/closedloopsensor
else
  echo "    ${CLS_MANIFEST} not found, skipping."
fi

# ACTUADOR=contenedor (default) deploys the containerised Java actuator acta0;
# ACTUADOR=yun does not deploy it, because the actuator is the physical Arduino Yún (topic B -> actuators/ack).
ACTUADOR="${ACTUADOR:-contenedor}"
if [ "${ACTUADOR}" = "yun" ]; then
  echo "==> Actuator: physical Arduino Yún (acta0 is not deployed)"
else
  echo "==> Applying Actuators and waiting rollouts"
  kubectl -n "${NS}" apply -f "${DIR}/fogfoga0-actuator-acta0.manifest.yaml"
  kubectl -n "${NS}" rollout status deploy/fogfoga0-actuator-acta0
fi

echo "==> Done."
kubectl -n "${NS}" get deploy,pods,svc
