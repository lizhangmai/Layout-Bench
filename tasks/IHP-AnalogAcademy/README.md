# IHP AnalogAcademy circuit cases

This directory catalogs the pinned `IHP-AnalogAcademy` submodule. Every
logical circuit case has exactly one configuration file under `cases/`:

```text
tasks/IHP-AnalogAcademy/cases/<case-id>.toml
```

The case ID is the file stem. A case configuration contains the circuit
identity, upstream source records, status, and—when the circuit is runnable—
the complete `[task]` declaration. Testbenches, Monte Carlo variants, and
supporting schematics are `[[sources]]` entries in their owning case; they do
not create separate configuration files.

`catalog.toml` is only the dataset index. The pinned catalog contains 50
upstream schematic sources grouped into 30 logical cases. Source paths and
digests remain bound to the recorded submodule commit. The historical
`module_0_foundations/PEX_Demo` and `utils/PEX_Demo` fixtures remain excluded
by the [input-isolation checklist](../../docs/tasks.md#input-isolation).

Non-configuration material uses one separate namespace:

```text
tasks/IHP-AnalogAcademy/cases/assets/<case-id>/
```

The qualified transmission-gate case is the current runnable example:

```text
cases/module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate.toml
cases/assets/module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate/
```

Its single case TOML contains the source records, `[source_export]`, the
complete `[task]`, reference/qualification asset declarations, and
`status = "qualified"`. The assets directory contains payload files only; it
does not contain another `task.toml`, `source.toml`, or circuit configuration.
Reference and qualification assets are evaluator/debugging materials and are
not materialized by a standard Agent run.

Statuses distinguish source review from readiness:

| Status | Meaning |
| --- | --- |
| `qualified` | A complete runnable case with frozen inputs, evaluation, reference, and qualification evidence. |
| `candidate` | A reviewed circuit that still needs a runnable task and qualification. |
| `source-only` | A source such as a Qucs/RF analysis that is not currently a layout task. |
| `supporting-source` | A standalone supporting/testbench group retained for provenance. |

The upstream root is Apache-2.0, but individual files may carry their own
notices (including GPL-licensed tool components). Review the corresponding
source file and the upstream [license](../../third_party/IHP-AnalogAcademy/LICENSE)
before redistributing a derived asset.
