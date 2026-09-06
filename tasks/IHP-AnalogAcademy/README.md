# IHP AnalogAcademy intake

This directory is the public intake namespace for the circuits published by
the pinned `IHP-AnalogAcademy` submodule. It mirrors the upstream module and
part names so a source record, a task, and its qualification evidence have one
stable home:

```text
tasks/IHP-AnalogAcademy/<module>/<part>/<circuit>/
```

`catalog.toml` is the complete inventory for submodule commit
`133ecf657572e021b5921b5a1b7693abfb209623`. It records every non-excluded
upstream `*.sch` source (50 records, including testbenches and the utility
gmid demonstration), its source format, role, content digest, and intake status. Each record also has a small
`intake.toml` at the mirrored path. These files are maintainer metadata; they
are not mounted as Agent inputs.

The catalog's artifact section is limited to circuit-bearing netlists, symbols,
models, RF decks, extraction records, and layouts associated with those source
records; unrelated utility chip/gallery layouts are not task inputs.

The statuses deliberately distinguish source intake from benchmark
qualification:

| Status | Meaning |
|---|---|
| `qualified` | A complete `netlist_to_gds` task with frozen inputs, an evaluation plan, a reference, and qualification evidence. Currently only the transmission gate has this status. |
| `candidate` | A circuit source that is eligible for a future layout task, but still needs an authoritative exported netlist, constraints, evaluation, and qualification. |
| `source-only` | A course source that is not currently a `netlist_to_gds` input (for example, a Qucs RF analysis schematic). |
| `supporting-source` | A testbench or integration schematic; it is tracked for provenance but is not a standalone layout task. |

The qualified transmission-gate task lives at
`module_3_8_bit_SAR_ADC/part_2_digital_comps/T_gate/`. Its task ID remains
`academy-tgate` for run-record compatibility; the filesystem namespace is now
the source hierarchy rather than a flat task name.

The catalog does not copy a complete upstream checkout into Agent-visible
inputs. Source paths and SHA-256 digests are resolved against the pinned
submodule, while generated/layout artifacts are inventory records only. The
historical `module_0_foundations/PEX_Demo` and `utils/PEX_Demo` fixtures and
their derivatives remain excluded by the input-isolation checklist in [the
task guide](../../docs/tasks.md#input-isolation).

The upstream root is Apache-2.0, but individual upstream files may carry
their own notices (including GPL-licensed tool components). Review the
corresponding source file and the upstream [license](../../third_party/IHP-AnalogAcademy/LICENSE)
before redistributing a derived asset.
