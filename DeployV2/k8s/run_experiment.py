#!/usr/bin/env python3
"""
Experiment runner for Use Case 2: Closed-Loop Reactor Control.

Usage:
    python3 run_experiment.py --name exp1_5nodes --duration 300
    python3 run_experiment.py --name exp2_50nodes --duration 600
    python3 run_experiment.py --name exp3_100nodes --duration 600

Prerequisites:
    - Kubernetes cluster running with namespace 'simulateiot' available
    - apply-all.sh and reset-all.sh in the same directory (or specify --k8s-dir)
    - MongoDB pod accessible via kubectl exec
    - docker accessible from the host (for docker stats)

What it does (in order):
    1. Creates the experiment output directory
    2. Saves experiment config
    3. Deploys everything (apply-all.sh)
    4. Starts docker stats collection in background
    5. Waits for the configured duration
    6. Stops docker stats collection
    7. Exports MongoDB collections to JSON
    8. Collects logs from all relevant pods (sensors, CEP, actuator, fog, closedloopsensor)
    9. Runs reset-all.sh to clean up
"""

import argparse
import datetime
import json
import os
import signal
import subprocess
import sys
import threading
import time


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NAMESPACE = "simulateiot"
MONGO_DB_PREFIX = "Fog_Node_"   # MongoGestor creates DBs as "Fog_Node_<fogId>"
STATS_INTERVAL_SEC = 2          # polling interval for docker stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def run(cmd, cwd=None, check=True, capture=False):
    """Run a shell command, optionally capturing output."""
    log(f"$ {cmd}")
    if capture:
        r = subprocess.run(cmd, shell=True, cwd=cwd, check=check,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return r.stdout.strip()
    else:
        subprocess.run(cmd, shell=True, cwd=cwd, check=check)
        return None


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Resource stats collector (runs in a background thread)
# Uses 'kubectl top pods' for Kubernetes environments
# ---------------------------------------------------------------------------
class ResourceStatsCollector:
    """Polls 'kubectl top pods' periodically and appends to a CSV."""

    def __init__(self, output_path, namespace=NAMESPACE, interval_sec=STATS_INTERVAL_SEC):
        self.output_path = output_path
        self.namespace = namespace
        self.interval = interval_sec
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        # Write CSV header
        with open(self.output_path, "w") as f:
            f.write("timestamp,pod_name,cpu_millicores,mem_mib\n")

        # Check if metrics-server is available
        test = subprocess.run(
            ["kubectl", "top", "pods", "-n", self.namespace, "--no-headers"],
            capture_output=True, text=True, timeout=15
        )
        if test.returncode != 0:
            log(f"WARNING: 'kubectl top pods' failed ({test.stderr.strip()}). "
                f"Resource collection may not work. Is metrics-server installed?")

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log(f"Resource stats collection started -> {self.output_path}")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=15)
        log("Resource stats collection stopped")

    def _loop(self):
        while not self._stop.is_set():
            try:
                ts = datetime.datetime.now().isoformat()
                result = subprocess.run(
                    ["kubectl", "top", "pods", "-n", self.namespace, "--no-headers"],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    with open(self.output_path, "a") as f:
                        for line in result.stdout.strip().split("\n"):
                            if not line.strip():
                                continue
                            # Format: "pod-name   123m   456Mi"
                            parts = line.split()
                            if len(parts) >= 3:
                                pod_name = parts[0]
                                # CPU: "123m" -> 123 millicores
                                cpu_str = parts[1]
                                cpu_mc = cpu_str.replace("m", "").strip()
                                # Memory: "456Mi" -> 456 MiB
                                mem_str = parts[2]
                                mem_mib = mem_str.replace("Mi", "").strip()
                                f.write(f"{ts},{pod_name},{cpu_mc},{mem_mib}\n")
            except Exception as e:
                log(f"kubectl top pods error: {e}")

            self._stop.wait(self.interval)


# ---------------------------------------------------------------------------
# MongoDB export
# ---------------------------------------------------------------------------
def find_mongo_pod():
    """Find the MongoDB pod name in the namespace."""
    out = run(
        f"kubectl get pods -n {NAMESPACE} -l app -o jsonpath='{{.items[*].metadata.name}}'",
        capture=True
    )
    pods = out.split()
    for p in pods:
        if "mongo" in p.lower():
            return p
    return None


def export_mongo(output_dir):
    """Export all collections from the Fog MongoDB to JSON files via kubectl exec."""
    mongo_pod = find_mongo_pod()
    if not mongo_pod:
        log("WARNING: No MongoDB pod found, skipping export")
        return

    log(f"Found MongoDB pod: {mongo_pod}")

    # List databases
    dbs_json = run(
        f"kubectl exec -n {NAMESPACE} {mongo_pod} -- "
        f"mongosh --quiet --eval 'JSON.stringify(db.adminCommand({{listDatabases:1}}).databases.map(d=>d.name))'",
        capture=True, check=False
    )

    if not dbs_json:
        log("WARNING: Could not list MongoDB databases")
        return

    try:
        dbs = json.loads(dbs_json)
    except json.JSONDecodeError:
        log(f"WARNING: Could not parse database list: {dbs_json}")
        return

    fog_dbs = [d for d in dbs if d.startswith(MONGO_DB_PREFIX) or d.startswith("Fog")]
    if not fog_dbs:
        log("WARNING: No Fog databases found in MongoDB")
        return

    log(f"Found Fog databases: {fog_dbs}")

    for db_name in fog_dbs:
        # List collections
        cols_json = run(
            f"kubectl exec -n {NAMESPACE} {mongo_pod} -- "
            f"mongosh --quiet --eval 'JSON.stringify(db.getSiblingDB(\"{db_name}\").getCollectionNames())'",
            capture=True, check=False
        )

        if not cols_json:
            continue

        try:
            collections = json.loads(cols_json)
        except json.JSONDecodeError:
            log(f"WARNING: Could not parse collections for {db_name}: {cols_json}")
            continue

        for col in collections:
            safe_col = col.replace("/", "_").replace("\\", "_")
            out_file = f"/tmp/mongo_export_{db_name}_{safe_col}.json"
            local_file = os.path.join(output_dir, f"{db_name}__{safe_col}.json")

            log(f"Exporting {db_name}.{col} ...")

            # Export via mongosh (mongoexport may not be installed in the image)
            run(
                f"kubectl exec -n {NAMESPACE} {mongo_pod} -- "
                f"mongosh --quiet --eval '"
                f"db.getSiblingDB(\"{db_name}\").getCollection(\"{col}\").find().forEach(function(d){{print(JSON.stringify(d))}})"
                f"' > {local_file}",
                check=False
            )

            if os.path.exists(local_file) and os.path.getsize(local_file) > 0:
                log(f"  -> {local_file} ({os.path.getsize(local_file)} bytes)")
            else:
                log(f"  -> WARNING: export empty or failed for {db_name}.{col}")


# ---------------------------------------------------------------------------
# Log collection
# ---------------------------------------------------------------------------
def collect_logs(output_dir):
    """Collect logs from all pods in the namespace."""
    out = run(
        f"kubectl get pods -n {NAMESPACE} -o jsonpath='{{.items[*].metadata.name}}'",
        capture=True, check=False
    )

    if not out:
        log("WARNING: No pods found for log collection")
        return

    pods = out.split()
    logs_dir = ensure_dir(os.path.join(output_dir, "logs"))

    for pod in pods:
        safe_name = pod.replace("/", "_")
        log_file = os.path.join(logs_dir, f"{safe_name}.log")
        log(f"Collecting logs from {pod} ...")
        run(
            f"kubectl logs -n {NAMESPACE} {pod} --tail=-1 > {log_file} 2>&1",
            check=False
        )


# ---------------------------------------------------------------------------
# Main experiment flow
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Fault injection: CEP outage during the measurement (Section 7.4.4 of the paper)
# ---------------------------------------------------------------------------
def wait_with_cep_crash(args, raw_dir):
    """Wait for the experiment duration and inject a CEP outage: at second args.crash_at the CEP Deployment is scaled
    to 0 replicas and restored to 1 after args.crash_duration seconds. The CEP log is saved first (the pod disappears)
    and the instants of the outage, of the restoration and of the moment the CEP is ready again (line CEP_STATS_MS=
    in the log of the new pod) are returned."""
    dep = "deploy/fogfoga0-cep-esper"
    info = {"crash_at_sec": args.crash_at, "crash_duration_sec": args.crash_duration}
    t0 = time.time()
    state = "before"
    try:
        while True:
            el = time.time() - t0
            if el >= args.duration:
                break
            if state == "before" and el >= args.crash_at:
                run(f"kubectl -n {NAMESPACE} logs {dep} > {os.path.join(raw_dir, 'cep_log_before_the_outage.log')} 2>&1",
                    check=False)
                info["crash_start_ms"] = int(time.time() * 1000)
                run(f"kubectl -n {NAMESPACE} scale {dep} --replicas=0", check=False)
                log(f"  CEP crash injected at {el:.0f}s")
                state = "down"
            elif state == "down" and el >= args.crash_at + args.crash_duration:
                info["crash_end_ms"] = int(time.time() * 1000)
                run(f"kubectl -n {NAMESPACE} scale {dep} --replicas=1", check=False)
                log(f"  CEP restored at {el:.0f}s")
                state = "restarting"
            elif state == "restarting":
                r = subprocess.run(["kubectl", "-n", NAMESPACE, "logs", dep],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                if "CEP_STATS_MS=" in (r.stdout or ""):
                    info["cep_ready_after_restart_ms"] = int(time.time() * 1000)
                    log(f"  CEP ready again at {el:.0f}s")
                    state = "after"
            time.sleep(1)
    except KeyboardInterrupt:
        log("Experiment interrupted by user")
    return info


def run_experiment(args):
    exp_dir = ensure_dir(os.path.join(args.output_base, args.name))
    raw_dir = ensure_dir(os.path.join(exp_dir, "raw"))

    log(f"========== EXPERIMENT: {args.name} ==========")
    log(f"Output directory: {exp_dir}")
    log(f"Duration: {args.duration}s")
    log(f"K8s manifests dir: {args.k8s_dir}")

    # ----- 1. Save config -----
    config = {
        "experiment_name": args.name,
        "duration_sec": args.duration,
        "stats_interval_sec": STATS_INTERVAL_SEC,
        "k8s_dir": os.path.abspath(args.k8s_dir),
        "namespace": NAMESPACE,
        # Environment variables read by apply-all.sh
        "actuador": os.environ.get("ACTUADOR", "contenedor"),
        "nodos": os.environ.get("NODOS", "manifest value"),
        "cep_cpu": os.environ.get("CEP_CPU", "unlimited"),
        "cep_w_ms": os.environ.get("CEP_W_MS", "5000 (default)"),
        "cep_h_ms": os.environ.get("CEP_H_MS", "50 (default)"),
        "cep_max": os.environ.get("CEP_MAX", "2000 (default)"),
        "started_at": datetime.datetime.now().isoformat(),
    }
    config_path = os.path.join(exp_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    log(f"Config saved to {config_path}")

    # ----- 2. Deploy -----
    log("Deploying (apply-all.sh) ...")
    t_deploy_start = time.time()
    run("bash apply-all.sh", cwd=args.k8s_dir)
    t_deploy_end = time.time()
    deploy_time = t_deploy_end - t_deploy_start
    log(f"Deployment completed in {deploy_time:.1f}s")

    # Save deploy time
    with open(os.path.join(raw_dir, "deploy_time.txt"), "w") as f:
        f.write(f"deploy_start={datetime.datetime.fromtimestamp(t_deploy_start).isoformat()}\n")
        f.write(f"deploy_end={datetime.datetime.fromtimestamp(t_deploy_end).isoformat()}\n")
        f.write(f"deploy_duration_sec={deploy_time:.2f}\n")

    # Copy the ESPER_STATS lines of the CEP in parallel to raw/cep_stats_stream.log, because under heavy load the
    # container log rotates and kubectl logs only returns the last part (seen at 2000 nodes). The loop reattaches
    # if the CEP pod restarts (injected outage).
    stats_stream_file = open(os.path.join(raw_dir, "cep_stats_stream.log"), "w")
    stats_stream = subprocess.Popen(
        f"while true; do kubectl -n {NAMESPACE} logs -f --tail=-1 deploy/fogfoga0-cep-esper 2>/dev/null"
        f" | grep --line-buffered '^ESPER_STATS'; sleep 2; done",
        shell=True, stdout=stats_stream_file, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)

    # Node and image (digest) of each pod, to record which images were used in each run
    try:
        jp = '{range .items[*]}{.metadata.name}{"\\t"}{.spec.nodeName}{"\\t"}{.status.containerStatuses[0].imageID}{"\\n"}{end}'
        out = subprocess.run(["kubectl", "get", "pods", "-n", NAMESPACE, "-o", "jsonpath=" + jp],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30).stdout
        with open(os.path.join(raw_dir, "pods_imagenes.txt"), "w") as f:
            f.write(out)
    except Exception as e:
        log(f"WARNING: could not save pods_imagenes.txt ({e})")

    # ----- 3. Start resource stats -----
    stats_file = os.path.join(raw_dir, "kubectl_top.csv")
    stats = ResourceStatsCollector(stats_file, interval_sec=STATS_INTERVAL_SEC)
    stats.start()

    # ----- 4. Wait for experiment duration -----
    log(f"Experiment running for {args.duration}s ...")
    log(f"  (Press Ctrl+C to stop early)")

    if args.crash_at is not None:
        config.update(wait_with_cep_crash(args, raw_dir))
    else:
        try:
            for remaining in range(args.duration, 0, -1):
                time.sleep(1)
                if remaining % 60 == 0:
                    log(f"  {remaining}s remaining ...")
        except KeyboardInterrupt:
            log("Experiment interrupted by user")

    # ----- 5. Stop docker stats -----
    stats.stop()

    # Stop the copy of the CEP statistics
    try:
        os.killpg(os.getpgid(stats_stream.pid), signal.SIGTERM)
        stats_stream.wait(timeout=10)
    except Exception as e:
        log(f"WARNING: could not stop the copy of the CEP statistics ({e})")
    stats_stream_file.close()

    # ----- 6. Export MongoDB -----
    log("Exporting MongoDB ...")
    mongo_dir = ensure_dir(os.path.join(raw_dir, "mongo"))
    export_mongo(mongo_dir)

    # ----- 7. Collect logs -----
    log("Collecting pod logs ...")
    collect_logs(raw_dir)

    # ----- 8. Save end time -----
    config["finished_at"] = datetime.datetime.now().isoformat()
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    # ----- 9. Reset -----
    log("Resetting (reset-all.sh) ...")
    run("bash reset-all.sh", cwd=args.k8s_dir)

    log(f"========== EXPERIMENT {args.name} COMPLETE ==========")
    log(f"Results in: {exp_dir}")
    log(f"  raw/kubectl_top.csv     - resource consumption over time (kubectl top pods)")
    log(f"  raw/mongo/              - MongoDB exports (JSON)")
    log(f"  raw/logs/              - pod logs")
    log(f"  raw/deploy_time.txt    - deployment timing")
    log(f"  config.json            - experiment parameters")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Run a closed-loop reactor experiment and collect all data"
    )
    parser.add_argument(
        "--name", required=True,
        help="Experiment name (e.g., exp1_5nodes, exp2_50nodes, exp3_100nodes)"
    )
    parser.add_argument(
        "--duration", type=int, default=300,
        help="Experiment duration in seconds (default: 300)"
    )
    parser.add_argument(
        "--k8s-dir", default=".",
        help="Directory containing apply-all.sh and reset-all.sh (default: current dir)"
    )
    parser.add_argument(
        "--output-base", default="experiments",
        help="Base directory for experiment outputs (default: ./experiments)"
    )

    # Fault injection: CEP outage during the measurement
    parser.add_argument("--crash-at", type=int, default=None,
                        help="Second of the measurement at which the CEP is scaled to 0 replicas (no crash if omitted)")
    parser.add_argument("--crash-duration", type=int, default=60,
                        help="Duration of the CEP outage in seconds (default: 60)")

    args = parser.parse_args()

    # Validate
    apply_script = os.path.join(args.k8s_dir, "apply-all.sh")
    reset_script = os.path.join(args.k8s_dir, "reset-all.sh")
    if not os.path.isfile(apply_script):
        print(f"ERROR: apply-all.sh not found in {args.k8s_dir}")
        sys.exit(1)
    if not os.path.isfile(reset_script):
        print(f"ERROR: reset-all.sh not found in {args.k8s_dir}")
        sys.exit(1)

    run_experiment(args)


if __name__ == "__main__":
    main()
