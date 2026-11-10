#!/usr/bin/env python3
"""Summary of a campaign of the HiL bench (a folder with <series>/<run>/ subfolders, e.g. data/scalability).

- One row per run (campana_runs_<window>.csv) with the median and P95 of each latency segment, the control fidelity
  (OS, US, TOB), the CEP drops, the CEP statistics (ESPER_STATS) and the median CPU and memory of the CEP.
- Aggregate per scale (campana_escalas_<window>.csv): median of the repetitions and range (min-max).
- Other series, e.g. the sensitivity settings h0/h200/w2000/max500 (campana_series_<window>.csv).
- Fault-injection series (campana_caidas_<window>.csv): recovery times and temperature peak of each repetition.
It reuses the functions of DeployV2/k8s/analyze_experiment.py, without figures. The summary of each run is cached in
results/resumen_run_<window>.json; with --budget it stops after N seconds and can be relaunched.
Window: --last N analyses the last N seconds of readings of the thermal sensor (anchored at the end of the run,
paper: --last 180); --warmup S discards the first S seconds after the first reading instead (--warmup 0 = whole run).
Usage: python3 analysis/aggregate_campaign.py data/scalability --last 180
       python3 analysis/aggregate_campaign.py data/fault_injection --warmup 120
       python3 analysis/aggregate_campaign.py data/parameter_sensitivity --warmup 120   (100-node rows of Table 6)
       python3 analysis/aggregate_campaign.py data/parameter_sensitivity --warmup 0     (500-node rows of Table 6, whole run)
Column names are in Spanish for compatibility with the campaign scripts: run, serie (series), nodos (nodes),
acks (control cycles), <segment>_med / _p95 (ms), OS, US (°C), TOB_pct (%), drop_late, drop_overflow (events),
cep_* (ESPER_STATS medians), cep_cpu_m_med (millicores), cep_mem_mib_max (MiB), ventana_sensor_s, muestras (samples).
"""
import argparse, contextlib, glob, io, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'DeployV2', 'k8s'))
import analyze_experiment as ae  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SEGS = [('L_src_ing', 'L_src→ing'), ('L_CEP', 'L_CEP'), ('L_src_dec', 'L_src→dec'), ('L_dec_eff', 'L_dec→eff'),
        ('L_act', 'L_act'), ('RTT_ctrl', 'RTT_ctrl'), ('L_e2e', 'L_e2e')]


def L(v):
    if isinstance(v, dict):
        return (v['high'] << 32) | (v['low'] & 0xffffffff)
    return v


def jsonl(path):
    out = []
    if path and os.path.isfile(path):
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    return out


def caida(run_dir, cfg):
    """Métricas de recuperación de una ejecución con caída del CEP."""
    mongo = os.path.join(run_dir, 'raw', 'mongo')
    cs, ce, cr = cfg.get('crash_start_ms'), cfg.get('crash_end_ms'), cfg.get('cep_ready_after_restart_ms')
    out = {'caida_s': (ce - cs) / 1000 if cs and ce else None,
           'cep_listo_tras_restaurar_s': (cr - ce) / 1000 if ce and cr else None}
    B = jsonl((glob.glob(os.path.join(mongo, '*__B.json')) or [None])[0])
    Z = jsonl((glob.glob(os.path.join(mongo, '*__Z.json')) or [None])[0])
    if ce:
        after = sorted(L(b['tsn_esper']) for b in B if 'tsn_esper' in b and L(b['tsn_esper']) > ce)
        out['primera_orden_tras_restaurar_s'] = (after[0] - ce) / 1000 if after else None
    if cs and Z:
        zs = sorted((L(z['tg']), z['val']) for z in Z if 'tg' in z and 'val' in z)
        out['T_antes_caida'] = next((v for t, v in reversed(zs) if t <= cs), None)
        post = [(t, v) for t, v in zs if t >= cs]
        out['T_pico'] = max((v for t, v in post), default=None)
        # vuelta a la banda: primera muestra dentro de [79, 80] después del pico
        if post:
            tpk = max(post, key=lambda x: x[1])[0]
            back = next((t for t, v in post if t >= tpk and ae.T_MIN <= v <= ae.T_MAX), None)
            out['vuelta_a_banda_desde_caida_s'] = (back - cs) / 1000 if back else None
            out['vuelta_a_banda_desde_restaurar_s'] = (back - ce) / 1000 if back and ce else None
    return out


def ventana_final(run_dir, sec):
    """Window of the last `sec` seconds of readings of the thermal sensor, expressed as the warm-up (seconds to
    discard) of each loader of analyze_experiment, whose origins differ: first reading of the sensor (Z), first ACK
    (tg of its reading), first ESPER_STATS line with events and first sample of kubectl top (local time of the host,
    time zone HIL_TZ, Europe/Madrid by default). Returns a dict with 'sensor', 'acks', 'cep', 'res' (s) and 't_fin' (ms)."""
    from zoneinfo import ZoneInfo
    import datetime as dt
    mongo = os.path.join(run_dir, 'raw', 'mongo'); raw = os.path.join(run_dir, 'raw')
    Z = jsonl((glob.glob(os.path.join(mongo, '*__Z.json')) or [None])[0])
    tz = sorted(L(z['tg']) for z in Z if 'tg' in z and 'val' in z and L(z['tg']) > 0)
    t_fin = tz[-1]; t_ini = t_fin - sec * 1000
    w = {'t_fin': t_fin, 'sensor': (t_ini - tz[0]) / 1000.0}
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            acks = ae.load_acks(mongo, warmup_ms=0)
        except SystemExit:
            acks = None
        cep = ae.load_cep_stats(raw, warmup_sec=0)
    w['acks'] = (t_ini - float(acks['tg'].min())) / 1000.0 if acks is not None and len(acks) else 0.0
    w['cep'] = (t_ini - float(cep['t'].min())) / 1000.0 if cep is not None and not cep.empty else 0.0
    w['res'] = 0.0
    top = os.path.join(raw, 'kubectl_top.csv')
    if os.path.isfile(top):
        with open(top) as f:
            f.readline(); first = f.readline().split(',')[0]
        t0 = dt.datetime.fromisoformat(first).replace(tzinfo=ZoneInfo(os.environ.get('HIL_TZ', 'Europe/Madrid'))).timestamp() * 1000
        w['res'] = (t_ini - t0) / 1000.0
    return {k: (max(v, 0.0) if k != 't_fin' else v) for k, v in w.items()}


def resumen_run(run_dir, warmup, last=None):
    cfg = json.load(open(os.path.join(run_dir, 'config.json')))
    out = {'run': os.path.basename(run_dir), 'serie': os.path.basename(os.path.dirname(run_dir))}
    for k in ['nodos', 'cep_cpu', 'actuador', 'duration_sec']:
        out[k] = cfg.get(k)
    mongo = os.path.join(run_dir, 'raw', 'mongo')
    raw = os.path.join(run_dir, 'raw')
    w = ventana_final(run_dir, last) if last else {'sensor': warmup, 'acks': warmup, 'cep': warmup, 'res': warmup}
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            acks = ae.load_acks(mongo, warmup_ms=w['acks'] * 1000)
        except SystemExit:
            acks = None
        sensor = ae.load_sensor_data(mongo, warmup_ms=w['sensor'] * 1000)
        cep = ae.load_cep_stats(raw, warmup_sec=w['cep'])
        res = ae.load_resource_stats(raw, warmup_sec=w['res'])
    if last:
        out['ventana_sensor_s'] = w['sensor']; out['muestras'] = int(len(sensor)) if sensor is not None else 0
    out['acks'] = 0 if acks is None else len(acks)
    for col, name in SEGS:
        if acks is not None and len(acks):
            out[f'{name}_med'] = float(acks[col].median())
            out[f'{name}_p95'] = float(acks[col].quantile(0.95))
            out[f'{name}_max'] = float(acks[col].max())
    fid = ae.compute_fidelity_summary(sensor)
    if fid:
        out['OS'] = float(fid['OS (°C)']); out['US'] = float(fid['US (°C)']); out['TOB_pct'] = float(fid['TOB (%)'])
    if cep is not None and not cep.empty:
        for k in ['rx', 'rel', 'pub', 'util', 'buf_ms_mean', 'occ']:
            if k in cep.columns:
                out[f'cep_{k}_med'] = float(cep[k].median())
        out['cep_buf_ms_max'] = float(cep['buf_ms_max'].max())
        out['cep_pub_ms_mean_med'] = float(cep['pub_ms_mean'].median())
        first, last = cep.iloc[0], cep.iloc[-1]
        # descartes dentro de la ventana analizada (tras el calentamiento) y totales de la ejecución
        out['drop_late'] = float(last.get('drop_late', 0) - first.get('drop_late', 0))
        out['drop_overflow'] = float(last.get('drop_overflow', 0) - first.get('drop_overflow', 0))
        out['drop_late_total'] = float(last.get('drop_late', 0)); out['drop_overflow_total'] = float(last.get('drop_overflow', 0))
    if res is not None and not res.empty:
        c = res[res['component'] == 'CEP']
        if len(c):
            out['cep_cpu_m_med'] = float(c['cpu_millicores'].median()); out['cep_mem_mib_max'] = float(c['mem_mb'].max())
    if out['serie'] == 'fallo':
        out.update(caida(run_dir, cfg))
    return out


def agrega(df, cols, by=('nodos',)):
    rows = []
    for k, g in df.groupby(list(by)):
        k = k if isinstance(k, tuple) else (k,)
        r = dict(zip(by, k)); r['repeticiones'] = len(g)
        for c in cols:
            if c in g.columns:
                v = g[c].dropna()
                if len(v):
                    r[f'{c}_mediana'] = float(v.median()); r[f'{c}_min'] = float(v.min()); r[f'{c}_max'] = float(v.max())
        rows.append(r)
    return pd.DataFrame(rows).sort_values(list(by)) if rows else pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('camp'); ap.add_argument('--warmup', type=int, default=30); ap.add_argument('--budget', type=int, default=0)
    ap.add_argument('--last', type=int, default=0, help='window = last N seconds of readings of the thermal sensor (anchored at the end); replaces --warmup')
    ap.add_argument('--force', action='store_true', help='recompute even if a cached summary exists')
    a = ap.parse_args()
    t0 = time.time()
    runs = sorted(d for d in glob.glob(os.path.join(a.camp, '*', '*')) if os.path.isfile(os.path.join(d, 'config.json')))
    pend = 0
    rows = []
    for d in runs:
        js = os.path.join(d, 'results', f'resumen_run_l{a.last}.json' if a.last else f'resumen_run_w{a.warmup}.json')
        if os.path.isfile(js) and not a.force:
            rows.append(json.load(open(js))); continue
        if a.budget and time.time() - t0 > a.budget:
            pend += 1; continue
        r = resumen_run(d, a.warmup, a.last or None)
        os.makedirs(os.path.dirname(js), exist_ok=True)
        json.dump(r, open(js, 'w'), indent=1)
        rows.append(r)
        print('ok', r['run'], f"({time.time() - t0:.0f} s)", flush=True)
    if pend:
        print(f'PENDING {pend}: run it again'); return
    df = pd.DataFrame(rows)
    df['nodos'] = pd.to_numeric(df['nodos'], errors='coerce')
    suf = f'_l{a.last}' if a.last else f'_w{a.warmup}'
    df.to_csv(os.path.join(a.camp, f'campana_runs{suf}.csv'), index=False)
    esc = df[df['serie'] == 'esc']
    cols = ['acks'] + [f'{n}_{s}' for _, n in SEGS for s in ('med', 'p95')] + ['OS', 'US', 'TOB_pct', 'drop_late',
            'drop_overflow', 'cep_rx_med', 'cep_rel_med', 'cep_util_med', 'cep_buf_ms_mean_med', 'cep_buf_ms_max',
            'cep_occ_med', 'cep_pub_ms_mean_med', 'cep_cpu_m_med', 'cep_mem_mib_max']
    if len(esc):
        agrega(esc, cols).to_csv(os.path.join(a.camp, f'campana_escalas{suf}.csv'), index=False)
    otras = df[~df['serie'].isin(['esc', 'fallo'])]   # p. ej. las series del bloque 7 (h0, h200, w2000, max500)
    if len(otras):
        agrega(otras, cols, by=('serie', 'nodos')).to_csv(os.path.join(a.camp, f'campana_series{suf}.csv'), index=False)
    fa = df[df['serie'] == 'fallo']
    if len(fa):
        fa.to_csv(os.path.join(a.camp, f'campana_caidas{suf}.csv'), index=False)
    print('DONE', len(df), 'runs')


if __name__ == '__main__':
    main()
