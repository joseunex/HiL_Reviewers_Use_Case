#!/usr/bin/env bash
set -euo pipefail

NS="simulateiot"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Resetting Kubernetes resources in namespace: ${NS}"
echo "==> Deleting Deployments (closedloopsensor, actuators, CEP, sensors, fog, mongo, mosquitto) - ignoring if missing"

# ClosedLoopSensor (reactor batch thermal model)
kubectl -n "${NS}" delete deploy closedloopsensor --ignore-not-found

# Actuators
kubectl -n "${NS}" delete deploy fogfoga0-actuator-acta0 --ignore-not-found

# CEP (Esper)
kubectl -n "${NS}" delete deploy fogfoga0-cep-esper --ignore-not-found

# Sensors
kubectl -n "${NS}" delete deploy fogfoga0-sensor-sensthread1 --ignore-not-found

# Fog services (NEW naming: fog<fogKey>-fog)
kubectl -n "${NS}" delete deploy fogfoga0-fog --ignore-not-found

# Mosquitto
kubectl -n "${NS}" delete deploy fogfoga0-mosquitto --ignore-not-found

echo "==> Deleting Services (mongo internal + mosquitto DNS + nodeports)"

# Mongo Services (ClusterIP internal)
kubectl -n "${NS}" delete deploy fogfoga0-mongo --ignore-not-found
kubectl -n "${NS}" delete svc  fogfoga0-mongo --ignore-not-found

# Mosquitto Services (stable DNS names)
kubectl -n "${NS}" delete svc mosquitto-foga0 --ignore-not-found

# Mosquitto NodePort Services (external access)
kubectl -n "${NS}" delete svc mosquitto-foga0-nodeport --ignore-not-found

echo "==> Deleting Mosquitto ConfigMaps"
kubectl -n "${NS}" delete cm fogfoga0-mosquitto-config --ignore-not-found

echo "==> Reset done. Current state:"
kubectl -n "${NS}" get deploy,pods,svc,cm
