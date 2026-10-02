# Related work and contribution boundaries

Generating databases to distinguish SQL queries and reducing failure-inducing inputs are established ideas. QueryWitness is a small engineering implementation of a bounded local workflow; the comparison below locates its scope. It is not a comprehensive literature review, a novelty assessment, or a reproduced performance comparison.

Primary sources were checked for this release on 2026-09-30. Findings about other systems below describe their stated goals and methods, not independent validation of their results.

| Work | Goal and mechanism in its primary source | Relation to QueryWitness |
| --- | --- | --- |
| [Semantic Evaluation for Text-to-SQL with Distilled Test Suites](https://arxiv.org/abs/2010.02840), Zhong, Yu, and Klein, EMNLP 2020; [code](https://github.com/taoyds/test-suite-sql-eval) | Approximates semantic accuracy using a small suite selected from generated databases to cover gold-query behavior | Direct prior art for going beyond one database. QueryWitness does not implement suite distillation or evaluate text-to-SQL models |
| [Data Generation for Testing and Grading SQL Queries](https://arxiv.org/abs/1411.6704), Chandra et al.; [journal record](https://doi.org/10.1007/s00778-015-0395-0) | Extends XData's mutation-killing database generation and applies it to SQL grading | Direct prior art for distinguishing correct queries from mutations. QueryWitness's sampler is finite-domain and query-independent, without comparable synthesis guarantees |
| [ParSEval: Plan-aware Test Database Generation for SQL Equivalence Evaluation](https://www.vldb.org/pvldb/vol18/p4750-miao.pdf), Chen et al., PVLDB 18(11), 2025; [code](https://github.com/sfu-db/ParSEval) | Models logical-query-plan operator behavior and uses execution-path/branch-coverage ideas to generate databases | Closely related query-pair evaluation. QueryWitness does not analyze logical plans or claim ParSEval's evaluated coverage or speed |
| [VeriEQL](https://github.com/VeriEQL/VeriEQL), He et al., OOPSLA 2024; [counterexample checker](https://github.com/VeriEQL/VeriEQL/blob/main/dbms_checker/counterexample_checker.py) | Bounded model checking for complex SQL with integrity constraints; the repository includes a MySQL checker that reexecutes counterexamples and checks constraints | Direct prior art for constraint-aware counterexamples and runtime checking. QueryWitness samples concrete SQLite instances; it has neither a symbolic proof procedure nor VeriEQL's bounded verification result |
| [Explaining Wrong Queries Using Small Examples](https://arxiv.org/abs/1904.04467), Miao, Roy, and Yang, SIGMOD 2019; [author-hosted paper](https://www.miaozhengjie.com/assets/pdf/ratest-sigmod19.pdf) | Studies smallest counterexample subinstances for query disagreements, including provenance/constraint-solver methods and a deployed relational-algebra teaching tool (RATest) | Direct prior art for small database explanations. QueryWitness's deletion search only establishes schema-relative row-1-minimality after a completed decisive scan; it does not implement those smallest-counterexample algorithms or claim a new explanation concept |
| [SQLancer](https://github.com/sqlancer/sqlancer), project documentation and linked papers | Finds DBMS implementation bugs using generated schemas/data/queries and multiple oracles; includes experimental reduction | Related database testing and failure reduction. QueryWitness holds the SQLite engine fixed and compares user-supplied query pairs; it is not a replacement DBMS fuzzer |
| [Simplifying and Isolating Failure-Inducing Input](https://www.st.cs.uni-saarland.de/papers/tse2002/), Zeller and Hildebrandt, IEEE TSE 28(2), 2002 | Establishes delta-debugging methods for simplifying and isolating failure-inducing input | Methodological prior art for chunk deletion. QueryWitness restricts deletion to schema-valid database rows and separately verifies its row-1-minimal condition |
| [DS-1000](https://ds1000-code-gen.github.io/), Lai et al., project page | Evaluates generated data-science code across seven Python libraries using execution-based and other criteria | Broader evaluation context, not direct SQL counterexample tooling. QueryWitness does not run DS-1000 or use its tasks, scale, human effort, or model results as evidence |

## Bounded contribution claim

The concrete deliverable is an inspectable Python/SQLite package connecting an explicit schema contract, restricted execution, exact numeric-aware bag/set/ordered comparison, deterministic sampling, constraint-preserving row reduction, and replayable artifacts. Its accompanying 12-family synthetic catalog and equal-trial-budget runner make this implementation's behavior inspectable under a declared protocol.

The practical hypothesis is that a small retained database and exact observations can make some query disagreements easier to understand and reproduce. The current release does not measure user comprehension, debugging time, real-world adoption, research influence, or superiority to the systems above. A catalog result cannot validate those hypotheses.

Three guarantees must remain distinct: formal equivalence for a stated language/theory, exhaustive symbolic checking within a stated finite model bound, and agreement on a sampled finite set of concrete instances. QueryWitness provides the third kind of testing, plus concrete successful mismatch witnesses. Neither larger seed budgets nor output minimization turn its no-witness result into either of the first two. Similarly, row-1-minimality under schema-valid deletion is weaker than global smallest-cardinality counterexample selection.

## What is not claimed

- No invention of differential SQL testing, mutation killing, test suites, or delta debugging
- No proof that an accepted query is deterministic, correct, safe against every exploit, or equivalent to another query
- No general completeness guarantee for the generator, solver-based synthesis, or global-minimum witness guarantee
- No external-system benchmark, SOTA ranking, human-reviewed dataset, LLM score, or publication acceptance
- No exhaustive name/trademark clearance or guarantee of novelty

Future comparative work would need compatible SQL/schema/comparison contracts, installed baseline versions, matched resource accounting, prespecified workloads, and published failures. Citation alone is not a baseline experiment. Sources linked here retain their own licenses; the original synthetic catalog is not a redistribution of those datasets or implementations.


## FK-closure deletion

The opt-in closure operator is a small constraint-preserving extension of ordinary
delta-debugging deletion. It is not a new minimization theory. [RATest (SIGMOD
2019)](https://www.miaozhengjie.com/assets/pdf/ratest-sigmod19.pdf) already studies
smallest counterexample subinstances and encodes FK implications in a
provenance/solver formulation. QueryWitness instead traverses concrete reverse-FK
dependencies under its unique-parent schema contract. Its final singleton-closure
scan establishes only operation-relative 1-minimality, not RATest-style optimality
or comparable performance. The motivating example and non-global counterexample
are in [the method](ALGORITHM.md#foreign-key-closure-reduction-opt-in).
