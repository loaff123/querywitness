#!/usr/bin/env python3
"""Build the public, read-only explorer from actual QueryWitness benchmark files.

No SQL is executed during this build. The only dependency is Python's standard
library. Missing, drifted, or checksum-invalid inputs fail before output changes.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'site'
QUERY_AWARE_DEMO = ROOT / 'benchmarks/query-aware-demo'
MARKER = '.querywitness-generated'
REPO = 'https://github.com/loaff123/querywitness'


def esc(value):
    return html.escape(str(value), quote=True)


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 16_000_000:
        raise ValueError(f'Input too large: {path.name}')
    def reject_constant(value):
        raise ValueError(f'Non-finite JSON value: {value}')
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=reject_constant)


def digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def number(value):
    return f'{int(value):,}'


def file_link(path, label, css='download'):
    return f'<a class="{css}" href="downloads/{esc(path)}" download>{esc(label)}<span aria-hidden="true"> ↗</span></a>'


def code_block(value, label):
    return f'<pre tabindex="0" aria-label="{esc(label)}"><code>{esc(value)}</code></pre>'


def typed_cell(cell):
    kind = cell['type']
    value = 'NULL' if kind == 'null' else cell['value']
    if kind == 'text':
        value = json.dumps(value, ensure_ascii=False)
    return f'<span class="cell-value{ " null" if kind == "null" else ""}">{esc(value)}</span><span class="cell-type">{esc(kind.upper())}</span>'


def input_cell(value):
    kind = 'null' if value is None else ('integer' if type(value) is int else 'real' if type(value) is float else 'text')
    # Input fixtures are JSON values; observations below retain exact encoded types.
    return typed_cell({'type': kind, 'value': value})


def table_html(columns, rows, label, *, typed=False):
    head = ''.join(f'<th scope="col">{esc(c)}</th>' for c in columns)
    body = ''.join('<tr>' + ''.join('<td>' + (typed_cell(v) if typed else input_cell(v)) + '</td>' for v in row) + '</tr>' for row in rows)
    if not rows:
        body = f'<tr><td class="empty-cell" colspan="{max(1, len(columns))}">Empty relation · 0 rows</td></tr>'
    return f'<div class="table-scroll" role="region" aria-label="{esc(label)}" tabindex="0"><table><caption class="sr-only">{esc(label)}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def validate_inputs(benchmark, catalog_path):
    summary = read_json(benchmark / 'summary.json')
    catalog = read_json(catalog_path)
    if summary.get('format_version') != 1:
        raise ValueError('Unsupported benchmark summary format')
    if summary.get('catalog_sha256') != digest(catalog):
        raise ValueError('Benchmark catalog checksum does not match the supplied catalog')
    families = summary.get('by_family', [])
    if not families or summary.get('families') != len(families):
        raise ValueError('Benchmark family count is missing or inconsistent')
    cases = {case['id']: case for case in catalog['cases']}
    seen, witnesses = set(), {}
    for family in families:
        ident = family['id']
        if not re.fullmatch(r'[a-z0-9_]+', ident) or ident in seen or ident not in cases:
            raise ValueError('Invalid, duplicate, or unknown benchmark family')
        seen.add(ident)
        witness_path = benchmark / 'witnesses' / ident / 'witness.json'
        detected = any(family['methods'][m]['mutant']['detected_runs'] for m in ('random', 'boundary'))
        if not witness_path.exists():
            if detected:
                raise ValueError(f'Missing witness for detected family: {ident}')
            continue
        witness = read_json(witness_path)
        unsigned = {k: v for k, v in witness.items() if k != 'integrity_sha256'}
        if witness.get('integrity_sha256') != digest(unsigned):
            raise ValueError(f'Witness integrity checksum mismatch: {ident}')
        if witness.get('format') != 'querywitness/witness' or witness.get('format_version') != 1:
            raise ValueError(f'Unsupported witness format: {ident}')
        case = cases[ident]
        if witness['reference'] != case['reference'] or witness['candidate'] != case['mutant'] or witness['policy'] != case['policy']:
            raise ValueError(f'Witness and catalog query contract differ: {ident}')
        if witness['comparison']['status'] != 'mismatch' or any(witness[k]['status'] != 'ok' for k in ('reference_observation', 'candidate_observation')):
            raise ValueError(f'Witness must contain two successful, differing observations: {ident}')
        if witness['provenance']['instance_sha256'] != digest(witness['instance']):
            raise ValueError(f'Witness instance checksum mismatch: {ident}')
        for filename in ('fixture.sql', 'report.html'):
            if not (witness_path.parent / filename).is_file():
                raise ValueError(f'Missing witness download: {ident}/{filename}')
        witnesses[ident] = witness
    for method in ('random', 'boundary'):
        declared = summary['method_detection'][method]
        actual = [f['methods'][method]['mutant'] for f in families]
        if declared['detected_family_runs'] != sum(x['detected_runs'] for x in actual) or declared['total_family_runs'] != sum(x['runs'] for x in actual) or declared['detected_distinct_families'] != sum(x['detected_runs'] > 0 for x in actual):
            raise ValueError(f'Inconsistent benchmark method counts: {method}')
    all_variants = [f['methods'][m][v] for f in families for m in ('random', 'boundary') for v in ('mutant', 'equivalent_control')]
    if summary['matched_budget_instance_evaluations'] != sum(x['instance_evaluations'] for x in all_variants):
        raise ValueError('Inconsistent benchmark evaluation count')
    if summary['matched_budget_runs'] != sum(x['runs'] for x in all_variants):
        raise ValueError('Inconsistent benchmark run count')
    controls = [f['methods'][m]['equivalent_control'] for f in families for m in ('random', 'boundary')]
    if summary['control_mismatches'] != sum(x['mismatch_instances'] for x in controls):
        raise ValueError('Inconsistent benchmark control mismatch count')
    if summary['inconclusive_instances'] != sum(x['inconclusive_instances'] for x in all_variants):
        raise ValueError('Inconsistent benchmark inconclusive count')
    if summary['benign_detected_families'] != sum(f['benign_status'] == 'mismatch' for f in families):
        raise ValueError('Inconsistent benchmark benign detection count')
    return summary, catalog, cases, witnesses


def render_witness(case, witness):
    if witness is None:
        return '<section class="panel no-witness"><h3>No witness saved</h3><p>This run did not save a counterexample for this family. Finite-budget agreement does not establish equivalence.</p></section>'
    ident = case['id']
    reduction = witness.get('reduction') or {}
    minimal = reduction.get('row_1_minimal') is True
    row_count = sum(len(rows) for rows in witness['instance'].values())
    reduction_text = 'row-1-minimal' if minimal else 'Minimality not established'
    guarantee = ('No single row can be deleted while preserving both the schema constraints and a successful output mismatch. This is not a globally smallest database; coordinated multi-row deletions may shrink it further.' if minimal else 'This is the best preserved witness recorded by the run. A complete single-row minimality check was not established.')
    tables = []
    for table in witness['schema']['tables']:
        name, columns = table['name'], table['columns']
        rows = witness['instance'][name]
        schema = ' · '.join(f'{c["name"]} {c["type"]}' + ('' if c.get('nullable', True) else ' NOT NULL') for c in columns)
        keys = []
        if table.get('primary_key'):
            keys.append('PRIMARY KEY (' + ', '.join(table['primary_key']) + ')')
        for key in table.get('unique', []):
            keys.append('UNIQUE (' + ', '.join(key) + ')')
        for key in table.get('foreign_keys', []):
            target = key['references']
            keys.append('FOREIGN KEY (' + ', '.join(key['columns']) + ') → ' + target['table'] + '(' + ', '.join(target['columns']) + ')')
        tables.append(f'<div class="data-card"><div class="card-head"><h4>{esc(name)}</h4><span>{number(len(rows))} rows</span></div>{table_html([c["name"] for c in columns], rows, "Input table " + name)}<p class="schema-line">{esc(schema)}</p>' + (f'<p class="schema-line">{esc(" · ".join(keys))}</p>' if keys else '') + '</div>')
    comparison = witness['comparison']
    if comparison.get('reason') == 'column_count':
        diff = f'Column count differs: reference {comparison["reference_columns"]}, candidate {comparison["candidate_columns"]}.'
    else:
        diff = f'{comparison["reference_only_count"]} reference-only row occurrences · {comparison["candidate_only_count"]} candidate-only row occurrences'
        if witness['policy'] == 'ordered':
            diff += '. Row order also participates in this comparison.'
    observations = []
    for side in ('reference', 'candidate'):
        observation = witness[side + '_observation']
        observations.append(f'<div class="data-card output-{side}"><div class="card-head"><h4>{side.capitalize()} output</h4><span>{number(len(observation["rows"]))} rows · successful</span></div>{table_html(observation["columns"], observation["rows"], side.capitalize() + " output", typed=True)}</div>')
    download_base = f'witnesses/{ident}/'
    downloads = ''.join(file_link(download_base + name, label) for name, label in [('witness.json', 'Witness JSON'), ('fixture.sql', 'SQL fixture'), ('report.html', 'Standalone report')])
    replay_command = 'python -m pip install .\nquerywitness replay witness.json'
    provenance = json.dumps({'search': witness.get('search'), 'reduction': reduction, 'provenance': witness['provenance'], 'execution_limits': witness['execution_limits'], 'integrity_sha256': witness['integrity_sha256']}, indent=2, ensure_ascii=False)
    return f'''<section class="witness-section" aria-labelledby="{ident}-input"><div class="section-heading"><h3 id="{ident}-input"><span>02</span> Minimized input</h3><p>{number(row_count)} total rows <span class="tag">{esc(reduction_text)}</span></p></div><div class="table-grid">{''.join(tables)}</div><p class="fine-print">{esc(guarantee)}</p></section>
<section class="witness-section" aria-labelledby="{ident}-output"><div class="section-heading"><h3 id="{ident}-output"><span>03</span> Observed discrepancy</h3><span class="status mismatch">Mismatch</span></div><p class="difference">{esc(diff)}</p><div class="query-grid">{''.join(observations)}</div><p class="fine-print">Cells include their recorded SQLite type. NULL is distinct from text. REAL observations use exact hexadecimal floating-point notation. Integer and real values compare numerically; columns compare by position, not name.</p></section>
<section class="witness-section replay-section" aria-labelledby="{ident}-replay"><div class="section-heading"><h3 id="{ident}-replay"><span>04</span> Reproduce locally</h3></div><p>Clone the <a href="{REPO}">source repository</a>, install from its root, then replay the downloaded witness:</p>{code_block(replay_command, 'Local installation and replay commands')}<div class="download-row">{downloads}</div><p class="fine-print">The JSON preserves the exact schema, tables, queries, typed observations, seed and checksums. Inspect SQL before running it. This page does not execute queries.</p><details class="provenance"><summary>Search, reduction &amp; integrity details</summary>{code_block(provenance, 'Witness provenance')}</details></section>'''


def render_family(case, family, witness, index):
    ident = case['id']
    queries = [('Reference', witness['reference'] if witness else case['reference']), ('Candidate mutant', witness['candidate'] if witness else case['mutant'])]
    panels = ''.join(f'<div class="query-card"><div class="card-head"><h4>{label}</h4><span>SQLite</span></div>{code_block(query, label + " SQL")}</div>' for label, query in queries)
    runs = ' · '.join(f'{m.capitalize()}: {family["methods"][m]["mutant"]["detected_runs"]}/{family["methods"][m]["mutant"]["runs"]} runs detected' for m in ('random', 'boundary'))
    return f'''<article id="family-{ident}" class="family" aria-labelledby="{ident}-title"><header class="family-heading"><p class="eyebrow">EXAMPLE {index:02d} <span>/</span> {esc(ident.replace('_', ' '))}</p><h2 id="{ident}-title" tabindex="-1">{esc(case['title'])}</h2><p class="mechanism">{esc(case['mechanism'])}</p><div class="family-meta"><span class="tag">{esc(case['policy'])} semantics</span><span>{esc(runs)}</span></div></header>
<section class="witness-section" aria-labelledby="{ident}-sql"><div class="section-heading"><h3 id="{ident}-sql"><span>01</span> Query pair</h3><span class="subtle">Exact SQL, unchanged</span></div><div class="query-grid">{panels}</div><details class="control"><summary>Equivalent control used in this benchmark</summary>{code_block(case['equivalent_control'], 'Equivalent control SQL')}<p class="fine-print">An algebraically motivated catalog control. Finite agreement on generated instances is not a proof of equivalence.</p></details></section>{render_witness(case, witness)}</article>'''


def render_benchmark(summary, benchmark):
    method_rows = []
    for method, label in [('random', 'Random generation'), ('boundary', 'Boundary-biased generation')]:
        result = summary['method_detection'][method]
        method_rows.append(f'<tr><th scope="row">{label}</th><td>{number(result["detected_family_runs"])} / {number(result["total_family_runs"])}</td><td>{number(result["detected_distinct_families"])} / {number(summary["families"])}</td></tr>')
    family_rows = ''.join(f'<tr><th scope="row"><a href="#family-{esc(f["id"])}">{esc(f["title"])}</a></th>' + ''.join(f'<td>{f["methods"][m]["mutant"]["detected_runs"]} / {f["methods"][m]["mutant"]["runs"]}</td>' for m in ('random', 'boundary')) + f'<td>{esc(f["benign_status"])}</td><td>{file_link("raw/" + f["id"] + ".jsonl", "JSONL", "text-link") if (benchmark / "raw" / (f["id"] + ".jsonl")).is_file() else "Not supplied"}</td></tr>' for f in summary['by_family'])
    links = ''.join(file_link(name, label) for name, label in [('summary.json', 'Summary JSON'), ('manifest.json', 'Run manifest'), ('REPORT.md', 'Benchmark report')] if (benchmark / name).is_file())
    return f'''<section id="benchmark" class="benchmark-section" aria-labelledby="benchmark-title"><div class="benchmark-intro"><div><p class="eyebrow">DEVELOPMENT-SET SYNTHETIC COVERAGE</p><h2 id="benchmark-title">The benchmark behind the examples</h2></div><p>Every count below comes from the supplied run. Random and boundary generation use equal trial budgets and paired seeds; neither stops after its first hit.</p></div><div class="benchmark-columns"><div><div class="table-scroll" tabindex="0" role="region" aria-label="Benchmark method detection"><table><caption>Mutant detection under the matched budget</caption><thead><tr><th scope="col">Method</th><th scope="col">Family-runs detected</th><th scope="col">Distinct families</th></tr></thead><tbody>{''.join(method_rows)}</tbody></table></div><p class="fine-print">Separate single-benign-fixture baseline: {number(summary['benign_detected_families'])}/{number(summary['families'])} mutants detected. These hand-authored masking fixtures are not an equal-budget baseline or a sample of production databases.</p></div><dl class="run-config"><div><dt>Instances / run</dt><dd>{number(summary['trials_per_run'])}</dd></div><div><dt>Seed repeats</dt><dd>{number(summary['repeats'])}</dd></div><div><dt>Base seed</dt><dd>{summary['seed']}</dd></div><div><dt>Maximum rows / table</dt><dd>{number(summary['max_rows'])}</dd></div><div><dt>Control mismatches</dt><dd>{number(summary['control_mismatches'])}</dd></div><div><dt>Inconclusive comparisons</dt><dd>{number(summary['inconclusive_instances'])}</dd></div></dl></div><details class="family-breakdown"><summary>All family results &amp; raw trial records</summary><div class="table-scroll" tabindex="0" role="region" aria-label="Per-family benchmark results"><table><caption>Detected mutant runs per method</caption><thead><tr><th scope="col">Family</th><th scope="col">Random</th><th scope="col">Boundary</th><th scope="col">Benign fixture</th><th scope="col">Raw records</th></tr></thead><tbody>{family_rows}</tbody></table></div></details><div class="download-row">{links}</div><div class="limitations"><h3>What these results can tell you</h3><p>{esc(summary['interpretation'])}</p><ul><li>The families are hand-authored synthetic regression examples, not a representative sample of real SQL workloads. No model is evaluated.</li><li>Seed repeats revisit the same tasks. They are not independent tasks, and no population confidence interval is claimed.</li><li>Search is bounded by schema domains, row counts and execution limits. Neither strategy is query-aware or complete.</li><li>Equivalent controls do not estimate the false-positive rate over arbitrary SQL. Query errors and timeouts are inconclusive, never counterexamples.</li></ul></div></section>'''


def build_site(benchmark, catalog_path, output):
    benchmark, catalog_path, output = map(lambda p: Path(p).resolve(), (benchmark, catalog_path, output))
    if output == ROOT or output == TEMPLATES or any(p == output or output in p.parents for p in (benchmark, catalog_path, TEMPLATES / 'index.html')):
        raise ValueError('Output must not contain source inputs or templates')
    if output.exists() and not (output / MARKER).is_file():
        raise ValueError('Output exists and is not owned by this generator; choose a new directory')
    summary, catalog, cases, witnesses = validate_inputs(benchmark, catalog_path)
    demo = read_json(QUERY_AWARE_DEMO / 'witness.json')
    if demo.get('integrity_sha256') != digest({k:v for k,v in demo.items() if k != 'integrity_sha256'}):
        raise ValueError('Supplementary query-aware witness checksum mismatch')
    if demo.get('comparison', {}).get('status') != 'mismatch' or any(
            demo[k]['status'] != 'ok' for k in ('reference_observation','candidate_observation')):
        raise ValueError('Supplementary query-aware witness must record a successful mismatch')
    if not all((QUERY_AWARE_DEMO / name).is_file() for name in ('fixture.sql','report.html','README.md')):
        raise ValueError('Supplementary query-aware witness bundle incomplete')
    navigation, families = [], []
    for index, family in enumerate(summary['by_family'], 1):
        case, ident = cases[family['id']], family['id']
        navigation.append(f'<a class="family-link" href="#family-{ident}" data-family="{ident}"><span class="family-number">{index:02d}</span><span>{esc(case["title"])}</span><span class="nav-marker" aria-hidden="true">↗</span></a>')
        families.append(render_family(case, family, witnesses.get(ident), index))
    manifest = read_json(benchmark / 'manifest.json') if (benchmark / 'manifest.json').is_file() else {}
    context = {'NAVIGATION': ''.join(navigation), 'FAMILIES': ''.join(families), 'BENCHMARK': render_benchmark(summary, benchmark),
               'FAMILY_COUNT': number(summary['families']), 'WITNESS_COUNT': number(len(witnesses)),
               'COMPARISON_COUNT': number(summary['matched_budget_instance_evaluations']),
               'CONTROL_MISMATCHES': number(summary['control_mismatches']), 'TOOL_VERSION': esc(summary['tool_version']),
               'SQLITE_VERSION': esc(manifest.get('sqlite_version', 'recorded in witness')), 'CATALOG_HASH': esc(summary['catalog_sha256']), 'REPO': REPO}
    document = (TEMPLATES / 'index.html').read_text(encoding='utf-8')
    for key, value in context.items():
        document = document.replace('{{' + key + '}}', value)
    if re.search(r'\{\{[A-Z_]+\}\}', document):
        raise ValueError('Unresolved template token')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Only generated files are replaced, and only after a complete successful build.
    with tempfile.TemporaryDirectory(prefix='.querywitness-build-', dir=output.parent) as temp:
        staged = Path(temp) / 'dist'
        staged.mkdir()
        (staged / 'index.html').write_text(document, encoding='utf-8')
        (staged / MARKER).write_text('Generated by scripts/build_demo.py\n', encoding='utf-8')
        for filename in ('styles.css', 'app.js', 'favicon.svg'):
            shutil.copyfile(TEMPLATES / filename, staged / filename)
        shutil.copytree(QUERY_AWARE_DEMO, staged / 'query-aware-example')
        downloads = staged / 'downloads'
        downloads.mkdir()
        for filename in ('summary.json', 'manifest.json', 'REPORT.md'):
            if (benchmark / filename).is_file():
                shutil.copyfile(benchmark / filename, downloads / filename)
        shutil.copyfile(catalog_path, downloads / 'catalog.json')
        for ident in witnesses:
            target = downloads / 'witnesses' / ident
            target.mkdir(parents=True)
            for filename in ('witness.json', 'fixture.sql', 'report.html'):
                shutil.copyfile(benchmark / 'witnesses' / ident / filename, target / filename)
        for family in summary['by_family']:
            source = benchmark / 'raw' / (family['id'] + '.jsonl')
            if source.is_file():
                (downloads / 'raw').mkdir(exist_ok=True)
                shutil.copyfile(source, downloads / 'raw' / source.name)
        backup = None
        if output.exists():
            backup = Path(temp) / 'previous'
            output.rename(backup)
        try:
            staged.rename(output)
        except OSError:
            if backup is not None:
                backup.rename(output)
            raise
    return {'output': str(output), 'families': summary['families'], 'witnesses': len(witnesses), 'comparisons': summary['matched_budget_instance_evaluations']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', type=Path, default=ROOT / 'benchmarks/v1')
    parser.add_argument('--catalog', type=Path, default=ROOT / 'src/querywitness/data/catalog.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'site/dist')
    args = parser.parse_args()
    try:
        print(json.dumps(build_site(args.benchmark, args.catalog, args.output), indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f'Explorer build failed: {error}\n')


if __name__ == '__main__':
    main()
