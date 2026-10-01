"""Materialize a fresh, pinned evaluation workspace; never overwrite a run.

Requires a Git checkout containing the product pin and sqlglot==27.29.0.
No network access or dependency installation is performed by this script.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile

PACK=Path(__file__).resolve().parent
REPO=PACK.parents[1]
PIN='4a9bfc55e9e6d2b0e02257a0c01fe0131317d8d9'

def extract_git(repo,pin,destination,paths=()):
    actual=subprocess.check_output(['git','-C',str(repo),'rev-parse',pin+'^{commit}'],text=True).strip()
    if actual!=pin:raise ValueError('source commit mismatch')
    archive=subprocess.check_output(['git','-C',str(repo),'archive','--format=tar',pin,*paths])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            name=PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or not (member.isfile() or member.isdir()):raise ValueError('unsafe archive entry')
            target=destination.joinpath(*name.parts)
            if member.isdir():target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with tar.extractfile(member) as source:target.write_bytes(source.read())

def verify_pack():
    manifest=json.loads((PACK/'PUBLIC_MANIFEST.json').read_text(encoding='utf-8'))
    for name,sha in manifest['files'].items():
        if hashlib.sha256((PACK/name).read_bytes()).hexdigest()!=sha:raise ValueError('public file hash mismatch: '+name)

def prepare(out,repo=REPO):
    verify_pack()
    out.mkdir(parents=True,exist_ok=False)
    for name in ('scripts','tests','inputs','sources'): (out/name).mkdir()
    for name in ('evaluate.py','replay_all.py','sqlite_checker.py','summarize.py'):shutil.copyfile(PACK/'harness'/name,out/'scripts'/name)
    for name in ('test_evaluator.py','test_replay.py'):shutil.copyfile(PACK/'harness'/name,out/'tests'/name)
    shutil.copyfile(PACK/'cohort/evaluation-cases.json',out/'inputs/evaluation-cases.json')
    shutil.copyfile(PACK/'cohort/protocol.json',out/'inputs/cohort-protocol.json')
    shutil.copyfile(PACK/'evaluation-protocol.json',out/'evaluation-protocol.json')
    extract_git(repo,PIN,out/'sources/querywitness')
    hashes=json.loads((PACK/'product-source-hashes.json').read_text(encoding='utf-8'))
    for name,sha in hashes.items():
        if hashlib.sha256((out/'sources/querywitness'/name).read_bytes()).hexdigest()!=sha:raise ValueError('product bytes differ: '+name)
    actual={p.relative_to(out/'sources/querywitness').as_posix() for p in (out/'sources/querywitness').rglob('*') if p.is_file()}
    if actual!=set(hashes):raise ValueError('product source inventory changed')
    inputs={str(p.relative_to(out).as_posix()):hashlib.sha256(p.read_bytes()).hexdigest() for p in [out/'evaluation-protocol.json',*sorted((out/'inputs').glob('*.json'))]}
    (out/'input-hashes.json').write_text(json.dumps(inputs,indent=2)+'\n',encoding='utf-8')
    subprocess.run([sys.executable,str(out/'scripts/evaluate.py'),'commit','--utc',datetime.now(timezone.utc).isoformat()],check=True)
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path);p.add_argument('--product-repo',type=Path,default=REPO);p.add_argument('--run',action='store_true');a=p.parse_args()
    out=prepare(a.out.resolve(),a.product_repo.resolve())
    if a.run:
        for script in ('evaluate.py','replay_all.py','summarize.py'):
            subprocess.run([sys.executable,str(out/'scripts'/script),*(['run'] if script=='evaluate.py' else [])],check=True)
    print('Prepared pinned workspace:',out)
