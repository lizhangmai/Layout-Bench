# Adding Tasks and Validating the Judge

See the [comparator case](../tasks/IHP-AnalogAcademy/cases/comparator/case.toml) for an executable task and its embedded toolchain, constraints, and evaluation plan. The selected public IHP and TO_Apr2025 cases are listed in [`tasks/IHP-AnalogAcademy/catalog.toml`](../tasks/IHP-AnalogAcademy/catalog.toml) and [`tasks/TO_Apr2025/catalog.toml`](../tasks/TO_Apr2025/catalog.toml); a case may be promoted only when the pinned upstream checkout already contains the reusable layout and corresponding physical evidence. Source review then freezes inputs, constraints, evaluation, tool bindings, and independent qualification. Models, budgets, repetitions, and access policy belong to the outer [run plan](running.md).

The catalog is an inventory index, not a shortcut around task qualification. A
`candidate` record becomes a benchmark task only after its authoritative
netlist, physical constraints, evaluation plan, and independent qualification
evidence are frozen. Qucs/RF schematics and testbenches remain explicitly
typed as `source-only` or `supporting-source`; they are not silently treated as
`netlist_to_gds` tasks. Each record is bound to the upstream submodule commit
and source digest, so updating the submodule requires a new source review.

IHP AnalogAcademy and TO_Apr2025 cases use one directory per circuit under
`tasks/<collection>/cases/<circuit>/`, with a single `case.toml` entry point.
The catalog's `config_path` locates the entry point; the full case ID and upstream
source paths remain in the manifest. File roles are declared by the manifest;
the loader does not require particular directory names.

### Problem, materials, tools, answer, and scoring

The [comparator case](../tasks/IHP-AnalogAcademy/cases/comparator/README.md)
provides a concrete entry point for this workflow:

| Role | Comparator location | Runtime responsibility |
|---|---|---|
| Problem | `problem.md` | Solver-facing objective, interface and acceptance requirements; declared as `inputs.description` |
| Materials | `materials/` | Authoritative netlist and public simulation testbench; declared inputs |
| Tools | Tool instructions in `problem.md`; `[toolchain]` in `case.toml` | The problem explains the shared EDA/PDK environment; the case binds evaluator backends on the host. Solver image, reviewed resources and harness come from the outer run configuration |
| Answer | `/workspace/output/final.gds`; maintainer witness in `reference/` | The solver explicitly submits a GDS snapshot; the reference demonstrates feasibility and is excluded from solver inputs |
| Scoring | Rules in `problem.md`; `[task.evaluation]` and `[task.constraints]` in `case.toml` | Public requirements, physical gates, candidate-derived RC and bounded simulation measurements; the evaluator produces `report.json` |

The comparator README records its circuit source, original issues, modification
rationale and validation summary. Its case directory contains only the current
problem, materials, tool instructions, case configuration and reference GDS;
development records remain in Git history and local `build/runs/` outputs.
`case.toml` defines one current scoring plan. These directory
names organize the case; `[task.inputs]` declares the files a solver
receives. The comparator materializes the problem, netlist and testbench; its problem
includes tool instructions and the complete scoring rules. Inline constraints and
evaluation are published in `/protocol/task.json` and supplied to the evaluator
from the same frozen definitions. The case configuration, reference GDS and source/modification README stay
outside solver inputs. Scoring reports task success
and declared metrics; introducing a scalar score is a separate benchmark design
decision. Other cases may retain their existing manifest-declared paths.

<a id="task-design"></a>

## 1. Confirm Sources and Published Content

Public tasks use public designs and open PDKs/EDAs approved for distribution, and publish their inputs, reference solution, and qualification materials. A reference solution is for debugging and demonstrating feasibility; it is neither the only answer nor an optimum or scoring denominator. A standard solve receives only declared inputs; debugging with reference materials must be distinguished from solving in an empty workspace.

An existing authoritative netlist can be frozen directly. When entering a case from a schematic, invoke the original tools on the files listed by the case TOML's `[source_export]` section and retain the untouched netlist, source-file digests, Git commit, actual image, and command. The current Xschem entry point is in the [tools guide](tools.md#source-preparation). Use a fixed PDK reader to cross-check the target circuit, device parameters, nets, and ports; a hand-copied CDL that matches a self-built layout does not establish fidelity to the source circuit.

<a id="asset-rights"></a>

### Sources, Licenses, and Visibility

Record the source, license, and permitted use and distribution scope separately for each design, PDK, EDA tool, model, and derived artifact. The framework's MIT license does not cover third-party assets; retain each license with its corresponding asset. A public package must preserve required license, copyright, and modification notices rather than summarizing all files under an upstream top-level license.

| Material | Storage and runtime visibility |
|---|---|
| Netlist, constraints, evaluation requirements, required testbench/model/description | Inputs declared by the case TOML's `[task]` section; readable by a standard Agent |
| Reference GDS, generators, qualification matrix, calibration, and counterexamples | Case-local maintainer materials; comparator keeps its reference GDS in `reference/` and its source, modifications and validation summary in `README.md`; downloadable for debugging but excluded from standard solve inputs |
| Preparation source records | May be referenced by `provenance`; not materialized for the Agent automatically |
| Process and tool materials | Separately reviewed resource bundles; do not mount a complete upstream checkout or repository |

Hidden tasks use only independently authored or authorized unpublished designs. Their inputs, reference solutions, qualification materials, and raw run evidence are held by the evaluator and do not enter public Git, images, or CI. Every requirement that affects the current task must be provided to the running Agent; hidden data must not become an undisclosed scoring rule. Restricted originals stay in approved environments. Private Git and zero-data-retention endpoints do not by themselves grant permission to store, process, or transmit the data. Bind the specific approval record through the [admission interface](admission.md).

<a id="task-configuration"></a>

## 2. Declare the case `[task]` section and Freeze Inputs

`benchmarking/tasks.py` loads the nested executable task using the existing schema-1 fields. For a public circuit case, those fields live under `[task]` in a schema-2 `kind = "layout_case"` file; standalone framework fixtures may still use the legacy schema-1 task file.

| Field | Meaning |
|---|---|
| `schema_version`, `kind` | Currently `1` and `netlist_to_gds`; unsupported versions or kinds are rejected |
| `id`, `title`, `family`, `status` | Task identity, display name, statistics family, and `candidate` / `qualified` status |
| `environment` | Required process and tool configuration identity; the actual run also records image and PDK-view digests |
| `inputs.netlist` | `path`, `sha256`, and target `subcircuit` |
| `constraints` or `inputs.constraints` | Exactly one: inline structured constraints, or `path` and `sha256` for a separate constraints file |
| `inputs.description`, `inputs.license` | Optional task description and license files, each declaring `path` and `sha256` |
| `evaluation` or `inputs.evaluation` | Optional evaluation plan: an inline table, or a TOML file declaring `path` and `sha256`; declaring both is rejected. Loading validates the [evaluation plan schema](#evaluation-plan) |
| `inputs.<role>` | Other named inputs such as testbenches, models, and stimulus files; declare `path` and `sha256`, with optional `format` (default `text`; simulation files may use `spice`) |
| `output` | Workspace-relative `path`, `format = "gds"`, `top_cell`, and positive-integer `max_bytes` |
| `provenance` | Optional preparation-source record with `path` and `sha256`; readable by maintainers but not materialized for the Agent |

An inventory case may additionally use `[[upstream_assets]]` to record a
reference GDS or upstream evidence file that already exists in its pinned
`origin.checkout`. Each entry contains only the upstream-relative `path`, role,
format, and digest. These records are not task inputs and are not
copied or regenerated by Layout-Bench; a reference/qualification workflow must
open the exact pinned file directly. A missing upstream asset is a screening
failure, not an invitation to create a replacement layout.

`[upstream_evaluation]` selects original assets by their `upstream_assets.id`:
`layout` selects a GDS reference or evaluation variant, and `netlist` selects
an original source/LVS netlist, never an extracted netlist. It also declares
`top_cell`, `subcircuit`, `drc_profile`, `lvs_profile`, and a nonempty `basis`
explaining the input selection and option provenance. Layout and reference
circuit names may differ. This maintainer mapping is independent of `[task]`
and does not grant qualification or expose reference assets to a solver.
Run it through `python -m benchmarking.upstream` as described in the
[tools guide](tools.md#original-asset-evaluation).

Resolve paths relative to the task configuration directory. Map inputs to `/task/<path>` and outputs to `/workspace/<output.path>`. The task ID, subcircuit, and top cell come from configuration; the runner does not hard-code tasks. The loader rejects unknown fields, unsupported versions, paths that escape their bounds or use symlinks, overlapping inputs, and digest mismatches. The configuration digest binds the original TOML bytes.

Materialize file snapshots validated at load time. Copy only declared inputs; do not bring in neighboring reference solutions, source records, or a complete checkout. Callers must still use read-only mounts and control access. Successful loading does not prove that the circuit is feasible or that the judge is correct; `status="qualified"` is not a qualification credential. The output path is a convention, and the Agent must explicitly submit it using the [submission protocol](running.md#submission).

## 3. Define Executable Constraints

Constraints can live directly in `[task.constraints]` of a circuit case (`[constraints]` in a standalone task). The table contains the existing geometry schema: `schema_version = 1`, `hard` and `quality` arrays. The loader freezes this data as a JSON asset, publishes it under `constraints` in `/protocol/task.json`, and supplies it as `input:constraints` to the evaluator. It does not create an extra solver file or expose the full case configuration. The case digest binds the inline definition. Task loading checks that inline data is a JSON-compatible table; the geometry backend validates its supported rules when evaluating.

Existing `inputs.constraints` files remain supported. Declare exactly one source; missing or duplicate definitions are rejected. The comparator uses inline constraints and keeps the human-readable requirements in `problem.md`.

For every constraint, specify object selection, relationships, units, tolerances, hard/soft status, and measurement method. Every requirement that affects success must come from frozen inputs, with the description and machine checks kept consistent. Identify objects from extracted electrical correspondence and trusted geometry analysis; do not rely only on cell names, labels, or sidecars written by the Agent.

Define the allowed device swaps, fingering, merging, and geometric equivalences for each task; leave out constraints that cannot be mapped reliably. State which functional layers and boundaries participate in area measurement. Metal area cannot stand in for wire length, and geometric symmetry does not establish electrical matching. Declare noise and mismatch requirements only when the models, extraction flow, and measurements actually support them. See the [geometry backend](tools.md#geometry) for the current implementation.

<a id="evaluation-plan"></a>

## 4. Declare an Evaluation Plan

Declare the plan inline under `[task.evaluation]` in a circuit case (`[evaluation]` in a standalone task), or reference a digest-bound TOML file through `inputs.evaluation`. An executable evaluation uses one source; declaring both is rejected. Inline plans use the same schema and validation as file plans. The loader freezes the inline table as a JSON snapshot and exposes its complete definition through `/protocol/task.json` under `evaluation`; it does not create an extra solver file. The case digest binds the original definition, while the evaluation report archives the plan snapshot with its format and digest. Existing TOML plan files retain their original bytes and digests.

Explain the complete scoring rules in the problem: check prerequisites, operating points, measurement definitions, thresholds, aggregation and failure semantics. Testbenches, stimulus, and required models remain declared task inputs. The plan describes what to measure. Trusted toolchain configuration binds each operation to a backend, while the core does not interpret simulator commands. A schema-2 case may contain an optional `[toolchain]` table with the existing toolchain schema: `schema_version = 1`, `[toolchain.backends.<id>]` (`type` and `settings`), and `[toolchain.bindings]`. This host configuration is separate from `[task.inputs]` and never materialized for the solver. Loading a task validates its inputs without starting tools; `load_toolchain` validates the backend configuration before instantiating registered adapters.

The current evaluation schema is `1` and contains `mode`, `jobs`, and `metrics`:

| Object | Fields and semantics |
|---|---|
| `mode` | `physical` performs physical validation only; `characterization` is for independent circuit measurement; only `post_layout` can establish complete task success |
| `jobs[]` | Unique `id`, `stage` (`check` / `extract` / `simulate` / `measure`), logical `operation`, and named `inputs`; optional `outputs`, `requires`, `gate`, and `parameters` |
| `inputs` | Names mapped to data references: `candidate` is the frozen GDS, `task` is a JSON description generated from the loaded configuration, `input:<role>` is a declared task file, and `job:<id>:<output>` is an upstream artifact |
| `outputs`, `requires` | Output-name to format mappings; artifact references create dependencies automatically, while `requires` adds prerequisites that produce check evidence only |
| `gate` | A check step may be marked `artifact`, `drc`, `lvs`, or `constraint`. A layout plan has one of each of the first three, and each must check the candidate GDS directly |
| `parameters` | A parameter table interpreted by the backend, such as measurement names and units, load, temperature, seed, or output filename. The core only checks that it can freeze the table as JSON; it does not interpret EDA syntax |
| `metrics[]` | Unique `id`, `category` (`physical` / `performance`), `observations` (`<job>:<measurement>`), `unit`, `direction` (`minimize` / `maximize` / `target`), and `aggregation` (`min` / `max`); optional `lower` and `upper` |

Physical metrics may consume a measurement from a successful `check` step, such as area reported by a geometry check. Performance metrics must still come from `simulate` or `measure`; a check status cannot stand in for performance.

The KLayout DRC adapter accepts an optional case-local `parameters.waivers` list. Each entry must name one report `category`, exact report `cell`, a nonempty list of exact textual `markers`, and a nonempty `reason`. Only those marker items are accepted; the native DRC report and raw violation count remain archived, and any unmatched item still fails the check. Keep waivers in the digest-bound case evaluation plan, never in the shared PDK deck, and use them only for reviewed, intentional structures.

Use separate named jobs for different conditions, and archive their parameters, models, and inputs with the result. **Evaluate limits observation by observation.** `aggregation` controls only how a summary is displayed; an average or one passing condition cannot hide an out-of-limit condition. Report metrics without limits as values only; `target` requires both lower and upper bounds. Units must match exactly. There is currently no implicit unit conversion; missing measurements, non-finite values, and unit mismatches are evaluation errors.

A `post_layout` plan must declare at least one limited performance metric. Its performance observations must come from simulation or a post-simulation measurement step, and the simulation must actually consume artifacts extracted from the candidate GDS. Reject plans that sort results after PEX but continue simulating the schematic netlist. `extract` denotes the post-layout extraction stage and must depend on the three physical-validity gates. Dependency-graph checks ensure that materials flow correctly; backend qualification remains responsible for whether the extracted content is correct.

Backends read conventions such as `output.top_cell` and `netlist_subcircuit` from the `task` input, so the plan need not hard-code them again. This description contains neither preparation sources nor reference solutions. Input references must come from the task manifest or from trusted generated materials, including the frozen `input:constraints` and `input:evaluation` assets for inline definitions. The executor gives a backend only the snapshots declared by its current job; it does not provide the entire task directory automatically.

<a id="evaluation"></a>

### Decisions and Reporting

The evaluator receives only the frozen GDS from the Agent; the authoritative netlist, top cell, constraints, and rules come from trusted preparation materials. The current evaluation container mounts the candidate and PDK view read-only. Trusted workflows pre-stage task materials, and the evaluator does not access the Agent's writable directory or credentials. A tool exit code of 0 is not sufficient: verify that checks completed, reports are complete, extraction is non-empty, and the specified circuit actually participated in the LVS comparison.

```text
physical_valid = artifact_ok ∧ drc_pass ∧ lvs_pass
task_success = physical_valid ∧ all hard constraints pass ∧ required post-layout complete ∧ all performance limits pass
```

DRC/LVS establishes physical validity under the selected rules and extraction configuration; it is not a complete tape-out signoff. A layout can be legal yet fail the task because its geometry or post-layout measurements exceed limits.

| Result | Meaning |
|---|---|
| `passed` | The current step produced an acceptable result |
| `failed` | A completed check or measurement violated a declared requirement |
| `error` | A crash, timeout, missing measurement, or similar condition prevented a valid result |
| `blocked` | A prerequisite did not pass, so the current step was not run |

Reports store `physical_valid`, `specs_pass`, and `task_success` separately; unknown or not applicable is `null`. Even when a `physical` or `characterization` run passes overall, `task_success` remains `null`. An out-of-limit performance result is a failure; a simulation crash is an evaluation error. Raw metrics may be saved for a physically valid candidate, while the primary quality report summarizes only successful candidates and discloses coverage. See [statistics](running.md#scoring) for the policy.

Independent re-evaluation does not run the Agent. `evaluate` and `run` use the case's `[toolchain]` by default. An explicit `--toolchain` selects an independent configuration instead, which remains required for cases without an embedded toolchain. `load_toolchain` also accepts a case TOML directly. Existing backend path semantics remain unchanged: relative `support` paths resolve from the launch working directory. Run from the repository root with a new output directory:

```text
uv run --locked python main.py evaluate <case.toml> <candidate.gds> --output <new-output-directory>
```

<a id="qualification"></a>

## 5. Validate the Task and Judge Qualification

The current comparator development intake uses a reviewed, narrower scope:
DRC disposition, a passing reference, candidate-derived parasitics and bounded
performance measurements, schematic/post-layout calibration, and minimal
rejection and candidate-sensitivity checks. A complete per-case counterexample
suite and dedicated repeatability runs are deferred. The comparator supplies
its repaired reference as a frozen GDS with documented changes and direct
evaluation instructions; no generator is required for this case. Its
[case README](../tasks/IHP-AnalogAcademy/cases/comparator/README.md)
records sources, modifications and the validation summary; it is not a claim
that the full qualification checklist below has passed.

The comparator's approved nominal scope tests −5, −3, +3 and +5 mV differential
inputs at TT, 27 °C, 1.2 V, 100 MHz and 50 fF per output. Its complete
`post_layout` plan gates RC extraction on physical checks and bounds every
operating point's decision delay, signed output and supply power. Its
`qualified` designation applies to that recorded development scope, with the
deferrals above; it does not imply PVT, mismatch or full ADC qualification.

The [full OTA](../tasks/IHP-AnalogAcademy/cases/full_OTA/README.md) uses the same
development intake scope, with its own nominal AC/DC requirements: TT model
corners, 27 °C, 1.2 V supply, 0.6 V input DC level, 80 µA bias sink and 500 fF
load. Its `post_layout` plan bounds gain, unity-gain bandwidth, phase margin,
supply power, output bias and the functional outline. Its reference passes;
original-asset and geometry rejections, performance decision boundaries, and
matched-condition source/post-layout calibration are covered. A full physical
performance counterexample suite and dedicated repeatability remain deferred;
`qualified` applies to that recorded development scope.

Before formal use, the evaluator and every task must pass the checks below. Repeat the affected checks whenever tools, rules, extraction parameters, constraint implementation, or quality metrics change:

- **Positive case**: An independently constructed witness passes, and allowed equivalent layouts also pass.
- **Counterexamples**: Construct separate samples for an empty top cell, wrong devices or parameters, shorts or opens, missing pins, DRC violations, and hard-constraint violations, and confirm that the corresponding checks reject each one.
- **Performance counterexample**: Include a layout that passes DRC/LVS but exceeds a post-layout specification and confirm that it cannot achieve task success. A legal change that improves parasitics should appear in the corresponding measurement.
- **Extraction and simulation**: Use a small circuit with analytically expected results to validate measurements and error paths, then check the real task's device models, parasitic extraction, and pre/post-layout results. Schema tests and substitutes cannot replace this step.
- **Equivalent transformations**: Translation, legal hierarchy changes, and allowed instance renaming leave the relevant decisions unchanged. Test rotations only when the task permits them.
- **Repeated evaluation**: Re-run the same frozen GDS in independent environments and obtain identical hard decisions; document tolerances for floating-point and quality metrics and any tool nondeterminism.
- **Feedback consistency**: When a harness declares `process-feedback.v1`, verify that each immutable process-check snapshot uses the same task plan and backend identities as the final judge and that its report is kept separate from the final score. A harness without the capability has no process-check path.

These tests validate the judge implementation and task measurability; they do not prove that a deck covers every manufacturing requirement. Defer formal tasks that include a requirement backed by an unreliable check.

When a public task is fully entered, provide its reference GDS, generator script, reproduction steps, check configuration, expected results, and counterexamples for key rejection paths. Archive pre-layout/post-layout calibration under the same conditions and record the actual tool identity. Pre-layout simulation cannot replace candidate post-layout simulation, and a witness is not an optimum-quality baseline. Fix families and measurement conditions before comparison; size variants of one template do not constitute independent circuit knowledge.

Qualification applies only to the fixed case, tools, rules, and declared conditions; requalify the affected scope after an environment change. An IHP or TO_Apr2025 case without upstream layout evidence must remain excluded rather than receiving a generated replacement reference.

<a id="input-isolation"></a>

## Historical Asset Exclusion Checklist

The following historically excluded assets and their copies must stay out of every task release bundle and Agent input:

- The original workspace asset `IHP-AnalogAcademy/modules/module_0_foundations/PEX_Demo/layout/inverter.gds`, including the same asset under `third_party/IHP-AnalogAcademy/`;
- The historical `third_party/IHP-AnalogAcademy/utils/PEX_Demo/` fixture and all geometry, netlists, reports, scripts, and intermediate artifacts produced by it;
- Geometry, images, netlists, reports, scripts, and intermediate artifacts produced by that inverter fixture;
- Historical run records named `local-inverter-unversioned-interface` and their derivatives;
- Historical candidates and caches or derived files with unknown provenance.

Keep these excluded artifacts inaccessible to both people and Agents: do not open, render, screenshot, parse, or count them. Renaming, moving, or archiving an asset does not change its exclusion status, and this checklist does not depend on an old run directory remaining present.

Construct new reference solutions and witnesses independently and record their sources. They may be public for debugging, but they are not standard solve inputs.
