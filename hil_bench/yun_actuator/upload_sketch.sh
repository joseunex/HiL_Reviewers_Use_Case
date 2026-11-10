#!/usr/bin/env bash
# Compiles the actuator sketch (yun_actuator.ino) with the same libraries that the SimulateIoT generator uses for
# Arduino nodes and uploads it to the Yún over the network: the hex file is copied to the Linux side of the Yún
# and the microcontroller is programmed from there. Requires arduino-cli with the arduino:avr core.
# The broker address (MQTT_HOST_foga0) is taken from HOST_IP of hil_bench/bench.env.
# Usage (on the host):  bash hil_bench/yun_actuator/upload_sketch.sh
set -e
source "$(dirname "$0")/../bench.env"
[ -n "${HOST_IP:-}" ] || { echo "Set HOST_IP in hil_bench/bench.env"; exit 1; }
[ -d "${ARDUINO_LIBS:-}" ] || { echo "Set ARDUINO_LIBS in hil_bench/bench.env (folder with Bridge, PubSubClient and TinkerKit)"; exit 1; }
YUN="${YUN_HOST:-root@arduino.local}"
SSHOPT=(-o ConnectTimeout=10 -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa
        -o KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1)
SKETCH="$(cd "$(dirname "$0")" && pwd)"
BUILD="$HOME/hil_build_yun"

echo "== libraries"
H=$(find "$ARDUINO_LIBS" -name PubSubClient.h | head -1)
echo "PubSubClient.h: $H"
grep -q "setBufferSize" "$H" && echo "PubSubClient with setBufferSize (2.8 or later)" || echo "WARNING: PubSubClient older than 2.8 (no setBufferSize)"
echo "== arduino:avr core"
if ! arduino-cli core list | grep -q "^arduino:avr"; then
  arduino-cli core update-index && arduino-cli core install arduino:avr
fi
arduino-cli core list | grep "^arduino:avr"

echo "== compiling (broker $HOST_IP)"
# the sketch is copied to a folder under $HOME (arduino-cli installed as a snap cannot read other mounts)
mkdir -p "$BUILD/sketch/yun_actuator"
sed "s/\"BROKER_IP\"/\"$HOST_IP\"/" "$SKETCH/yun_actuator.ino" > "$BUILD/sketch/yun_actuator/yun_actuator.ino"
arduino-cli compile --fqbn arduino:avr:yun --libraries "$ARDUINO_LIBS" --build-path "$BUILD" "$BUILD/sketch/yun_actuator"
HEX="$BUILD/yun_actuator.ino.hex"
ls -l "$HEX"

echo "== uploading to the Yún ($YUN): it will ask for its password"
ssh "${SSHOPT[@]}" "$YUN" 'cat > /tmp/sketch.hex && merge-sketch-with-bootloader.lua /tmp/sketch.hex && (kill-bridge 2>/dev/null || true) && run-avrdude /tmp/sketch.hex' < "$HEX"
echo "== done: the Yún starts the sketch, synchronises its clock and connects to the broker (10-20 s)"
