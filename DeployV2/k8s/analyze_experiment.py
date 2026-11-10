#!/usr/bin/env python3
"""
Experiment analysis and figure generation for Use Case 2.

Usage:
    python3 analyze_experiment.py --exp-dir experiments/exp1_5nodes
    python3 analyze_experiment.py --exp-dir experiments/exp1_5nodes --warmup 30

Reads:
    <exp-dir>/raw/mongo/       -> ACKs and sensor data (JSON lines)
    <exp-dir>/raw/docker_stats.csv -> resource consumption

Produces:
    <exp-dir>/results/         -> PNG + PDF figures, LaTeX tables, summary CSV
"""

import argparse
import glob
import json
import os
import re
import sys
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.patches import Patch

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------
PALETTE = {
    "primary":   "#2563EB",   # blue
    "secondary": "#059669",   # green
    "accent":    "#D97706",   # amber
    "danger":    "#DC2626",   # red
    "neutral":   "#6B7280",   # gray
    "cool_on":   "#93C5FD",   # light blue (cooling ON band)
    "band_fill": "#FEF3C7",   # light yellow (admissible band)
}

SEGMENT_COLORS = {
    "L_src→ing":  "#3B82F6",
    "L_CEP":      "#8B5CF6",
    "L_dec→eff":  "#F59E0B",
    "L_act":      "#10B981",
    "RTT_ctrl":   "#EF4444",
    "L_e2e":      "#6366F1",
    "L_src→dec":  "#EC4899",
}

T_MIN = 79.0
T_MAX = 80.0

def setup_style():
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.grid": True,
        "axes.grid.which": "major",
        "grid.alpha": 0.3,
        "grid.linewidth": 0.5,
        "font.family": "serif",
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.1,
    })


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_jsonl(filepath):
    """Load a JSON-lines file into a list of dicts."""
    records = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def mongo_num(val, default=-1):
    """Parse a value that may be:
    - a plain number (int/float)
    - MongoDB extended JSON: {"$numberLong": "123"}, {"$numberInt": "123"}, {"$numberDouble": "1.5"}
    - BSON Long from mongosh JSON.stringify: {"low": -997104296, "high": 412, "unsigned": false}
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, dict):
        # BSON Long raw format (mongosh JSON.stringify output)
        if "low" in val and "high" in val:
            try:
                low = val["low"]
                high = val["high"]
                # Convert low to unsigned 32-bit
                if low < 0:
                    low = low + (1 << 32)
                return high * (1 << 32) + low
            except (ValueError, TypeError, KeyError):
                return default
        # MongoDB extended JSON formats
        for key in ("$numberLong", "$numberInt", "$numberDouble"):
            if key in val:
                try:
                    return float(val[key]) if "." in str(val[key]) else int(val[key])
                except (ValueError, TypeError):
                    return default
        return default
    if isinstance(val, str):
        try:
            return int(val) if "." not in val else float(val)
        except ValueError:
            return default
    return default


def find_ack_file(mongo_dir):
    """Find the actuators_ack export file."""
    patterns = ["*actuators_ack*", "*actuators__ack*"]
    for pattern in patterns:
        matches = glob.glob(os.path.join(mongo_dir, pattern))
        if matches:
            return matches[0]
    return None


def find_sensor_file(mongo_dir):
    """Find the ClosedLoopSensor topic export file (topic Z)."""
    # Prefer __Z.json explicitly (ClosedLoopSensor publishes on topic Z)
    for f in glob.glob(os.path.join(mongo_dir, "*__Z.json")):
        return f
    for f in glob.glob(os.path.join(mongo_dir, "*_Z.json")):
        return f
    # Fallback: any file that is not actuators_ack, Fog, B, or C
    for f in sorted(glob.glob(os.path.join(mongo_dir, "*.json"))):
        basename = os.path.basename(f).lower()
        if any(x in basename for x in ["actuators", "fog", "__b.", "__c.", "_b.", "_c."]):
            continue
        return f
    return None


def load_acks(mongo_dir, warmup_ms=0):
    """Load ACK data, compute latencies, apply warmup filter."""
    ack_file = find_ack_file(mongo_dir)
    if not ack_file:
        print("ERROR: No actuators_ack file found in", mongo_dir)
        sys.exit(1)

    print(f"Loading ACKs from: {ack_file}")
    raw = load_jsonl(ack_file)
    print(f"  Raw records: {len(raw)}")

    rows = []
    for r in raw:
        try:
            sensor = r.get("sensor", {})
            cep = r.get("cep", {})
            act = r.get("actuator", {})
            drops = cep.get("cep_drops", {})

            row = {
                "sensor_id":      sensor.get("id", ""),
                "seq":            mongo_num(sensor.get("seq"), -1),
                "tg":             mongo_num(sensor.get("tg"), -1),
                "val":            mongo_num(sensor.get("val"), None),
                "tsr_esper":      mongo_num(cep.get("tsr_esper"), -1),
                "tsn_esper":      mongo_num(cep.get("tsn_esper"), -1),
                "t_cmd_rcv_act":  mongo_num(act.get("t_cmd_rcv_act"), -1),
                "t_act_act":      mongo_num(act.get("t_act_act"), -1),
                "t_ack_pub_act":  mongo_num(act.get("t_ack_pub_act"), -1),
                "t_rcv_fog":      mongo_num(r.get("t_rcv_fog"), -1),
                "applied_state":  act.get("applied_state", ""),
                "desired_state":  act.get("desired_state", ""),
                "actuator_id":    act.get("id", ""),
                "cmd_topic":      act.get("cmd_topic", ""),
                "drops_total":    mongo_num(drops.get("total"), 0),
                "drops_late":     mongo_num(drops.get("late"), 0),
                "drops_overflow": mongo_num(drops.get("overflow"), 0),
                "drops_missing":  mongo_num(drops.get("missing_tg"), 0),
            }
            rows.append(row)
        except Exception:
            continue

    df = pd.DataFrame(rows)
    if df.empty:
        print("ERROR: No valid ACK records")
        sys.exit(1)

    # Filter invalid timestamps
    for col in ["tg", "tsr_esper", "tsn_esper", "t_cmd_rcv_act", "t_act_act", "t_ack_pub_act", "t_rcv_fog"]:
        df = df[df[col] > 0]

    if df.empty:
        print("ERROR: No valid ACK records after timestamp filtering")
        sys.exit(1)

    # Compute latencies (ms)
    df["L_src_ing"]  = df["tsr_esper"] - df["tg"]
    df["L_CEP"]      = df["tsn_esper"] - df["tsr_esper"]
    df["L_src_dec"]  = df["tsn_esper"] - df["tg"]
    df["L_dec_eff"]  = df["t_act_act"] - df["tsn_esper"]
    df["L_act"]      = df["t_act_act"] - df["t_cmd_rcv_act"]
    df["RTT_ctrl"]   = df["t_rcv_fog"] - df["tsn_esper"]
    df["L_e2e"]      = df["t_rcv_fog"] - df["tg"]

    # Time relative to first event (seconds)
    t0 = df["tg"].min()
    df["t_rel"] = (df["tg"] - t0) / 1000.0

    total_span_sec = df["t_rel"].max()
    print(f"  Data time span: {total_span_sec:.1f}s  |  Records before warmup: {len(df)}")

    # Apply warmup (auto-reduce if it would discard everything)
    warmup_sec = warmup_ms / 1000.0
    if warmup_sec >= total_span_sec:
        warmup_sec = max(0, total_span_sec * 0.1)
        print(f"  WARNING: Warmup ({warmup_ms/1000:.0f}s) >= data span ({total_span_sec:.1f}s). "
              f"Auto-reduced warmup to {warmup_sec:.1f}s")

    df = df[df["t_rel"] >= warmup_sec].copy()
    df["t_rel"] = df["t_rel"] - warmup_sec

    # Sort by time
    df = df.sort_values("tg").reset_index(drop=True)

    print(f"  After filtering + warmup ({warmup_sec:.1f}s): {len(df)} records")
    return df


def load_sensor_data(mongo_dir, warmup_ms=0):
    """Load raw sensor topic data for temperature trajectory."""
    sensor_file = find_sensor_file(mongo_dir)
    if not sensor_file:
        print("WARNING: No sensor topic file found, skipping temperature plots")
        return None

    print(f"Loading sensor data from: {sensor_file}")
    raw = load_jsonl(sensor_file)

    rows = []
    for r in raw:
        try:
            tg_val = mongo_num(r.get("tg"), -1)
            val_val = mongo_num(r.get("val"), None)
            row = {
                "id":         r.get("id", ""),
                "seq":        mongo_num(r.get("seq"), -1),
                "tg":         tg_val,
                "val":        val_val,
                "cooling_on": r.get("cooling_on", None),
            }
            if row["tg"] > 0 and row["val"] is not None:
                rows.append(row)
        except Exception:
            continue

    df = pd.DataFrame(rows)
    if df.empty:
        return None

    # Filter to ClosedLoopSensor only
    cls_mask = df["id"].str.contains("ClosedLoop", case=False, na=False)
    if cls_mask.sum() > 0:
        df = df[cls_mask].copy()

    t0 = df["tg"].min()
    df["t_rel"] = (df["tg"] - t0) / 1000.0

    warmup_sec = warmup_ms / 1000.0
    df = df[df["t_rel"] >= warmup_sec].copy()
    df["t_rel"] = df["t_rel"] - warmup_sec

    df = df.sort_values("tg").reset_index(drop=True)
    df["val"] = pd.to_numeric(df["val"], errors="coerce")

    print(f"  Sensor records (ClosedLoop, after warmup): {len(df)}")
    return df


def load_resource_stats(exp_raw_dir, warmup_sec=0):
    """Load resource stats CSV (kubectl top pods or docker stats)."""
    # Try kubectl_top.csv first, then docker_stats.csv
    for fname in ["kubectl_top.csv", "docker_stats.csv"]:
        stats_path = os.path.join(exp_raw_dir, fname)
        if os.path.isfile(stats_path) and os.path.getsize(stats_path) > 50:
            print(f"Loading resource stats from: {stats_path}")
            df = pd.read_csv(stats_path, parse_dates=["timestamp"])

            if df.empty:
                continue

            # Detect format by columns
            if "pod_name" in df.columns:
                # kubectl top pods format: timestamp,pod_name,cpu_millicores,mem_mib
                df["cpu_millicores"] = pd.to_numeric(df["cpu_millicores"], errors="coerce")
                df["mem_mib"] = pd.to_numeric(df["mem_mib"], errors="coerce")
                df.rename(columns={"pod_name": "container_name", "mem_mib": "mem_mb"}, inplace=True)
                # Convert millicores to percentage (1000m = 100%)
                df["cpu_perc"] = df["cpu_millicores"] / 10.0

            elif "container_name" in df.columns:
                # docker stats format
                df["cpu_perc"] = pd.to_numeric(
                    df["cpu_perc"].astype(str).str.replace("%", ""), errors="coerce")
                def parse_mem(s):
                    s = str(s).strip()
                    if "GiB" in s: return float(s.replace("GiB", "").strip()) * 1024
                    elif "MiB" in s: return float(s.replace("MiB", "").strip())
                    elif "KiB" in s: return float(s.replace("KiB", "").strip()) / 1024
                    elif "B" in s: return float(s.replace("B", "").strip()) / (1024 * 1024)
                    return np.nan
                df["mem_mb"] = df["mem_usage"].apply(parse_mem)

            else:
                continue

            # Relative time in seconds
            t0 = df["timestamp"].min()
            df["t_rel"] = (df["timestamp"] - t0).dt.total_seconds()
            df = df[df["t_rel"] >= warmup_sec].copy()
            df["t_rel"] = df["t_rel"] - warmup_sec

            # Classify containers/pods
            def classify(name):
                name = str(name).lower()
                if "closedloop" in name: return "ClosedLoopSensor"
                elif "sensor" in name: return "Sensor"
                elif "esper" in name or "cep" in name: return "CEP"
                elif "actuator" in name: return "Actuator"
                elif "fog" in name and "mongo" not in name and "mosquitto" not in name: return "Fog"
                elif "mosquitto" in name: return "Mosquitto"
                elif "mongo" in name: return "MongoDB"
                else: return "Other"

            df["component"] = df["container_name"].apply(classify)

            # Filter out "Other" (registry, system pods, etc.)
            df = df[df["component"] != "Other"].copy()

            print(f"  Resource stats records (after warmup, excl. Other): {len(df)}")
            return df

    print("WARNING: No resource stats file found")
    return None


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------
def compute_latency_summary(df):
    """Compute summary stats for each latency segment."""
    segments = {
        "L_src→ing":  "L_src_ing",
        "L_CEP":      "L_CEP",
        "L_src→dec":  "L_src_dec",
        "L_dec→eff":  "L_dec_eff",
        "L_act":      "L_act",
        "RTT_ctrl":   "RTT_ctrl",
        "L_e2e":      "L_e2e",
    }

    rows = []
    for label, col in segments.items():
        s = df[col].dropna()
        if len(s) == 0:
            continue
        rows.append({
            "Segment":  label,
            "Count":    len(s),
            "Min":      f"{s.min():.1f}",
            "Median":   f"{s.median():.1f}",
            "Mean":     f"{s.mean():.1f}",
            "P95":      f"{s.quantile(0.95):.1f}",
            "P99":      f"{s.quantile(0.99):.1f}",
            "Max":      f"{s.max():.1f}",
            "Std":      f"{s.std():.2f}",
        })
    return pd.DataFrame(rows)


def compute_fidelity_summary(sensor_df):
    """Compute OS, US, TOB from sensor data."""
    if sensor_df is None or sensor_df.empty:
        return None

    vals = sensor_df["val"].dropna()
    dt = 1.0  # sampling period

    os_val = max(0, (vals - T_MAX).max())
    us_val = max(0, (T_MIN - vals).max())
    out_of_band = ((vals < T_MIN) | (vals > T_MAX)).sum() * dt
    total_time = len(vals) * dt
    tob_pct = (out_of_band / total_time * 100) if total_time > 0 else 0

    return {
        "T_min": T_MIN,
        "T_max": T_MAX,
        "OS (°C)": f"{os_val:.4f}",
        "US (°C)": f"{us_val:.4f}",
        "TOB (s)": f"{out_of_band:.0f}",
        "TOB (%)": f"{tob_pct:.1f}",
        "Total samples": len(vals),
        "Total time (s)": f"{total_time:.0f}",
    }


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def save_fig(fig, results_dir, name):
    """Save figure as both PNG and PDF."""
    fig.savefig(os.path.join(results_dir, f"{name}.png"))
    fig.savefig(os.path.join(results_dir, f"{name}.pdf"))
    plt.close(fig)
    print(f"  Saved: {name}.png / .pdf")


def fig_latency_boxplot(df, results_dir):
    """Boxplot of latency decomposition by segment."""
    segments = ["L_src_ing", "L_CEP", "L_dec_eff", "L_act", "RTT_ctrl", "L_e2e"]
    labels =   ["$L_{src→ing}$", "$L_{CEP}$", "$L_{dec→eff}$", "$L_{act}$", "$RTT_{ctrl}$", "$L_{e2e}$"]
    colors_list = [SEGMENT_COLORS[k] for k in ["L_src→ing", "L_CEP", "L_dec→eff", "L_act", "RTT_ctrl", "L_e2e"]]

    data = [df[s].dropna().values for s in segments]

    fig, ax = plt.subplots(figsize=(7, 3.5))
    bp = ax.boxplot(data, labels=labels, patch_artist=True, widths=0.6,
                    showfliers=True, flierprops=dict(marker=".", markersize=2, alpha=0.3))

    for patch, color in zip(bp["boxes"], colors_list):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    for median in bp["medians"]:
        median.set_color("black")
        median.set_linewidth(1.5)

    ax.set_ylabel("Latency (ms)")
    ax.set_title("Latency Decomposition by Segment")
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
    fig.tight_layout()
    save_fig(fig, results_dir, "fig_latency_boxplot")


def fig_rtt_cdf(df, results_dir):
    """CDF of RTT_ctrl."""
    rtt = np.sort(df["RTT_ctrl"].dropna().values)
    cdf = np.arange(1, len(rtt) + 1) / len(rtt)

    fig, ax = plt.subplots(figsize=(5, 3.5))
    ax.plot(rtt, cdf, color=SEGMENT_COLORS["RTT_ctrl"], linewidth=1.5)
    ax.set_xlabel("$RTT_{ctrl}$ (ms)")
    ax.set_ylabel("CDF")
    ax.set_title("Cumulative Distribution of $RTT_{ctrl}$")
    ax.set_ylim(0, 1.02)

    # Mark percentiles
    for pct, ls in [(0.50, "--"), (0.95, ":"), (0.99, "-.")]:
        val = np.percentile(rtt, pct * 100)
        ax.axhline(pct, color=PALETTE["neutral"], linestyle=ls, linewidth=0.7, alpha=0.5)
        ax.axvline(val, color=PALETTE["neutral"], linestyle=ls, linewidth=0.7, alpha=0.5)
        ax.annotate(f"P{int(pct*100)}={val:.0f}ms",
                    xy=(val, pct), fontsize=7, color=PALETTE["neutral"],
                    xytext=(5, -3), textcoords="offset points")

    fig.tight_layout()
    save_fig(fig, results_dir, "fig_rtt_cdf")


def fig_jitter_histogram(df, results_dir):
    """Histogram of jitter for RTT_ctrl and L_dec_eff."""
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.5))

    for ax, col, label, color in [
        (axes[0], "RTT_ctrl",  "$J_{RTT_{ctrl}}$",  SEGMENT_COLORS["RTT_ctrl"]),
        (axes[1], "L_dec_eff", "$J_{L_{dec→eff}}$", SEGMENT_COLORS["L_dec→eff"]),
    ]:
        series = df[col].dropna().values
        jitter = np.diff(series)

        ax.hist(jitter, bins=60, color=color, alpha=0.7, edgecolor="white", linewidth=0.3)
        ax.axvline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
        ax.set_xlabel(f"{label} (ms)")
        ax.set_ylabel("Count")
        ax.set_title(f"Jitter Distribution: {label}")

        # Stats annotation
        stats_text = f"μ={np.mean(jitter):.1f}\nσ={np.std(jitter):.1f}\nmed={np.median(jitter):.1f}"
        ax.text(0.97, 0.95, stats_text, transform=ax.transAxes, fontsize=7,
                verticalalignment="top", horizontalalignment="right",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    fig.tight_layout()
    save_fig(fig, results_dir, "fig_jitter_histogram")


def fig_rtt_timeline(df, results_dir):
    """Timeline of RTT_ctrl over experiment duration."""
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.scatter(df["t_rel"], df["RTT_ctrl"], s=3, alpha=0.4, color=SEGMENT_COLORS["RTT_ctrl"], edgecolors="none")

    # Rolling median
    if len(df) > 20:
        window = max(10, len(df) // 50)
        rolling_med = df["RTT_ctrl"].rolling(window=window, center=True, min_periods=1).median()
        ax.plot(df["t_rel"], rolling_med, color="black", linewidth=1.2, alpha=0.8, label=f"Rolling median (w={window})")
        ax.legend(loc="upper right")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("$RTT_{ctrl}$ (ms)")
    ax.set_title("$RTT_{ctrl}$ Over Time")
    fig.tight_layout()
    save_fig(fig, results_dir, "fig_rtt_timeline")


def fig_temperature_trajectory(sensor_df, results_dir):
    """Temperature trajectory with admissible band and cooling state."""
    if sensor_df is None or sensor_df.empty:
        print("  Skipping temperature trajectory (no sensor data)")
        return

    fig, ax = plt.subplots(figsize=(8, 3.5))

    # Admissible band
    ax.axhspan(T_MIN, T_MAX, color=PALETTE["band_fill"], alpha=0.6, label=f"Admissible band [{T_MIN}, {T_MAX}]°C")
    ax.axhline(T_MIN, color=PALETTE["accent"], linewidth=0.8, linestyle="--", alpha=0.7)
    ax.axhline(T_MAX, color=PALETTE["danger"], linewidth=0.8, linestyle="--", alpha=0.7)

    # Cooling state background
    if "cooling_on" in sensor_df.columns and sensor_df["cooling_on"].notna().any():
        cooling = sensor_df["cooling_on"].astype(bool)
        t = sensor_df["t_rel"].values
        for i in range(len(t) - 1):
            if cooling.iloc[i]:
                ax.axvspan(t[i], t[i + 1], color=PALETTE["cool_on"], alpha=0.15)

    # Temperature line
    ax.plot(sensor_df["t_rel"], sensor_df["val"], color=PALETTE["primary"], linewidth=0.8, label="Reactor temperature")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("Reactor Temperature Trajectory")

    # Custom legend
    handles = [
        plt.Line2D([0], [0], color=PALETTE["primary"], linewidth=1.2, label="Temperature"),
        Patch(facecolor=PALETTE["band_fill"], alpha=0.6, label=f"Band [{T_MIN}, {T_MAX}]°C"),
        Patch(facecolor=PALETTE["cool_on"], alpha=0.3, label="Cooling ON"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=8)

    fig.tight_layout()
    save_fig(fig, results_dir, "fig_temperature_trajectory")


def fig_overshoot_vs_latency(df, results_dir):
    """Scatter of overshoot/undershoot vs RTT_ctrl at threshold-crossing ACKs."""
    # Filter ACKs from ClosedLoopSensor only
    cls = df[df["sensor_id"].str.contains("ClosedLoop", case=False, na=False)].copy()

    if cls.empty:
        print("  Skipping overshoot scatter (no ClosedLoopSensor ACKs)")
        return

    # ON commands -> overshoot (val should be above T_MAX)
    on_cmds = cls[cls["applied_state"].str.upper() == "ON"].copy()
    on_cmds["overshoot"] = pd.to_numeric(on_cmds["val"], errors="coerce") - T_MAX

    # OFF commands -> undershoot (val should be below T_MIN)
    off_cmds = cls[cls["applied_state"].str.upper() == "OFF"].copy()
    off_cmds["undershoot"] = T_MIN - pd.to_numeric(off_cmds["val"], errors="coerce")

    fig, axes = plt.subplots(1, 2, figsize=(8, 3.5))

    # Overshoot
    ax = axes[0]
    if not on_cmds.empty and on_cmds["overshoot"].notna().any():
        ax.scatter(on_cmds["RTT_ctrl"], on_cmds["overshoot"], s=12, alpha=0.5,
                   color=PALETTE["danger"], edgecolors="none")
        # Trend line
        valid = on_cmds[on_cmds["overshoot"].notna() & on_cmds["RTT_ctrl"].notna()]
        if len(valid) > 5:
            z = np.polyfit(valid["RTT_ctrl"], valid["overshoot"], 1)
            p = np.poly1d(z)
            x_range = np.linspace(valid["RTT_ctrl"].min(), valid["RTT_ctrl"].max(), 100)
            ax.plot(x_range, p(x_range), "--", color="black", linewidth=0.8, alpha=0.6)
    ax.axhline(0, color=PALETTE["neutral"], linewidth=0.5, linestyle=":")
    ax.set_xlabel("$RTT_{ctrl}$ (ms)")
    ax.set_ylabel("Overshoot above " + f"{T_MAX}°C")
    ax.set_title("Overshoot vs. $RTT_{ctrl}$")

    # Undershoot
    ax = axes[1]
    if not off_cmds.empty and off_cmds["undershoot"].notna().any():
        ax.scatter(off_cmds["RTT_ctrl"], off_cmds["undershoot"], s=12, alpha=0.5,
                   color=PALETTE["secondary"], edgecolors="none")
        valid = off_cmds[off_cmds["undershoot"].notna() & off_cmds["RTT_ctrl"].notna()]
        if len(valid) > 5:
            z = np.polyfit(valid["RTT_ctrl"], valid["undershoot"], 1)
            p = np.poly1d(z)
            x_range = np.linspace(valid["RTT_ctrl"].min(), valid["RTT_ctrl"].max(), 100)
            ax.plot(x_range, p(x_range), "--", color="black", linewidth=0.8, alpha=0.6)
    ax.axhline(0, color=PALETTE["neutral"], linewidth=0.5, linestyle=":")
    ax.set_xlabel("$RTT_{ctrl}$ (ms)")
    ax.set_ylabel("Undershoot below " + f"{T_MIN}°C")
    ax.set_title("Undershoot vs. $RTT_{ctrl}$")

    fig.tight_layout()
    save_fig(fig, results_dir, "fig_overshoot_vs_latency")


def fig_cep_drops(df, results_dir):
    """CEP drops over time."""
    cls = df[df["sensor_id"].str.contains("ClosedLoop", case=False, na=False)].copy()
    if cls.empty:
        cls = df.copy()

    if cls["drops_total"].max() == 0:
        print("  Skipping cep_drops plot (no drops recorded)")
        # Still save a note
        with open(os.path.join(results_dir, "cep_drops_note.txt"), "w") as f:
            f.write("No CEP drops recorded during this experiment.\n")
        return

    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(cls["t_rel"], cls["drops_total"], color=PALETTE["danger"], linewidth=1, label="Total")
    ax.plot(cls["t_rel"], cls["drops_late"], color=PALETTE["accent"], linewidth=0.8, linestyle="--", label="Late")
    ax.plot(cls["t_rel"], cls["drops_overflow"], color=PALETTE["secondary"], linewidth=0.8, linestyle=":", label="Overflow")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Cumulative drops")
    ax.set_title("CEP Ingress Drops Over Time")
    ax.legend(loc="upper left")
    fig.tight_layout()
    save_fig(fig, results_dir, "fig_cep_drops")


def fig_resources(stats_df, results_dir):
    """CPU and RAM over time by component type."""
    if stats_df is None or stats_df.empty:
        print("  Skipping resource plots (no docker stats)")
        return

    component_colors = {
        "Sensor":           "#3B82F6",
        "ClosedLoopSensor": "#6366F1",
        "CEP":              "#8B5CF6",
        "Actuator":         "#F59E0B",
        "Fog":              "#10B981",
        "Mosquitto":        "#EC4899",
        "MongoDB":          "#6B7280",
        "Other":            "#D1D5DB",
    }

    # Aggregate by component type and time bucket (10s)
    stats_df["t_bucket"] = (stats_df["t_rel"] // 10) * 10
    grouped = stats_df.groupby(["t_bucket", "component"]).agg(
        cpu_sum=("cpu_perc", "sum"),
        mem_sum=("mem_mb", "sum"),
    ).reset_index()

    components_present = [c for c in component_colors if c in grouped["component"].unique()]

    fig, axes = plt.subplots(2, 1, figsize=(8, 5), sharex=True)

    # CPU
    ax = axes[0]
    for comp in components_present:
        sub = grouped[grouped["component"] == comp]
        ax.plot(sub["t_bucket"], sub["cpu_sum"], linewidth=1,
                color=component_colors.get(comp, "#999"), label=comp, alpha=0.8)
    ax.set_ylabel("CPU (%)")
    ax.set_title("CPU Usage by Component Type")
    ax.legend(loc="upper right", fontsize=7, ncol=2)

    # RAM
    ax = axes[1]
    for comp in components_present:
        sub = grouped[grouped["component"] == comp]
        ax.plot(sub["t_bucket"], sub["mem_sum"], linewidth=1,
                color=component_colors.get(comp, "#999"), label=comp, alpha=0.8)
    ax.set_ylabel("Memory (MB)")
    ax.set_xlabel("Time (s)")
    ax.set_title("Memory Usage by Component Type")
    ax.legend(loc="upper right", fontsize=7, ncol=2)

    fig.tight_layout()
    save_fig(fig, results_dir, "fig_resources")


# ---------------------------------------------------------------------------
# LaTeX table export
# ---------------------------------------------------------------------------
def export_latex_table(df_table, filepath, caption="", label=""):
    """Export a DataFrame as a LaTeX table (manual, no jinja2 dependency)."""
    if df_table.empty:
        print(f"  Skipping {os.path.basename(filepath)} (empty table)")
        return

    cols = list(df_table.columns)
    col_fmt = "l" * len(cols)

    with open(filepath, "w") as f:
        f.write("\\begin{table}[htbp]\n")
        f.write("\\centering\n")
        f.write(f"\\caption{{{caption}}}\n")
        f.write(f"\\label{{{label}}}\n")
        f.write(f"\\begin{{tabular}}{{{col_fmt}}}\n")
        f.write("\\hline\n")
        f.write(" & ".join(str(c) for c in cols) + " \\\\\n")
        f.write("\\hline\n")
        for _, row in df_table.iterrows():
            f.write(" & ".join(str(row[c]) for c in cols) + " \\\\\n")
        f.write("\\hline\n")
        f.write("\\end{tabular}\n")
        f.write("\\end{table}\n")

    print(f"  Saved: {os.path.basename(filepath)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ============================================================
# B2: CEP runtime statistics (ESPER_STATS lines of the CEP log)
# ============================================================
CEP_STATS_COLS = ["rx", "rel", "pub", "pub_err", "pub_ms_mean", "pub_ms_max",
                  "util", "buf_ms_mean", "buf_ms_max", "occ"]


def load_cep_stats(exp_raw_dir, warmup_sec=0):
    """Parse the ESPER_STATS lines (one per CEP_STATS_MS, 1 s by default) of the CEP log.
    The origin of t_rel is the first line with received events, and the warmup is discarded from it."""
    # Under heavy load the container log rotates and kubectl logs only keeps the last part, so run_experiment.py
    # also copies the ESPER_STATS lines to raw/cep_stats_stream.log; the most complete file is used.
    logs = sorted(glob.glob(os.path.join(exp_raw_dir, "logs", "*cep-esper*.log")))
    stream = os.path.join(exp_raw_dir, "cep_stats_stream.log")
    candidates = ([stream] if os.path.isfile(stream) else []) + logs
    if not candidates:
        print("  No CEP log found (raw/logs/*cep-esper*.log)")
        return pd.DataFrame()
    rows, src = [], None
    for path in candidates:
        cur = []
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.startswith("ESPER_STATS"):
                    continue
                rec = {}
                for part in line.strip().split("|")[1:]:
                    if "=" in part:
                        k, v = part.strip().split("=", 1)
                        try:
                            rec[k] = float(v)
                        except ValueError:
                            pass
                cur.append(rec)
        if len(cur) > len(rows):
            rows, src = cur, path
    if not rows:
        print("  No ESPER_STATS lines in the CEP log (CEP image without the B2 changes?)")
        return pd.DataFrame()
    df = pd.DataFrame(rows).fillna(0)
    if "t" in df.columns:
        df = df.drop_duplicates(subset="t", keep="first").sort_values("t").reset_index(drop=True)
    logs = [src]
    active = df[df["rx"] > 0]
    if active.empty:
        return pd.DataFrame()
    t0 = active["t"].iloc[0]
    df["t_rel"] = (df["t"] - t0) / 1000.0
    df = df[df["t_rel"] >= warmup_sec].copy()
    df["t_rel"] = df["t_rel"] - warmup_sec
    df["util_pct"] = df["util"] * 100.0
    print(f"Loading CEP stats from: {logs[0]}")
    print(f"  ESPER_STATS lines: {len(rows)}  |  After warmup ({warmup_sec:.0f}s): {len(df)}")
    return df


def summarize_cep_stats(df):
    out = []
    for c in CEP_STATS_COLS:
        if c not in df.columns:
            continue
        v = df[c]
        out.append({"Metric": c, "Median": round(v.median(), 3), "Mean": round(v.mean(), 3),
                    "P95": round(v.quantile(0.95), 3), "Max": round(v.max(), 3)})
    return pd.DataFrame(out)


def fig_cep_stats(df, results_dir):
    """Rates, utilisation of the release thread and residence time in the reorder buffer over time."""
    if df.empty:
        print("  Skipping cep_stats plot (no ESPER_STATS lines)")
        return
    fig, axes = plt.subplots(3, 1, figsize=(7, 6.5), sharex=True)
    ax = axes[0]
    ax.plot(df["t_rel"], df["rx"], label="received")
    ax.plot(df["t_rel"], df["rel"], label="released to Esper")
    ax.plot(df["t_rel"], df["pub"], label="published")
    ax.set_ylabel("events/s")
    ax.legend(fontsize=8, loc="upper right")
    ax = axes[1]
    ax.plot(df["t_rel"], df["util_pct"], color="tab:red")
    ax.set_ylabel("release thread\nbusy (%)")
    ax = axes[2]
    ax.plot(df["t_rel"], df["buf_ms_mean"], label="mean")
    ax.plot(df["t_rel"], df["buf_ms_max"], label="max", alpha=0.7)
    ax.set_ylabel("time in reorder\nbuffer (ms)")
    ax.set_xlabel("Time (s, after warmup)")
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    save_fig(fig, results_dir, "fig_cep_stats")


def main():
    parser = argparse.ArgumentParser(description="Analyze experiment data and generate figures")
    parser.add_argument("--exp-dir", required=True, help="Experiment directory (e.g., experiments/exp1_5nodes)")
    parser.add_argument("--warmup", type=int, default=30, help="Warmup period to discard (seconds, default: 30)")
    args = parser.parse_args()

    setup_style()

    exp_dir = args.exp_dir
    mongo_dir = os.path.join(exp_dir, "raw", "mongo")
    results_dir = os.path.join(exp_dir, "results")
    os.makedirs(results_dir, exist_ok=True)

    warmup_ms = args.warmup * 1000

    print(f"========== ANALYZING: {exp_dir} ==========")
    print(f"Warmup: {args.warmup}s")
    print()

    # ----- Load data -----
    df_acks = load_acks(mongo_dir, warmup_ms=warmup_ms)
    df_sensor = load_sensor_data(mongo_dir, warmup_ms=warmup_ms)
    df_stats = load_resource_stats(os.path.join(exp_dir, "raw"), warmup_sec=args.warmup)

    if len(df_acks) < 3:
        print(f"\nWARNING: Only {len(df_acks)} ACK records after filtering.")
        print("  The experiment may have been too short, or the warmup too long.")
        print("  Try: python3 analyze_experiment.py --exp-dir ... --warmup 0")
        if len(df_acks) == 0:
            print("  Cannot generate any analysis with 0 records. Exiting.")
            sys.exit(1)

    # ----- Summary tables -----
    print("\n--- Latency Summary ---")
    lat_summary = compute_latency_summary(df_acks)
    print(lat_summary.to_string(index=False))

    lat_summary.to_csv(os.path.join(results_dir, "latency_summary.csv"), index=False)
    export_latex_table(lat_summary,
                       os.path.join(results_dir, "latency_summary.tex"),
                       caption="Latency decomposition (ms)",
                       label="tab:latency")

    print("\n--- Fidelity Summary ---")
    fid = compute_fidelity_summary(df_sensor)
    if fid:
        fid_df = pd.DataFrame([fid])
        print(fid_df.to_string(index=False))
        fid_df.to_csv(os.path.join(results_dir, "fidelity_summary.csv"), index=False)
        export_latex_table(fid_df,
                           os.path.join(results_dir, "fidelity_summary.tex"),
                           caption="Control-fidelity metrics",
                           label="tab:fidelity")

    print("\n--- CEP Drops Summary ---")
    drops_final = {
        "Total":    int(df_acks["drops_total"].max()),
        "Late":     int(df_acks["drops_late"].max()),
        "Overflow": int(df_acks["drops_overflow"].max()),
        "Missing":  int(df_acks["drops_missing"].max()),
    }
    print(f"  {drops_final}")
    with open(os.path.join(results_dir, "cep_drops_summary.json"), "w") as f:
        json.dump(drops_final, f, indent=2)

    print("\n--- CEP Runtime Stats (ESPER_STATS) ---")
    df_cep = load_cep_stats(os.path.join(exp_dir, "raw"), warmup_sec=args.warmup)
    if not df_cep.empty:
        cep_summary = summarize_cep_stats(df_cep)
        print(cep_summary.to_string(index=False))
        cep_summary.to_csv(os.path.join(results_dir, "cep_stats_summary.csv"), index=False)
        df_cep.to_csv(os.path.join(results_dir, "cep_stats.csv"), index=False)

    # ----- Figures -----
    print("\n--- Generating figures ---")
    figure_funcs = [
        ("fig_latency_boxplot",       lambda: fig_latency_boxplot(df_acks, results_dir)),
        ("fig_rtt_cdf",               lambda: fig_rtt_cdf(df_acks, results_dir)),
        ("fig_jitter_histogram",      lambda: fig_jitter_histogram(df_acks, results_dir)),
        ("fig_rtt_timeline",          lambda: fig_rtt_timeline(df_acks, results_dir)),
        ("fig_temperature_trajectory",lambda: fig_temperature_trajectory(df_sensor, results_dir)),
        ("fig_overshoot_vs_latency",  lambda: fig_overshoot_vs_latency(df_acks, results_dir)),
        ("fig_cep_drops",             lambda: fig_cep_drops(df_acks, results_dir)),
        ("fig_resources",             lambda: fig_resources(df_stats, results_dir)),
        ("fig_cep_stats",             lambda: fig_cep_stats(df_cep, results_dir)),
    ]
    for name, func in figure_funcs:
        try:
            func()
        except Exception as e:
            print(f"  WARNING: {name} failed: {e}")

    print(f"\n========== ANALYSIS COMPLETE ==========")
    print(f"Results in: {results_dir}")


if __name__ == "__main__":
    main()
