# Full OTA: SG13G2 Layout from a Netlist

Create an IHP SG13G2 layout for `two_stage_OTA_layout` in
[materials/circuit.cdl](materials/circuit.cdl). Preserve the specified MOS
and MIM devices, dimensions, connectivity, well/substrate nodes and tap devices.
The layout must pass physical checks, fit the specified functional outline and
meet nominal OTA performance limits after RC extraction from the submitted GDS.

## Materials and Interface

| Input | Purpose |
|---|---|
| [materials/circuit.cdl](materials/circuit.cdl) | Authoritative LVS export of the matched schematic; preserves device multiplicity, tap area/perimeter and MIM dimensions |
| [materials/circuit.spice](materials/circuit.spice) | Equivalent simulator export of the same schematic, for pre-layout simulation |
| [materials/testbench.spice](materials/testbench.spice) | Nominal stimuli, PDK corner selection, operating point and AC measurements |
| [materials/LICENSE](materials/LICENSE) | License for the delivered circuit materials |
| `/protocol/task.json` | Published constraints, evaluation plan, input paths and submission contract |

| Ordered port | Meaning | Nominal external connection |
|---|---|---|
| `v-` | Inverting voltage input | DC feedback from `vout`; AC grounded through the feedback fixture |
| `v+` | Non-inverting voltage input | 0.6 V DC, unit AC excitation |
| `vss` | Ground / substrate supply | 0 V |
| `vdd` | Positive supply | 1.2 V |
| `iout` | Bias-current node | Ideal 80 µA current sink to ground |
| `vout` | Single-ended voltage output | 500 fF load to ground |

Provide one external metal label for each port, on six distinct conductors.
Internal circuit nodes must not be declared as external ports. Port order is
`v- v+ vss vdd iout vout`; `iout` is the bias node, not the voltage output.

## Tools and Use

| Item | Use |
|---|---|
| Environment | `ihp-sg13g2-full-ota-rc-tt`; tool and support identities are recorded in evaluation results |
| PDK | SG13G2 commit `5e6d592e4002946a4616f798c357f0f3c06cf3b6` |
| Resource discovery | `/protocol/resources.json` gives mounted resource paths, import checks and environment variables |
| KLayout CLI / Python | Generate/read GDS and run native artifact, DRC and LVS checks |
| Magic | Extract the simulation DUT from the candidate GDS using `ngspice()` style, zero capacitance threshold, distributed resistance and no device/network simplification |
| ngspice | Simulate the authoritative circuit or extracted DUT with the supplied testbench and the reviewed MOS, capacitor and resistor model bundle |
| Optional process feedback | If `/protocol/harness.json` declares `process-feedback.v1`, run `python -I /protocol/process_check.py` |

For pre-layout simulation, copy `materials/circuit.spice` byte-for-byte to
`dut.spice` beside the testbench. Use the reviewed analog model bundle and its
`.spiceinit` startup settings. Model calls preserve each MOS `w`, `l`, `ng` and
`m`; tap area/perimeter parameters also determine their simulation resistance.
LVS reads `circuit.cdl` through the native PDK reader; the source regression
checks that the two exports describe equivalent devices and connections.
For scoring, the evaluator supplies candidate-derived PEX as `dut.spice` and
includes it without edits. Solver-provided simulation results cannot replace
independent extraction and measurement.

Use the shared Magic 8.3.678 build with the driver-selection fix for W/L below
one. An unpatched build can omit internal-node resistance despite zero
extraction thresholds. Native PDK LVS simplification defines parallel-device
merging and source/drain equivalence; the candidate must match the source's
total MOS widths, channel lengths, device classes and connections. Pre-layout
calibration must retain source finger counts and multiplicities before that
LVS simplification.

## Submission

| Requirement | Value |
|---|---|
| Output | `/workspace/output/final.gds` |
| Format / top cell | GDSII / `two_stage_OTA_layout` |
| Maximum size | 10485760 bytes (10 MiB) |
| Submit | Run `python -I /protocol/submit.py` and wait for the receipt |
| Evaluated artifact | Last accepted, frozen GDS submission |

Use runtime paths from `/protocol/task.json`. Evaluation uses trusted materials
in an independent environment after the framework freezes the submission.

## Evaluation

| Step | Requirement or action | Prerequisites |
|---|---|---|
| Artifact | Readable, nonempty target cell, complete hierarchy and declared file-size limit | Frozen GDS |
| DRC | Zero violations, no waivers; pinned PDK main plus additional maximal rules, deep mode, density and antenna disabled | Frozen GDS |
| LVS | Native match against the authoritative circuit, with explicit taps and native simplification; course compare-only port policy | Frozen GDS and circuit material |
| Geometry | Functional bounding box at most 80 µm wide and 50 µm high in submitted coordinates | Artifact, DRC and LVS pass |
| RC extraction | Extract from the same GDS; verify the six ordered ports and reject multiple ports on one conductor | Artifact, DRC, LVS and geometry pass |
| Nominal simulation | DC operating point and AC transfer of the extracted circuit | Extraction succeeds |

The physical profiles are `drc-upstream.json` and `lvs-analogacademy.json`.
The latter does not add `flag_missing_ports`; the RC stage checks the declared
interface. Failed or errored prerequisites block dependent jobs.

### Functional Outline

Measure the bounding box of recursive polygons on these GDS layers. All listed
layers use datatype 0; text, pin markers and nonfunctional annotations do not
enlarge the outline. Port positions are free. Width and height refer to the
submitted coordinate axes; a rotation must still meet both limits.

| Geometry | Layer numbers |
|---|---|
| Active, gates, contacts, implants and process blocks | 1, 5, 6, 7, 14, 28, 46 |
| Wells and substrate recognition | 31, 32, 40 |
| Metals and routing vias | 8, 10, 19, 29, 30, 49, 50, 67, 125, 126, 133, 134 |
| MIM and capacitor vias | 36, 129 |

Report functional area as bounding-box width × height in µm², without an
additional area limit. `/protocol/task.json` exposes this same layer selection
and the executable geometry constraints.

### Operating Conditions and Measurements

| Condition | Setting |
|---|---|
| Supply / input DC level | 1.2 V / 0.6 V |
| Bias / load | 80 µA sink at `iout` / 500 fF at `vout` |
| Numerical conditioning | `rshunt=1e12`: 1 TΩ from every analog node to ground; identical in pre/post analysis, with PEX bytes retained |
| Process / temperature | `mos_tt`, `cap_typ`, `res_typ` / 27 °C |
| DC feedback | 4 GH from `vout` to `v-`; 4 GF from `v-` to ground opens the AC loop |
| AC sweep | 100 points/decade, 1 Hz through 10 MHz |
| Differential transfer | `A(f) = V(vout) / (V(v+) - V(v-))` |

| Metric | Measurement definition | Inclusive limit |
|---|---|---|
| Low-frequency gain | `20 log10(abs(A(1 Hz)))`, in dB | ≥60 dB |
| Unity-gain bandwidth | First downward 0 dB crossing inside the sweep, in Hz | ≥3 MHz |
| Phase margin | 180° plus continuously unwrapped phase of `A` at that crossing | ≥55° |
| Quiescent supply power | `-V(vdd) * I(VDD)` at the DC operating point, in W; excludes external input/bias-source power | 0–220 µW |
| Output bias | `V(vout)` at the closed-feedback DC operating point | 0.55–0.65 V |

All declared measurements must be present and finite. A missing crossover,
model error, crash or timeout is an evaluation error. Raw AC and operating-point
waveforms are retained for diagnosis. `task_success=true` requires all physical
checks, the geometry constraint, extraction, simulation and every performance
limit to pass. A completed violation is a failure; a tool error cannot establish
success. Report the raw metrics individually, with no weighted or
reference-normalized score. The declared nominal scope excludes CMRR, PSRR,
large-signal settling/slew, noise, PVT and mismatch qualification.
