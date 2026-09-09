# 160 GHz low-noise amplifier

This is a source candidate, without a frozen task or qualified witness.
[case.toml](case.toml) is the configuration entry point and pins upstream
commit `63e203a0eccfb6028a1a0a8364553e4e979b55b3`. Sources remain under
upstream `160GHz_LNA/`. The root declares Apache-2.0; no separate license
file was found in this project tree. Retain individual notices and separate
PDK/model/tool licenses.

## Sources and known gaps

- `design_data/qucs-s/160GHz_LNA(MAIN).sch` is a Qucs 24.4.1 document with
  four HBT stages, four `rsil`, four `rhigh`, sixteen MIM and nine RF MIM
  components, plus the RF test circuit. Its twelve S2P instances refer to
  seven available files. Identical bytes for `2nd_TL.s2p` and `3rd_TL.s2p`
  are retained as supplied; this alone does not establish physical interchangeability.
- The separately inventoried `160GHz_LNA_pi_model.sch` is a supporting
  Qucs schematic. The available `160GHz_LNA_pi_model.dat.ngspice` belongs
  by filename to this variant, not automatically to the selected MAIN source.
  Do not claim a MAIN simulation from that dataset without correspondence checks.
- `design_data/klayout/lvs/160GHz_LNA.cdl` is a portless `TOP` circuit of
  legacy primitive cards: four HBTs with NE/m values 4, 4, 2, 2; four `rsil`,
  four `rhigh`, and three aggregated MIM capacitor cards. RF MIM and
  transmission-line representations from the simulation schematic are absent.
  This may be an LVS abstraction, but no reproducible same-source export and
  RF-device correspondence has been established.
- Final GDS top is `FMD_QNC_04_160GHz_LNA`; the different-digest KLayout
  evaluation variant has top `TOP`, consistent with the historical LVS
  database's circuit name. Matching names alone do not identify historical
  GDS bytes or runset settings. `TOP_extracted.cir` is layout evidence.

The [upstream description](../../../../third_party/TO_Apr2025/160GHz_LNA/README.md)
reports a 146–173 GHz band, 5.77 dB noise figure at 160 GHz, 12.5 dB peak
gain and −11.4 dBm input compression point. These are historical design
claims, not approved benchmark limits. Their bias, RF extraction, reference
planes and measurement definitions require independent freezing.

## Physical status and next work

Use the [collection reproduction commands](../../README.md#reproduce-the-source-checks).
Artifact validation passes; current main plus extra DRC reports 3289 unwaived
items. LVS errors on legacy two-terminal `rhigh` input before comparison;
this CDL does not contain `rppd`. Archived minimal/maximal databases have
zero items, under unidentified historical deck versions. No physical repair
or waiver has been applied.

This is fourth in the implementation order because it combines the largest
current DRC backlog with RF-capacitor and distributed-line semantics. Audit
MAIN versus pi-model versus LVS topology and dependencies before choosing a
circuit authority. Same-source exports, candidate-derived RC/RF extraction,
noise/compression calibration, geometry requirements and qualification remain
open. Reference S2P data cannot replace extraction from a new candidate GDS.
