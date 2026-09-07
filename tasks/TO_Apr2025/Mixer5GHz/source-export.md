# Mixer5GHz source export

On 2026-09-07, the pinned source manifest was run with the network-isolated
preparation command below from the `Layout-Bench` repository root:

```text
uv run --locked python -m benchmarking.prepare \
  tasks/TO_Apr2025/Mixer5GHz/source.toml \
  build/to-apr2025-mixer-source \
  --checkout to_apr2025=third_party/TO_Apr2025 \
  --checkout pdk=third_party/IHP-Open-PDK \
  --image layout-bench-tools:local
```

The export completed successfully with the local tool image
`sha256:2de5401330243fb3a5fc7132f1d36bdafd8c2307d2bcf938eeb7a937e98888d6`
(`Xschem V3.4.4`). The raw `Mixer5GHz.spice` output was 2,530 bytes with
SHA-256
`ad94f3f50310cf3172383231d691154b5bbe683849b32d9bf9b7b8da04f3f867`.
The source manifest digest recorded by the preparation tool is
`1cb45c21d6fec9ba4867cca3fe3c80363eeb6f56dc487bf42fea99afc7776d59`.
The full machine-generated provenance remains in the ignored `build/`
directory; rerunning the command produces it again.

The exported top-level declaration is:

```spice
.subckt Mixer5GHz RFN RFP VDC IFP IFN GND IDC OSCN OSCP VCC ICC GND
```

This confirms the source-preparation path works, but it also confirms that the
source currently declares `GND` twice. The historical CDL has the same
duplicate port, while its `L1`/`L2` oscillator-inductor lines are commented
out even though the raw source export contains `L1`–`L4`. We must resolve this
source/interface discrepancy before freezing an authoritative task netlist;
the exported file is therefore not copied into `inputs/`.
