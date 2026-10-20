"""Guards for the campaign scripts under ``scripts/campaigns/``.

Why this file exists: the 024 campaign drivers used to live inside the gitignored
data directory, so they were never version-controlled. Now that they are tracked,
these guards keep them honest:

1. every campaign script must compile (a moved file with a broken import path is
   a silent breakage otherwise);
2. **no script may assign to another module's module-level constant** — the
   ``v2.CONVENTION = CONVENTION`` pattern silently replaced the V campaign's
   convention inside the shared module and made the V driver raise ``KeyError: 'V'``
   (ledger #84). Lowercase/subscript targets such as
   ``v2.wf._STEP_HANDLERS['cu'] = handle`` are intentional registrations and stay
   allowed;
3. the data root must resolve through ``campaign_paths`` (never through
   ``Path(__file__).parent``), so moving the code cannot silently relocate the data.
"""
from __future__ import annotations

import ast
import compileall
import io
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CAMPAIGN_DIR = REPO / 'scripts' / 'campaigns' / '024_CuFeMn_V'

if str(CAMPAIGN_DIR) not in sys.path:
    sys.path.insert(0, str(CAMPAIGN_DIR))


def _scripts() -> list[Path]:
    if not CAMPAIGN_DIR.exists():
        return []
    return sorted(p for p in CAMPAIGN_DIR.rglob('*.py') if '__pycache__' not in p.parts)


def test_campaign_scripts_exist():
    assert CAMPAIGN_DIR.exists(), f'campaign scripts missing: {CAMPAIGN_DIR}'
    assert len(_scripts()) >= 15, f'expected the campaign script set, found {len(_scripts())}'


@pytest.mark.parametrize('path', _scripts(), ids=lambda p: p.name)
def test_campaign_script_compiles(path: Path):
    assert compileall.compile_file(str(path), quiet=2), f'compile failed: {path}'


@pytest.mark.parametrize('path', _scripts(), ids=lambda p: p.name)
def test_no_cross_module_constant_assignment(path: Path):
    """`other_module.CONST = ...` is the #84 pollution pattern; refuse it."""
    tree = ast.parse(io.open(path, encoding='utf-8').read())
    offenders = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Attribute) and t.attr.isupper()
    ]
    assert not offenders, f'{path.name} assigns another module constant: {offenders}'


def test_campaign_paths_resolves_data_root():
    import campaign_paths

    assert campaign_paths.REPO == REPO
    assert campaign_paths.DATA_ROOT.name == '024_CuFeMn_V'
    # the data directory is gitignored, so it only exists on a machine that ran the campaign
    if not campaign_paths.DATA_ROOT.exists():
        pytest.skip(f'campaign data not present on this machine: {campaign_paths.DATA_ROOT}')
    assert campaign_paths.CU_DATA.exists()


def test_drivers_use_the_shared_data_root():
    """The V and Cu drivers must point at campaign_paths.DATA_ROOT, not at their own folder."""
    import campaign_paths

    if not campaign_paths.DATA_ROOT.exists():
        pytest.skip('campaign data not present on this machine')
    sys.path.insert(0, str(CAMPAIGN_DIR / 'cu'))
    import run_cu_campaign as cu
    import run_v2_campaign as v2

    assert v2.ROOT == campaign_paths.DATA_ROOT
    assert cu.ROOT == campaign_paths.DATA_ROOT
    # the #84 regression: importing the Cu driver must not touch the V convention
    assert v2.CONVENTION['V'] == 3.25
    assert 'Cu' not in v2.CONVENTION
