# Mixer5GHz candidate

`Mixer5GHz` is the first TO_Apr2025 intake candidate. The upstream design is
a 5 GHz up-converter mixer with a cross-coupled oscillator and includes an
Xschem source, historical GDS, and DRC/LVS artifacts.

This directory currently records only source intake. It is **not** a
`netlist_to_gds` task yet:

- the source must be exported in the pinned, network-isolated preparation
  image and checked for a valid top-level port list;
- the historical CDL has two `GND` entries in its `.subckt` declaration and
  must not be copied into the task as an authoritative netlist;
- the source schematic contains oscillator inductors, while the historical
  CDL comments out their `L1`/`L2` entries; this discrepancy needs an
  upstream/source-level resolution;
- geometry constraints, circuit-level acceptance metrics, post-layout
  extraction, and independent qualification are still missing.

Use `source.toml` with `benchmarking.prepare` to reproduce the raw Xschem
export. Keep the generated export and logs in a trusted preparation directory;
do not add them to the standard Agent input until the source and evaluation
review is complete.
