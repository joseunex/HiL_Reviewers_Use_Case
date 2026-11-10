#!/usr/bin/env bash
# Runs a campaign of experiments on the HiL bench, one run_experiment.py execution after another, in rounds that
# cover all the scenarios in a random order (fixed seed), so that the repetitions of a scenario are spread over
# time. It is resumable (finished runs are skipped) and stops after two consecutive failures.
#
# Series (SERIES, space separated):
#   esc     scalability: one run per scale in SCALES (paper: 5 100 250 500 1000 1500, 600 s, 5 rounds)
#   fallo   fault injection at CRASH_NODES nodes: CEP scaled to 0 replicas at CRASH_AT s for CRASH_DUR s (paper: 5 nodes, 420 s, 5 rounds)
#   h0 h200 w2000 max500   sensitivity to the synchronization settings (paper: 3 rounds, 300 s):
#           h0 = 100 nodes with H = 0, h200 = 100 nodes with H = 200 ms, w2000 = 500 nodes with W = 2 s,
#           max500 = 500 nodes with a 500-event buffer. The default settings at 100 and 500 nodes are the esc runs.
# Environment (defaults in brackets): SERIES [esc], SCALES [5 100 250 500 1000 1500], ROUNDS [5], DURATION [600],
#   CEP_CPU [100m], ACTUADOR [yun | contenedor], SENSOR_NODE [raspberry | host], CRASH_NODES [5], CRASH_AT [150],
#   CRASH_DUR [60], DURATION_CRASH [420], BASE [$HOME/hil_campaign], MIN_FREE_GB [20], SEED [20261103], DRY [0]
# Usage (on the host, from the root of the repository, after filling hil_bench/bench.env):
#   mkdir -p ~/hil_campaign && nohup systemd-inhibit --what=sleep:idle:handle-lid-switch --why="HiL campaign" \
#     bash hil_bench/campaign/run_campaign.sh > ~/hil_campaign/nohup.log 2>&1 &
#   Progress: tail -f ~/hil_campaign/campaign.log     Stop after the current run: touch ~/hil_campaign/STOP
#   Plan only: DRY=1 bash hil_bench/campaign/run_campaign.sh
#   Without physical devices (everything in containers): ACTUADOR=contenedor SENSOR_NODE=host bash hil_bench/campaign/run_campaign.sh
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
[ -f "$HERE/../bench.env" ] && source "$HERE/../bench.env"
SRC_K8S="$ROOT/DeployV2/k8s"
BASE=${BASE:-"$HOME/hil_campaign"}
K8S="$BASE/k8s"
DATA="$BASE/data"
LOG="$BASE/campaign.log"
STATUS="$BASE/status.csv"
SERIES=${SERIES:-"esc"}
SCALES=${SCALES:-"5 100 250 500 1000 1500"}
ROUNDS=${ROUNDS:-5}
DURATION=${DURATION:-600}
CEPCPU=${CEP_CPU:-100m}
ACTUADOR=${ACTUADOR:-yun}
SENSOR_NODE=${SENSOR_NODE:-raspberry}
CRASH_NODES=${CRASH_NODES:-5}
CRASH_AT=${CRASH_AT:-150}
CRASH_DUR=${CRASH_DUR:-60}
DURATION_CRASH=${DURATION_CRASH:-420}
MIN_FREE_GB=${MIN_FREE_GB:-20}
SEED=${SEED:-20261103}
DRY=${DRY:-0}

mkdir -p "$BASE" "$DATA" "$BASE/runs"
log() { echo "$(date '+%F %T') | $*" | tee -a "$LOG"; }
stop_requested() { [ -f "$BASE/STOP" ]; }
CUR=""   # folder of the run in progress (if interrupted it is renamed so that it is not taken as valid)
on_signal() {
  log "Campaign interrupted (signal)"
  if [ -n "$CUR" ] && [ -d "$CUR" ]; then mv "$CUR" "${CUR}_interrupted_$(date +%s)"; log "  $(basename "$CUR") marked as interrupted"; fi
  exit 130
}
trap on_signal INT TERM

# Plan: round, series and nodes, with the order of each round shuffled with a fixed seed
plan() {
  for r in $(seq 1 "$ROUNDS"); do
    { for s in $SERIES; do
        case "$s" in
          esc)    for n in $SCALES; do echo "esc $n"; done ;;
          fallo)  echo "fallo $CRASH_NODES" ;;
          h0|h200) echo "$s 100" ;;
          w2000|max500) echo "$s 500" ;;
          *) echo "unknown series $s" >&2; exit 1 ;;
        esac
      done; } \
      | python3 -c "import sys, random; l = [x.strip() for x in sys.stdin if x.strip()]; random.seed($SEED + $r); random.shuffle(l); print('\n'.join(l))" \
      | sed "s/^/$r /"
  done
}
if [ "$DRY" = "1" ]; then plan; exit 0; fi

# Checks of the bench (repeated before every run)
checks() {
  local ok=0 lapnode lap
  lapnode=$(kubectl get nodes --no-headers 2>/dev/null | awk '$1!="raspberrypi"{print $1}' | head -n 1)
  lap=$(kubectl get nodes --no-headers 2>/dev/null | awk '$1!="raspberrypi"{print $2}' | head -n 1)
  [ "$lap" = "Ready" ] || { log "WARNING: the host node is not Ready ($lap)"; ok=1; }
  if [ "$SENSOR_NODE" = "raspberry" ]; then
    local rpi ip
    rpi=$(kubectl get nodes --no-headers 2>/dev/null | awk '$1=="raspberrypi"{print $2}')
    [ "$rpi" = "Ready" ] || { log "WARNING: the Raspberry Pi node is not Ready ($rpi)"; ok=1; }
    # Ready is not enough (a node can be Ready while unreachable): ping its IP
    ip=$(kubectl get node raspberrypi -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null)
    ping -c 2 -W 2 "${ip:-${RPI_IP:-}}" >/dev/null 2>&1 || { log "WARNING: the Raspberry Pi (${ip:-${RPI_IP:-?}}) does not answer to ping"; ok=1; }
  fi
  local term
  term=$(kubectl -n simulateiot get pods --no-headers 2>/dev/null | grep -c Terminating)
  [ "${term:-0}" -eq 0 ] || { log "WARNING: $term pods in Terminating state in simulateiot"; ok=1; }
  if [ "$ACTUADOR" = "yun" ]; then
    # the Yún answers to ping or on its SSH port (22)
    local h yun=1
    h=${YUN_HOST:-root@arduino.local}; h=${h#*@}
    if ping -c 2 -W 2 "$h" >/dev/null 2>&1 || timeout 5 bash -c "</dev/tcp/$h/22" 2>/dev/null; then yun=0; fi
    [ $yun -eq 0 ] || { log "WARNING: the Yún does not answer ($h)"; ok=1; }
  fi
  curl -s -m 5 http://localhost:5000/v2/ >/dev/null || { log "WARNING: the local registry does not answer"; ok=1; }
  local free; free=$(df --output=avail -BG "$HOME" | tail -n 1 | tr -dc '0-9')
  [ "${free:-0}" -ge "$MIN_FREE_GB" ] || { log "WARNING: ${free} GB free on the disk (minimum $MIN_FREE_GB: Kubernetes evicts pods under disk pressure)"; ok=1; }
  local dp; dp=$(kubectl get node "$lapnode" -o jsonpath='{.status.conditions[?(@.type=="DiskPressure")].status}' 2>/dev/null)
  [ "${dp:-False}" = "False" ] || { log "WARNING: the host node is in DiskPressure"; ok=1; }
  return $ok
}
wait_checks() {   # up to 15 minutes of retries before giving up
  local i
  for i in $(seq 1 30); do checks && return 0; sleep 30; done
  return 1
}
done_already() { [ -f "$DATA/$1/$2/config.json" ] && grep -q finished_at "$DATA/$1/$2/config.json" 2>/dev/null; }

# Local copy of the deployment scripts (the campaign does not depend on the repository folder while it runs)
[ -d "$K8S" ] || cp -r "$SRC_K8S" "$K8S"
[ -f "$STATUS" ] || echo "name,series,nodes,round,start,end,seconds,exit_code,acks" > "$STATUS"

log "===== Campaign: series=[$SERIES] scales=[$SCALES] rounds=$ROUNDS duration=${DURATION}s CEP_CPU=$CEPCPU actuator=$ACTUADOR sensor=$SENSOR_NODE (fault runs: $CRASH_NODES nodes, ${DURATION_CRASH}s, outage at ${CRASH_AT}s for ${CRASH_DUR}s)"
log "Plan: $(plan | tr '\n' ';')"

failures=0
while read -r r series n; do
  name=$(printf "%s_n%04d_r%d" "$series" "$n" "$r")
  if done_already "$series" "$name"; then log "already done: $name"; continue; fi
  if stop_requested; then log "Stop requested: the campaign stops before $name"; exit 0; fi
  if ! wait_checks; then log "The bench is not ready after 15 minutes: campaign stopped before $name"; exit 1; fi
  outdir="$DATA/$series"
  mkdir -p "$outdir"
  [ -d "$outdir/$name" ] && mv "$outdir/$name" "$outdir/${name}_incomplete_$(date +%s)"
  extra=""; dur=$DURATION; envx=""
  case "$series" in
    fallo)  extra="--crash-at $CRASH_AT --crash-duration $CRASH_DUR"; dur=$DURATION_CRASH ;;
    h0)     envx="CEP_H_MS=0" ;;
    h200)   envx="CEP_H_MS=200" ;;
    w2000)  envx="CEP_W_MS=2000" ;;
    max500) envx="CEP_MAX=500" ;;
  esac
  log "START $name (round $r, $series, nodes=$n, CEP_CPU=$CEPCPU $envx)"
  CUR="$outdir/$name"
  ini=$(date +%s); ini_iso=$(date -Iseconds)
  ( cd "$K8S" && env CEP_CPU=$CEPCPU NODOS=$n ACTUADOR=$ACTUADOR SENSOR_NODE=$SENSOR_NODE $envx python3 run_experiment.py --name "$name" \
      --duration "$dur" --k8s-dir "$K8S" --output-base "$outdir" $extra ) > "$BASE/runs/$name.out" 2>&1 < /dev/null
  rc=$?
  CUR=""
  fin=$(date +%s)
  acks=0
  f=$(ls "$outdir/$name"/raw/mongo/*actuators_ack.json 2>/dev/null | head -n 1)
  [ -n "$f" ] && acks=$(grep -c . "$f")
  cp "$BASE/runs/$name.out" "$outdir/$name/salida_run_experiment.txt" 2>/dev/null
  echo "$name,$series,$n,$r,$ini_iso,$(date -Iseconds),$((fin - ini)),$rc,$acks" >> "$STATUS"
  if [ $rc -ne 0 ]; then
    log "FAILED $name (exit code $rc, see runs/$name.out); cleaning the deployment"
    ( cd "$K8S" && bash reset-all.sh ) >> "$BASE/runs/$name.out" 2>&1 < /dev/null
    sleep 20
    failures=$((failures + 1))
    if [ $failures -ge 2 ]; then log "Two consecutive failed runs: campaign stopped, check the bench"; exit 1; fi
  else
    failures=0
    log "END $name in $((fin - ini)) s, $acks ACK"
  fi
done < <(plan)
log "===== Campaign finished ====="
