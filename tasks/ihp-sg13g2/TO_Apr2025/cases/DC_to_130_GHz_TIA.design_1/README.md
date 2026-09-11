# DC–130 GHz TIA, design 1

This is a source candidate, not an executable or qualified layout task.
[case.toml](case.toml) binds all selected inputs and historical evidence to
TO_Apr2025 commit `63e203a0eccfb6028a1a0a8364553e4e979b55b3`.
The [upstream project](../../../../../third_party/TO_Apr2025/DC_to_130_GHz_TIA/README.rst)
explicitly declares Apache-2.0, consistent with the root license; PDK/model/tool
licenses remain separate; the collection and materials retain the Apache-2.0
license. The editable core derivative below is supplied; the upstream GDS is
unchanged and is not a passing witness. A separately identified, physically
clean repair proposal is supplied below for review; it is not a qualified task
witness.

## Source versions and circuit correspondence

Paths below are relative to upstream `DC_to_130_GHz_TIA/design_1/`.

| Material | Version and limitation |
| --- | --- |
| `design_data/qucs-s/DC_to_130_GHz_TIA.sch` | Qucs 25.1.2 document; includes the circuit, two independent 2 V sources, 50-ohm RF ports, external 5 uF blocking capacitors, probes and four EM S2P blocks |
| `design_data/lvs/TOP.cdl` | Header identifies Qucs 25.1.0 and an unavailable `lvs_check_copy1.sch`; top-level wrapper calls, no `TOP` subcircuit; joins both supplies as `VCC2V`; not a demonstrated export of the published schematic |
| `design_data/lvs/LVS_Check_Netlist.cdl` | Author-labeled modified Qucs netlist; portless `TOP`, separate `VCC2V`/`VCC2V1`, explicit tap and legacy primitive cards; this is the original-evaluation reference |
| `design_data/lvs/TOP_extracted.cir` | Explicitly KLayout-extracted; uses `VDD2V`/`VDD2V$1` and `VSS`; diagnostic layout evidence, never a schematic export |
| `design_data/gds/FMD_QNC_03a_DC_to_130_GHz_TIA_Design.gds` | Top `FMD_QNC_03a_TIA_1`; physical bounding box 760 × 900 um; this is not an adopted area constraint |
| `design_data/lvs/DC_to_130_GHz_TIA.lvsdb` | Historical `TOP` circuits; historical rule identity and exact GDS pairing remain unverified |
| `design_data/qucs-s/DC_to_130_GHz_TIA.dat.ngspice` | Qucs dataset 25.1.2; historical operating-point/RF results, without a complete reproducible run identity |
| `design_data/openEMS/s2p files/` | `INPUT.s2p`, `RF_OUT.s2p`, `272em.s2p`, `254em.s2p`; all four schematic filenames are available and digest-bound |

The published schematic and design description specify HBT multiplicities
Nx=5 and Nx=4, collector/feedback/load `rppd` W/L values of 15/4, 29/6.3 and
11.5/2 um, and two 30 × 30 um MIM capacitors. Independent extraction of the
original GDS with the current pinned runset confirms that HBT/resistor core,
including stage-one collector to stage-two base connectivity. It identifies
five ports: `INPUT`, `OUTPUT`, `VCC2V`, `VCC2V$1`, `VEE`. Supply conductors are
separate; all three resistor substrates and both HBT emitter/substrate pairs
connect to VEE. The extracted tap has A=3.6504 um² and P=18.72 um.

The source audit identified two distinct issues:

- Current extraction places the two capacitor upper terminals on separate
  internal nets, outside the supply/core nets. The author's LVS reference and
  archived extracted circuit put them on the supplies. This establishes a
  physical connectivity defect, independently confirmed by metal/via tracing
  below. The derivative preserves the intended supply decoupling; it does not
  make the capacitors float to obtain LVS agreement.
- Relocating the old Qucs library paths to current PDK libraries is insufficient.
  A native Qucs-S 26.1.1 export succeeds in both CDL and ngspice modes, but the
  new `rppd` bulk pins are unconnected, and device pin locations differ from the
  old wires. CDL mode also retains XSPICE transfer-function blocks from the
  RF test circuit. A `.cdl` extension does not make this a usable LVS netlist.

The Qucs path-only probe remains a diagnostic of the original source. The
case instead supplies a separately identified Xschem derivative; it does not
replace or modify the original Qucs bytes.

## Editable core derivative and exports

[source/FMD_QNC_03a_TIA_1.sch](source/FMD_QNC_03a_TIA_1.sch) redraws the
published two-stage circuit with explicit connections and current PDK symbols.
Its subcircuit is `FMD_QNC_03a_TIA_1`, with ordered interface
`INPUT OUTPUT VCC2V VCC2V1 VEE`. `VCC2V1` names the second independent supply;
the original GDS repeats `VCC2V` on both physical conductors, and the native
SPICE writer disambiguates the second as `VCC2V$1`. No GDS labels were changed.

| Device | Retained circuit / explicit adaptation |
| --- | --- |
| Q1 / Q2 | `npn13G2`, Nx=5 / 4; fixed 0.07 × 0.9 um emitter geometry; C/B/E/S ordering; emitters and substrates at VEE |
| RC1 | `rppd`, W/L=15/4 um; VCC2V to DN1, substrate VEE |
| RC2 | `rppd`, W/L=11.5/2 um; VCC2V1 to OUTPUT, substrate VEE |
| RF | `rppd`, W/L=29/6.3 um; DN1 to INPUT, substrate VEE |
| C1 / C2 | `cap_cmim`, 30 × 30 um, m=1; respective supply to VEE, preserving the intended circuit |
| RTAP | VEE tie/substrate, A=3.6504 um² and P=18.72 um, supported by both the author LVS reference and current physical extraction |

Q1 collector drives Q2 base at DN1. The two supplies remain distinct. Device
parameters have not been adjusted to reference simulation results. HBT `Nx`
is used once; legacy `NE` and `m` values are not multiplied together.
External RF ports, blocking capacitors, probes and S2P blocks are outside this
core schematic. This separation does not qualify an RF extraction boundary.

The native PDK HBT/MIM symbols are unchanged. Two local symbols retain PDK
notices and document their formatting changes:

- [rppd_lvs.sym](source/sg13g2_case/rppd_lvs.sym) derives from the pinned PDK
  `rppd.sym`. Its LVS format emits a native three-terminal geometry card,
  avoiding an unevaluated `expr_eng(...)` resistance expression. Its simulation
  format, dimensions and body property are unchanged; the native PDK reader
  accepts the exported three-node circuit without a reader or rule patch.
- [ptap_ap.sym](source/sg13g2_case/ptap_ap.sym) reuses the maintained
  AnalogAcademy A/P symbol adaptation. It exports explicit physical A/P for
  LVS and the unchanged PDK tap model with
  `r=1/(A/9.8e-10+P/9.8e-4)` for simulation. It describes a physical ring,
  rather than inventing equivalent rectangular dimensions.

[materials/circuit.cdl](materials/circuit.cdl) and
[materials/circuit.spice](materials/circuit.spice) are raw exports of this
same schematic using Xschem 3.4.7's LVS and simulation formats. Netlists are
not postprocessed. The case's `[source_export]` pins every case-staged source
by digest, with PDK symbols supplied by the referenced `pdk.toml#xschem-symbols`
profile (`pdk_profile`); `[assets]` binds the derivative and material bytes. These
remain maintainer assets because no solver task or acceptance plan is frozen.

Reproduce CDL and both-format consistency checks from the repository root:

```bash
uv run --locked python -m benchmarking.prepare \
  tasks/ihp-sg13g2/TO_Apr2025/cases/DC_to_130_GHz_TIA.design_1/case.toml \
  build/runs/to-design1-export \
  --checkout case=tasks/ihp-sg13g2/TO_Apr2025/cases/DC_to_130_GHz_TIA.design_1 \
  --checkout pdk=third_party/IHP-Open-PDK
uv run --locked pytest tests/integration/test_to_apr2025_schematic.py
```

Use fresh output directories. The exporter records the source commits and
hashes, image ID, command, Xschem version and raw output digest. The integration
check independently exports SPICE, records its identity and inputs, compares
both frozen files byte-for-byte, parses CDL with the current native PDK
reader, and checks both graphs against the stated circuit and tap formula.

## Capacitor connection defect

Comparing the original GDS against the derivative CDL completes with native
`NoMatch`: Q1, Q2, RC1, RC2, RF and RTAP are individually `Match`; C1 and C2
are `Mismatch`. This is a completed electrical comparison, unlike the old
CDL reader error. The original compare-only port profile is retained for
this diagnostic; it is not a qualified named-port delivery policy.

Independent conductor tracing, without device extraction or simplification,
finds the following two unconnected TopMetal1-to-TopMetal2 pad transitions
(coordinates in um in the original GDS):

| Capacitor MIM rectangle | TM1/TM2 overlap at supply pad | Passivation opening |
| --- | --- | --- |
| (303,641)–(333,671) | (362,698)–(412,748) | (364,700)–(410,746) |
| (449,125)–(479,155) | (376,45)–(426,95) | (378,47)–(424,92) |

Each capacitor upper plate reaches the underlying TopMetal1 route through
VMIM. Each route overlaps a 50 × 50 um TopMetal2 region labeled `VCC2V`,
but neither route intersects any TopVia2. Their connected TopMetal2 area is
zero. Overlapping metal on different layers is insufficient for a connection.
This explains the original GDS capacitor mismatches independently of
the historical database. The repair proposal below reconnects both paths.

Any repair must respect the pad opening as well as via width, spacing and
enclosure. The PDK's TopVia2 rules specify 0.90 um cuts, 1.06 um spacing and
0.50 um TM1/TM2 enclosure. The maximal deck's recommended pad rules also
address via placement outside the opening and 1.40 um TM1 enclosure. Simply
placing a via array at the pad center would ignore that packaging restriction.

## Core operating-point check

[materials/testbench.spice](materials/testbench.spice) is a shared-form DC
bench that consumes `circuit.spice`. It applies the source's two independent
2 V supplies at 26.85 °C, with `hbt_typ`, `res_typ` and `cap_typ`. There is no
external DC input/output load: the source RF ports are DC-blocked. The bare
core omits the reference EM networks, including their DC resistance. It does
not reproduce the archived full RF simulation and sets no performance limits.

[tasks/ihp-sg13g2/pdk.toml](../../../../../tasks/ihp-sg13g2/pdk.toml)
pins the unmodified PDK HBT/resistor/capacitor include closure at commit
`5e6d592e4002946a4616f798c357f0f3c06cf3b6`. HBTs use ngspice's native VBIC;
R3_CMC and the capacitor-library MoM dependencies are compiled with OpenVAF.
R3_CMC's original ECL-2.0 license, IHP adaptation notices and NOTICE file are
retained, alongside the PDK license. Availability of mismatch/statistical
sections in the closure does not establish validation of those corners.

With ngspice 42, the nominal source check gives INPUT=0.949977 V,
OUTPUT=1.340087 V, and supply currents 14.16384 mA and 12.86757 mA. The
integration test checks finite simulator output, real model loading, both
supply sources and measurement agreement with the raw operating-point data.
These values are observations, not threshold definitions or qualification
results. No post-layout calibration has been performed. The repair proposal passes
physical checks, but its RF boundary and extraction/port contract remain open;
the DC bench alone cannot qualify RF behavior.

The `[toolchain]` in `case.toml` binds the diagnostic LVS and simulation
backends. Their support bundles can be prepared independently:

```bash
uv run --locked python -m benchmarking.prepare_support \
  third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml#klayout build/support/to-design1-klayout
uv run --locked python -m benchmarking.prepare_support \
  third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml#hbt-models build/support/to-design1-models
```

The integration tests prepare their own fresh bundles and retain their native
LVS and operating-point reports under pytest's output directory. They do not
require local reports or pre-existing support bundles from a maintainer.

## Physical validation and reproduction

Use the [collection commands](../../README.md#reproduce-the-source-checks)
with this case. The original GDS passes artifact validation. Current main plus
extra DRC reports 110 unwaived items: LU.b 72, Pad.fR_M1 15,
`topmetal2_drw_Angle45` 9, M1Fil.a2 4, M1.f 3, Pas.c 3, M1.i 2,
GFil.i 1 and Pad.fR_TM1 1. Against the archived author CDL, LVS stops at
the current reader's three-node poly-resistor requirement before comparison.
Against the new schematic export, comparison completes with the two capacitor
mismatches described above. No waiver or PDK edit is applied.

The archived minimal/maximal databases contain 2/1 items (M1Fil.h/k and
TM2.c/d), despite the upstream validation text claiming zero errors. Their
scope is not today's main plus extra deck scope.

Run the maintained source checks from the repository root:

```bash
uv run --locked pytest tests/integration/test_to_apr2025_source.py
```

The tests exercise physical error reporting, native `net_only` extraction
without any reference-netlist input, core connectivity and the capacitor
mismatch, and both native Qucs export dialects. The Qucs check records the
original and staged input digests, resolved image identity, tool version,
output netlists and logs in its pytest temporary directory. To retain those
newly generated diagnostics at a chosen location, add
`--basetemp=build/runs/to-source-tests` using a new directory (pytest clears
an existing basetemp directory). No local report is a published qualification
credential.

## Complete physical repair proposal

[reference/drc-clean-proposal.gds](reference/drc-clean-proposal.gds) is a
ready-to-inspect derivative of the pinned upstream GDS, digest-bound as an
`unqualified-reference-layout` in `case.toml`. It is a consolidated design
proposal, not an accepted RF implementation or a qualified benchmark witness.
It retains Apache-2.0 under the collection license. The following table records
its modifications to the original design; the original upstream bytes are
unchanged. Coordinates are in um unless identified as TIA-local.

| Original finding | Repair in the proposal | Design impact |
| --- | --- | --- |
| Two disconnected capacitor upper terminals | Add TM1/TM2 landing rectangles (355,718)–(364,728) and (424,64)–(433,74), each with a 2×4 array of 0.90 um TopVia2 at 1.96 um pitch; cuts remain outside passivation | Restores the schematic's supply decoupling; the longer landings satisfy the 7 um pad-exit recommendation |
| `LU.b`: 72 | Remove the six auxiliary cross/grid mark groups drawn directly in top-level Activ/Cont: 36 Activ shapes and 72 Cont shapes; preserve all hierarchical functional Activ/Cont geometry | Removes auxiliary mark features, not HBTs or substrate ties; manufacturing/alignment acceptance of this removal is a required review decision |
| `M1.f`: 3 and `M1.i`: 2 | Trim three local metal boundaries and the small 45° corner; remove the 33-cut V1 row exposed by one narrower landing | Preserves connectivity and device parameters; changes interconnect resistance/current capacity |
| `M1Fil.a2`: 4 | Segment four long seal-ring Metal1 filler rails into pieces no longer than 4.9 um, at 6 um pitch | Retains their location and 4.2 um transverse width; lowers local dummy-metal coverage; density is not qualified by this check |
| `Pas.c`: 3 and eight RF-pad non-45° edges | Enclose the unchanged 75×40 um RF passivation openings with 79.2×50 um rectangular TM2 pads and matching physical `dfpad` outlines | Changes RF pad metal geometry; the two previously missing pad outlines now identify actual metal surrounding actual openings, with no device underneath; RF/packaging review required |
| Ninth TM2 non-45° edge | Fill the small output-metal bevel to an orthogonal boundary | Changes a local wire shape, with no connectivity change |
| `Pad.fR_M1`: 15 | Close small ground-grid gaps at pad exits, then introduce 17 real 2.8×16 um holes in broad ground rails, clear of required exits | Meets exit and metal-width rules together; the holes are subtracted from drawing geometry, not merely represented by markers |
| `Pad.fR_TM1`: 1 | Extend the existing second-supply TM1 exit at (421.685,99.7)–(423.685,101.6) | Meets the 7 um exit recommendation |
| Output-pad exit interaction | Add the TM2 exit rectangle (620,422)–(632,430.3) | Meets TM2 spacing and pad-exit rules together after the RF pad change |
| `GFil.i`: 1 | Narrow/separate the oversized connected GatPoly nofill region with the corridors (440,290)–(450,518), (180,290)–(710,298), and (180,509)–(710,518) | Each remaining connected keepout fits within 400×400 um; existing GatPoly/Activ filler geometry is unchanged, including filler already in the corridors; future fill regeneration must use the revised keepout intent |

The auxiliary mark group bounding regions are near (260,146)–(285,171),
(523,164)–(548,189), (568,568)–(593,593), (513,581)–(539,607),
(481,626)–(507,651), and (237,630)–(262,655). They are not declared
circuit devices. Removal must not be interpreted as a foundry statement that
such marks are unnecessary.

The M1 trims in the original TIA cell frame are
(977.2,413.06)–(1002,414.4), (975.5,384.925)–(992.6,385.225), and
(959.8,435.9)–(972.9,436.36). The proposal additionally trims the instantiated
landing at top coordinates (391.2,382.98)–(408,383.28), with the exposed V1
row removed, and the small corner at (411.95,408.86)–(412.025,408.93).
No resistor W/L, HBT multiplicity, MIM dimensions, tap A/P, source netlist,
passivation opening, external port label or chip bounding box is changed.
The proposal is flattened; hierarchy flattening is checked by geometric
comparison rather than assumed to preserve devices.

### Reproduce and interpret the physical result

Use the pinned PDK and unified tools image, then run from the repository root:

```bash
uv run --locked pytest tests/integration/test_to_apr2025_schematic.py
```

This exports both schematic netlists, runs the nominal core simulation,
reproduces the original capacitor failure, checks the proposal's layer and
label changes, and evaluates the supplied proposal using the case's toolchain.
The physical proposal test requires both native DRC databases to be empty,
requires all eight devices to match in the native LVS cross-reference, and
requires `physical_valid=true` with `task_success=null`. Fresh reports are
generated by the test; no unpublished maintainer report is required.

With the declared KLayout 0.30.11 / pinned PDK environment, the supplied GDS
passes artifact validation, the current main DRC deck with **0 items**, the
additional maximal deck with **0 items**, and native LVS against
`materials/circuit.cdl`. The existing `drc-upstream.json` profile is unchanged:
main plus extra/maximal scope, with density and antenna disabled as in the
original audit. No waiver, runset edit or check-switch change is used.
This is zero DRC in that declared scope, not full foundry signoff.

The existing compare-only LVS policy remains in use. Both original supply
conductors still carry the label `VCC2V`; native SPICE disambiguates the second
as `VCC2V$1`. Its correspondence to schematic `VCC2V1` is established by the
circuit comparison, not by a qualified named-port contract. RC extraction must
resolve that interface explicitly; it must not silently alias the supplies.

## Remaining circuit and qualification decisions

The complete proposal demonstrates a physically clean option with the fixed
core circuit. Its mark removal, RF-pad changes, ground-grid slots, via-row
reduction, filler segmentation and nofill intent need review together before
adopting it as the reference implementation. Physical feasibility does not
approve those manufacturing/RF tradeoffs or freeze task constraints.

The upstream specification lists transimpedance bandwidth ≥130 GHz,
transimpedance gain ≥40 dB-ohm, S21 gain ≥10 dB, S11/S22 ≤−10 dB and group
delay ≤8 ps. These are source design targets, not approved benchmark limits;
frequency intervals and measurement definitions still need to be frozen.
The schematic uses 26.85 °C, two 2 V sources and a 100 MHz–170 GHz RF sweep.
Its external blocking capacitors and EM networks belong to a specifically
chosen RF test boundary, not automatically to the on-chip LVS circuit.

A candidate's RC extraction cannot reuse reference S2P files as if they came
from that candidate. The HBT model bundle validates nominal core operation, not the source RF/EM
flow. RC-only validation
has not been shown adequate for its 130 GHz transmission lines and pads;
RF/EM qualification and any narrower characterization scope need an explicit
design decision. No pre/post simulation calibration, accepted performance
limits, geometry contract, accepted witness or qualification claim is supplied.
