"""Representative computational research workflow through the notebook adapter.

Synthetic, deliberately simple: explicit Euler integration of dN/dt = -kN compared with the
analytic solution. It exercises the real evidence lifecycle (raw input, analysis script, run
provenance, derived data, figure provenance, checkpoints, validation, PDF finalization, index).

It is a workflow demonstration, not a scientific claim about Euler integration.
Run:  <venv>/bin/python examples/computational_demo.py --workspace <dir>
"""
from __future__ import annotations

import argparse
import json
import math
import os
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'mcp' / 'runner'))
_vendor = HERE.parent / '.levin-plugin' / 'vendor' / 'python'
if _vendor.is_dir():
    sys.path.insert(0, str(_vendor))

import adapter  # noqa: E402

ANALYSIS = '''\
import csv, json, math, os, sys
import matplotlib
matplotlib.use("Agg")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import matplotlib.pyplot as plt

# house style: Arial (Latin) + Heiti (CJK) inside figures; captions are set by the report renderer
try:
    from plot_style import apply_plot_style, label_axes, legend_with_style
    apply_plot_style()
except Exception:
    label_axes = legend_with_style = None
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = ["Arial", "Heiti TC", "DejaVu Sans"]

k = 0.5
n0 = 1.0
cases = [(0.2, 20), (0.1, 40), (0.05, 80), (0.025, 160)]
rows = []
for dt, steps in cases:
    n = n0
    for _ in range(steps):
        n += -k * n * dt
    exact = n0 * math.exp(-k * dt * steps)
    rows.append({"dt": dt, "steps": steps, "euler": n, "analytic": exact,
                 "abs_error": abs(n - exact)})

with open(sys.argv[1], "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

dts = [r["dt"] for r in rows]
errs = [r["abs_error"] for r in rows]
fig, ax = plt.subplots(figsize=(4.2, 3.0))
ax.loglog(dts, errs, "o-", color="#1f4e79", label="observed global error")
ref = [errs[0] * (d / dts[0]) for d in dts]
ax.loglog(dts, ref, "--", color="#8c4a00", label="first-order reference slope")
if label_axes:
    label_axes(ax, title="Euler 与解析解对比", xlabel="步长 dt (s)", ylabel="N 的绝对误差 (mol/L)")
else:
    ax.set_xlabel("step size dt (s)"); ax.set_ylabel("absolute error in N (mol/L)")
ax.set_xticks(dts)
ax.set_xticklabels([f"{d:g}" for d in dts])
ax.set_yticks([min(errs), max(errs)])
ax.set_yticklabels([f"{min(errs):.2e}", f"{max(errs):.2e}"])
ax.minorticks_off()
ax.grid(True, which="major", alpha=0.3)
if legend_with_style:
    legend_with_style(ax, fontsize=7)
else:
    ax.legend(fontsize=7, frameon=False)
fig.tight_layout()
fig.savefig(sys.argv[2], dpi=300)
fig.savefig(sys.argv[3])
'''


def call(name, **arguments):
    payload = getattr(adapter, 'research_record_' + name)(None, arguments)
    if payload.get('ok') is not True:
        raise SystemExit(f'{name} failed: {payload}')
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    ws = Path(parser.parse_args().workspace).expanduser().resolve()
    (ws / 'data').mkdir(parents=True, exist_ok=True)
    (ws / 'levin_scratch' / 'demo-agent').mkdir(parents=True, exist_ok=True)

    raw = ws / 'data' / 'decay_conditions.csv'
    if not raw.exists():
        raw.write_text('k,n0,units\n0.5,1.0,mol/L\n')

    init = call('init', workspace_dir=str(ws), task_id='euler-decay-demo', agent_id='demo-agent',
                title='Euler convergence on exponential decay',
                objective='Quantify how explicit Euler global error scales with step size for dN/dt=-kN.',
                hypothesis='Global error falls approximately first order with step size.',
                expected_result='Error should halve when dt halves, giving slope about 1 on log-log axes.')
    eid = init['experiment_id']
    print('experiment', eid, 'resumed' if init['resumed'] else 'created')

    exp = ws / 'levin_notebook' / 'experiments' / eid
    script = exp / 'scripts' / 'euler_analysis.py'
    script.write_text(ANALYSIS)
    style_source = HERE / 'plot_style.py'
    if style_source.is_file():
        (exp / 'scripts' / 'plot_style.py').write_text(style_source.read_text())
    derived = exp / 'data' / 'convergence.csv'
    figure = exp / 'figures' / 'error_scaling.png'
    vector = exp / 'figures' / 'error_scaling.svg'

    raw_art = call('register_artifact', workspace_dir=str(ws), experiment_id=eid, artifact={
        'role': 'raw', 'location': str(raw.relative_to(ws)),
        'description': 'Decay parameters used by the analysis; original kept unmodified.',
        'conditions': {'k': 0.5, 'n0': 1.0, 'units': 'mol/L', 'synthetic': True}})
    script_art = call('register_artifact', workspace_dir=str(ws), experiment_id=eid, artifact={
        'role': 'script', 'location': str(script.relative_to(ws)),
        'description': 'Deterministic Euler integrator and log-log error plot script.'})

    env = {'python': sys.version.split()[0], 'matplotlib': __import__('matplotlib').__version__}
    run = call('register_run', workspace_dir=str(ws), experiment_id=eid, run={
        'backend': 'local', 'execution_status': 'success',
        'command': f'{sys.executable} {script.name} convergence.csv error_scaling.png error_scaling.svg',
        'parameters': {'k': 0.5, 'n0': 1.0, 'cases': [[0.2, 20], [0.1, 40], [0.05, 80], [0.025, 160]]},
        'environment': env, 'input_ids': [raw_art['artifact_id']], 'output_ids': []})
    run_id = run['run_id']

    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    subprocess.run([sys.executable, str(script), str(derived), str(figure), str(vector)],
                   check=True, cwd=exp / 'scripts', env={**os.environ, 'MPLCONFIGDIR': str(ws / 'levin_scratch' / 'demo-agent' / 'mpl')})

    derived_art = call('register_artifact', workspace_dir=str(ws), experiment_id=eid, artifact={
        'role': 'derived', 'location': str(derived.relative_to(ws)),
        'description': 'Per-step-size Euler result, analytic value and absolute error.',
        'input_ids': [raw_art['artifact_id']], 'script_id': script_art['artifact_id'], 'run_id': run_id,
        'conditions': {'units': 'mol/L', 'analysis': 'deterministic, no random seed'}})
    fig_art = call('register_artifact', workspace_dir=str(ws), experiment_id=eid, artifact={
        'role': 'figure', 'location': str(figure.relative_to(ws)),
        'description': 'Log-log absolute error vs step size with first-order reference slope. '
                       'Units mol/L; 4 step sizes, deterministic single replicate.',
        'input_ids': [derived_art['artifact_id']], 'script_id': script_art['artifact_id'], 'run_id': run_id})
    call('register_run', workspace_dir=str(ws), experiment_id=eid, run={
        'id': run_id, 'backend': 'local', 'execution_status': 'success',
        'command': f'{sys.executable} {script.name} ...', 'parameters': {'k': 0.5, 'n0': 1.0},
        'environment': env, 'input_ids': [raw_art['artifact_id']],
        'output_ids': [derived_art['artifact_id'], fig_art['artifact_id']]})

    call('checkpoint', workspace_dir=str(ws), experiment_id=eid, agent_id='demo-agent',
         kind='method', title='Forward Euler integration', when_note='Run once, deterministic, no replicate',
         text='Explicit forward Euler with dt in {0.2,0.1,0.05,0.025} to t=4 s; compared against the '
         'closed-form solution N0*exp(-k t).',
         evidence_ids=[script_art['artifact_id'], run_id])
    call('checkpoint', workspace_dir=str(ws), experiment_id=eid, agent_id='demo-agent',
         kind='observation', title='Monotone error decrease',
         text='Absolute error decreased monotonically with dt and tracked the first-order reference '
         'line on log-log axes.',
         evidence_ids=[derived_art['artifact_id'], fig_art['artifact_id']])
    call('checkpoint', workspace_dir=str(ws), experiment_id=eid, agent_id='demo-agent',
         kind='conclusion', title='First-order scaling within range',
         text='Within the tested range the observed global error is consistent with first-order '
         'convergence; the data do not establish behaviour outside it.',
         evidence_ids=[derived_art['artifact_id']])

    check = call('validate', workspace_dir=str(ws), experiment_id=eid)
    print('pre-finalize validation:', check['valid'], check['errors'], check['warnings'])

    final = call('finalize', workspace_dir=str(ws), experiment_id=eid,
                 execution_status='success',
                 interpretation='Euler global error decreased in proportion to dt across 0.2 to '
                 '0.025 s, consistent with first-order accuracy for this smooth problem. '
                 'No claim is made for stiff systems or larger step sizes.',
                 limitations='Single smooth linear ODE, one solver family, four step sizes, no '
                 'randomised replicates, no adaptive or higher-order comparison. Error in N is an '
                 'absolute (not relative) measure at t=4 s.',
                 visualization={'beneficial': True,
                                'reason': 'Error scaling is the result and is read directly from log-log axes.',
                                'figure_ids': [fig_art['artifact_id']], 'reviewed_by': 'demo-agent'},
                 lessons=['Halving dt halves the error only while dt stays well inside the stability limit.',
                          'Log-log slope is a blunt check: report the halving ratios next to it.'],
                 plans=['Repeat with a stiff system where the stability limit dominates.',
                        'Compare against a second-order method to confirm the slope discriminates.'])
    print(json.dumps({'experiment_id': eid, 'finalized': final['finalized'],
                      'report': final['report']['pdf_path'], 'render_state': final['report']['render_state']}, indent=2))

    idx = call('index', workspace_dir=str(ws), query='euler')
    print('indexed:', [(r['experiment_id'], r['title']) for r in idx['experiments']])
    print('notebook:', ws / 'levin_notebook')
    return 0 if final['finalized'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
