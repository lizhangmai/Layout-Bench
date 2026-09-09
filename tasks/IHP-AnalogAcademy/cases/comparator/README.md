# Comparator Layout Task

Give the model a problem, materials, and tools, then evaluate its submitted GDS
against public rules. Start with [problem.md](problem.md);
[case.toml](case.toml) is the framework entry point.

| Role | Location | Purpose |
|---|---|---|
| Problem | [problem.md](problem.md) | Circuit objective, ports, submission requirements, and passing conditions |
| Materials | [materials/](materials/) | Authoritative circuit netlist `circuit.spice` and simulation testbench `testbench.spice` |
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
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK technology/sg13g2/mos-models.json build/support/comparator-models
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

- `materials/circuit.spice` freezes the upstream `layout/lvs_netlist/DIFF_COMPARATOR.spice` without content changes.
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
- Both upstream schematic taps are 100 × 100 µm, with different areas/perimeters
  from the frozen LVS netlist. Pre-layout calibration uses the frozen LVS netlist
  and the native PDK formula `R = 1 / (A / 9.8e-10 + P / 9.8e-4)`
  (A in m², P in m), giving ntap 8.553275 Ω and ptap 11.236470 Ω.
  During calibration, native netlist readers/writers convert device calls to the
  PDK subcircuit interface and adapt escaped `V-` and `OUT-` names. Device
  parameters and connections are preserved, without removing taps or shorting
  bulk terminals. The authoritative LVS netlist remains unchanged.
- Post-layout simulation extracts distributed RC from the submitted GDS.
  The RC netlist does not call tap subcircuits, so the scoring testbench omits
  unused tap model includes;
  pre-layout calibration retains the actual PDK tap models. The evaluator
  generates the post-layout DUT, waveforms, and measurements.

Pre-layout/post-layout calibration under the same conditions showed an
approximately +1.8 mV shift in the dynamic ramp transition. This is not a static
offset or Monte Carlo measurement. The problem's input points and performance
limits are benchmark requirements informed by calibration; they do not
represent the course's full original 8-bit ADC accuracy specification.

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
