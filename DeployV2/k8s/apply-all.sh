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

echo "==> Applying Esper (CEP) and waiting rollouts"
kubectl -n "${NS}" apply -f "${DIR}/fogfoga0-cep-esper.manifest.yaml"
kubectl -n "${NS}" rollout status deploy/fogfoga0-cep-esper

echo "==> Applying Sensors and waiting rollouts"
kubectl -n "${NS}" apply -f "${DIR}/fogfoga0-sensor-sensthread1.manifest.yaml"
kubectl -n "${NS}" rollout status deploy/fogfoga0-sensor-sensthread1

echo "==> Applying ClosedLoopSensor (reactor batch thermal model)"
if [ -f "${DIR}/closedloopsensor.manifest.yaml" ]; then
  kubectl -n "${NS}" apply -f "${DIR}/closedloopsensor.manifest.yaml"
  kubectl -n "${NS}" rollout status deploy/closedloopsensor
else
  echo "    closedloopsensor.manifest.yaml not found, skipping."
fi

echo "==> Applying Actuators and waiting rollouts"
kubectl -n "${NS}" apply -f "${DIR}/fogfoga0-actuator-acta0.manifest.yaml"
kubectl -n "${NS}" rollout status deploy/fogfoga0-actuator-acta0

echo "==> Done."
kubectl -n "${NS}" get deploy,pods,svc
