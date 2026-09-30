# Archived generator debugging evidence

This is the actual first 6,144-comparison run, before fixing the generator's nullable-foreign-key blind spot. It is debugging evidence, not a preregistered independent experiment or an external benchmark. The original results are retained unchanged: random 85/96 and boundary 88/96 detected family-runs; both missed `not_in_null` entirely.

The generator originally overwrote a sampled NULL with a parent key whenever parent rows existed. Consequently it never built the legal database needed for this catalog family. The final generator preserves any sampled NULL component under SQLite MATCH SIMPLE foreign-key semantics and still validates every instance.

`source_snapshot/` contains the exact core Python files and catalog used for this run; `SHA256.json` records their SHA-256 digests. Reproduce using the pinned SQLGlot dependency and Python 3.11+:

```
python scripts/reproduce_ablation.py --out /tmp/querywitness-ablation
```

The script verifies the archived source digests and imports that snapshot in an isolated temporary directory. Compare seeds, statuses, and instance hashes in raw JSONL; elapsed time and runtime metadata vary. The corrected run in `../v1/` is development-set performance: these 12 tasks were used to diagnose this generator issue. No independence or statistical-generalization claim follows from the improvement.
