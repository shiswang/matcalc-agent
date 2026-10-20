"""Advance the Cu campaign on a cadence, stopping at a chosen review gate.

Usage: python monitor_cu_campaign.py [interval_seconds] [max_iterations] [gate_step]
The monitor only calls advance_workflow; it never edits workflow state itself.
Set V2_ALLOW_SUBMIT=1 in the environment to release static submissions.
"""
import sys, time, traceback
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # 024_CuFeMn_V/
import run_v2_campaign as v
import run_cu_campaign as c
from matcalc import workflows as wf

INTERVAL = int(sys.argv[1]) if len(sys.argv) > 1 else 600
MAX_ITER = int(sys.argv[2]) if len(sys.argv) > 2 else 60
GATE = sys.argv[3] if len(sys.argv) > 3 else 'none'


def log(msg: str):
    print(time.strftime('[%Y-%m-%d %H:%M:%S] ') + msg, flush=True)


log(f'cu monitor start: wf={c.WFID} interval={INTERVAL}s max_iter={MAX_ITER} gate={GATE}')
for i in range(MAX_ITER):
    state = wf._load_state(c.WFID, c.PROJECT)
    if state is None:
        log('ERROR: no workflow state'); break
    if state['status'] == 'done':
        log('workflow status=done; monitor exiting'); break
    cur = state['steps'][state['current']]
    if cur['name'] == GATE and cur['status'] == 'pending':
        log(f'review gate reached: step "{GATE}" is pending; stopping for human review'); break
    try:
        out = wf.advance_workflow(c.WFID, c.PROJECT, expected_revision=state['revision'])
        summary = ' | '.join(l.strip() for l in out.splitlines() if l.strip())
        log(f'iter {i}: ' + summary[:300])
    except Exception as exc:
        log(f'advance FAILED: {exc!r}')
        traceback.print_exc()
        break
    state = wf._load_state(c.WFID, c.PROJECT)
    if state and state['status'] == 'done':
        log('workflow status=done; monitor exiting'); break
    time.sleep(INTERVAL)
else:
    log('iteration cap reached; relaunch the monitor to continue')
log('monitor exit')
