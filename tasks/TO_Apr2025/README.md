# TO_Apr2025 circuit catalog

This directory contains the public circuit records selected from the pinned
`TO_Apr2025` submodule. `catalog.toml` is intentionally an incremental
catalog: it currently contains the first source slice only. The named circuit
configuration files are maintainer metadata; they are not mounted as Agent
inputs and do not imply that a circuit is a runnable or qualified benchmark
task.

For example, the mixer record is
`Mixer5GHz/Mixer5GHz.toml`; each circuit record keeps its source identity and
status in that one named file. `source.toml`, when present, is only the
tool-specific preparation manifest.

The first source slice is `Mixer5GHz/`, recorded as a `candidate`: its source
is an Xschem schematic and can be prepared with the current source-preparation
entry point, but its exported top-level interface, physical constraints,
evaluation plan, and independent qualification still need to be frozen. The
second slice, `40_GHZ_LOW_NOISE_TIA/`, is recorded as `source-only` because
the current preparation contract does not yet support its Qucs-S source.
The third slice, `DC_to_130_GHz_TIA/design_1/`, is likewise source-only until
the Qucs-S/EM model preparation boundary is reproducible.

The upstream checkout is fixed at commit
`63e203a0eccfb6028a1a0a8364553e4e979b55b3`. Keep the checkout, PDK, EDA tools,
models, and derived artifacts under their own provenance and license records.
The upstream GDS and historical LVS database are reference evidence only;
they are not task inputs.
