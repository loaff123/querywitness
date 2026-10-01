"""Extract every added regression fixture and reproduce actual upstream outputs."""
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys

FIXTURE = 'tests/fixtures/optimizer/simplify.sql'

def upstream(root, pin, evaluate=()):
    proc = subprocess.run([sys.executable, str(root / 'scripts/upstream_helper.py'), str(root / 'sources' / ('sqlglot-' + pin))],
        input=json.dumps({'evaluate': list(evaluate)}), capture_output=True, text=True, check=True)
    result = json.loads(proc.stdout)
    result['stderr'] = proc.stderr
    return result

def prepare(root):
    protocol = json.loads((root / 'protocol.json').read_text())
    clusters = []
    for cluster in protocol['clusters']:
        old = upstream(root, cluster['parent'])
        new = upstream(root, cluster['fix'])
        remaining = Counter(json.dumps(x, sort_keys=True) for x in old['fixtures'])
        added = []
        indices = []
        for index, pair in enumerate(new['fixtures'], 1):
            key = json.dumps(pair, sort_keys=True)
            if remaining[key]:
                remaining[key] -= 1
            else:
                added.append(pair)
                indices.append(index)
        # Pool rule uses complete upstream fixture identities, never cherry-picks.
        old_outputs = upstream(root, cluster['parent'], added)
        new_outputs = upstream(root, cluster['fix'], added)
        raw = (root / 'sources' / ('sqlglot-' + cluster['fix']) / FIXTURE).read_text()
        fixtures = []
        for n, (pair, index, parent_output, fixed_output) in enumerate(zip(added, indices, old_outputs['outputs'], new_outputs['outputs']), 1):
            meta, sql, expected = pair
            matches = list(re.finditer(r'^' + re.escape(sql) + r';$', raw, flags=re.MULTILINE))
            assert len(matches) == 1, 'Source anchor must be a unique complete fixture expression'
            source_offset = matches[0].start()
            assert fixed_output == expected, (cluster['id'], n, fixed_output, expected)
            fixtures.append({'id': f"{cluster['id']}_{n:02d}", 'cluster': cluster['id'], 'upstream_fixture_index': index,
                'source_path': FIXTURE, 'source_line_start': raw[:source_offset].count('\n') + 1,
                'source_line_end': raw[:source_offset+len(sql)].count('\n') + 1,
                'meta': meta, 'source': sql, 'expected': expected,
                'parent_output': parent_output, 'fixed_output': fixed_output,
                'fixed_matches_expected': fixed_output == expected,
                'upstream_url': f"https://github.com/tobymao/sqlglot/blob/{cluster['fix']}/{FIXTURE}#L{raw[:source_offset].count(chr(10)) + 1}"})
        clusters.append({**cluster, 'parent_fixture_count': len(old['fixtures']), 'fixed_fixture_count': len(new['fixtures']),
            'removed_pair_count': sum(remaining.values()), 'fixtures': fixtures,
            'upstream_helper': {'parent': old_outputs['helper_nodes'], 'fix': new_outputs['helper_nodes'],
                                'parent_schema': old_outputs['schema'], 'fix_schema': new_outputs['schema'],
                                'parent_schema_source': old_outputs['schema_source'], 'fix_schema_source': new_outputs['schema_source'],
                                'parent_stderr': old_outputs['stderr'], 'fix_stderr': new_outputs['stderr']}})
    return {'format_version': 1, 'provenance': 'Exact upstream test-helper outputs, not invented mutants; helpers compiled unchanged from archived source AST.', 'clusters': clusters}

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    result = prepare(root)
    target = root / 'source-pool.json'
    target.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'pool': str(target), 'counts': {c['id']: len(c['fixtures']) for c in result['clusters']}}))
