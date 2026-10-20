"""Advance the v2 campaign on a cadence, stopping at a chosen review gate.

Usage:  python monitor_v2_campaign.py [interval_seconds] [max_iterations] [gate_step]

The monitor only calls advance_workflow (the sanctioned path); it never edits workflow
state itself.  It stops when:
  * the workflow finishes,
  * the next pending step is `gate_step` (default `statics`) - the human review gate,
  * an advance raises (protocol check failure) - so the failure can be inspected,
  * the iteration cap is reached (relaunch to continue).
"""
import sys, time, traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_v2_campaign as v
from matcalc import workflows as wf

INTERVAL = int(sys.argv[1]) if len(sys.argv) > 1 else 600
MAX_ITER = int(sys.argv[2]) if len(sys.argv) > 2 else 60
GATE = sys.argv[3] if len(sys.argv) > 3 else 'statics'


def log(msg: str):
    print(time.strftime('[%Y-%m-%d %H:%M:%S] ') + msg, flush=True)


log(f'monitor start: wf={v.WFID} interval={INTERVAL}s max_iter={MAX_ITER} gate={GATE}')
for i in range(MAX_ITER):
    state = wf._load_state(v.WFID, v.PROJECT)
    if state is None:
        log('ERROR: no workflow state'); break
    if state['status'] == 'done':
        log('workflow status=done; monitor exiting'); break
    cur = state['steps'][state['current']]
    if cur['name'] == GATE and cur['status'] == 'pending':
        log(f'review gate reached: step "{GATE}" is pending and was NOT submitted; stopping for human review')
        break
    try:
        out = wf.advance_workflow(v.WFID, v.PROJECT, expected_revision=state['revision'])
        summary = ' | '.join(l.strip() for l in out.splitlines() if l.strip())
        log(f'iter {i}: ' + summary[:300])
    except Exception as exc:                                   # noqa: BLE001
        log(f'advance FAILED: {exc!r}')
        traceback.print_exc()
        break
    state = wf._load_state(v.WFID, v.PROJECT)
    if state and state['status'] == 'done':
        log('workflow status=done; monitor exiting'); break
    time.sleep(INTERVAL)
else:
    log('iteration cap reached; relaunch the monitor to continue')
log('monitor exit')
