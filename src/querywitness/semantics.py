"""Fail-closed SQLGlot AST guardrails for an intentionally narrow SQLite subset.

SQL is parsed only for inspection, never rewritten. SQLite remains the actual
execution authority. Passing this guard is not a proof of determinism.
"""
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

PARSER_VERSION = sqlglot.__version__


def is_aggregate(node):
    # SQLite MIN/MAX are scalar with two or more arguments.
    if isinstance(node,(exp.Min,exp.Max)) and node.expressions: return False
    return isinstance(node,exp.AggFunc) or (isinstance(node,exp.Anonymous) and node.name.lower()=="total")


def scope_nodes(node):
    yield node
    for child in node.iter_expressions():
        if not isinstance(child,(exp.Query,exp.Subquery,exp.CTE)):
            yield from scope_nodes(child)


def column_key(column):
    return tuple(part.name.lower() for part in column.parts)


def parse_supported(sql):
    try: statements=sqlglot.parse(sql,read='sqlite')
    except (SqlglotError,RecursionError,ValueError) as error:
        return None,'SQL is outside the supported parser subset: '+str(error)[:300]
    if len(statements)!=1 or not isinstance(statements[0],exp.Query):
        return None,'Only one SELECT/CTE query is supported'
    tree=statements[0]
    stack=[(tree,0)];count=0
    while stack:
        node,depth=stack.pop();count+=1
        if count>4096 or depth>80:
            return None,'SQL syntax tree exceeds 4096 nodes or depth 80'
        stack.extend((child,depth+1) for child in node.iter_expressions())
    if tree.find(exp.Collate):
        return None,'Explicit collations are excluded to avoid representation and ordering ambiguity'
    if tree.find(exp.Limit,exp.Offset,exp.Window):
        return None,'LIMIT/OFFSET and window queries are excluded by the query contract'
    for subquery in tree.find_all(exp.Subquery):
        if not isinstance(subquery.parent,(exp.From,exp.Join,exp.In,exp.CTE)):
            return None,'Scalar or unclassified subqueries are excluded; use a derived relation, IN, or EXISTS'
    for select in tree.find_all(exp.Select):
        group=select.args.get('group')
        regions=list(select.expressions)+[v for k in ('having','order') if (v:=select.args.get(k)) is not None]
        if group is None and not any(is_aggregate(n) for region in regions for n in scope_nodes(region)):
            continue
        allowed=set()
        if group is not None:
            for item in group.expressions:
                if not isinstance(item,exp.Column) or item.is_star:
                    return None,'GROUP BY requires explicit simple columns; aliases, ordinals, and expressions are excluded'
                allowed.add(column_key(item))
        aliases={e.alias.lower():e.this for e in select.expressions if isinstance(e,exp.Alias)}
        def check(node,resolve_alias=False):
            if is_aggregate(node): return None
            if isinstance(node,exp.Filter) and is_aggregate(node.this): return None
            if isinstance(node,(exp.Query,exp.Subquery)):
                return 'Subqueries in aggregate projections, HAVING, or ORDER BY are excluded'
            if isinstance(node,exp.Star): return 'Bare wildcard in aggregate projection excluded'
            if isinstance(node,exp.Column):
                key=column_key(node)
                if resolve_alias and len(key)==1 and key[0] in aliases:
                    return check(aliases[key[0]],False)
                if key not in allowed: return 'Bare non-grouped column in aggregate query: '+node.sql(dialect='sqlite')
                return None
            for child in node.iter_expressions():
                reason=check(child,False)
                if reason:return reason
            return None
        for region in regions:
            if isinstance(region,exp.Order):
                for term in region.expressions:
                    reason=check(term.this,isinstance(term.this,exp.Column))
                    if reason:return None,reason
            else:
                reason=check(region,False)
                if reason:return None,reason
    return tree,None


def ordered_reason(sql):
    tree,reason=parse_supported(sql)
    if reason:return reason
    # To avoid tie ambiguity, require ordering by every projected value. This is
    # conservative and excludes SELECT *, compound queries, and implicit order.
    if not isinstance(tree,exp.Select) or any(e.is_star for e in tree.expressions):
        return 'Ordered policy requires a simple SELECT with explicit projections'
    order=tree.args.get('order')
    if order is None:return 'Ordered policy requires ORDER BY covering every projected value'
    projections=[e.this if isinstance(e,exp.Alias) else e for e in tree.expressions]
    alias_names=[e.alias.lower() for e in tree.expressions if isinstance(e,exp.Alias)]
    if len(alias_names)!=len(set(alias_names)):
        return 'Ordered policy excludes duplicate output aliases'
    aliases={e.alias.lower():i for i,e in enumerate(tree.expressions) if isinstance(e,exp.Alias)}
    covered=set()
    for item in order.expressions:
        expression=item.this
        if isinstance(expression,exp.Literal) and not expression.is_string:
            try:index=int(expression.this)-1
            except ValueError:continue
            if 0<=index<len(projections):covered.add(index)
        elif isinstance(expression,exp.Column) and not expression.table and expression.name.lower() in aliases:
            covered.add(aliases[expression.name.lower()])
        else:
            for i,projection in enumerate(projections):
                if expression==projection:covered.add(i)
    return None if len(covered)==len(projections) else 'ORDER BY must cover every projected value to exclude ambiguous ties'
