# 40_GHZ_LOW_NOISE_TIA source-only record

The 40 GHz low-noise single-ended TIA is the second TO_Apr2025 source slice.
Its upstream documentation provides a useful RF specification and a compact
set of schematic, layout, LVS, DRC, and openEMS artifacts.

This record remains **source-only** for now. The source is a Qucs-S 24.4.1
schematic, while the current Layout-Bench preparation entry point accepts
only `xschem-lvs`. The schematic also refers to custom Qucs libraries,
absolute Windows model paths, and six S2P files through the author's local
workspace. A direct Qucs-S conversion in the unified image exits zero but
reports `Could not go throughAllComps` and produces only an include stub; the
result is not an authoritative netlist.

The historical LVS CDL and GDS stay catalogued as provenance/reference
artifacts. Before this design can become a candidate task, we need a pinned
Qucs source-preparation adapter (or an upstream-exported authoritative
netlist), a license-approved staged model bundle, explicit task ports and
constraints, and a post-layout RF evaluation plan. The upstream validation
document currently contains no measurement results.
