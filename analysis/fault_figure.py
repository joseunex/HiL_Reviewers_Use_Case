#!/usr/bin/env python3
"""Figure 12 of the paper: reactor temperature of the five fault-injection runs aligned at the instant of the CEP
outage, with the run of median recovery time highlighted.
Usage: python3 analysis/fault_figure.py data/fault_injection --out <folder>"""
import argparse, glob, json, os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.size': 8, 'axes.titlesize': 9, 'axes.titleweight': 'bold', 'legend.fontsize': 7,
                     'axes.grid': True, 'grid.alpha': 0.3, 'grid.linestyle': '--', 'pdf.fonttype': 42})
num = lambda v: (v['high'] << 32) + (v['low'] & 0xffffffff) if isinstance(v, dict) else v

ap = argparse.ArgumentParser(); ap.add_argument('camp'); ap.add_argument('--out', required=True); a = ap.parse_args()
runs = []
for d in sorted(glob.glob(os.path.join(a.camp, 'fallo', 'fallo_n*_r*'))):
    cfg = json.load(open(os.path.join(d, 'config.json')))
    c0, c1, ready = cfg['crash_start_ms'], cfg['crash_end_ms'], cfg['cep_ready_after_restart_ms']
    Z = [json.loads(l) for l in open(glob.glob(os.path.join(d, 'raw/mongo/*__Z.json'))[0])]
    Z = sorted((num(r['tg']), float(r['val'])) for r in Z if 'ClosedLoop' in str(r.get('id')))
    t = (np.array([z[0] for z in Z]) - c0) / 1000.0; T = np.array([z[1] for z in Z])
    ipk = np.argmax(np.where(t >= 0, T, -1)); back = t[(t > t[ipk]) & (T <= 80)][0]
    runs.append(dict(name=os.path.basename(d), t=t, T=T, dur=(c1 - c0) / 1000, ready=(ready - c0) / 1000, back=back))
runs.sort(key=lambda r: r['back']); rep = runs[len(runs) // 2]
fig, ax = plt.subplots(figsize=(7.73, 3.0))
ax.axhspan(79, 80, color='#ffd54f', alpha=0.25, linewidth=0, label='Admissible band')
ax.axvspan(0, rep['dur'], color='#d62728', alpha=0.12, linewidth=0, label='CEP outage (60 s)')
for r in runs:
    if r is not rep:
        ax.plot(r['t'], r['T'], color='0.6', linewidth=0.7, alpha=0.8)
ax.plot([], [], color='0.6', linewidth=0.7, label='Other repetitions')
ax.plot(rep['t'], rep['T'], color='#1f77b4', linewidth=1.3, label='Median-recovery run')
ax.axvline(rep['ready'], color='#2ca02c', linestyle='--', linewidth=0.9, label='Restarted CEP ready')
ax.axhline(80, color='#1f77b4', linestyle=':', linewidth=0.6); ax.axhline(79, color='#ff9800', linestyle=':', linewidth=0.6)
ax.set_xlim(-60, 300); ax.set_xlabel('Time from the fault (s)'); ax.set_ylabel('Reactor temperature (°C)')
ax.set_title('Temporary CEP outage and automatic recovery (5 nodes, 5 repetitions)')
ax.legend(loc='upper right', ncol=2)
fig.tight_layout(); fig.savefig(os.path.join(a.out, 'fig_fault_recovery.pdf')); plt.close(fig)
print('run resaltado:', rep['name'], 'vuelta a la banda a +%.0f s' % rep['back'], '| orden de recuperación:', [(r['name'][-2:], round(r['back'])) for r in runs])
