# Contributing

Contributions should improve the correctness, inspectability, or reproducibility of the bounded local workflow. Begin with the [semantic contract](docs/CONTRACT.md), [method](docs/ALGORITHM.md), and [security policy](SECURITY.md). Discuss a broad semantic/API expansion before implementing it.

## Development checks

```sh
python -m venv .venv
. .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
python -m querywitness catalog --validate
python -m querywitness demo count_nullable --out contribution-demo
python -m querywitness replay contribution-demo/witness.json
```

Use a new output directory on each run. Run a clean wheel installation outside the repository as described in [REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md) for packaging changes. Record the environment when reporting a failure; SQLite differs across Python distributions.

## Change checklist

1. Add a failing regression test that captures the expected behavior before changing the implementation
2. Keep schema validation, actual SQLite constraints, and generated/reduced instances consistent; do not weaken a constraint to obtain a witness
3. Keep execution errors, timeouts, and unsupported cases inconclusive rather than relabeling them mismatches or agreements
4. Preserve explicit policy semantics, bounded-work behavior, and fail-closed exclusions; test bypasses as well as ordinary inputs
5. Verify reduction claims and replay behavior, including incomplete reduction and runtime drift
6. Update docs, versioned formats/provenance, and compatibility notes when observable behavior changes
7. Run the full suite and a relevant bounded benchmark; retain real negatives and failures, not just favorable examples

Do not broaden the function allowlist, authorize more SQL operations, or relax parser guards without a concrete need and adversarial tests. Never use private data as a regression fixture. Report sensitive vulnerabilities through the route in SECURITY.md.

## Catalog contributions

Provide the requirement and mechanism, supported schema with explicit domains where relevant, reference and mutant SQL, justified equivalent control, benign and revealing fixtures, and independently reasoned expected outputs. Keep a new semantic family distinct from a seeded variation of an existing family. Explain why the control is valid under the complete schema; do not infer its equivalence from a few passing examples.

Disclose authorship/provenance and licensing, including material AI assistance or reuse from another source. Do not label data human-reviewed without an actual documented human review. Do not copy third-party benchmark data or paper figures merely because a citation is present.

## Research reporting

Prespecify budgets and selection criteria when making comparisons. Report denominator, exact versions, method order, control outcomes, inconclusive results, and timing scope. Keep the single masking fixture separate from matched-budget generation. Do not treat repeated seeds as independent research tasks or claim a statistical false-positive rate from a few equivalent controls.

The project welcomes stronger independent oracles and broader held-out validation. Such work should be described as new evidence, without retroactively presenting the current synthetic catalog as representative or expert-reviewed.

## Pull requests and license

Keep changes focused and explain what behavior changes, how it was tested, and any remaining limitation. Avoid unrelated formatting or generated-file churn. Contributions are distributed under the repository's MIT license; submit only material you have permission to contribute. Citation metadata should use real identifiers and contributor attribution, never an invented DOI or publication.
