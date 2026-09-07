# TO_Apr2025 intake

This directory contains the public intake records for circuits selected from
the pinned `TO_Apr2025` submodule. `catalog.toml` is intentionally an
incremental catalog: it currently contains the first intake slice only. Intake
records are maintainer metadata; they are not mounted as Agent inputs and do
not imply that a circuit is a runnable or qualified benchmark task.

The first intake slice is `Mixer5GHz/`. It is deliberately recorded as a
`candidate`: its source is an Xschem schematic and can be prepared with the
current source-preparation entry point, but its exported top-level interface,
physical constraints, evaluation plan, and independent qualification still
need to be frozen.

The upstream checkout is fixed at commit
`63e203a0eccfb6028a1a0a8364553e4e979b55b3`. Keep the checkout, PDK, EDA tools,
models, and derived artifacts under their own provenance and license records.
The upstream GDS and historical LVS database are reference evidence only;
they are not task inputs.
