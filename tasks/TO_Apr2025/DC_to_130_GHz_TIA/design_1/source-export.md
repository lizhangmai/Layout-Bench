# DC-to-130-GHz TIA source-preparation probe

The pinned Qucs-S schematic was run in the unified image with networking
disabled using the same diagnostic command as the 40 GHz TIA:

```text
qucs-s -n -i /source/DC_to_130_GHz_TIA.sch \
  -o /out/130.spice --ngspice
```

Observed with local image
`sha256:2de5401330243fb3a5fc7132f1d36bdafd8c2307d2bcf938eeb7a937e98888d6`
(`Qucs-S 26.1.1`): exit code `0`, but stderr contained:

```text
Error: Could not go throughAllComps
Error giving NodeNames
```

The output file was 116 bytes and contained only the Qucs math-function
include. The source embeds absolute paths to custom Qucs libraries, PDK model
files, OSDI files, and `254em.s2p`, `272em.s2p`, `INPUT.s2p`, and `RF_OUT.s2p`.
The probe therefore does not establish a reproducible authoritative netlist;
the historical CDL remains an upstream artifact pending source-level export.
