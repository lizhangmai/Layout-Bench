# Input Pair Layout Case

This case contains a physically verified reference for the SG13G2 common-centroid
PMOS input pair from IHP AnalogAcademy's Module 1 OTA layout lesson.
[case.toml](case.toml) records the pinned schematic, CDL, GDS and extracted
netlist. [materials/circuit.cdl](materials/circuit.cdl) is a byte-for-byte
copy of the new Xschem export of the unchanged source schematic. The repaired
[reference GDS](reference/input_common_centroid.gds) passes artifact, DRC and LVS
checks against this circuit. The [integration regression](../../../../tests/integration/test_input_pair_source.py)
reproduces the physical checks through the framework API.

The case remains **candidate**, with physical verification and nominal input-admittance
characterization. It has no solver task definition or post-layout performance
qualification. The five-port
interface and all schematic device parameters are fixed; `dn2` remains internal.

## Source and License

| Identity | Value |
|---|---|
| Source | IHP AnalogAcademy, Module 1, Part 3, `OTA_layout/input_pair` |
| Source commit | `133ecf657572e021b5921b5a1b7693abfb209623` |
| License | [Apache-2.0](../../LICENSE); upstream file-level notices apply |
| PDK commit | `5e6d592e4002946a4616f798c357f0f3c06cf3b6` |
| Top cell / subcircuit | `input_common_centroid` |
| Original CDL SHA-256 | `329e60bdfd1b64087bd6b147911f508ce30132ecceaa5ff6da11606bc0eb3595` |
| Original GDS SHA-256 | `72e3412c6f11b713088d9ce6f5e1b143e4485857368f5324be75f6862704e09e` |

The [layout lesson](../../../../third_party/IHP-AnalogAcademy/modules/module_1_bandgap_reference/part_3_layout/README.md)
provides the circuit context. The manifest identifies the exact files and
their digests. The schematic is the design authority; archived extraction is
diagnostic evidence. The archived CDL is not a verified export
of the current schematic; the source comparison below identifies a tap mismatch.
The reference repairs the layout to match the schematic, without editing the
schematic, PDK or exported CDL. The material retains its `.cdl` extension and
native PDK LVS dialect; it is not directly compatible with ngspice.

## Circuit and Interface

The original ordered interface is `v- v+ vdd dn3 dn4`.

| Node | Role |
|---|---|
| `v-`, `v+` | Gates of M1 and M2 respectively |
| `dn3`, `dn4` | Drain outputs of M1 and M2 respectively |
| `vdd` | Well-tap supply and dummy gate/source connections |
| `dn2` (internal) | Shared source of M1/M2 and drain of M15/M16; absent from the port list |
| `bulk` (internal) | PMOS well, connected to `vdd` through explicit tap R1 |

All six MOS instance cards use `sg13_lv_pmos`, `l=3.7u`, `w=3.64u`,
`ng=1`, `m=2`. M8/M10 and M15/M16 retain their upstream dummy connections.
The schematic, CDL and archived extracted circuit all leave `dn2` internal.
The dummy gates and sources connect to `vdd`; they do not supply a defined
tail-current bias for a standalone differential-pair performance test.
An independently biased task therefore needs an explicit interface decision
before defining transconductance, balance or bandwidth requirements.

## Re-export and Compare the Schematic

The case's `[source_export]` manifest supplies only the original `.sch` and the
two required, checksum-pinned PDK symbols to Xschem. Built-in port and label
symbols come from the tools image. No layout or extracted netlist enters export.
Rebuild the shared image, then run from the repository root with a fresh output
directory:

```bash
uv run --locked python scripts/public_preview.py build --network host
uv run --locked python -m benchmarking.prepare \
  tasks/IHP-AnalogAcademy/cases/input_pair/case.toml \
  build/runs/input-pair-source-export \
  --checkout analogacademy=third_party/IHP-AnalogAcademy \
  --checkout pdk=third_party/IHP-Open-PDK
uv run --locked pytest tests/integration/test_input_pair_source.py
```

Use `--network default` for the build if a host-local proxy is not needed.
The export command creates `input_common_centroid.cdl`, `provenance.json` and
`netlist.log` in the specified output directory. Provenance records the actual
image, Xschem version, command, input commits/digests and untouched export digest.
The regression additionally reads the fresh and archived CDL with the pinned
native PDK reader, without extracting a layout or simplifying either circuit.

| Item | Fresh schematic export versus archived CDL |
|---|---|
| Interface | Same five ordered ports: `v- v+ vdd dn3 dn4` |
| MOS population and connectivity | Same six instance cards and connections, including internal `dn2` |
| MOS parameters | Same `w=3.64u`, `l=3.7u`, `ng=1`, `m=2` on every card |
| Instance names | Current symbols prefix the names: `M1` becomes `MM1`, `R1` becomes `RR1`; these are names, not extra devices |
| Tap connectivity | Same `vdd` to `bulk` connection |
| Tap geometry | Different, as shown below |

The original schematic explicitly gives R1 `w=13e-6`, `l=34e-6`. The unchanged
PDK `ntap1.sym` defines `A=w*l` and `P=2*(w+l)`, so Xschem emits
**A=442 µm², P=94 µm**. These are schematic-derived rectangular dimensions,
not measurements of the layout's tap ring.

| R1 parameter | Fresh schematic export | Archived CDL | Original layout extraction |
|---|---:|---:|---:|
| Area (µm²) | 442 | 197.9248 | 28.7556 |
| Perimeter (µm) | 94 | 243.6 | 185.52 |

The archived CDL's tap values therefore do not reproduce this schematic with
the pinned symbols. Their historical derivation remains unverified. The archive
remains recorded under `upstream_assets`; `materials/circuit.cdl` now contains
the untouched new export. No layout-derived numbers replace schematic parameters.

The tools image uses native Xschem `ev7` support. The previous Ubuntu Xschem
package could emit a bare `?` instead of the tap while returning success,
because that helper was absent. This is an export-environment incompatibility,
separate from the three different tap geometries above. The source regression
rejects missing taps and checks area/perimeter against the schematic dimensions.

## Layout Correspondence and Tap Geometry

Native LVS of the original GDS against the fresh schematic export reports `NoMatch`. All five
external pins and the internal `dn2` net match. All MOS device pairs match
after native parallel simplification; M15/M16 become one equivalent device.
The R1 pair reports `MatchWithWarning` with different A/P parameters; its
adjacent VDD/BULK networks are marked `Mismatch`. This identifies a tap
discrepancy, rather than evidence for a different differential-pair topology.

The original GDS explains the numerical difference independently of the CDL.
KLayout region measurements on merged drawing layers give:

| Region | Geometry | Area (µm²) | Perimeter (µm) |
|---|---|---:|---:|
| NWell, `31/0` | Rectangle from `(21.650,-25.095)` to `(55.650,-12.095)`, 34 × 13 µm | 442 | 94 |
| Tap active ring, `1/0` | Same outer rectangle; opening from `(21.960,-24.785)` to `(55.340,-12.405)`, 33.38 × 12.38 µm | 28.7556 | 185.52 |

The ring width is 0.31 µm. Its area is
`34*13 - 33.38*12.38 = 28.7556`; its total inner-plus-outer perimeter is
`2*(34+13) + 2*(33.38+12.38) = 185.52`.
These independently measured quantities agree exactly with native tap
extraction. The schematic's dimensions instead equal the NWell/ring outer
bounding box; the rectangular tap symbol does not subtract the opening or
include its inner perimeter. This is a geometry-modeling discrepancy, not
evidence that the extractor confused the MOS topology.

The public history supports the same input-pair lineage:

- The [January 2025 layout upload](https://github.com/IHP-GmbH/IHP-AnalogAcademy/commit/2031391a13ef8410cffedb7c61a7fcd1be0b90fd)
  already contains the same ring area/perimeter and a schematic with R1
  `w=13e-6`, `l=34e-6`. Later saved versions retain those dimensions.
- The [March 2025 version](https://github.com/IHP-GmbH/IHP-AnalogAcademy/tree/95190cc4d5ef56a4234f132866ac5830cf0059e8/modules/module_1_bandgap_reference/part_3_layout/OTA_layout/input_pair)
  contains the exact schematic and GDS bytes used by this case. The archived
  CDL's differing tap values already appear in the
  [February version](https://github.com/IHP-GmbH/IHP-AnalogAcademy/tree/cf131dd83b31ad2b28aa29564f93f8c84618af27/modules/module_1_bandgap_reference/part_3_layout/OTA_layout/input_pair).
- The [course-recommended PDK tap symbol](https://github.com/IHP-GmbH/IHP-Open-PDK/blob/eb1b540c58346cf6259285a38d09b2a04feb344a/ihp-sg13g2/libs.tech/xschem/sg13g2_pr/ntap1.sym)
  also uses `A=w*l`, `P=2*(w+l)`. Thus upgrading Xschem does not explain the
  archived CDL's 197.9248/243.6 values.
- The original full OTA's archived extraction contains an input-well tap with
  the same 28.7556 µm² / 185.52 µm geometry, consistent with reuse of this block.

This evidence supports correspondence to `input_common_centroid.sch`, but does
not prove which local schematic revision the author used to draw the layout.
The inspected history does not explain the archived CDL's tap numbers.
Export fidelity establishes what the schematic says; it does not establish
that its rectangular tap parameters describe the implemented ring. Any change
to the schematic specification or physical implementation needs an explicit
design basis. The reference below retains the schematic's rectangular tap
parameters and modifies the physical implementation to satisfy them.

## Repaired Reference

The repaired GDS implements the schematic's R1 area of 442 µm² and perimeter
of 94 µm. It does not substitute ring geometry into the circuit specification.
All coordinates below are in µm.

| Region | Change and rationale |
|---|---|
| Tap active, `1/0` | Remove the original 0.31-wide ring. Add a solid 34 × 13 rectangle from `(21.650,-40.000)` to `(55.650,-27.000)`, below the unchanged MOS array. Its dimensions implement the schematic directly. |
| Contacts / Metal1, `6/0`, `8/0` | Remove contacts belonging to the old ring, retain its Metal1 supply routing, and add 0.16-square contacts on a 0.5 grid over the new tap. Vertical 0.26-wide Metal1 stripes join a horizontal rail and a bridge to the existing VDD conductor. |
| NWell, `31/0` | Use `(21.400,-40.250;55.900,-11.845)` to contain the MOS array and solid tap in the same well, with at least 0.25 enclosure of the tap. This resolves the original `NW.e` violations. |
| nBuLay, `32/0` | Fill the region of NWell expanded by 0.35, removing the original narrow ring and gaps responsible for `NBL.a` and `NBL.b`. |
| GatPoly, `5/0` | Extend contact landings to provide 0.07 enclosure and fill local narrow notches within each connected polygon. This resolves `Cnt.d` while preserving every gate/active intersection. |
| Pin markers, `8/2`, `30/2`, and labels | Inset markers by 0.1 from their original boundaries and remove duplicate identical labels. The original `v-` marker touched the conductor edge at x=43.415; Magic rounded its search origin to x=43.410, outside the wire. Insetting fixes RC extraction without changing any drawing-layer geometry or port names. |
| Metal1 spacing, `8/0` | Trim `(28.865,-18.950;32.425,-18.910)` from the upper conductor edge to increase the affected gap from 0.18 to 0.22, resolving `M1.e`. |

Original versus repaired MOS gate/active regions have an empty geometric XOR.
Native LVS matches all devices, ports and nets, with the explicit tap extracted
as **A=442 µm², P=94 µm**. Both declared DRC decks report **zero items**; no
waivers, tap-extraction bypasses or PDK rule modifications are used. Overall
GDS bounds are 38.895 × 31.990 µm; this is an observation, not an area limit.
GDS timestamps are disabled when saving the supplied reference.

| Material | SHA-256 |
|---|---|
| Authoritative schematic-export CDL | `b45f487caa8c330106828ceffec1a445f52ef4a5cff1e1999ce4b43c0b2e88c5` |
| Repaired reference GDS | `56656af05ed20de527cd8fd4636516c0069c150d42cf0c867e3a9a43a12bae4b` |

The check scope is the pinned main-plus-maximal DRC, with density and antenna
disabled, and the native explicit-tap AnalogAcademy LVS profile described below.
This establishes physical validity under those rules, not full manufacturing
signoff, performance, mismatch or PVT qualification. The reference is supplied
ready to use; no repair generator is required.

## Original Physical Checks

With KLayout 0.30.11 and the pinned PDK, the unmodified GDS and CDL produce:

| Check | Result |
|---|---|
| Artifact | Passed |
| Main DRC deck | Failed: 54 items |
| Additional maximal DRC deck | Failed: 9 items |
| Native LVS | `NoMatch`: tap parameters differ; combined MOS devices and ports match |

| DRC category | Items | Affected feature |
|---|---:|---|
| `Cnt.d` | 49 | Poly enclosure of contacts |
| `NBL.b` | 4 | nBuLay spacing/notches |
| `M1.e` | 1 | Long-run Metal1 spacing |
| `NW.e` | 8 | NWell enclosure of well ties |
| `NBL.a` | 1 | nBuLay width |

Counts are native report items, not independent root causes. No waivers or
PDK rule changes are applied. `drc-upstream.json` runs the main and additional
maximal decks in deep mode, with density and antenna checks disabled.
`lvs-analogacademy.json` retains explicit taps and native simplification,
without the additional named-port mismatch check. These profiles reconstruct
documented defaults on the pinned PDK; the author's exact historical switches
were not archived. See [tool scope](../../../../docs/tools.md#original-asset-evaluation).

| R1 parameter | Source CDL | Original GDS extraction |
|---|---:|---:|
| Active area | 197.9248 µm² | 28.7556 µm² |
| Perimeter | 243.6 µm | 185.52 µm |

The archived upstream extraction agrees with the fresh extraction on these
tap values. Replacing the CDL numbers alone would not resolve the DRC failures;
a repaired tap must have its geometry independently measured and its source
parameters reconciled before qualification.

## Reproduce the Checks

Run from the repository root with the pinned course and PDK submodules
initialized and the [shared tools image](../../../../docs/tools.md#manual-tools)
available. Run the maintained physical regression:

```bash
uv run --locked pytest tests/integration/test_input_pair_source.py \
  -k repaired_reference --basetemp build/runs/input-pair-physical-tests
```

Choose a new `--basetemp` path: pytest clears that directory when starting.
The regression prepares its own support bundle, loads the manifest's frozen
reference and new CDL, and invokes the existing evaluation API with the declared
physical profiles. It checks that the reference passes artifact/DRC/LVS and
that the original GDS fails DRC/LVS against the same new CDL. A successful test
exits **0** only when both expectations hold.

Under the generated test directory, `reference/report.json` records
`physical_valid=true`; `original/report.json` records the rejections. Each
report links native evidence, extraction, logs, candidate/netlist digests and
actual tool/support identities. This physical-only run does not establish
benchmark task success. No case-local verification script is required.

To reproduce the historical baseline against the original CDL instead, prepare
a fresh support bundle and use the existing upstream evaluator:

```bash
uv run --locked python -m benchmarking.prepare_support \
  third_party/IHP-Open-PDK technology/sg13g2/klayout.json \
  build/support/input-pair-klayout
uv run --locked python -m benchmarking.upstream \
  tasks/IHP-AnalogAcademy/cases/input_pair/case.toml \
  --support build/support/input-pair-klayout \
  --output build/runs/input-pair-original
```

The original-asset command is expected to exit **1** for the completed physical
rejections above. It creates `build/runs/input-pair-original/report.json` and
content-addressed evidence, including both native DRC reports, the LVS database,
extracted circuit, tool logs and actual tool/support identities. These outputs
are generated by the reader's run; they are not distributed qualification
evidence. Verify source provenance separately with:

```bash
uv run --locked pytest tests/integration/test_catalog_assets.py -k IHP-AnalogAcademy
```

## Nominal Post-layout Characterization

[materials/testbench.spice](materials/testbench.spice) measures the input
admittance matrix with the original five-port interface. The source-model
[simulation netlist](materials/circuit.spice) is a separate, unmodified
Xschem export of the same schematic using the native PDK simulation format
(`lvs_netlist=0`, `spiceprefix=1`). Its `.spice` suffix denotes simulator input;
LVS continues to use `circuit.cdl`. The source regression re-exports both
formats and compares their devices, connectivity and geometry with the native
PDK reader and the reviewed model-call adapter. The tap simulation call uses
`w=13e-6`, `l=34e-6`, `R=1.828358`, computed by the PDK symbol from those
schematic dimensions; it is not fitted to extracted parasitics.

The [maintained regression](../../../../tests/integration/test_input_pair_postlayout.py)
builds a characterization plan using the physical scope and `[toolchain]` bindings
in [case.toml](case.toml). It runs artifact/DRC/LVS gates, Magic RC extraction of the
candidate GDS, and identical source/post-layout ngspice testbenches. Post-layout
simulation consumes that run's RC output; the archived upstream extraction is
not an input. The extraction preserves all five ordered ports and extracts
resistance on both input networks, both drain networks, VDD and the internal
common-source network.

| Condition | Value |
|---|---|
| Models | Pinned SG13G2 `mos_tt`, `res_typ` |
| Temperature | 27 °C |
| Supply | VDD = 1.2 V |
| DC boundary conditions | Both inputs and both drains clamped to 0.6 V |
| AC excitation | Separate 1 V excitations on `v+` and `v-`; all other external ports at AC ground |
| Frequency sweep | 1 kHz–1 GHz, 40 points/decade |
| Numerical conditioning | `rshunt=1e12` in both source and extracted simulations |
| Extraction | Pinned Magic `ihp-sg13g2` technology, `ngspice()` style; distributed RC, no inductance |

For input i and excitation j, `Yij = -I(Vi)/Vj`, using the voltage-source
current convention. The deck reports `Im(Yij)/(2*pi*f)` in farads and the
signed real admittance in siemens at 1 MHz; full complex AC and operating-point
waveforms are also retained. Off-diagonal capacitance coefficients are signed,
not positive lumped capacitor values.

| Coefficient at 1 MHz | Schematic (fF) | Extracted reference (fF) |
|---|---:|---:|
| `C++` | 55.93081 | 78.89307 |
| `C--` | 55.93081 | 78.85078 |
| `C-+` | -0.57215 | -6.09023 |
| `C+-` | -0.57215 | -6.09025 |

These are nominal loading observations under the stated voltage clamps, not
gain, bandwidth, matching or performance acceptance limits. The internal
common source has no external tail bias, and the dummy devices do not provide
a defined active bias current. The numerical shunts regularize floating
extraction nodes; operating-point currents must not be treated as physical
leakage measurements. No shunt-sensitivity, PVT or statistical mismatch
qualification is claimed.

Reproduce the source comparison and complete physical/RC/simulation chain with
the shared tools image and pinned submodules initialized:

```bash
uv run --locked pytest tests/integration/test_input_pair_source.py \
  tests/integration/test_input_pair_postlayout.py \
  --basetemp build/runs/input-pair-postlayout-tests
```

Choose a fresh `--basetemp` directory; pytest clears it. The tests prepare
support bundles from the pinned PDK and write evaluation reports underneath
that directory. `characterization/report.json` links the frozen candidate,
CDL, extracted netlist, waveforms, simulator measurements and tool evidence.
The regression independently recomputes the reported admittance from raw source
currents, verifies the voltage excitation, and checks the symmetric source
loading and added extracted loading. Physical checks also retain the original
GDS as a negative control. This is reproducible characterization, not a
qualified benchmark task or a performance score.

## Remaining Task Definition

Following the [comparator structure](../comparator/README.md), promotion requires
an English `problem.md`, declared solver inputs, an output contract, physical
constraints, and an independently specified performance plan compatible with
the fixed circuit/interface. The nominal characterization above provides an initial source/RC comparison;
performance requirements and the applicable positive, negative, sensitivity
and repeatability checks still need to establish the stated
[qualification scope](../../../../docs/tasks.md#qualification).

The source's common-centroid arrangement is a design technique, not a currently
implemented geometry or mismatch scoring condition. A future task must state
which placement properties are actually checked. No statistical matching,
PVT coverage, or complete OTA performance is established by this baseline.

Only explicitly declared task inputs and reviewed tool resources may enter a
standard solver environment. Reference layouts, source records and diagnostic
extractions remain outside those inputs; the
[historical asset exclusion rules](../../../../docs/tasks.md#input-isolation)
continue to apply.
