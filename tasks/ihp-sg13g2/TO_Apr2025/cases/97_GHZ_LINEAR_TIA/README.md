# 97 GHz linear TIA

This is a source candidate, without a frozen task or qualified witness.
[case.toml](case.toml) is the configuration entry point and pins upstream
commit `63e203a0eccfb6028a1a0a8364553e4e979b55b3`. Sources remain under
upstream `97_GHZ_LINEAR_TIA/`. The root declares Apache-2.0; no separate
license file was found in this project tree. Retain individual notices and
separate PDK/model/tool licenses.

## Sources and known gaps

- `design_data/qucs-s/97_GHZ_LINEAR_TIA.sch` is a Qucs 24.3.0 document with
  twelve HBTs, bias/feedback circuitry, ten `rhigh`, four `rppd`, one `rsil`
  and three MIM component instances. Eight named S2P dependencies are present.
  Its `.dat.ngspice` is archived simulation evidence, without a frozen
  author tool/model identity.
- The CDL header names Qucs 25.1.0 and an unavailable
  `new_design_netlist.sch`. The portless subcircuit is
  `FMD_QNC_01_LIN_TIA`; the file terminates with `.END`. It uses legacy
  primitive parameters and additional capacitor cards. Export consistency
  with the published schematic is not established.
- Final and KLayout GDS files share top `FMD_QNC_01_LIN_TIA` but have
  different digests. The manifest selects the KLayout version. The historical
  LVS database refers to `TOP`; capacitor representations in its simplified
  reference differ from the standalone CDL. Simplification versus input
  version differences must be resolved before inferring a circuit change.
- `FMD_QNC_01_LIN_TIA_extracted.cir` is layout-derived diagnostic evidence,
  not an authoritative schematic export. Current Qucs symbol compatibility,
  resistor bulks, HBT multiplicities, bias ports and capacitor networks all
  require circuit-level verification.

The [upstream description](../../../../../third_party/TO_Apr2025/97_GHZ_LINEAR_TIA/README.md)
reports 97 GHz bandwidth and approximately 17.3 pA/√Hz input-referred noise.
These are historical claims, not adopted limits. Linearity, noise and RF
bandwidth need explicit bias, stimulus, model and reference-plane definitions.

## Physical status and next work

Use the [collection reproduction commands](../../README.md#reproduce-the-source-checks).
Artifact validation passes; current main plus extra DRC reports 544 unwaived
items, and LVS errors on two-terminal poly-resistor input before comparison.
Archived minimal/maximal databases have zero items, under unidentified
historical deck versions. No physical repair or waiver has been applied.

This is third in the implementation order: EM file coverage is good, but the
bias network makes circuit-version reconciliation more involved than the two
smaller TIAs. Freeze and export a reviewed circuit before repairing geometry.
Candidate-derived RC/RF extraction, same-condition pre/post calibration,
constraints, thresholds and qualification remain open.
