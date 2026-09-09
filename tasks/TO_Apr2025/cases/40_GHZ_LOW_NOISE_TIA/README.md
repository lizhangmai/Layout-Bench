# 40 GHz low-noise TIA

This is a source candidate, without a frozen task or qualified witness.
[case.toml](case.toml) is the configuration entry point and pins upstream
commit `63e203a0eccfb6028a1a0a8364553e4e979b55b3`. Source assets remain
under upstream `40_GHZ_LOW_NOISE_TIA/`. The upstream root declares
Apache-2.0; no separate license file was found in this project tree.
Retain file-level notices and separate PDK/model/tool licenses.

## Sources and known gaps

- `design_data/qucs-s/40_GHz_Low_Noise_TIA.sch` is a Qucs 24.4.1 document
  containing three HBTs, three `rppd` and two `rsil` resistors, three MIM
  components and the RF test circuit. Its `.dat.ngspice` file is archived
  simulation evidence; the author environment and run identity are not frozen.
- `design_data/klayout/lvs/40_GHz_Low_Noise_TIA.cdl` uses legacy primitive
  cards, a portless `FDM_QNC_00_LN_TIA` subcircuit, and a mismatched `.ENDS TOP`
  terminator. Its three 30 × 60 um capacitor cards have m=2. No same-source
  schematic export relationship is established by this file.
- Both final and KLayout evaluation GDS variants exist, with different digests
  and top `FDM_QNC_00_LN_TIA`. The manifest selects the KLayout variant.
  The historical LVS database instead refers to `TOP` and compares zero
  layout pins against nine reference pins. It does not establish today's
  named-port interface or exact historical input pairing.
- Six EM files are inventoried. The schematic names `TL_20_um.s2p`, which is
  absent from this project tree. `degenration_TL_data/deg_TL.s2p` exists, but
  substituting it requires evidence of equivalence. Both original and
  zero-frequency-modified peaking files are retained upstream; the schematic
  selects `peaking_TL_0hz_changed.s2p`.
- `TOP_extracted.cir` is layout extraction evidence, not a schematic netlist.
  Qucs library-path relocation needs pin/parameter checks against the current
  PDK symbols before any source export is adopted.

The [upstream description](../../../../third_party/TO_Apr2025/40_GHZ_LOW_NOISE_TIA/README.md)
reports 40 GHz bandwidth and approximately 9.5 pA/√Hz input-referred noise.
These are historical design claims, not benchmark acceptance limits. The
noise bandwidth, input/output reference planes, supply conditions and
candidate-derived RF extraction must be specified independently.

## Physical status and next work

Use the [collection reproduction commands](../../README.md#reproduce-the-source-checks).
Artifact validation passes; current main plus extra DRC reports 1585 unwaived
items, and LVS errors on two-terminal `rppd` input before comparison.
Archived minimal/maximal databases have zero items, under unidentified
historical deck versions. No physical repair or waiver has been applied.

This case follows design 1 in the implementation order because its active
core is small, but first needs the missing EM dependency resolved, an audit
of capacitor multiplicity and circuit connections, and a current-symbol
schematic source with reproducible CDL/SPICE exports. No circuit materials,
reference witness, performance limits or qualification scope have been frozen.
