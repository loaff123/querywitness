"""Run the exact pinned upstream fixture loader and simplify helper in isolation.

Only top-level helper function nodes and the literal TestOptimizer.setUp schema
are compiled. This avoids importing DuckDB/pandas and running unrelated tests,
without reimplementing or modifying the helper. No QueryWitness code is loaded.
"""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import sqlglot
from sqlglot import exp, optimizer, parse_one
from sqlglot.optimizer.annotate_types import annotate_types

helper_path = root / 'tests' / 'helpers.py'
spec = importlib.util.spec_from_file_location('pinned_helpers', helper_path)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
source_path = root / 'tests' / 'test_optimizer.py'
source = source_path.read_text()
tree = ast.parse(source)
funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('simplify', 'parse_and_optimize')]
assert len(funcs) == 2
namespace = {'optimizer': optimizer, 'parse_one': parse_one, 'annotate_types': annotate_types}
exec(compile(ast.Module(body=funcs, type_ignores=[]), str(source_path), 'exec'), namespace)
klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TestOptimizer')
setup = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == 'setUp')
assignment = next(n for n in setup.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == 'schema' for t in n.targets))
schema = eval(compile(ast.Expression(assignment.value), str(source_path), 'eval'), {'exp': exp})
fixtures = list(helper.load_sql_fixture_pairs('optimizer/simplify.sql'))
request = json.load(sys.stdin)
outputs = []
for fixture in request.get('evaluate', []):
    meta, sql, expected = fixture
    assert not set(meta) - {'dialect'}, ('unhandled upstream metadata', meta)
    dialect = meta.get('dialect')
    kwargs = {'schema': schema}
    if dialect:
        kwargs['dialect'] = dialect
    optimized = namespace['parse_and_optimize'](namespace['simplify'], sql, dialect, **kwargs)
    outputs.append(optimized.sql(pretty=False, dialect=dialect))
print(json.dumps({'fixtures': fixtures, 'outputs': outputs, 'schema': schema, 'schema_source': ast.get_source_segment(source, assignment),
                  'sqlglot_module': str(Path(sqlglot.__file__).relative_to(root)),
                  'helper_nodes': [{ 'name': f.name, 'line_start': f.lineno, 'line_end': f.end_lineno,
                    'source_sha256': hashlib.sha256(ast.get_source_segment(source, f).encode()).hexdigest()} for f in funcs]}, indent=2, default=lambda value: {'sqlglot_ast_sql': value.sql(), 'sqlglot_ast_repr': repr(value)}))
