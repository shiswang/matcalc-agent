"""Campaign code lives in scripts/campaigns/024_CuFeMn_V/ ; campaign data lives in server/outputs/024_CuFeMn_V/.

Why this module exists: the campaign scripts used to sit *inside* the data directory
(`server/outputs/...`), which is gitignored — so the code that produced the delivered
results was never in version control and died with the disk. Now the code is tracked
here and only the data (workflows, OUTCARs, results, zips) stays outside git.

Override the data location with the MATCALC_CAMPAIGN_ROOT environment variable.
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent                 # scripts/campaigns/024_CuFeMn_V
REPO = HERE.parents[2]                                 # repository root
DEFAULT_DATA = REPO / 'server' / 'outputs' / '024_CuFeMn_V'
DATA_ROOT = Path(os.environ.get('MATCALC_CAMPAIGN_ROOT') or DEFAULT_DATA)
CU_DATA = DATA_ROOT / 'cu'
