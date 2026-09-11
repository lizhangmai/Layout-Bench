# TO_Apr2025 candidate circuits

The [catalog](catalog.toml) indexes four public source candidates at upstream
commit `63e203a0eccfb6028a1a0a8364553e4e979b55b3`. Each case's `case.toml` is
its only configuration entry point. None has a frozen executable task or a
qualified witness. Upstream screening establishes available source assets,
not schematic/layout equivalence or task success.

## Source inventory and implementation order

All four cases have a Qucs schematic, GDS, archived LVS circuit and database,
a layout-extracted netlist, DRC databases, and RF simulation materials.
The case manifests also identify archived Qucs datasets. Those datasets are
historical simulation evidence, not reproducible candidate-derived PEX results.

| Order | Case | Source advantages | Principal blockers |
| --- | --- | --- | --- |
| 1 | [DC–130 GHz TIA, design 1](cases/DC_to_130_GHz_TIA.design_1/README.md) | Two HBT stages, three resistors, two capacitors; four named EM models; explicit design specifications | Editable core, dual exports and a DRC/LVS-clean repair proposal available; manufacturing/RF changes need review; RF/PEX qualification remains open |
| 2 | [40 GHz low-noise TIA](cases/40_GHZ_LOW_NOISE_TIA/README.md) | Three HBTs; compact resistor network; archived RF/noise results | Unresolved `TL_20_um.s2p` dependency; capacitor multiplicity; historical top-name discrepancy; physical rejection |
| 3 | [97 GHz linear TIA](cases/97_GHZ_LINEAR_TIA/README.md) | Eight named EM models and detailed bias circuit | Twelve HBTs and feedback/bias networks; capacitor representation and historical input pairing; physical rejection |
| 4 | [160 GHz LNA](cases/160GHz_LNA/README.md) | Four HBT stages; seven EM files; separate pi-model schematic | RF-capacitor/EM representation versus LVS abstraction; dataset belongs to pi variant; largest current DRC backlog |

The order favors a tractable circuit-version audit before increasing circuit
and RF-model complexity. It does not rank layout quality. Every candidate
needs a reviewed circuit boundary, same-source CDL/SPICE exports, physical
constraints, candidate-derived extraction and independently justified metrics.
No gain, bandwidth or noise threshold has been adopted from reference results.

## Reproduce the source checks

Initialize the pinned upstreams using the [tools guide](../../../docs/tools.md#external-sources)
and build the unified tools image. From the repository root:

```bash
uv run --locked pytest tests/integration/test_catalog_assets.py
uv run --locked python -m benchmarking.prepare_support \
  third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml#klayout build/support/to-original
for case in DC_to_130_GHz_TIA.design_1 40_GHZ_LOW_NOISE_TIA 97_GHZ_LINEAR_TIA 160GHz_LNA; do
  uv run --locked python -m benchmarking.upstream \
    "tasks/ihp-sg13g2/TO_Apr2025/cases/$case/case.toml" \
    --support build/support/to-original --output "build/runs/to-original-$case"
done
```

These commands generate local evidence; use new output directories. Each
original evaluation is expected to reject, with artifact `passed`, DRC
`failed`, and LVS `error` because of legacy two-terminal poly-resistor cards.
Inspect individual job status: the overall CLI exit is 1 because DRC completes
with violations. With PDK `5e6d592e4002946a4616f798c357f0f3c06cf3b6` and
KLayout 0.30.11:

| Case | Archived minimal / maximal DRC items | Current main + extra DRC items |
| --- | ---: | ---: |
| DC–130 GHz design 1 | 2 / 1 | 110 |
| 40 GHz TIA | 0 / 0 | 1585 |
| 97 GHz TIA | 0 / 0 | 544 |
| 160 GHz LNA | 0 / 0 | 3289 |

Historical deck versions and exact input pairings are not established by report
filenames. Native zero-item databases do not prove that the current GDS passed
the current rules. The source regression for design 1 separately checks current
extraction and the unsafe Qucs symbol migration:

```bash
uv run --locked pytest tests/integration/test_to_apr2025_source.py \
  tests/integration/test_to_apr2025_schematic.py
```

## Asset roles and rights

The upstream [root license](../../../third_party/TO_Apr2025/LICENSE) is Apache-2.0;
design 1 also declares Apache-2.0 in its project README. No separate LICENSE,
NOTICE or COPYING file was found inside these four selected project trees.
Retain per-file author notices and review any newly selected dependency's own
license. PDK symbols, compact models and tools remain separately licensed.
Current case records refer to upstream bytes; they do not redistribute a tool,
model library or reference GDS as solver input.

Design 1 now supplies an editable source, raw CDL/SPICE and a nominal DC
testbench, all marked as maintainer assets. Its original GDS still fails LVS
and DRC; a separately identified complete physical repair proposal passes the
current main plus extra DRC and compare-only LVS. It remains unqualified and
requires review of manufacturing/RF changes. For an admitted task, `problem.md` will describe the approved interface
and scoring; `materials/circuit.cdl`, `materials/circuit.spice` and
`materials/testbench.spice` will hold the LVS circuit, simulation circuit and
shared pre/post testbench; `reference/` will hold the reviewed witness.
The proposal is not an accepted witness; unresolved task roles are not populated
with placeholder files. Original source names stay unchanged in the submodule.
Only declared `[task.inputs]` may be delivered to an Agent; historical assets,
reference geometry, EM results and full source checkouts are not implicit inputs.
Follow the [isolation checklist](../../../docs/tasks.md#input-isolation).
