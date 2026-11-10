#!/usr/bin/env bash
# Multi-architecture image of the ClosedLoopSensor (amd64 for the host, arm64 for the Raspberry Pi) with Buildx.
# It reuses the jar built by Testing/Packaging/phase1-compile-packages.py (ClosedLoopSensor/target), so the code is
# exactly the same as in the single-architecture image; only the image becomes multi-architecture.
# No emulation is needed because the Dockerfile only copies the jar on top of the Java base image.
# Usage (on the host, after phase 1):  bash hil_bench/host/build_closedloopsensor_multiarch.sh
set -e
source "$(dirname "$0")/../bench.env"
REG=${REGISTRY:?Set REGISTRY (or HOST_IP) in hil_bench/bench.env}
REPO=closedloopsensor
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
JAR=$(ls "$ROOT"/ClosedLoopSensor/target/ClosedLoopSensor-*-thorntail.jar | head -1)
BASE=openjdk:11.0.11-jre-slim
# work folder under $HOME (Docker installed as a snap has its own /tmp)
WORK="$(mktemp -d "$HOME/hil_build_XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

echo "== 1. jar: $JAR"
mkdir -p "$WORK/target"; cp "$JAR" "$WORK/target/"
sha256sum "$WORK/target/$(basename "$JAR")"

echo "== 2. base image: does it have an arm64 variant?"
docker buildx imagetools inspect "$BASE" | grep -E "Platform:" | sort -u
docker buildx imagetools inspect "$BASE" | grep -q "linux/arm64" || { echo "The base image $BASE has no arm64 variant"; exit 1; }
J=$(basename "$JAR")
printf 'FROM %s\nCOPY target/%s /%s\nENTRYPOINT ["java", "-jar", "/%s"]\n' "$BASE" "$J" "$J" "$J" > "$WORK/Dockerfile"
cat "$WORK/Dockerfile"

echo "== 3. Buildx builder with HTTP access to the local registry"
printf '[registry."localhost:5000"]\n  http = true\n  insecure = true\n[registry."%s"]\n  http = true\n  insecure = true\n' "$REG" > "$WORK/buildkitd.toml"
docker buildx inspect hil >/dev/null 2>&1 || docker buildx create --name hil --driver docker-container --driver-opt network=host --config "$WORK/buildkitd.toml"
docker buildx inspect hil --bootstrap | grep -E "Name:|Platforms:" | head -4

echo "== 4. multi-architecture build and push to the registry"
docker buildx build --builder hil --platform linux/amd64,linux/arm64 -t "localhost:5000/$REPO:latest" --push "$WORK"

echo "== 5. check: platforms of $REPO:latest in the registry"
docker buildx imagetools inspect --builder hil "localhost:5000/$REPO:latest" | grep -E "Platform:" | sort -u || echo "(could not check from here)"
