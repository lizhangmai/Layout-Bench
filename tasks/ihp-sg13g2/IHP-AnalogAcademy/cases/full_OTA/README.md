# Full OTA Layout Case

This case provides an authoritative circuit, a nominal testbench and a repaired
reference layout for an IHP SG13G2 two-stage OTA. Start with
[problem.md](problem.md); [case.toml](case.toml) is the configuration entry point.

The case is **qualified for the nominal public development scope described
below**. The [reference GDS](reference/two_stage_OTA_layout.gds) passes artifact,
DRC, LVS, functional-outline, RC extraction and AC/DC performance checks under
the declared conditions. Its complete `post_layout` evaluation reports
`task_success=true`.

## Source and License

The two-stage OTA comes from IHP AnalogAcademy's Module 1 bandgap-reference
[Part 3 layout lesson](../../../../../third_party/IHP-AnalogAcademy/modules/module_1_bandgap_reference/part_3_layout/README.md).
The earlier [Part 1 testbench](../../../../../third_party/IHP-AnalogAcademy/modules/module_1_bandgap_reference/part_1_OTA/testbenches/ota_testbench.sch)
provides the nominal operating conditions. It instantiates a different schematic
revision. The case uses the matched derivative schematic described below.

| Identity | Value |
|---|---|
| Source checkout / commit | `third_party/IHP-AnalogAcademy` / `133ecf657572e021b5921b5a1b7693abfb209623` |
| License | [Apache-2.0](../../LICENSE); derived materials retain notices and identify changes |
| PDK commit | `5e6d592e4002946a4616f798c357f0f3c06cf3b6` |
| Top cell / subcircuit | `two_stage_OTA_layout` |
| Ordered interface | `v- v+ vss vdd iout vout` |

`case.toml` records source paths and digests for the original schematic, GDS,
CDL, extracted circuit and upstream DRC reports, as well as the Part 1 materials.
It also binds the delivered inputs and reference assets. The reference repairs
the upstream GDS; upstream checkouts and PDK files are unchanged.

The task baseline retains the established reference circuit's MOS/MIM population,
dimensions and signal topology. [source/two_stage_OTA_layout.sch](source/two_stage_OTA_layout.sch)
is a deliberately modified version of the upstream layout schematic, matched to
the case reference GDS. It is not an untouched upstream original.
`materials/circuit.cdl` is its raw LVS export; `materials/circuit.spice` is its
raw simulator export; `materials/testbench.spice` supplies the shared pre/post
stimuli and measurements. The original `.sch` and `.cdl` identities remain
recorded under `sources` and `upstream_assets`.

The [asset exclusion and input isolation rules](../../../../../docs/tasks.md#input-isolation) apply.
Only declared problem/material files and reviewed resources enter a standard
solver environment. This README, source records, whole case directory, reference
GDS and diagnostic outputs are not delivered to the solver.

## Original Physical Verification

Direct evaluation of the original GDS and CDL, without preprocessing or
waivers, gives the results below. The upstream author's exact historical
switches were not archived; the profiles reconstruct documented defaults on
the pinned PDK. See [reproduction instructions](#reproduce-the-checks).

| Setting | Actual value |
|---|---|
| Physical verification tool | KLayout 0.30.11 |
| DRC | `drc-upstream.json`: main plus additional maximal deck, deep mode, density and antenna off |
| LVS | `lvs-analogacademy.json`: explicit taps, native simplification, compare-only port policy |
| Artifact | Passed |
| DRC | Failed: 1047 main-deck items plus 25 additional-deck items |
| LVS | Failed: native top-circuit `NoMatch` |

The upstream minimal, maximal and full reports contain 17, 1047 and 1060 items
respectively. None is clean. The archived full report has 12 `NW.e` items,
compared with 24 in the current two-deck run; its other category counts agree.
Counts do not establish identical historical versions or rule coverage.

### DRC Findings and Implemented Disposition

The repairs follow the stated block-level scope without waivers. Their basis
is the pinned PDK's `SG13G2_os_layout_rules.pdf`,
sections 5.1, 5.3, 5.14, 5.16, 5.17 and 7.4, and executable rules. Counts are
report items, not independent root causes. Dimensions below are in µm.

| Rule | Original items | Requirement / evidence | Implemented treatment |
|---|---:|---|---|
| `Cnt.c` | 698 | Active enclosure of contact ≥0.07 | Rebuild five tap-ring contact arrays, with centered 0.16 square contacts and compliant active enclosure |
| `Cnt.d` | 176 | Poly enclosure of contact ≥0.07; original example only 0.010 | Widen gate landings outside active and reposition affected contacts |
| `Cnt.e` | 32 | Poly contact to active ≥0.14; original example only 0.010 | Move 27 input-stage NMOS gate contacts to the inter-device corridor and five bias contacts by +0.06 in x |
| `Cnt.g2` | 98 | pSD contact overlap ≥0.09 | Widen substrate tap rings to 0.30 and restore implant enclosure |
| `NBL.b` | 16 | Same-net nBuLay spacing/notch ≥1.50; original gap down to 0.005 | Union the drawn nBuLay with NWell expanded by 0.35; close narrow same-region gaps |
| `NBL.a` | 1 | nBuLay width ≥1.00; original section 0.975 | Restore compliant nBuLay width with the preceding repair |
| `NW.e` | 24 | NWell enclosure of well tie ≥0.24 | Inset ntap active rings by 0.25 within the unchanged wells |
| `M1.b` | 2 | Metal1 spacing/notch ≥0.18 | Close same-net IOUT notches; trim the affected VSS landing |
| `M1.e` | 5 | Applicable long-run Metal1 spacing ≥0.22 | Trim local conductor edges while retaining valid via enclosure |
| `M2.b` | 2 | Metal2 spacing/notch ≥0.21 | Repair same-net notches and trim the VSS landing |
| `M2.e` | 9 | Applicable long-run Metal2 spacing ≥0.24 | Close IOUT notches using native connectivity to prevent unrelated-net joins |
| `M3.e` | 8 | Applicable long-run Metal3 spacing ≥0.24 | Repair same-net IOUT notches |
| `Pin.f_M2` | 1 | Pin must be enclosed by metal drawing | Rebuild the six external pin markers on their conductors |

The final GDS has **zero items in both declared DRC decks**, with no rule
changes or waivers. Original and repaired NWell, MIM and Vmim regions have empty
geometric XORs. NMOS and PMOS gate/active intersections, checked separately by
implant type, also have empty XORs. Drawn nBuLay area changes from 205.37775 to
1059.21125 µm². Overall GDS bounds change from 69.640 × 39.095 to
69.665 × 39.095 µm; these observations are not scoring limits.

### Source and Connectivity Repairs

| Original problem | Change / basis |
|---|---|
| R4/R5 commas cause native device class `,`, with tap names parsed as terminals | Remove those separators in the derived circuit material |
| M6 bulk is `bulk3`, whereas the schematic shares the NMOS substrate | Connect M6 to `bulk2` |
| M5/M9 well `bulk4` lacks its VDD tie; R5 incorrectly targets `bulk3` | Connect R5 to `bulk4`, preserving the explicit well-tap device |
| Tap CDL A/P values disagree with physical rings | Use the independently computed areas/perimeters of the repaired rings below |
| Two disconnected native `vss` clusters | Add a 0.5-wide Metal5 ground bridge with Via1–Via4 stacks, crossing the existing Metal4 IOUT trunk |
| MIM top plate floats in both archived and fresh extraction | Connect its existing TopMetal1 route to DN4 through Metal3–Metal5 and TopVia1 (125/0); preserve the capacitor plates and dimensions |
| Input substrate ring lacks the marker needed for explicit tap extraction | Add `sub!` on 63/0 inside its substrate-recognition region; the output substrate ring already has a marker |
| Internal nodes appear as ports, external labels repeat | Recreate six unique external metal labels and pins; remove internal pin markers |
| Layout schematic has extra M11–M14 absent from the reference geometry | Remove these four dummy instances and their local wires/labels in the matched schematic; retain the twelve implemented MOS instances |

| Tap | Connection | Repaired active area (µm²) | Perimeter (µm) |
|---|---|---:|---:|
| R1 | VDD to input-pair NWell | 28.1356 | 181.52 |
| R2 | VSS to input-stage substrate | 8.559 | 57.06 |
| R3 | VDD to bias-stage NWell | 6.9626 | 44.92 |
| R4 | VSS to output-stage substrate | 30.288 | 201.92 |
| R5 | VDD to output-PMOS NWell | 26.815 | 173.00 |

Native LVS reports **Match** against the matched schematic's raw CDL export.
The CDL contains 12 MOS instances; native LVS combines parallel instances.
The unmodified upstream schematic contains 16 MOS instances and has no explicit
tap dimensions. With the current Xschem and pinned PDK symbols, those taps
inherit 0.78 × 0.78 µm defaults. Neither that population nor those tap geometries
represent this reference. The earlier literal `?` export failure arose from the
old Xschem environment, not from a missing physical device specification in the
matched derivative.

The repaired reference is ready to read directly. No repair generator is required.

### Matched Schematic and Reproducible Exports

The matched source preserves the upstream drawing's core circuitry and the six
ordered ports. It removes M11–M14, retains M8/M10/M15/M16, and keeps the existing
MOS/MIM dimensions and multiplicities. M5/M7 and R1–R5 are renamed to match the
case's established instance correspondence; `well`, `well2`, `well1` and `sub!`
become `bulk`, `bulk1`, `bulk4` and `bulk2` respectively. Both NMOS stages share
`bulk2`; the output-PMOS tap connects VDD to `bulk4`. The capacitor connects
DN4 to VOUT, matching the repaired route. This source targets the case reference,
not the defective original GDS.

The case-local [ntap symbol](source/sg13g2_case/ntap_ap.sym) and
[ptap symbol](source/sg13g2_case/ptap_ap.sym) derive from the pinned PDK symbols,
retain their notices and terminal order, and take explicit active area `A` and
perimeter `P`. These parameters describe the physical rings listed above;
they are not equivalent rectangular W/L dimensions. Their LVS format emits
native tap A/P cards. Their simulation format calls the unchanged PDK tap model
with `a`, `p` and `r = 1/(A/9.8e-10 + P/9.8e-4)`. Xschem evaluates resistance
with native `ev7`; exported netlists are not rewritten. The PDK itself is unchanged.

`[source_export]` in [case.toml](case.toml) pins the derivative schematic
and the two local tap symbols; the native MOS/MIM symbols come from the
referenced `pdk.toml#xschem-symbols` profile (`pdk_profile`). Only exported
circuit materials enter the solver task; the source drawing and local symbols
remain maintainer assets. To export CDL from a clean checkout with the tools
image and pinned PDK initialized, run from the repository root:

```bash
uv run --locked python -m benchmarking.prepare \
  tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/full_OTA/case.toml \
  build/runs/full-ota-matched-export \
  --checkout case=tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/full_OTA \
  --checkout pdk=third_party/IHP-Open-PDK
uv run --locked pytest tests/integration/test_matched_schematic_exports.py
```

Use a fresh export directory. The command creates raw `circuit.cdl`, provenance
and the Xschem log. The regression additionally exports `circuit.spice` using
the simulation format, checks both frozen files byte-for-byte, compares their
unsimplified device graphs through the native PDK reader/model-call adapter,
and independently checks tap geometry and the resistance formula.


## PEX and Calibration

The evaluation scope is nominal AC/DC: VDD=1.2 V, VSS=0 V, input DC level
0.6 V, an 80 µA sink at `iout`, 500 fF output load, `mos_tt`, `cap_typ`,
`res_typ`, and 27 °C. The upstream 4 GH / 4 GF feedback fixture establishes DC
bias while opening the AC loop. The sweep is 100 points/decade from 1 Hz to
10 MHz. Both pre-layout and post-layout analysis use `rshunt=1e12`.
[problem.md](problem.md) and the delivered testbench define the measurements
and power boundary.

The shared [analog model profile](../../../../../tasks/ihp-sg13g2/pdk.toml)
contains the pinned MOS, capacitor and resistor dependency closure, license
notices, compiled OSDI models and startup settings. Upstream model bytes are
unchanged. `cap_cmim` uses the PDK plate model and 55 mΩ series resistance;
pre-layout taps use the PDK area/perimeter resistance formula.

### Extraction Requirements

The original layout fails the RC interface check with nine ports instead of
six, substrate-tile warnings and failed differential-input wire searches.
Those problems disappear after repair. Unsafe `v-` and `v+` names are aliased
only in the geometrically checked extraction copy.

The extraction and simulation environment requires two adaptations:

| Issue | Cause | Implementation |
|---|---|---|
| Floating capacitive pwell nodes | Two extracted well nodes have capacitive connections but no DC path, causing a singular operating-point problem. | The testbench uses ngspice `rshunt=1e12`, providing a 1 TΩ path from every analog node to ground, identically for pre/post analysis. PEX bytes remain unchanged. |
| Missing resistance on DN3 and DN4 | Magic 8.3.678 truncates W/L during driver selection in `ResProcessNode`, omitting these internal nets whose drivers have W/L below one. | The shared Dockerfile changes the accumulator and maximum to floating point. The RC regression checks an independently calculated wire-resistance increment between two low-W/L devices. |

The tool change follows the pinned
[Magic reader](https://github.com/RTimothyEdwards/magic/blob/8.3.678/resis/ResReadExt.c)
and [driver selection](https://github.com/RTimothyEdwards/magic/blob/8.3.678/resis/ResRex.c).
The [Dockerfile](../../../../../Dockerfile) applies the correction with an exact
source-match assertion; [the regression](../../../../../tests/integration/test_magic_rc.py)
measures the extracted wire using idealized channel models to separate its
resistance from transistor/body-bias effects. No PDK rules were patched.

The [ngspice manual](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf),
section 11.1.2.1, describes `rshunt` for capacitive nodes without a DC ground
path. This numerical conditioning is part of the declared simulation conditions.

The repaired GDS now expands all six interface nets and all three
transistor-bearing internal nets into resistance networks. The two capacitive
pwell nodes remain without drivers and use the conditioning above. The
extractor checks interface ports and preserves candidate geometry during
preparation. Grid-rescaling notices reflect Magic input-grid refinement.

### Schematic Exports and Matched-Condition Results

[materials/circuit.cdl](materials/circuit.cdl) supplies the native LVS circuit.
[materials/circuit.spice](materials/circuit.spice) supplies pre-layout simulation
from the same matched schematic. Both preserve MOS `w`, `l`, `ng`, `m`,
MIM dimensions/multiplicity, and all five tap connections and A/P parameters.
The native PDK reader and reviewed model-call adapter independently establish
their device-graph equivalence without simplifying the simulation input.

Calibration uses the simulator export, KLayout 0.30.11, Magic 8.3.678 with the
driver-selection correction, and ngspice 42 in the shared tools image.

| Metric | Pre-layout | Post-layout | Acceptance limit |
|---|---:|---:|---:|
| Low-frequency gain | 70.119 dB | 69.991 dB | ≥60 dB |
| Unity-gain bandwidth | 4.149 MHz | 4.081 MHz | ≥3 MHz |
| Phase margin | 61.277° | 60.004° | ≥55° |
| Quiescent VDD power | 197.041 µW | 197.035 µW | 0–220 µW |
| DC output bias | 0.59963 V | 0.59971 V | 0.55–0.65 V |

Both runs use byte-identical testbench material, the same model bundle and
simulation image. Post-layout simulation consumes the exported PEX netlist
byte-for-byte, bound to the same GDS that passed physical checks. Independent
calculations from raw complex node voltages and VDD current agree with every
reported measurement within printed precision. Each sweep contains one downward
unity crossing; the low-frequency phase confirms the feedback polarity.

The numerical limits are benchmark requirements for this operating point;
the upstream lesson does not specify them for the repaired OTA. They require
at least 1000 V/V gain, MHz-class bandwidth and nominal feedback stability,
while bounding supply current and keeping the output near mid-supply. The
output-bias window is not an offset or mismatch specification. Calibration
establishes feasibility with margin, without making the reference an optimum
or scoring denominator.

## Validation Scope

The reference passes the complete evaluation with zero findings in both DRC
decks and matching LVS. Its functional outline is 69.665 × 39.095 µm, within
the 80 × 50 µm limits, and its reported bounding-box area is 2723.553175 µm².
Area has no additional threshold or weighted score.

The [integration checks](../../../../../tests/integration/test_full_ota.py) exercise
the reference and source calibration through the same case definitions and
reviewed support bundles. They also confirm that the original GDS fails DRC/LVS,
blocking geometry, PEX and simulation. A 90-degree rotation of the repaired
reference passes DRC/LVS but exceeds the height limit; geometry rejects it and
blocks PEX and simulation. The
[performance boundary checks](../../../../../tests/unit/test_full_ota_contract.py)
use synthetic tool measurements to verify each inclusive limit and rejection
immediately outside it. These decision checks do not constitute a physical
performance counterexample.

CMRR, PSRR, large-signal settling/slew, noise, PVT and mismatch remain outside
the nominal scope. Native Magic well/substrate modeling, including the
explicit conditioning above, is the declared extraction scope; this is not
foundry substrate/noise or tape-out signoff. Dedicated repeatability and a
complete counterexample suite, including a physically valid layout that fails
performance, have not been performed. The `qualified` designation applies to
this development scope, with these deferrals; it does not satisfy the full
formal-use checklist in the [qualification guide](../../../../../docs/tasks.md#qualification).

## Reproduce the Checks

Run from the repository root after following the
[tool setup instructions](../../../../../docs/tools.md#manual-tools). Initialize
the pinned PDK as described in the [resource setup guide](../../../../../docs/tools.md#external-sources).
Prepare the case's support bundles once if absent; use a new output directory
for each evaluation. Existing frozen bundles are not updated in place.

```bash
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml#klayout build/support/full-ota-klayout-spice
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml#magic build/support/full-ota-magic
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml#analog-models build/support/full-ota-models
uv run --locked python main.py evaluate tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/full_OTA/case.toml tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/full_OTA/reference/two_stage_OTA_layout.gds --output build/runs/full-ota-reference
```

The reference evaluation exits **0** and sets `physical_valid`, `specs_pass`
and `task_success` to `true`. Replace the reference GDS path with a candidate
GDS to score another answer. Standard solves use the outer
[run configuration](../../../../../docs/running.md#offline-cli) to provide the
harness and reviewed solver resources; only the case's declared task inputs
are materialized for the solver.

To reproduce source/post-layout calibration and the minimal rejection checks,
run the integration suite with the tools image and pinned PDK available:

```bash
git submodule update --init --depth 1 third_party/IHP-AnalogAcademy
uv run --locked pytest tests/integration/test_matched_schematic_exports.py \
  tests/integration/test_full_ota.py --basetemp build/runs/full-ota-validation
```

Choose a fresh `--basetemp` directory because pytest replaces its contents.
The suite prepares its own support bundles and writes per-test reports,
including `pre` and `post` calibration results. Calibration derives the nominal
simulation job from `case.toml` and uses the delivered `materials/circuit.spice`;
both simulations use the case's backend settings and public testbench.

The original-asset check remains available independently:

```bash
git submodule update --init --depth 1 third_party/IHP-AnalogAcademy
uv run --locked python -m benchmarking.upstream tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/full_OTA/case.toml --support build/support/full-ota-klayout-spice --output build/runs/full-ota-original
```

That command uses the original GDS/CDL, exits 1 and reports DRC/LVS rejection.
Submitting the original GDS through the case evaluator against the corrected
circuit also fails DRC/LVS and blocks PEX and simulation.

Each evaluation creates its own `report.json`, native logs and archived inputs
under the requested output directory. Those generated reports record the actual
image and support-bundle identities for the reader's run.

The reported success applies to the published nominal task requirements and
the validation scope above.
