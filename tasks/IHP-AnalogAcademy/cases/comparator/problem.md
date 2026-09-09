# Comparator: SG13G2 Layout from a Netlist

Create an IHP SG13G2 layout for `DIFF_COMPARATOR` in the
[authoritative netlist](materials/circuit.spice). Preserve its connectivity and
device parameters, including well/substrate connections and tap devices. The
layout must pass the physical checks and meet the performance limits after
parasitic RC extraction.

## Materials

| Material | Purpose |
|---|---|
| [materials/circuit.spice](materials/circuit.spice) | Authoritative circuit for LVS |
| [materials/testbench.spice](materials/testbench.spice) | Public simulation stimuli and measurement expressions |
| `/protocol/task.json` → `constraints` | Exact functional layers, geometry limits and area definition |
| `/protocol/task.json` → `evaluation` | Complete scoring plan: step inputs, dependencies, parameters and metrics |

The [scoring rules](#scoring) below describe the same requirements in words.

## Tools and Usage

Tools are installed in the shared tools image. The PDK is supplied through
reviewed resource bundles, with resources selected for each execution role.

| Environment item | Value or location |
|---|---|
| Environment ID | `ihp-sg13g2-comparator-rc-tt` |
| PDK commit | `5e6d592e4002946a4616f798c357f0f3c06cf3b6` |
| Tool versions | Fixed by the shared image; actual image and resource digests are recorded in the run results |
| Resource locations | `/protocol/resources.json`: mounted paths, environment variables and available import checks |
| Harness capabilities | `/protocol/harness.json` |
| Working directory | `/workspace` |

| Tool | Role in this task |
|---|---|
| KLayout CLI / Python API | Create and read GDS; the evaluator runs artifact, DRC, LVS and functional bounding-box checks |
| Magic | Extract a distributed RC netlist, including wire resistance and capacitance, from the submitted GDS |
| ngspice | Run the supplied performance testbench on the extracted netlist |
| SG13G2 PDK | Provide devices/PCells, layer definitions, rules, extraction technology and simulation models |

| Evaluation operation | Configuration and scope |
|---|---|
| DRC | `drc-upstream.json`: pinned PDK main and additional maximal rules, deep mode, density and antenna checks disabled, no waivers |
| LVS | `lvs-analogacademy.json`: preserve explicit taps and the original netlist; use native PDK simplification and comparison. No additional `flag_missing_ports` check is applied. RC extraction still requires all eight ports listed below. |
| RC extraction | Magic `ngspice()` style: retain capacitance and extract wire resistance, without device merging or resistor-network simplification. Each declared port must correspond to a distinct conductor; multiple ports on one conductor are unsupported. |
| Simulation | ngspice uses the submitted layout's extracted netlist, fixed PDK MOS models, and the supplied testbench and parameters |

The evaluator compares the layout with the authoritative netlist and independently
derives the simulation DUT, waveforms and measurements from the submitted GDS.
Solver-supplied netlists, waveforms or measurements cannot replace this evaluation.

If the harness declares `process-feedback.v1`, run
`python -I /protocol/process_check.py` to check the current candidate. The final
submission is still evaluated independently.

## Submission

| Requirement | Value |
|---|---|
| Output file | `/workspace/output/final.gds` |
| Format | GDSII |
| Top cell | `DIFF_COMPARATOR` |
| Maximum file size | 10 MiB (10485760 bytes) |
| Extraction port order | `vdd gnd V+ V- clk out- out+ vbias` |
| Submit command | `python -I /protocol/submit.py` |
| Scored artifact | The last accepted submission snapshot; wait for the submission receipt |

| Port | Meaning |
|---|---|
| `vdd`, `gnd` | Supply and ground |
| `V+`, `V-` | Positive and negative differential inputs |
| `clk` | Clock |
| `out-`, `out+` | Negative and positive differential outputs |
| `vbias` | Bias input |

Use the input and output paths in `/protocol/task.json` at runtime. After writing
the GDS, run the submit command and wait for its receipt.

## Scoring

### Evaluation Steps

| Step | Requirement or action | Prerequisites |
|---|---|---|
| GDS validation | Readable GDS, complete hierarchy references and a nonempty target cell; meet the submission contract | Submitted GDS |
| DRC | Zero violations under the stated rule scope; no waivers | Submitted GDS |
| LVS | Match the authoritative netlist | Submitted GDS and authoritative netlist |
| Geometry | The bounding box of all shapes on the specified functional layers, including child cells, must be at most 45 µm wide and 45 µm high | GDS validation, DRC and LVS pass |
| RC extraction | Extract distributed RC from the submitted GDS | All physical and geometry checks pass |
| Performance simulation | Run the extracted circuit at all four operating points and check every required observation | RC extraction succeeds |

The `constraints` field in `/protocol/task.json` supplies the exact functional
layer list and geometry definition. Functional area is the bounding-box width
multiplied by its height. A failed or errored prerequisite blocks dependent steps.

### Operating Conditions

| Parameter | Setting |
|---|---|
| Differential input, `V+ − V-` | −5, −3, +3 and +5 mV, each tested separately |
| Process corner | TT |
| Temperature | 27 °C |
| Supply | VDD = 1.2 V |
| Input reference and bias | `V- = vbias = 0.6 V` |
| Clock | 100 MHz, with 500 ps rise and fall times |
| Output load | 50 fF on each output |
| Simulation duration | 100 ns |
| Maximum time step | 10 ps |
| Evaluated cycles | Skip the first two cycles and check the next eight |

### Performance Requirements

| Metric | Measurement | Limit at every operating point |
|---|---|---|
| Decision delay | Each cycle, from the clock's falling edge at 50% level until the differential output in the correct polarity reaches 1 V | 0–3 ns, inclusive |
| Output margin | Minimum differential output in the correct polarity over the window from +3 to +4 ns after each clock falling edge | ≥1 V throughout the window |
| Average supply power | Average VDD supply power over 20–100 ns; excludes external clock, input and bias driver power | 0–80 µW, inclusive |

| Input polarity | Differential output used for delay and margin |
|---|---|
| `V+ − V- > 0` | `out+ − out-` |
| `V+ − V- < 0` | `out- − out+` |

All 32 delay observations, 32 output-margin observations and four power
observations must meet their limits individually. Summary values cannot hide a
violation in any cycle or operating point. The supplied testbench contains the
exact stimuli and measurement expressions; `/protocol/task.json` → `evaluation`
contains the executable workflow and thresholds.

### Results

| Result | Meaning |
|---|---|
| Success | `task_success = true` only when every requirement passes |
| Failure | Any completed check or measurement violates a requirement |
| Evaluation error | A tool crash, timeout or missing measurement prevents a passing result; an already established violation still determines failure |
| Reported metrics | Functional area, maximum decision delay, minimum output margin and maximum average supply power |
| Area scoring | Report the functional bounding-box area; there is no additional area threshold or reference-normalized score |
| Scope | Only the nominal conditions specified above |
