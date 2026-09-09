# Comparator Layout Task

Give the model a problem, materials, and tools, then evaluate its submitted GDS
against public rules. Start with [problem.md](problem.md);
[case.toml](case.toml) is the framework entry point.

| Role | Location | Purpose |
|---|---|---|
| Problem | [problem.md](problem.md) | Circuit objective, ports, submission requirements, and passing conditions |
| Materials | [materials/](materials/) | LVS netlist `circuit.cdl`, simulator netlist `circuit.spice`, and shared `testbench.spice` |
| Tools | [Tool instructions in the problem](problem.md#tools-and-usage), `[toolchain]` in `case.toml` | The problem explains tools and usage; the configuration binds evaluator EDA backends and PDK support bundles |
| Answer | The model writes `/workspace/output/final.gds` and explicitly submits it | [reference/DIFF_COMPARATOR.gds](reference/DIFF_COMPARATOR.gds) is the maintainer's feasibility witness and is excluded from model inputs |
| Scoring | [Scoring rules in the problem](problem.md#scoring), `[task.evaluation]` and `[task.constraints]` in `case.toml` | Physical checks → RC extraction → simulation at four operating points → individual decisions, reported in `report.json` |

The model receives three files: the problem, netlist, and testbench. The problem
fully describes tools, scoring, and passing conditions. Geometric constraints
and the evaluation plan are defined in `[task.constraints]` and
`[task.evaluation]` in `case.toml`. At runtime, the `constraints` and `evaluation`
fields in `/protocol/task.json` expose the same structured definitions used by
the evaluator. Scoring rules are public; the reference answer and this README
stay outside the standard solve environment. Results include `task_success`
and metrics such as area, delay, output margin, and power, with no additional
percentage scoring formula.

## Workflow

Run these commands from the repository root. Output directories must not exist yet.

1. Inspect the task and export the files the model will receive:

   ```bash
   uv run --locked python main.py task tasks/IHP-AnalogAcademy/cases/comparator/case.toml --materialize build/runs/comparator-inputs
   ```

2. Solve in the tools image with reviewed PDK resources. The outer
   [run configuration](../../../../docs/running.md#offline-cli) selects the model,
   harness, budget, and resource bundles; `main.py run` loads this case for a solve.
   After writing the GDS, the model calls `python -I /protocol/submit.py` so the
   framework can freeze and evaluate the submission.

3. Evaluate an existing answer independently:

   ```bash
   uv run --locked python main.py evaluate tasks/IHP-AnalogAcademy/cases/comparator/case.toml /path/to/final.gds --output build/runs/comparator-score
   ```

   Replace `/path/to/final.gds` with the reference GDS path to verify the evaluation
   environment. A passing evaluation exits with code 0 and sets `physical_valid`,
   `specs_pass`, and `task_success` to `true` in `report.json`.

## Prepare Evaluation Tools

Prepare the shared image with the repository's
[tool setup workflow](../../../../docs/tools.md#manual-tools). The `[toolchain]`
section in `case.toml` uses `layout-bench-tools:local` and the three support bundle
locations below. Prepare them once if absent; existing validated bundles can be reused:

```bash
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK technology/sg13g2/klayout.json build/support/comparator-klayout
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK technology/sg13g2/magic.json build/support/comparator-magic
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK technology/sg13g2/analog-models.json build/support/comparator-analog-models
```

These are evaluator support bundles. The run configuration separately supplies
the solver's PDK resource bundle. Tools and PDKs are shared through the framework;
the case directory does not copy tool programs or an entire PDK.

## Circuit Source

The circuit comes from the
[IHP AnalogAcademy comparator lesson](../../../../third_party/IHP-AnalogAcademy/modules/module_3_8_bit_SAR_ADC/part_5_analog_layout/comparator)
in Module 3 (8-bit SAR ADC), Part 5 (analog layout). The pinned upstream commit is
`133ecf657572e021b5921b5a1b7693abfb209623`, under the
[upstream Apache-2.0 license](../../LICENSE) and file-level notices.
`case.toml` records source paths and digests.

- `source/DIFF_COMPARATOR.sch` is a matched derivative of the upstream
  `layout/schematic/DIFF_COMPARATOR.sch`. It preserves all 13 MOS instances,
  their parameters and connections, and the eight ordered ports. The two taps
  use the active-ring geometry of the current reference and archived LVS circuit.
- `materials/circuit.cdl` and `materials/circuit.spice` are untouched Xschem
  exports of that matched schematic in the LVS and simulator formats respectively.
  The archived upstream LVS netlist remains recorded under `upstream_assets`.
- `reference/DIFF_COMPARATOR.gds` is based on the upstream `layout/DIFF_COMPARATOR.gds`, with the two geometric repairs below.
- Simulation stimuli are based on the upstream `xschem_post_layout/testbench/comparator_tb.sch`. The current fixed-input tests, measurement definitions, and limits are benchmark requirements established after calibration.

The corresponding IHP Open PDK commit is `5e6d592e4002946a4616f798c357f0f3c06cf3b6`.
The rule basis is sections 5.1 and 5.3 of that version's
`SG13G2_os_layout_rules.pdf`, along with KLayout's `5_3_nbulay.drc` and
`sg13g2_maximal.drc`. See the [tool instructions in the problem](problem.md#tools-and-usage)
for the checks used in evaluation.

## Original Issues and Modifications

The original GDS passes LVS, but DRC with the pinned PDK reports 5 `NBL.b`
and 2 `NW.d` findings. The following changes provide a reference that passes
the current checks. All coordinates are in µm.

| Object | Original issue and rationale | Modification |
|---|---|---|
| nBuLay ring, GDS `32/0` | A 0.105 µm gap between the drawn ring and automatically generated regions causes 5 `NBL.b` findings. The rule requires at least 1.5 µm same-net spacing/notch width and includes automatically generated regions. | Shrink the inner opening from `(5.025,15.345;16.995,26.175)` to `(5.130,15.450;16.890,26.070)`, filling the gap and adding 4.7439 µm². |
| NWell corners, GDS `31/0` | The maximal check reports 2 `NW.d` findings. The PDF clause applies to external N+ active, while this active ring is entirely inside NWell and meets the 0.24 µm enclosure requirement. This is a difference in check applicability. The repair accommodates the pinned check. | Add rectangles `(4.130,14.380;6.165,14.450)` and `(15.855,14.380;17.890,14.450)`, extending the corners by 0.070 µm and adding 0.2849 µm² in total. |

Both repairs add only the regions above; all other cell geometry, instances, and
connections remain unchanged. GDS timestamps are disabled when saving. No upstream
assets or PDK files were changed, and no DRC waivers were added. The repaired GDS
is supplied directly, with no generation step.

| GDS | SHA-256 |
|---|---|
| Original upstream file | `2716d3953e42766c1c6ce270cbb9dac418862a612e67c174b1204435d9462bb1` |
| Case reference file | `9f2548f157ccfc4448820dbd71f26c60d9a0525043e86d8928ea448cf56d7279` |

Simulation uses the following conditions and model adaptations to match the
authoritative netlist:

- `V-` connects to `vbias = 0.6 V`, as in the upstream testbench. The testbench
  explicitly sets 27 °C and exports waveforms. Evaluation uses the four fixed
  input points in the problem in place of the upstream input ramp.
  Clock edges, loads, time steps, and measurement windows are explicit, with
  delay and output margin checked for each cycle.
- The original schematic's two 100 × 100 µm rectangular taps are replaced in
  the matched derivative by explicit active area/perimeter: R1 ntap A=15.376 µm²,
  P=99.2 µm; R2 ptap A=11.376 µm², P=75.84 µm. These are the existing physical
  rings, not a change to the reference GDS or the 45 × 45 µm task outline.
  The local [ntap symbol](source/sg13g2_case/ntap_ap.sym) and
  [ptap symbol](source/sg13g2_case/ptap_ap.sym) derive from the pinned PDK symbols
  with preserved terminal order and notices. LVS emits native A/P cards;
  simulation emits PDK model calls and evaluates
  `R = 1 / (A / 9.8e-10 + P / 9.8e-4)` (A in m², P in m), giving
  8.553275 Ω and 11.236470 Ω. The upstream PDK is unchanged.
- Both analyses use the same testbench and pinned `analog-models` bundle,
  including `mos_tt` and `res_typ`. Pre-layout uses `circuit.spice` directly;
  post-layout uses the current candidate's distributed RC extraction without
  modifying its bytes. The MOS finger counts and multiplicities are preserved
  in the simulator export; no simplified LVS graph is used to create it.

### Reproduce the Matched Schematic

[source/DIFF_COMPARATOR.sch](source/DIFF_COMPARATOR.sch) targets the current
reference layout. Its change from the upstream schematic is the tap geometry
representation and the corresponding symbol/label arrangement, plus a derivative
notice. It is not presented as an untouched upstream schematic.
`[source_export]` in [case.toml](case.toml) pins the drawing, local tap symbols,
and required PDK symbols. Source files remain maintainer assets; only declared
task inputs enter the solver environment.

Run from the repository root with the shared tools image and pinned PDK available:

```bash
uv run --locked python -m benchmarking.prepare \
  tasks/IHP-AnalogAcademy/cases/comparator/case.toml \
  build/runs/comparator-matched-export \
  --checkout case=tasks/IHP-AnalogAcademy/cases/comparator \
  --checkout pdk=third_party/IHP-Open-PDK
uv run --locked pytest tests/integration/test_matched_schematic_exports.py \
  tests/integration/test_comparator.py \
  --basetemp build/runs/comparator-matched-validation
```

Use fresh output directories; pytest clears its `--basetemp` directory.
The export command creates raw CDL, provenance and the Xschem log. The source
regression re-exports both dialects, checks the frozen bytes, compares their
unsimplified native device graphs, and verifies the tap resistance formula.
The comparator regression evaluates the actual reference and runs all four
pre-layout input points through the same stimuli and models. It independently
recomputes cycle delays, output margins and mean supply power from raw waveform
voltages/current. Generated `pre/report.json` and `reference/report.json`
record these measurements and the actual tool/support identities.

Across the four declared input points (±3 mV and ±5 mV), nominal calibration gives:

| Observation | Pre-layout | Post-layout | Acceptance limit |
|---|---:|---:|---:|
| Maximum cycle delay | 1.872 ns | 2.542 ns | ≤3 ns |
| Minimum settled output margin | 1.19997 V | 1.19818 V | ≥1 V |
| Maximum mean VDD power | 58.152 µW | 64.153 µW | 0–80 µW |

These are fixed-input transient measurements, not static offset or Monte Carlo
results. The declared limits are unchanged; no dynamic-ramp transition result is
claimed by this calibration.

The reference passes the complete evaluation with the shared
[Magic driver-selection correction](../../../../docs/tools.md#ngspice-and-magic):
zero DRC findings, matching LVS, a functional footprint of
40.800 × 40.745 µm, worst-case delay of approximately 2.542 ns, minimum output
margin of approximately 1.198 V, and maximum average VDD power of approximately
64.153 µW. The original GDS is still rejected for the seven DRC findings above,
which block subsequent RC extraction and simulation. Validation is limited to
the nominal conditions in the problem. PVT, mismatch, a complete comparator
counterexample suite, and dedicated repeatability checks are outside this scope.

Use the [evaluation workflow](#workflow) to reproduce these checks. The generated
report records measurements, native tool results, and the actual image and
support-bundle identities for that run.
