# DC_to_130_GHz_TIA design_1 source-only record

This record covers the two-stage `design_1` variant of the TO_Apr2025
DC-to-130-GHz SiGe HBT TIA. The upstream README explicitly publishes the
design under Apache-2.0 and includes schematic, GDS, EM, DRC, and LVS data.

It remains **source-only** at this stage. The authoritative source is a Qucs-S
schematic with absolute Windows paths to custom PDK libraries, Ngspice/OSDI
models, and four openEMS S2P files. The current Qucs-S probe exits zero while
producing only an include stub, so the historical `TOP.cdl` and
`LVS_Check_Netlist.cdl` cannot be promoted to task input. The published
validation also says that measured results are still pending.

Before promotion to `candidate`, add a pinned Qucs source-preparation adapter
or an upstream raw export, stage the license-approved PDK/model/S2P bundle,
freeze the top-level ports and physical constraints, and define a genuine
candidate-GDS post-layout RF evaluation. The existing GDS, LVS database, and
DRC reports remain reference/provenance artifacts only.
