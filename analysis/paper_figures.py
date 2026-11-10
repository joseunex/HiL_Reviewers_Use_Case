#!/usr/bin/env python3
"""Figures and tables of the scalability study of the paper (Section 7.4.3): Table 4 (per-segment latencies), Table 5
(control fidelity and CEP drops), Figure 10 (reactor temperature) and Figure 11 (resources), in the steady-state
window (last 180 s of each run) of the six scales. It also draws a latency figure (fig_scal_latency.pdf) that the paper
does not use. The CEP drops come from its per-second statistics; if a run has none in the window (rotated log) they are
approximated with the cumulative counters carried by each CEP command (topic B).
Requires the per-run summaries of aggregate_campaign.py --last 180 (campana_runs_l180.csv in the data folder).
Usage: python3 analysis/paper_figures.py --out <folder> [--tablas <file.tex>] [--data data/scalability]
The LaTeX comment lines written with the tables are in Spanish (runs per scale, cycles, ranges, resources)."""
import argparse, contextlib, glob, io, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'DeployV2', 'k8s'))
import analyze_experiment as ae  # noqa: E402
import aggregate_campaign as ag  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({'font.size': 8, 'axes.titlesize': 9, 'axes.titleweight': 'bold', 'legend.fontsize': 7,
                     'axes.grid': True, 'grid.alpha': 0.3, 'grid.linestyle': '--', 'pdf.fonttype': 42})
DATA_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'scalability')
SCALES = (5, 100, 250, 500, 1000, 1500)
# Window: the last 180 s of readings of the thermal sensor of each run (aggregate_campaign.py --last 180), anchored at the end.
SCALE_COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#9467bd', '#8c564b', '#e377c2', '#d62728']
COMPS = ['Sensor', 'ClosedLoopSensor', 'Fog', 'CEP', 'MongoDB', 'Mosquitto']
num = lambda v: (v['high'] << 32) + (v['low'] & 0xffffffff) if isinstance(v, dict) else v


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


def fmt(v, dec=0):
    return '--' if v is None or (isinstance(v, float) and np.isnan(v)) else f'{v:,.{dec}f}'


def jsonl(path):
    with open(path) as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def z_rows(d):
    """Lecturas del ClosedLoopSensor (topic Z): (tg, t_rcv_fog, val) ordenadas por tg."""
    rows = []
    for r in jsonl(glob.glob(os.path.join(d, 'raw/mongo/*__Z.json'))[0]):
        if 'ClosedLoop' not in str(r.get('id', '')):
            continue
        tg, tr = num(r.get('tg')), num(r.get('t_rcv_fog'))
        if isinstance(tg, int) and tg > 0:
            rows.append((tg, tr if isinstance(tr, int) else None, float(r['val'])))
    return sorted(rows)


def drops_from_commands(d, warm):
    """Descartes (late, overflow) en la ventana a partir de los contadores acumulados de las órdenes del CEP (topic B)."""
    t0 = z_rows(d)[0][0]
    rows = []
    for r in jsonl(glob.glob(os.path.join(d, 'raw/mongo/*__B.json'))[0]):
        c, ts = r.get('cep_drops'), num(r.get('tsn_esper'))
        if c and isinstance(ts, int):
            rows.append((ts, c['late'], c['overflow']))
    rows = sorted(r for r in rows if r[0] - t0 >= warm * 1000)
    if len(rows) < 2:
        return float('nan'), float('nan')
    return rows[-1][1] - rows[0][1], rows[-1][2] - rows[0][2]


def fog_arrival(d, warm):
    """Mediana de t_rcv_fog - tg (ms) de las lecturas del ClosedLoopSensor en la ventana."""
    rows = z_rows(d); t0 = rows[0][0]
    v = [tr - tg for tg, tr, _ in rows if tr is not None and tg - t0 >= warm * 1000]
    return float(np.median(v)) if v else float('nan')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--tablas', default=None)
    ap.add_argument('--data', default=DATA_DEFAULT, help='campaign folder with esc/ and campana_runs_l180.csv')
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    SRC = {n: (a.data, 'l180') for n in SCALES}
    scales = sorted(SRC)
    runs, summ, W = {}, [], {}
    for n in scales:
        camp, w = SRC[n]; W[n] = w
        runs[n] = sorted(d for d in glob.glob(os.path.join(camp, 'esc', f'esc_n{n:04d}_r*')) if os.path.isfile(os.path.join(d, 'config.json')))
        df = pd.read_csv(os.path.join(camp, f'campana_runs_{w}.csv')); df = df[(df['serie'] == 'esc') & (df['nodos'] == n)].copy()
        df['camp'] = camp; summ.append(df)
    summ = pd.concat(summ, ignore_index=True); summ['nodos'] = summ['nodos'].astype(int)
    # descartes totales en la ventana (late + overflow); aproximación por las órdenes si faltan las estadísticas
    summ['drops'] = summ['drop_late'] + summ['drop_overflow']; aprox = []
    for i, r in summ.iterrows():
        if np.isnan(r['drops']):
            late, over = drops_from_commands(os.path.join(r['camp'], 'esc', r['run']), VEN[os.path.join(r['camp'], 'esc', r['run'])]['sensor'])
            summ.loc[i, 'drop_late'], summ.loc[i, 'drop_overflow'], summ.loc[i, 'drops'] = late, over, late + over; aprox.append(r['run'])
    rep = {}
    for n in scales:
        g = summ[summ['nodos'] == n].sort_values('TOB_pct'); rep[n] = os.path.join(SRC[n][0], 'esc', g.iloc[len(g) // 2]['run'])
    VEN = {d: ag.ventana_final(d, 180) for n in scales for d in runs[n]}   # calentamientos por run y por cargador

    # (a) temperatura en la ventana estable, run representativo, seis paneles
    nrows = (len(scales) + 1) // 2
    fig, axes = plt.subplots(nrows, 2, figsize=(7.73, 1.65 * nrows), sharex=True)
    for i, n in enumerate(scales):
        ax = axes[i // 2][i % 2]; s = quiet(ae.load_sensor_data, os.path.join(rep[n], 'raw', 'mongo'), 0)
        wv = VEN[rep[n]]['sensor']; s = s[s['t_rel'] >= wv]
        ax.axhspan(79, 80, color='#ffd54f', alpha=0.25, linewidth=0)
        ax.axhline(80, color='#1f77b4', linestyle='--', linewidth=0.6); ax.axhline(79, color='#ff9800', linestyle='--', linewidth=0.6)
        ax.plot(s['t_rel'] - wv, s['val'], color='#1f77b4', linewidth=0.9)
        ax.set_title(f'({chr(97 + i)}) {n} nodes'); ax.set_xlim(0, 180)
        # misma escala vertical mientras el lazo mantiene la banda; más amplia donde ya no (1500 y 2000 nodos)
        lo, hi = (76.5, 81.5) if n <= 1000 else (min(72, np.floor(s['val'].min()) - 1), max(84, np.ceil(s['val'].max()) + 1))
        ax.set_ylim(lo, hi)
        if i % 2 == 0: ax.set_ylabel('Temp. (°C)')
    if len(scales) % 2: axes[-1][1].axis('off'); axes[-2][1].tick_params(labelbottom=True); axes[-2][1].set_xlabel('Time in the steady-state window (s)')
    axes[-1][0].set_xlabel('Time in the steady-state window (s)')
    if len(scales) % 2 == 0: axes[-1][1].set_xlabel('Time in the steady-state window (s)')
    fig.tight_layout(); fig.savefig(os.path.join(a.out, 'fig_scal_temp.pdf')); plt.close(fig)

    # (b) recursos en la ventana estable
    res = {n: {c: {'cpu': [], 'mem': []} for c in COMPS} for n in scales}
    for n in scales:
        for d in runs[n]:
            df = quiet(ae.load_resource_stats, os.path.join(d, 'raw'), VEN[d]['res'])
            if df is None: continue
            for c in COMPS:
                g = df[df['component'] == c]
                if len(g): res[n][c]['cpu'].append(g['cpu_perc'].median()); res[n][c]['mem'].append(g['mem_mb'].median())
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.73, 2.8)); x = np.arange(len(COMPS)); bw = 0.8 / len(scales)
    for i, n in enumerate(scales):
        cpu = [np.median(res[n][c]['cpu']) if res[n][c]['cpu'] else 0 for c in COMPS]; mem = [np.median(res[n][c]['mem']) if res[n][c]['mem'] else 0 for c in COMPS]
        ax1.bar(x + (i - (len(scales) - 1) / 2) * bw, cpu, bw, color=SCALE_COLORS[i], label=f'{n} nodes', edgecolor='black', linewidth=0.3)
        ax2.bar(x + (i - (len(scales) - 1) / 2) * bw, mem, bw, color=SCALE_COLORS[i], edgecolor='black', linewidth=0.3)
    for ax, yl in ((ax1, 'CPU (%)'), (ax2, 'Memory (MiB)')):
        ax.set_xticks(x); ax.set_xticklabels(COMPS, rotation=30, ha='right'); ax.set_ylabel(yl)
    ax2.legend(*ax1.get_legend_handles_labels(), loc='upper right'); fig.suptitle('Steady-state resource consumption by component type', fontweight='bold', fontsize=9)
    fig.tight_layout(); fig.savefig(os.path.join(a.out, 'fig_scal_resources.pdf')); plt.close(fig)

    # (c) latencias por tramo frente a la carga, cajas y bigotes en escala lineal, dos paneles: (a) detalle hasta 1000 nodos,
    # (b) todas las escalas. Cada caja reúne los ciclos de control de las 5 repeticiones (bigotes en P5 y P95, sin puntos).
    SEGS = [('L_src→ing', '$L_{\\mathrm{src \\rightarrow ing}}$', '#2a78d6'), ('L_CEP', '$L_{\\mathrm{CEP}}$', '#eb6834'),
            ('L_dec→eff', '$L_{\\mathrm{dec \\rightarrow eff}}$', '#1baf7a'), ('RTT_ctrl', '$RTT_{\\mathrm{ctrl}}$', '#e87ba4'),
            ('L_e2e', '$L_{\\mathrm{e2e}}$', '#008300')]
    lat = {n: {k: [] for k, _, _ in SEGS} for n in scales}
    for n in scales:
        for d in runs[n]:
            df = quiet(ae.load_acks, os.path.join(d, 'raw', 'mongo'), VEN[d]['acks'] * 1000)
            for k, _, _ in SEGS: lat[n][k] += list(df[k.replace('→', '_')].dropna().values)
    from matplotlib.patches import Patch
    def boxpanel(ax, sc, ymax):
        bw = 0.8 / len(SEGS)
        for i_n, n in enumerate(sc):
            for i_k, (k, _, col) in enumerate(SEGS):
                pos = i_n + (i_k - (len(SEGS) - 1) / 2) * bw
                bp = ax.boxplot([lat[n][k]], positions=[pos], widths=bw * 0.85, whis=(5, 95), patch_artist=True, manage_ticks=False, showfliers=False,
                                medianprops=dict(color='black', linewidth=0.9), whiskerprops=dict(color=col, linewidth=0.8), capprops=dict(color=col, linewidth=0.8),
                                boxprops=dict(linewidth=0.6))
                bp['boxes'][0].set_facecolor(col); bp['boxes'][0].set_alpha(0.85)
        ax.set_xticks(range(len(sc))); ax.set_xticklabels([str(n) for n in sc]); ax.set_xlim(-0.6, len(sc) - 0.4); ax.set_ylim(0, ymax); ax.set_xlabel('Sensor nodes')
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.73, 3.2), gridspec_kw={'width_ratios': [1, 1.15]})
    boxpanel(ax1, [n for n in scales if n <= 1000], 1000); ax1.set_ylabel('Latency (ms)'); ax1.set_title('(a) Up to 1000 nodes (detail)')
    boxpanel(ax2, scales, 10000); ax2.set_title('(b) All scales'); ax2.set_yticks([0, 2000, 4000, 6000, 8000, 10000]); ax2.set_yticklabels(['0', '2,000', '4,000', '6,000', '8,000', '10,000'])
    fig.legend(handles=[Patch(facecolor=col, label=lab) for _, lab, col in SEGS], ncol=len(SEGS), loc='upper center', bbox_to_anchor=(0.5, 1.0), framealpha=0.9, fontsize=7.5)
    fig.tight_layout(rect=(0, 0, 1, 0.92)); fig.savefig(os.path.join(a.out, 'fig_scal_latency.pdf')); plt.close(fig)

    # ciclos de control y llegada al Fog
    cycles, fog = {}, {}
    for n in scales:
        cycles[n] = [len(quiet(ae.load_acks, os.path.join(d, 'raw', 'mongo'), VEN[d]['acks'] * 1000)) for d in runs[n]]
        fog[n] = [fog_arrival(d, VEN[d]['sensor']) for d in runs[n]]

    # tablas
    def med(col, n, dec=0): return fmt(summ[summ['nodos'] == n][col].dropna().median(), dec)
    def medrange(col, n, dec=0):
        v = summ[summ['nodos'] == n][col].dropna(); return f'{fmt(v.median(), dec)} [{fmt(v.min(), dec)}--{fmt(v.max(), dec)}]'
    L = []
    segs_all = [('L_src→ing', '$L_{\\mathrm{src \\rightarrow ing}}$'), ('L_CEP', '$L_{\\mathrm{CEP}}$'), ('L_src→dec', '$L_{\\mathrm{src \\rightarrow dec}}$'),
                ('L_dec→eff', '$L_{\\mathrm{dec \\rightarrow eff}}$'), ('L_act', '$L_{\\mathrm{act}}$'), ('RTT_ctrl', '$RTT_{\\mathrm{ctrl}}$'), ('L_e2e', '$L_{\\mathrm{e2e}}$')]
    L.append('% runs por escala: ' + '; '.join(f'{n}: {len(runs[n])}' for n in scales))
    L.append('% TABLA LATENCIAS (ms): mediana entre repeticiones de la mediana y del P95 de cada run, ventana estable')
    L.append('\\begin{tabular}{l ' + 'rr ' * len(scales) + '}\n\\toprule')
    L.append(' & ' + ' & '.join(f'\\multicolumn{{2}}{{c}}{{\\textbf{{{n} nodes}}}}' for n in scales) + ' \\\\')
    L.append(''.join(f'\\cmidrule(lr){{{2 + 2 * i}-{3 + 2 * i}}}' for i in range(len(scales))))
    L.append('\\textbf{Segment} & ' + ' & '.join('Med. & P95' for _ in scales) + ' \\\\\n\\midrule')
    for k, lab in segs_all:
        L.append(lab + ' & ' + ' & '.join(f'{med(k + "_med", n)} & {med(k + "_p95", n)}' for n in scales) + ' \\\\')
    L.append('\\bottomrule\n\\end{tabular}\n')
    L.append('% ciclos analizados: ' + '; '.join(f'{n}: {sum(cycles[n])} ({min(cycles[n])}--{max(cycles[n])})' for n in scales))
    for k in ('L_src→ing', 'L_CEP', 'L_e2e'):
        L.append(f'% rangos med {k}: ' + '; '.join(f'{n}: {medrange(k + "_med", n)}' for n in scales))
        L.append(f'% rangos P95 {k}: ' + '; '.join(f'{n}: {medrange(k + "_p95", n)}' for n in scales))
    L.append('% llegada al Fog de las lecturas del ClosedLoopSensor (t_rcv_fog - tg, mediana, ms): ' + '; '.join(f'{n}: {np.nanmedian(fog[n]):.0f} [{np.nanmin(fog[n]):.0f}--{np.nanmax(fog[n]):.0f}]' for n in scales))
    L.append('% TABLA FIDELIDAD: mediana [min--max], ventana estable; descartes = late + overflow')
    L.append('\\begin{tabular}{l ' + 'r ' * len(scales) + '}\n\\toprule\n\\textbf{Metric} & ' + ' & '.join(f'\\textbf{{{n} nodes}}' for n in scales) + ' \\\\\n\\midrule')
    L.append('Peak overshoot ($OS$) [$^\\circ$C] & ' + ' & '.join(medrange('OS', n, 2) for n in scales) + ' \\\\')
    L.append('Peak undershoot ($US$) [$^\\circ$C] & ' + ' & '.join(medrange('US', n, 2) for n in scales) + ' \\\\')
    L.append('Time outside band ($TOB$) [\\%] & ' + ' & '.join(medrange('TOB_pct', n, 1) for n in scales) + ' \\\\')
    L.append('CEP ingress drops & ' + ' & '.join(medrange('drops', n) for n in scales) + ' \\\\')
    L.append('\\bottomrule\n\\end{tabular}\n')
    L.append('% drop_late ventana: ' + '; '.join(f'{n}: {medrange("drop_late", n)}' for n in scales))
    L.append('% drop_overflow ventana: ' + '; '.join(f'{n}: {medrange("drop_overflow", n)}' for n in scales))
    L.append('% descartes aproximados por las órdenes (sin estadísticas del CEP en la ventana): ' + (', '.join(aprox) if aprox else 'ninguno'))
    L.append('% eventos recibidos en la ventana ~ nodos x 180: ' + '; '.join(f'{n}: {n * 180:,}' for n in scales))
    summ['util_pct'] = summ['cep_util_med'] * 100
    for k, lab in (('cep_rx_med', 'rx/s'), ('cep_rel_med', 'rel/s'), ('util_pct', 'util %'), ('cep_buf_ms_mean_med', 'buf mean ms'), ('cep_buf_ms_max', 'buf max ms'), ('cep_occ_med', 'occ'), ('cep_cpu_m_med', 'cpu m'), ('cep_mem_mib_max', 'mem MiB'), ('acks', 'acks run')):
        L.append(f'% CEP {lab}: ' + '; '.join(f'{n}: {medrange(k, n, 1 if k == "util_pct" else 0)}' for n in scales))
    L.append('% runs representativos (TOB mediano): ' + ', '.join(f'{n}: {os.path.basename(rep[n])}' for n in scales))
    for n in scales:
        L.append(f'% recursos {n}: ' + ', '.join(f'{c} {np.median(res[n][c]["cpu"]):.1f}% / {np.median(res[n][c]["mem"]):.0f} MiB' for c in COMPS if res[n][c]['cpu']))
    txt = '\n'.join(L)
    if a.tablas: open(a.tablas, 'w').write(txt)
    print(txt)


if __name__ == '__main__':
    main()
