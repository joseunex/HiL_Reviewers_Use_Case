# HiL bench

Files needed to run the experiments of the paper on physical devices, as in Section 7.4: the thermal sensor of the
loop (`ClosedLoopSensor`, a `UserDevice`) on a Raspberry Pi joined to the Kubernetes cluster, the cooling valve on an
Arduino Yún, and the rest of the components (broker, Fog node, MongoDB, CEP, background sensors) on the host.
Without physical devices the repository runs as described in `EXPERIMENT_GUIDE.txt`; this folder only adds the
variant with the two HiL nodes.

## Hardware of the bench of the paper

- Host: a laptop with Ubuntu 22.04, K3s server, the local Docker registry, chrony as NTP server of the bench and
  the Mosquitto NodePort (30100). Table 3 of the paper lists the versions.
- Raspberry Pi 3 Model B+ with Raspberry Pi OS 64-bit (arm64), K3s agent, wired Ethernet. Its node name must be
  `raspberrypi` (used by the node selector of `DeployV2/k8s/closedloopsensor.raspberry.manifest.yaml`).
- Arduino Yún (Wi-Fi) with a TinkerKit relay or LED module on output O0 as the valve. It must have its own power
  adapter: powered from the USB of the Raspberry Pi it causes under-voltage on the Pi.
- All three on the same local network. Fill in `bench.env` (copy `bench.env.example`) with the addresses.

## Setup, in order

1. Host as the time server of the bench: `sudo bash hil_bench/host/ntp_server.sh`.
2. Raspberry Pi: install K3s as an agent (https://docs.k3s.io/quick-start) with the token of the host, then
   `source hil_bench/bench.env && ssh "$RPI_HOST" "sudo bash -s $HOST_IP $RPI_IP $RPI_IFACE" < hil_bench/raspberry/join_k3s.sh`
   (server address, node IP and access to the registry of the host over HTTP) and
   `ssh "$RPI_HOST" "sudo bash -s $HOST_IP" < hil_bench/raspberry/ntp_client.sh` (chrony against the host only).
   Check with `kubectl get nodes` that `raspberrypi` is Ready.
3. Images: run phases 1 to 3 of `EXPERIMENT_GUIDE.txt` on the host and then
   `bash hil_bench/host/build_closedloopsensor_multiarch.sh`, which rebuilds the `closedloopsensor` image as a
   multi-architecture image (amd64 + arm64) with Buildx so that the Raspberry Pi can pull it.
4. Arduino Yún: connect it to the network through its web panel, then `bash hil_bench/yun_actuator/prepare_yun.sh`
   (NTP against the host and the clock helper `hil_clock.py` on its Linux side) and
   `bash hil_bench/yun_actuator/upload_sketch.sh` (compiles `yun_actuator.ino` with arduino-cli and the libraries of
   the generator, inserting the broker address, and uploads it over the network). The sketch subscribes to topic `B`,
   drives the valve, and publishes on `actuators/ack` the same JSON as the containerised actuator with 64-bit
   timestamps synchronised every 30 s with the Linux side of the Yún (Cristian's algorithm through the Bridge).
5. Clock alignment: `bash hil_bench/measure_clocks.sh` reports the chrony state of the host and of the Raspberry Pi
   and the NTP offset of the Yún (Section 7.4.3: Raspberry Pi within 0.1 ms, Linux side of the Yún about 2 ms,
   microcontroller about 5.5 ms more).

## Running

A single run, from `DeployV2/k8s/`:

```
CEP_CPU=100m NODOS=100 ACTUADOR=yun SENSOR_NODE=raspberry python3 run_experiment.py --name test --duration 600
```

`ACTUADOR=yun` does not deploy the containerised actuator (the Yún is the actuator) and `SENSOR_NODE=raspberry`
deploys the thermal sensor on the Raspberry Pi. The other variables are described in `EXPERIMENT_GUIDE.txt`.

The campaigns of the paper, with `hil_bench/campaign/run_campaign.sh` (resumable, random order per round, checks
of the bench before every run, stop file `~/hil_campaign/STOP`):

```
# scalability (Section 7.4.3): 6 scales x 5 rounds x 600 s, about 6 h
bash hil_bench/campaign/run_campaign.sh
# fault injection (Section 7.4.4): 5 nodes, 5 rounds, 420 s, CEP outage at 150 s for 60 s
SERIES=fallo bash hil_bench/campaign/run_campaign.sh
# sensitivity to the synchronization settings (Section 7.4.5): 3 rounds of 300 s; the default rows are scalability runs at 100 and 500 nodes
SERIES="h0 h200 w2000 max500" ROUNDS=3 DURATION=300 bash hil_bench/campaign/run_campaign.sh
```

The results go to `~/hil_campaign/data/<series>/<run>/` with the layout of `data/`. Summaries, tables and figures
are obtained with the scripts of `analysis/` (see `data/README.md`).

## Notes

- With the CPU of the CEP limited, the CEP needs from seconds to minutes after it starts before it settles (JIT
  compilation of the JVM under the quota); `apply-all.sh` waits for the CEP to be ready before deploying the sensors,
  and the paper analyses the last 180 s of each 600 s run.
- The Yún occasionally stops publishing acknowledgments in the middle of a run (twice in about a hundred runs).
  The campaign script counts the ACKs of every run in `status.csv`; a run with far fewer ACKs than the other
  runs of its series should be discarded and repeated after power-cycling the Yún.
- Under heavy load the container log of the CEP rotates; `run_experiment.py` streams the `ESPER_STATS` lines to
  `raw/cep_stats_stream.log` during the run so that the statistics are complete.
- Keep at least 20 GB free on the disk of the host: Kubernetes evicts the pods under disk pressure, and a 600 s run
  at 1500 nodes produces about 1 GB of logs and exports.
