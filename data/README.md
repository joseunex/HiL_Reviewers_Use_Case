# Experimental data of the batch-reactor use case (Section 7.4 of the paper)

Light version of every run reported in the paper: per-run configuration, the MongoDB exports that the analysis
reads, the per-second statistics of the CEP, the resource samples and the cached per-run summaries. Everything in
the tables and figures of Section 7.4 can be regenerated from this folder with the scripts of `analysis/`.

## Layout

```
data/
  scalability/            Table 4, Table 5, Figure 10, Figure 11  (Section 7.4.3)
    esc/esc_n<nodes>_r<k>/   5, 100, 250, 500, 1000 and 1500 nodes, 5 runs each, 600 s, CEP limited to 0.1 core
    campana_runs_l180.csv    one row per run, steady-state window = last 180 s of readings of the thermal sensor
    campana_escalas_l180.csv aggregate per scale: median of the five runs and range
  fault_injection/        Figure 12 and the recovery statistics of Section 7.4.4
    fallo/fallo_n0005_r<k>/  5 nodes, 5 runs, 420 s, CEP scaled to zero replicas at 150 s for 60 s
    campana_caidas_w120.csv  one row per run with the recovery statistics (outage, peak, return to the band)
  parameter_sensitivity/  Table 6 (Section 7.4.5)
    h0/, h200/               100 nodes with H = 0 and H = 200 ms, 3 runs each, 300 s
    w2000/, max500/          500 nodes with W = 2 s and with a 500-event buffer, 3 runs each, 300 s
    esc/                     default settings (W = 5 s, H = 50 ms, 2000 events) at 100 and 500 nodes, 5 runs each, 300 s
    campana_series_w120.csv  per-setting aggregate over the steady-state window (100-node rows of Table 6)
    campana_series_w0.csv    per-setting aggregate over the whole run (500-node rows of Table 6)
    campana_runs_w120.csv, campana_runs_w0.csv, campana_escalas_*.csv   per-run rows and the aggregate of the default runs
```

Series and folder names come from the campaign scripts: `esc` = scalability, `fallo` = fault injection, `h0`, `h200`,
`w2000`, `max500` = sensitivity settings. `n<nodes>` is the total number of sensor nodes (background sensors plus the
thermal sensor of the loop) and `r<k>` the repetition. All the runs were executed on the HiL bench described in
Section 7.4.2 (thermal sensor on the Raspberry Pi, Arduino Yún as actuator, CEP limited to 0.1 core).

## Files of a run

| File | Content |
|---|---|
| `config.json` | Name, duration, settings passed through the environment (`actuador`, `nodos`, `cep_cpu`, `cep_w_ms`, `cep_h_ms`, `cep_max`; the values are `"yun"`, the number of nodes, `"100m"` and the defaults) and start/end times. Fault runs add `crash_at_sec`, `crash_duration_sec`, `crash_start_ms`, `crash_end_ms` and `cep_ready_after_restart_ms`. |
| `raw/mongo/*__Z.json` | Readings of the thermal sensor (topic `Z`) as stored by the Fog node: `id`, `seq`, `tg` (source timestamp, ms), `val` (°C), `t_rcv_fog`. |
| `raw/mongo/*__B.json` | Commands of the CEP to the actuator (topic `B`), with the sensor fields, the CEP timestamps (`tsr_esper`, `tsn_esper`) and the cumulative drop counters (`cep_drops`). |
| `raw/mongo/*__actuators_ack.json` | Acknowledgments of the actuator with every timestamp of the control cycle (sensor, CEP, `t_cmd_rcv_act`, `t_act_act`, `t_ack_pub_act`, Fog reception). The latencies of Table 2 are computed from these records. |
| `raw/cep_stats_stream.log`, `raw/logs/*cep-esper*.log` | `ESPER_STATS` lines printed by the CEP every second: received, released and published events, utilisation of the release thread, residence time and occupancy of the reorder buffer, late and overflow drops. The pod logs are reduced to these lines (the full logs are tens of MB per run). Fault runs also keep `raw/cep_log_before_the_outage.log`, the log of the pod that was scaled down. |
| `raw/kubectl_top.csv` | CPU (millicores) and memory (MiB) of every pod, sampled every 2 s with `kubectl top`. |
| `raw/logs/closedloopsensor-*.log` | Log of the thermal sensor. |
| `raw/deploy_time.txt`, `raw/pods_imagenes.txt`, `salida_run_experiment.txt` | Deployment time, node and image digest of each pod, and the console output of `run_experiment.py`. |
| `results/resumen_run_<window>.json` | Cached per-run summary written by `analysis/aggregate_campaign.py` (`l180` = last 180 s, `w120` = after a 120 s warm-up, `w0` = whole run). |

Timestamps are milliseconds of the Unix epoch. In the MongoDB exports the 64-bit values appear as `{"high", "low"}`
pairs (value = high · 2^32 + (low mod 2^32)); the scripts decode them with the helper `num()` / `L()`.

The exports of the background-sensor topic (`C`) and the full logs of the broker, the Fog node and the sensors are
not included (15 GB in total); they are available from the authors on request. The exploratory runs at 2000 nodes
and the runs discarded because of bench failures are not part of the paper and are not included either.

## Regenerating the tables and figures

From the root of the repository (Python 3 with pandas, numpy and matplotlib):

```
python3 analysis/aggregate_campaign.py data/scalability --last 180            # per-run summaries, Tables 4 and 5
python3 analysis/paper_figures.py --out figures --tablas figures/tables.tex   # Figures 10 and 11, Tables 4 and 5 in LaTeX
python3 analysis/aggregate_campaign.py data/fault_injection --warmup 120      # recovery statistics of Section 7.4.4
python3 analysis/fault_figure.py data/fault_injection --out figures           # Figure 12
python3 analysis/aggregate_campaign.py data/parameter_sensitivity --warmup 120  # 100-node rows of Table 6
python3 analysis/aggregate_campaign.py data/parameter_sensitivity --warmup 0    # 500-node rows of Table 6 (whole run)
```

`aggregate_campaign.py` uses the cached summaries when they exist; add `--force` to recompute them from the raw files.
The window of the resource samples uses the local time zone of the host that ran the experiments (`HIL_TZ`, `Europe/Madrid`
for the data of the paper); set it when analysing runs taken elsewhere.
The 500-node rows of Table 6 report the median across runs of the sum of late and overflow drops of each run
(`drop_late + drop_overflow` in `campana_runs_w0.csv`). A single run can also be analysed with
`python3 DeployV2/k8s/analyze_experiment.py --exp-dir data/scalability/esc/esc_n0100_r1 --warmup 420`.
