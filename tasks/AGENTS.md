# Task Authoring Conventions

This file applies to `tasks/`. Follow these conventions when adding or organizing cases. The [task guide](../docs/tasks.md) owns protocol details; consult the [tools guide](../docs/tools.md) for tool environments. Use the task guide to distinguish candidate assets from executable benchmark tasks; a complete directory alone does not establish readiness.

## One Circuit per Directory

Place each case in `<collection>/cases/<circuit>/`, with `case.toml` as its single configuration entry point and the collection's `catalog.toml` as an index. Organize responsibilities around "problem, materials, tools → submitted answer → scoring" without creating a directory for every role.

| Role | Location and requirements |
|---|---|
| Problem | Write `problem.md` in English, using tables where practical for interfaces, tool usage, submission requirements, and scoring conditions. It must explain what to build, how to submit it, and how it will be judged. |
| Materials | Store the authoritative netlist, simulation testbench, and other required inputs in `materials/`. The testbench is a material. Declare delivered files explicitly in `[task.inputs]`. |
| Tools | Put tool descriptions and usage in `problem.md`, and evaluator backend bindings in `[toolchain]` in `case.toml`. Reuse framework resources for shared tools and PDKs. |
| Answer | Define the GDS delivery contract in `[task.output]` in `case.toml`; the framework freezes the model's explicit submission. Keep the maintainer's passing witness in `reference/` to demonstrate feasibility. |
| Scoring | Disclose all evaluation steps, operating conditions, measurement methods, limits, and result decisions in `problem.md`. Define structured constraints and evaluation in `[task.constraints]` and `[task.evaluation]` in `case.toml`. |
| Sources and modifications | Record the circuit source, upstream version and license, original asset issues, reasons and details of changes, validation results, and scope in `README.md`. |

Keep the directory compact: consolidate tool instructions, constraints, and scoring configuration in the files above instead of separate `tools/README.md`, `tools/toolchain.toml`, `constraints.json`, or `scoring/plan.toml` files. Keep development history in Git and temporary outputs under `build/`, following repository conventions; do not create `maintenance/`. Deliver a repaired reference layout as a ready-to-use GDS, with its rationale in the README, without requiring a repair generator first.

## Public Rules and Reference Isolation

- Keep the problem text consistent with the structured definitions in `case.toml`. Publish those same constraints and evaluation definitions through `/protocol/task.json` at runtime instead of maintaining another configuration copy.
- A standard solve receives only declared inputs and approved tool resources. Keep the full case directory, host tool bindings, source records, and reference answers outside delivered materials. Read the [input isolation and historical asset exclusion checklist](../docs/tasks.md#input-isolation) before source selection.
- A reference witness demonstrates feasibility; it is not the only answer, an optimum, or a scoring denominator. Apply the declared success conditions and metrics. Adding a weighted aggregate score requires an explicit scoring design decision.

## Changes and Validation

- When reorganizing files, update configuration paths, input digests, and documentation links, then verify task loading and delivered materials. Preserve circuit and scoring semantics during reorganization and translation.
- Present a concrete proposal for user decision before making an unauthorized key choice about circuit repairs, DRC disposition, performance limits, or qualification scope. Continue implementation that is already authorized.
- Base qualification claims on recorded scope and real validation. DRC/LVS alone does not establish full task success; post-layout metrics must have explicit limits and come from PEX of the candidate GDS. Consult [qualification](../docs/tasks.md#qualification) for requirements and the comparator's approved scope; case-specific deferrals are not general exemptions.
- Run affected checks from the [verification matrix](../CONTRIBUTING.md#verification). Follow the [test conventions](../tests/AGENTS.md) when changing tests. Documentation cleanup does not require new directory snapshots or fixed file-count tests.
