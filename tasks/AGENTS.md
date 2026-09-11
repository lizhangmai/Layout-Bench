# Task Authoring Conventions

Applies to `tasks/`. The [task guide](../docs/tasks.md) owns protocol details; the [tools guide](../docs/tools.md) owns tool environments. A complete directory alone does not establish task readiness — use the task guide to distinguish candidate assets from executable benchmark tasks.

## One Circuit per Directory

Cases are grouped by PDK, then by source collection: each case lives in `<pdk>/<collection>/cases/<circuit>/`, with `case.toml` as its single configuration entry and the collection's `catalog.toml` as index. The PDK directory's `pdk.toml` is the reviewed manifest of upstream tool and model files for that PDK, including the xschem export symbols referenced by case `source_export.pdk_profile`.

| Role | Location and requirements |
|---|---|
| Problem | `problem.md` in English, tables where practical: what to build, how to submit, how it is judged. |
| Materials | Authoritative netlist, simulation testbench, and other required inputs in `materials/` (the testbench is a material); declare delivered files in `[task.inputs]`. |
| Tools | Tool usage in `problem.md`; evaluator backend bindings in `[toolchain]` in `case.toml`. Reuse framework resources for shared tools and PDKs. |
| Answer | GDS delivery contract in `[task.output]`; the framework freezes the model's explicit submission. Keep the maintainer's passing witness in `reference/` to demonstrate feasibility. |
| Scoring | Disclose all evaluation steps, operating conditions, measurement methods, limits, and result decisions in `problem.md`; define them structurally in `[task.constraints]` and `[task.evaluation]`. |
| Sources | Circuit source, upstream version and license, original asset issues, reasons and details of changes, validation results, and scope in `README.md`. |

Keep the directory compact: consolidate tool instructions, constraints, and scoring configuration in the files above — no separate `tools/README.md`, `tools/toolchain.toml`, `constraints.json`, `scoring/plan.toml`, or `maintenance/`. Keep development history in Git and temporary outputs under `build/`. Deliver a repaired reference layout as a ready-to-use GDS with its rationale in the README, without requiring a repair generator first.

## Public Rules and Reference Isolation

- Keep `problem.md` consistent with the structured definitions in `case.toml`; publish them through `/protocol/task.json` at runtime instead of maintaining another configuration copy.
- A standard solve receives only declared inputs and approved tool resources; keep the full case directory, host tool bindings, source records, and reference answers outside delivered materials. Read the [input isolation and historical asset exclusion checklist](../docs/tasks.md#input-isolation) before source selection.
- A reference witness demonstrates feasibility; it is not the only answer, an optimum, or a scoring denominator. Apply the declared success conditions and metrics; adding a weighted aggregate score requires an explicit scoring design decision.

## Changes and Validation

- When reorganizing files, update configuration paths, input digests, and documentation links, then verify task loading and delivered materials. Preserve circuit and scoring semantics during reorganization and translation.
- Present a concrete proposal for user decision before making an unauthorized key choice about circuit repairs, DRC disposition, performance limits, or qualification scope; continue implementation that is already authorized.
- Base qualification claims on recorded scope and real validation. DRC/LVS alone does not establish full task success; post-layout metrics must have explicit limits and come from PEX of the candidate GDS. Consult [qualification](../docs/tasks.md#qualification) for requirements and the comparator's approved scope; case-specific deferrals are not general exemptions.
- Run affected checks from the [verification matrix](../CONTRIBUTING.md#verification); follow the [test conventions](../tests/AGENTS.md) when changing tests. Documentation cleanup does not require new directory snapshots or fixed file-count tests.
