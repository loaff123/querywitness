"""Opt-in FK-closure reduction and a separately bounded, read-only audit.

The schema and guarded SQL engine remain the final acceptance gates. Graph
reachability changes only which row occurrences are proposed for deletion.
"""

from __future__ import annotations

from copy import deepcopy
import math
import time

from .artifacts import closure_context, closure_scope_sha256
from .compare import compare_results
from .engine import ExecutionLimits, execute
from .fk_graph import (
    ClosureDeadlineExceeded,
    build_fk_graph,
    deletion_closure,
    materialize,
)
from .schema import Schema


class _Run:
    """One cooperative deadline and query-pair budget, including reproduction."""

    def __init__(
        self, schema, reference, candidate, policy, limits, max_checks, seconds
    ):
        if type(max_checks) is not int or not 1 <= max_checks <= 10000:
            raise ValueError("Invalid reduction check budget")
        if (
            type(seconds) not in (float, int)
            or not math.isfinite(seconds)
            or not 0 < seconds <= 300
        ):
            raise ValueError("Invalid reduction time budget")
        if policy not in ("bag", "set", "ordered"):
            raise ValueError("Unknown comparison policy")
        self.deadline = time.monotonic() + seconds
        self.schema, self.reference, self.candidate, self.policy = (
            schema,
            reference,
            candidate,
            policy,
        )
        self.limits = limits or ExecutionLimits()
        self.max_checks, self.seconds = max_checks, seconds
        self.checks = self.query_executions = self.inconclusive = 0

    def guard(self, stage):
        if time.monotonic() >= self.deadline:
            raise ClosureDeadlineExceeded(stage)

    def evaluate(self, data):
        self.guard("validation")
        # An invalid least-closure proposal or database load is a consistency
        # failure. Never disguise it as evidence against a deletion.
        self.schema.validate_instance(data)
        self.guard("validation")
        if self.checks >= self.max_checks:
            raise ClosureDeadlineExceeded("check_budget")
        self.checks += 1
        self.guard("reference_execution")
        left = execute(
            self.schema, data, self.reference, self.limits, policy=self.policy
        )
        self.query_executions += 1
        self.guard("reference_execution")
        right = execute(
            self.schema, data, self.candidate, self.limits, policy=self.policy
        )
        self.query_executions += 1
        self.guard("candidate_execution")
        result = compare_results(left, right, self.policy)["status"]
        self.guard("comparison")
        if result == "inconclusive":
            self.inconclusive += 1
        return result

    def proposal(self, graph, alive, seeds):
        self.guard("closure")
        removed = deletion_closure(
            graph, alive, frozenset(seeds), deadline=self.deadline
        )
        remaining = alive - removed
        data = materialize(graph, remaining, deadline=self.deadline)
        self.guard("materialize")
        return remaining, data

    def counts(self):
        return {
            "checks": self.checks,
            "query_executions": self.query_executions,
            "inconclusive_checks": self.inconclusive,
            "max_checks": self.max_checks,
            "seconds": self.seconds,
        }


def _copy_input(run, instance):
    # Full validation and deepcopy are cooperative phases, not process-level
    # isolation. Bracketing retains the existing schema implementation intact.
    run.guard("initial_validation")
    run.schema.validate_instance(instance)
    run.guard("initial_validation")
    current = deepcopy(instance)
    run.guard("initial_copy")
    return current


def minimize_fk_closure(
    schema: Schema,
    instance: dict,
    reference: str,
    candidate: str,
    policy="bag",
    max_checks=500,
    seconds=30.0,
    limits: ExecutionLimits | None = None,
) -> dict:
    run = _Run(schema, reference, candidate, policy, limits, max_checks, seconds)
    current = instance
    status, stage = "minimized", None
    reproduced = complete = False
    roots_checked = scan_inconclusive = 0
    try:
        current = _copy_input(run, instance)
        initial = run.evaluate(current)
        if initial == "agreement":
            status = "not_a_witness"
        elif initial == "inconclusive":
            status = "initial_check_inconclusive"
        else:
            reproduced = True
            graph = build_fk_graph(schema, current, deadline=run.deadline)
            run.guard("graph")
            alive = frozenset(range(len(graph.coordinates)))
            for name in graph.tables:
                n = 2
                while True:
                    run.guard("chunk_schedule")
                    rows = [
                        ident
                        for ident in sorted(alive)
                        if graph.coordinates[ident][0] == name
                    ]
                    if not rows:
                        break
                    width = max(1, math.ceil(len(rows) / n))
                    changed = False
                    for begin in range(0, len(rows), width):
                        remaining, proposal = run.proposal(
                            graph, alive, rows[begin : begin + width]
                        )
                        if run.evaluate(proposal) == "mismatch":
                            current, alive = proposal, remaining
                            n, changed = max(2, n - 1), True
                            break
                    if changed:
                        continue
                    if n >= len(rows):
                        break
                    n = min(len(rows), n * 2)
            while True:
                run.guard("final_scan")
                roots_checked = scan_inconclusive = 0
                changed = False
                for root in sorted(alive):
                    remaining, proposal = run.proposal(graph, alive, (root,))
                    outcome = run.evaluate(proposal)
                    if outcome == "mismatch":
                        current, alive = proposal, remaining
                        roots_checked = scan_inconclusive = 0
                        changed = True
                        break
                    roots_checked += 1
                    scan_inconclusive += outcome == "inconclusive"
                if not changed:
                    run.guard("final_scan")
                    complete = True
                    break
            if run.inconclusive:
                status = "inconclusive_reduction"
    except ClosureDeadlineExceeded as error:
        status, stage = "budget_exhausted", error.stage
    # Reporting is necessarily possible after budget exhaustion. No query runs
    # here; this copy keeps a pre-reproduction timeout from aliasing user input.
    current = deepcopy(current)
    context = closure_context()
    scope = closure_scope_sha256(
        schema, current, reference, candidate, policy, run.limits, context=context
    )
    if status != "budget_exhausted" and time.monotonic() >= run.deadline:
        status, stage = "budget_exhausted", "metadata"
    minimal = reproduced and complete and not run.inconclusive and status == "minimized"
    return {
        "status": status,
        "instance": current,
        "deletion_mode": "fk-closure",
        **context,
        "scope_sha256": scope,
        **run.counts(),
        "initial_rows": sum(map(len, instance.values())),
        "final_rows": sum(map(len, current.values())),
        "witness_reproduced": reproduced,
        "row_1_minimal": minimal,
        "fk_closure_1_minimal": minimal,
        "final_scan_complete": complete,
        "final_scan_roots_checked": roots_checked,
        "final_scan_inconclusive": scan_inconclusive,
        "budget_stage": stage,
        "guarantee": (
            "No singleton least-FK-closure deletion preserves a successful mismatch; "
            "not a global minimum"
            if minimal
            else "Minimality not established; see witness_reproduced and status"
        ),
    }


def check_fk_closure_minimality(
    schema: Schema,
    instance: dict,
    reference: str,
    candidate: str,
    policy="bag",
    *,
    limits: ExecutionLimits,
    max_checks=500,
    seconds=30.0,
) -> dict:
    """Audit each singleton closure of this exact instance without reducing it."""
    run = _Run(schema, reference, candidate, policy, limits, max_checks, seconds)
    status, stage, reason, refutation = "verified", None, None, None
    reproduced = complete = False
    checked = 0
    try:
        current = _copy_input(run, instance)
        initial = run.evaluate(current)
        if initial == "agreement":
            status, reason = "refuted", "not_a_witness"
        elif initial == "inconclusive":
            status, reason = "inconclusive", "initial_check_inconclusive"
        else:
            reproduced = True
            graph = build_fk_graph(schema, current, deadline=run.deadline)
            alive = frozenset(range(len(graph.coordinates)))
            for root in sorted(alive):
                remaining, proposal = run.proposal(graph, alive, (root,))
                outcome = run.evaluate(proposal)
                checked += 1
                if outcome == "mismatch":
                    table, index = graph.coordinates[root]
                    refutation = {
                        "seed": {"table": table, "index": index},
                        "removed_rows": len(alive) - len(remaining),
                    }
                    status = "refuted"
                    break
            else:
                run.guard("final_scan")
                complete = True
                if run.inconclusive:
                    status = "inconclusive"
    except ClosureDeadlineExceeded as error:
        status, stage = "budget_exhausted", error.stage
    result = {
        "status": status,
        **run.counts(),
        "witness_reproduced": reproduced,
        "final_scan_complete": complete,
        "final_scan_roots_checked": checked,
        "budget_stage": stage,
    }
    if reason is not None:
        result["reason"] = reason
    if refutation is not None:
        result.update(refutation)
    return result
