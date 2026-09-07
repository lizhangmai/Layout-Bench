# 40 GHz TIA source-preparation probe

The current preparation command is intentionally Xschem-only, so no
`source.toml` claiming Qucs support is added for this design. As a diagnostic,
the pinned Qucs-S schematic was run in the unified image with networking
disabled:

```text
docker run --rm --network none --cap-drop ALL \
  --security-opt no-new-privileges \
  --mount type=bind,src=<TO checkout>/40_GHZ_LOW_NOISE_TIA/design_data/qucs-s,dst=/source,readonly \
  --mount type=bind,src=<empty output directory>,dst=/out \
  layout-bench-tools:local \
  qucs-s -n -i /source/40_GHz_Low_Noise_TIA.sch \
  -o /out/40.spice --ngspice
```

Observed with local image `sha256:2de5401330243fb3a5fc7132f1d36bdafd8c2307d2bcf938eeb7a937e98888d6`
(`Qucs-S 26.1.1`): exit code `0`, but stderr contained:

```text
Error: Could not go throughAllComps
Error giving NodeNames
```

The output file was only 119 bytes and contained the Qucs math-function
include rather than a circuit netlist. The source also embeds absolute paths
to custom component libraries, HBT/CAP/RES models, OSDI, and the six openEMS
S2P files. This probe is therefore evidence that the historical schematic is
not yet reproducible through the current task-preparation contract; it is not
a generated task netlist.
