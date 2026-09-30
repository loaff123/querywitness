#!/usr/bin/env python3
"""Re-run the archived, pre-fix generator debugging experiment in isolation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
archive = root / 'benchmarks' / 'ablation-forced-fk' / 'source_snapshot'
manifest = json.loads((archive / 'SHA256.json').read_text(encoding='utf-8'))
for name, expected in manifest.items():
    actual = hashlib.sha256((archive / name).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f'Archived source checksum mismatch: {name}')
with tempfile.TemporaryDirectory(prefix='querywitness-ablation-') as temporary:
    package = Path(temporary) / 'querywitness'
    (package / 'data').mkdir(parents=True)
    for path in archive.glob('*.py'):
        shutil.copy2(path, package / path.name)
    shutil.copy2(archive / 'catalog.json', package / 'data' / 'catalog.json')
    env = os.environ.copy()
    # Resolve any caller-provided development paths before changing directory.
    extras = [str(Path(p).resolve()) for p in env.get('PYTHONPATH', '').split(os.pathsep) if p]
    env['PYTHONPATH'] = os.pathsep.join([temporary, *extras])
    result = subprocess.run([sys.executable, '-m', 'querywitness', 'benchmark', '--out', str(args.out.resolve()),
                             '--trials', '16', '--repeats', '8', '--seed', '20260930', '--max-rows', '8'],
                            cwd=temporary, env=env)
    raise SystemExit(result.returncode)
