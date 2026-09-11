# Test Conventions

Core principles for writing tests, applicable to any project.

1. **Protect a contract, not the implementation.** Every test names a behavior, protects a contract, and has a real defect that would make it fail. Derive expectations independently — from requirements, public interfaces, or separate calculation. Comparing code with itself or copying current output proves nothing.
2. **Declare each value once.** Every limit, digest, count, or option has exactly one authoritative home: the configuration, the protocol, or the documentation. A test that restates a declared value as a literal locks a second copy — it breaks on legitimate changes and catches no defect. Read the value from its authority at runtime and assert behavior or relationships instead. When two records must agree, check them against each other; a third copy in the test adds nothing.
3. **Keep refactoring cheap.** Assert only what the contract guarantees. Exact paths, ordering, counts, and internal call sequences are off-limits unless the contract specifies them.
4. **Fake only the boundaries.** Test doubles belong at external I/O, tools, and execution; the behavior under test runs for real. Prefer minimal synthetic inputs through public entry points; use real data only where the check depends on it.
5. **A failing test is a question, not noise.** Check requirements and implementation first. Update expectations only when the contract has changed — copying new output to restore a pass is not a fix. Remove assertions that no longer distinguish correct from incorrect.
