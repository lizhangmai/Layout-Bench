# Test Conventions

This file applies to `tests/`. See [CONTRIBUTING](../CONTRIBUTING.md#verification) for test commands and validation scope. The [task guide](../docs/tasks.md) defines task and scoring semantics; the [running guide](../docs/running.md) defines execution and statistics.

## What Makes a Good Test

Before writing or changing a test, identify the contract it protects, a real defect that would make it fail, and the basis for its expected result. Name the function after the behavior under test. Briefly explain physical formulas, tolerances, and specific regression cases nearby.

- **Expectations are independent of the implementation.** Derive them from public interfaces, approved task requirements, independent calculations, or known regressions. Generating expectations with the function under test, comparing an expression with itself, or copying current output cannot establish correctness.
- **Reasonable refactoring remains possible.** When external behavior is unchanged, moving files, adjusting internal functions, or adding valid cases should generally leave tests intact. Assert exact paths, ordering, or counts only when they are part of the contract.
- **Assertions distinguish correct from incorrect behavior.** Check relevant results after a successful call. Scoring tests verify decisions, error tests verify the expected failure, and isolation tests verify that out-of-scope content is inaccessible. Limit assertions to the behavior the test claims to protect.
- **Cost matches value.** Prioritize scoring, input isolation, evidence integrity, error propagation, and real tool behavior. Test counts and coverage cannot replace that evidence; reversible documentation or directory changes usually need no dedicated new tests.

## Inputs, Expectations, and Test Doubles

- Use minimal synthetic inputs for generic loader, CLI, and protocol tests, preferably through public entry points. Use real circuits for their input consistency, qualification, and EDA checks; keep generic tests independent of cases such as the comparator.
- Use constants for explicit test inputs, protocol values, approved limits, or justified physical expectations. Cross-check declared inventories and case counts against actual contents instead of maintaining another copy of the current inventory.
- Compare independently declared digests with actual bytes. This verifies asset identity, not DRC, LVS, or simulation. Derive scoring-limit expectations from approved requirements rather than reading a limit from the configuration under test and comparing it with itself.
- Put test doubles at external I/O, tool, or execution boundaries while retaining the real implementation of the behavior under test. Assert necessary boundary arguments and effects. Verify complete internal call ordering only when that ordering affects correctness.
- Construct input variants with explicit parameters or small fixtures, rather than replacing Python source fragments. Shared helpers should extract repeated setup without becoming another general-purpose testing framework.
- Keep unit tests independent of optional upstream checkouts, Docker, and paid services. Put real tool and upstream file checks in the integration layer and state their environment requirements. Source surveys and validation still follow the [asset exclusion checklist](../docs/tasks.md#input-isolation).

## Cleanup and Validation

1. Assess individual assertions: remove self-comparisons, existence checks for completed migrations, duplicate inventories, and unjustified snapshots. Retain useful behavioral assertions in the same function.
2. When a test fails, check the requirements and implementation first. Update expectations only when the contract has changed; copying the new implementation to restore a passing result is not a fix. Obtain task authorization before changing scoring rules or qualification scope.
3. Confirm that rewrites preserve useful defect detection. If needed, inject a corresponding defect into a temporary copy to check an assertion. There is no need to replace every removed assertion with a new test or routinely expand counterexample and repeatability suites.
4. Run affected tests and the checks required by the contribution guide. Report the behaviors verified, environment checks not run, and Git status. A passing test count does not establish circuit feasibility or judge correctness.
