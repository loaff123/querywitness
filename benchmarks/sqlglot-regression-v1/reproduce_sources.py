"""Reproduce all 32 exact parent/fix simplifier outputs from a local SQLGlot clone.

The clone must contain the six complete commit IDs in cohort/protocol.json.
Only the pinned package and original test helpers are run; no QueryWitness
code, generators or outcome-dependent case selection is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from reproduce import PACK,extract_git,verify_pack

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--sqlglot-repo',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    verify_pack();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);(out/'scripts').mkdir()
    shutil.copyfile(PACK/'cohort/protocol.json',out/'protocol.json')
    for name in ('prepare_sources.py','upstream_helper.py'):shutil.copyfile(PACK/'upstream'/name,out/'scripts'/name)
    protocol=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    for cluster in protocol['clusters']:
        for pin in (cluster['parent'],cluster['fix']):
            extract_git(a.sqlglot_repo.resolve(),pin,out/'sources'/('sqlglot-'+pin),('sqlglot','tests/helpers.py','tests/test_optimizer.py','tests/fixtures/optimizer/simplify.sql','LICENSE'))
    subprocess.run([sys.executable,str(out/'scripts/prepare_sources.py')],check=True)
    expected=(PACK/'cohort/source-pool.json').read_bytes();actual=(out/'source-pool.json').read_bytes()
    if actual!=expected:raise SystemExit('Upstream output or provenance drift: inspect the complete retained output; do not replace the frozen cohort.')
    print('All 32 source/parent/fix records match:',hashlib.sha256(actual).hexdigest())
