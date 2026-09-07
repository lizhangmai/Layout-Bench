# Tool Environments, Resource Preparation, and EDA Adapters

For the first run, use `quickstart` from the root [README](../README.md#quick-start-no-model-key-required); it builds only one `layout-bench-tools:local` image. This page covers stepwise preparation, troubleshooting, and changes to the tool environment. Run every command from the repository root and use a new output directory. Repository-local generated outputs use `build/`: benchmark runs go under `build/runs/`, independently prepared support bundles under `build/support/`, and Python distributions under `build/dist/`.

## Stepwise Preparation and Reuse

The host uses Linux x86-64, Git, uv, Python 3.12+, and accessible Docker/BuildKit. Versions are maintained by the [Dockerfile](../Dockerfile), [pyproject.toml](../pyproject.toml), and [uv.lock](../uv.lock); framework development needs only `uv sync --locked`.

| `scripts/public_preview.py` subcommand | When to use it |
|---|---|
| `doctor` | Check the host and Docker before downloading; does not call a model |
| `build` | Build only the unified image; accepts `--image`, defaulting to `layout-bench-tools:local` |
| `prepare --output <new-directory>` | Prepare the view, Magic, MOS models, KLayout rules, Agent resource bundle, and configurations from the pinned PDK, binding all of them to the actual image ID |
| `run --prepared <prepared-directory> --output <new-directory>` | Re-evaluate the public reference, verify expected-failure submissions, and run two independent repetitions while saving raw evidence |
| `qualify --prepared <prepared-directory> --output <new-directory>` | Rebuild the reference and counterexamples and revalidate public-task qualification and pre-layout calibration |

`quickstart` chains host checks, image build, PDK initialization, preparation, and smoke validation, and writes `prepared/` and `run/`. It reuses build caches and the pinned upstream checkout, but prepares derived resources and fresh run artifacts again. `--skip-build` reuses an existing image and still binds its actual ID; it does not download an unpublished prebuilt image or overwrite existing output. The smoke run evaluates the reference, the original offline protocol probe, and the provider-neutral canonical probe; the latter is a deterministic harness control, not a model baseline. The prepared directory contains both probe configurations. The script assembles only public preview fixtures; use `main.py` and your own tool configuration for custom tasks.

The unified image contains KLayout, Python, ngspice, Qucs-S/Qucsator, Magic, OpenVAF, and Xschem. Harness runtimes are deliberately outside this image: a harness supplies its executable and reviewed files, or selects an image that provides them, while the benchmark only requires the common session protocol. Each operation still starts an isolated container, but every EDA operation resolves the same image ID. The image contains no task, PDK, harness source, or credentials; `.dockerignore` allows only dependency declarations and lock files. Install the KLayout CLI and Python API from separate packages and have tool checks confirm that their versions agree. The build does not depend on a local KLayout source tree or private cache.

The build needs access to system packages, tool release sites, and the Python index, and verifies downloaded artifacts against fixed digests. The distribution still resolves base system packages, so the final image identity binds the result; the Dockerfile alone cannot guarantee a byte-for-byte rebuild. To use a host loopback proxy:

```bash
uv run --locked python scripts/public_preview.py build --network host
```

The script preserves existing `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` variables. Proxy settings affect the build only; the harness controls networking for run containers.

<a id="preview-troubleshooting"></a>

## Startup Troubleshooting

| Symptom | Handling |
|---|---|
| Docker command is missing or cannot reach the daemon | Install/start Docker first and ensure the current user can run `docker version`; `doctor` checks this before downloading and preparing |
| Native ARM, macOS, or Windows environment | Use a Linux x86-64 host; the current tool image is fixed to amd64 and other platforms are unvalidated |
| `PDK missing` or a pinned source file is absent | Run `quickstart` to initialize the PDK and the required nested KLayout Python dependencies, or run `git submodule update --init --depth 1 third_party/IHP-Open-PDK` followed by `git -C third_party/IHP-Open-PDK submodule update --init --depth 1 ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api ihp-sg13g2/libs.tech/klayout/python/pypreprocessor`; when a source digest differs, inspect local changes and the recorded commit and keep the hash check enabled |
| A required nested PDK directory is non-empty but has no Git metadata | Do not run recursive update over it. Move the partial directory aside, then run the targeted nested-submodule command above; if its reviewed marker files are complete, `quickstart` reuses it and `prepare` verifies the content |
| `No such image` or image validation fails during preparation | Run `quickstart` or `build`; when naming an image manually, pass `--image` to `prepare` |
| A `build/...` support bundle is missing | Complete `prepare` first. The preview script creates separate tool configurations; older configurations that still use `.cache/sg13g2-*` remain supported when those paths are supplied explicitly |
| Output directory already exists | Choose a new `--output` path; logs produced by failed steps remain in the old directory for diagnosis |
| Build download fails | Check connectivity to Ubuntu, the Python package index, and tool release sites; downloads require matching digests. With a host loopback proxy, add `--network host` to `quickstart` or `build` and preserve `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`; see [stepwise preparation and reuse](#stepwise-preparation-and-reuse) for other network setup |
| Protocol probe exits 1 / success rate is 0 | The probe draws only a rectangle and does not implement a circuit, so evaluation failure is expected. The preview wrapper checks normal exit, submission, and statistics; do not treat an infrastructure failure as a passing probe |
| A real model lacks a key or cannot be reached | Validate the environment with the no-key public flow first, then configure your endpoint, model, and host key variable using [the model gateway and declared wire adapter](running.md#model-inference); public CI does not call a paid model |

<a id="external-sources"></a>

## Upstream and Process Resources

The addresses in `third_party/` are declared by [.gitmodules](../.gitmodules), and versions are fixed by Git submodule references; nested dependencies use the commits recorded upstream. The public preview needs the PDK and its two KLayout Python dependencies used by the reviewed view. Digital, openEMS, Palace, course, and tapeout materials are optional sources for investigation. See the [task guide](tasks.md#asset-rights) for source, license, and distribution requirements; retain licenses with each upstream and component. Do not put a complete checkout in Agent mounts or the common image.

```bash
git submodule update --init --depth 1 third_party/IHP-Open-PDK
git -C third_party/IHP-Open-PDK submodule update --init --depth 1 \
  ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api \
  ihp-sg13g2/libs.tech/klayout/python/pypreprocessor
git submodule status --recursive
```

To update an upstream, fetch it in the target submodule, choose an official commit, fix it at a detached checkout, synchronize nested dependencies, and then inspect `git diff --submodule=log` in the public repository. Validate affected environments and tasks before committing the reference; normal runs do not follow a remote branch automatically. Make PDK source fixes and run upstream regressions in that repository.

| Resource | Preparation and validation |
|---|---|
| PDK view | `benchmarking.environment` prepares primitives, callbacks, layer tables, rules, and licenses using the per-file digests in [sg13g2_view.json](../benchmarking/sg13g2_view.json); `--bundle` generates the Agent resource bundle |
| Tool support bundle | `benchmarking.prepare_support` follows the [technology/sg13g2](../technology/sg13g2) manifests to prepare Magic, MOS models, and KLayout rules; compile models in a separate container |
| Frozen bundle | `manifest.json` binds files, sources, and the actual build environment; loading rejects modifications, missing or extra files, and symlinks, while backends consume byte snapshots. A reviewed PDK bundle is auto-detected by sessions; `/protocol/resources.json` publishes its container-local import paths and a preflight import command without adding task or reference files |

Keep originals byte-for-byte as supplied upstream and register framework-generated startup settings separately in the manifest. Preserve the license notices for components such as PSP models, PyCell, and pypreprocessor. The PDK view currently validates only basic MOS/tap primitives; importing a tool or device does not qualify every parameter or process rule.

<a id="source-preparation"></a>

### Prepare a Netlist from a Schematic

`benchmarking.prepare` gives a network-isolated preparation container only the files explicitly listed by a case TOML's `[source_export]` section, invokes Xschem to export the raw LVS netlist, and saves source digests and diagnostic logs. Arguments include the case configuration, output directory, and `--checkout NAME=PATH` for each source. Use the unified image with `--image layout-bench-tools:local`. Any source export is preparation evidence, not a substitute for an upstream layout. See the [task guide](tasks.md) for source and input-semantics checks.

## EDA Backend Contract

The backend extension interface is described in [architecture](architecture.md#extension-layers). `main.py characterize` performs an independent measurement and `main.py evaluate` re-evaluates a GDS. A plan returns 0 when it passes, 1 when a check or specification fails, and 2 for a configuration or execution error. Output includes `report.json` and artifacts saved by digest. Characterization fixtures are not formal layout tasks.

### ngspice and Magic

ngspice writes an input role as `<role>.spice` and uses `deck.spice` as its entry point. The testbench declares analyses and measurements; `parameters.values` generates `parameters.spice`, `parameters.measurements` specifies names and units, and `parameters.exports` names declared artifacts. Exit 0 still requires a complete set of finite measurements. See the [RC](../tests/fixtures/characterization/rc.toml), [divider](../tests/fixtures/characterization/divider.toml), and [MOS post-layout](../tests/fixtures/sg13g2/switch.toml) characterization fixtures.

Magic's `layout.extract_capacitance` takes the top cell and ordered `ports` from trusted configuration; check the port list against the authoritative netlist. Later jobs must reference the extracted netlist exported as-is rather than replacing it with string substitutions or a hand-written netlist. The current flow extracts devices and parasitic capacitance only and records `wire_resistance=false`; it cannot claim complete RC extraction. A case-specific qualification record must document the exact conditions and calibration scope.

### KLayout Physical Checks

`klayout-docker` implements the same Backend interface, with `check` selecting `artifact`, `drc`, or `lvs`. A task job supplies only `layout` and `task`; LVS additionally supplies the authoritative `netlist`. For standalone debugging, use `parameters.top_cell`, `max_bytes`, and the LVS `subcircuit`; when `task` is supplied, these must not conflict with it. Checks do not publish an extracted netlist for post-layout simulation. The LVS extraction result is diagnostic evidence; a separate PEX job re-extracts from the same GDS for post-layout simulation.

The artifact check uses KLayout's native reader to validate the GDSII stream, the published file-size limit, the specified top cell, non-empty geometry, and unresolved hierarchy references. DRC/LVS configuration is a JSON file in the frozen support bundle that specifies `deck`, fixed `variables`, and explanatory `scope`; DRC also declares `required_categories`. The optional DRC `additional_decks` list contains `{deck, required_categories}` entries sharing the same variables. Every deck runs in its own KLayout process and must complete and produce its required categories. The gate sums their counts and fails if any deck fails; an execution or report error takes precedence. `report.db` and `report-1.db` (and corresponding logs/completion markers) remain separate native evidence, with per-deck results in `result.json`. Required categories guard against skipping rule groups but are not a complete rule list. Exact case-local `parameters.waivers` remain available to other reviewed tasks, but the AnalogAcademy upstream reproduction path supplies none. For LVS, native cross-reference data must confirm that comparison occurred, the reference circuit is non-empty, and the requested circuit participated. The `ignore_top_ports_mismatch` variable controls whether the upstream runset and adapter add named-port checks after comparison. The reader follows KLayout's [LVS database](https://www.klayout.de/doc/code/class_LayoutVsSchematic.html) and [comparison result](https://www.klayout.de/doc/code/class_NetlistCrossReference.html) documentation. A missing report, skipped run, crash, or timeout is `error`; a completed check with unwaived violations is `failed`.

<a id="original-asset-evaluation"></a>

### Original-asset evaluation

The former `drc.json`, `lvs.json` and `lvs-comparator.json` profiles are removed. Reprepare support from `technology/sg13g2/klayout.json`; old frozen bundles are not updated in place. The profiles now make their upstream scope explicit:

| Profile | Mapping and provenance |
|---|---|
| `drc-upstream.json` | Current pinned PDK GUI defaults (`tech/macros/sg13g2_drc.lym` → `drc/run_drc.py`): main plus extra `sg13g2_maximal.drc`, deep mode, density and antenna off. This is not the historical minimal deck. |
| `lvs-upstream.json` | Current pinned PDK GUI defaults (`tech/macros/sg13g2_lvs.lym`): explicit taps, native simplification, strict named ports. |
| `lvs-analogacademy.json` | Course-era defaults mapped to the current PDK: explicit taps, native simplification, and comparison without the additional `flag_missing_ports` check. The historical [GUI options](https://github.com/IHP-GmbH/IHP-Open-PDK/blob/eb1b540c58346cf6259285a38d09b2a04feb344a/ihp-sg13g2/libs.tech/klayout/tech/macros/lvs_options.yml) and [LVS runset](https://github.com/IHP-GmbH/IHP-Open-PDK/blob/eb1b540c58346cf6259285a38d09b2a04feb344a/ihp-sg13g2/libs.tech/klayout/tech/lvs/sg13g2.lvs) establish these defaults, not the author's actual saved options. |

`python -m benchmarking.upstream` evaluates all eight currently cataloged cases through one API, one case per invocation. Each case's `[upstream_evaluation]` declares the original layout/netlist asset IDs, separate layout and reference circuit names, profile names, and selection basis. The entry point checks the upstream commit and selected asset hashes, invokes the existing evaluation API, and archives the exact case TOML alongside the report. It does not export or rewrite netlists, remove taps, tie bulk nodes, change device parameters, or supply waivers. Native runset simplification is part of upstream evaluation, not input preprocessing. The comparator task also materializes a byte-for-byte copy of its declared upstream LVS netlist; the former normalization script and record have been removed. `tasks/IHP-AnalogAcademy/evaluate.py` remains a thin compatibility entry point. The standalone file-size limit is 64 MiB and the per-job timeout defaults to 600 seconds (`--timeout-seconds`); these do not change executable task limits.

```bash
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK technology/sg13g2/klayout.json build/support/upstream-all
uv run --locked python -m benchmarking.upstream \
  tasks/IHP-AnalogAcademy/cases/module_1_bandgap_reference.part_3_layout.OTA_layout.input_pair.toml \
  --support build/support/upstream-all \
  --output build/runs/upstream-input-pair
```

Run the same command with any case listed in either `tasks/*/catalog.toml`,
using a fresh output directory. The metadata supplies the top cell;
`--top-cell` is an optional assertion and rejects conflicts. `--root` specifies
the checkout root (default: current working directory).

The TO_Apr2025 `lvs-to-apr2025.json` profile maps native compare-only port
semantics independently of the course profile. The archived 40 GHz LVS
database records `Match` with zero layout pins and nine reference pins;
adding strict named-port checks would change that evaluation policy. Other
switches use current pinned defaults, since the historical options are not
archived. DRC uses current main plus extra scope; archived minimal/maximal
report names do not establish equality with today's rule coverage.

| Case | Original evaluation GDS selection / top cell | Original reference circuit |
|---|---|---|
| AnalogAcademy full OTA | Declared reference / `two_stage_OTA_layout` | `two_stage_OTA_layout` |
| AnalogAcademy input pair | Declared reference / `input_common_centroid` | `input_common_centroid` |
| AnalogAcademy output stage | Declared reference / `output_stage` | `output_stage` |
| AnalogAcademy comparator | Hierarchical reference / `DIFF_COMPARATOR` | `DIFF_COMPARATOR` |
| TO 160 GHz LNA | `design_data/klayout/` variant / `TOP` | `TOP` |
| TO 40 GHz TIA | `design_data/klayout/` variant / `FDM_QNC_00_LN_TIA` | `FDM_QNC_00_LN_TIA` |
| TO 97 GHz TIA | `design_data/klayout/` variant / `FMD_QNC_01_LIN_TIA` | `FMD_QNC_01_LIN_TIA` |
| TO DC–130 GHz TIA design 1 | Declared reference / `FMD_QNC_03a_TIA_1` | `TOP` in `LVS_Check_Netlist.cdl` |

TO cases keep the final delivery GDS in their inventory but explicitly select
the available KLayout evaluation variant. For 160 GHz, that variant's `TOP`
name also agrees with the archived LVS database. DC–130 GHz uses the author's
existing `LVS_Check_Netlist.cdl`, which identifies itself as the modified Qucs-s
netlist for KLayout LVS; `TOP.cdl` remains inventoried as a source export.
Layout-Bench performs neither that upstream modification nor cell renaming.
The 40/97 GHz historical reports refer to `TOP`, unlike the available GDS/CDL
names; their exact historical input pairing therefore remains unverified.

The complete eight-case run with the pinned PDK and KLayout 0.30.11 produced
the following native results, without waivers:

| Case | DRC items (main + extra) | LVS job |
|---|---:|---|
| full OTA | 1072 | `NoMatch` |
| input pair | 63 | `NoMatch` |
| output stage | 727 | `NoMatch` |
| comparator | 7 | `Match` |
| 160 GHz LNA | 3289 | Reader error: two-terminal poly resistor |
| 40 GHz TIA | 1585 | Reader error: two-terminal poly resistor |
| 97 GHz TIA | 544 | Reader error: two-terminal poly resistor |
| DC–130 GHz TIA design 1 | 110 | Reader error: two-terminal poly resistor |

All four TO source LVS netlists use two-terminal `rppd` devices. The current
PDK's `lvs/rule_decks/custom_reader.lvs:create_resistor` unconditionally
requires three nodes for poly resistors and raises `Poly resistor should
have 3 nodes, please recheck` before comparison. There is no exposed switch
for accepting the old two-terminal form. This is a toolchain/input
compatibility blocker, not `NoMatch` or a port-policy failure. The mapping
retains the original bytes and records the error; it does not invent a bulk
connection, replace the reference with extraction, or patch the runset.
Use each job's status when interpreting the report: the evaluation API may
return overall `failed` (exit 1) for a completed DRC rejection even when LVS
has an execution `error`.

Use new support/output directories on subsequent preparations. The result is physical evidence, not qualification: exit 0 means passed, 1 rejected, 2 an evaluation error. With PDK `5e6d592e4002946a4616f798c357f0f3c06cf3b6` and KLayout 0.30.11, the original input pair reports 63 unwaived DRC items (54 main, 9 extra) and fails LVS on tap parameters; the five combined PMOS devices and five ports match. The original comparator (`module_3_8_bit_SAR_ADC.part_5_analog_layout.comparator.toml`, top cell `DIFF_COMPARATOR`) passes LVS with the same profiles and reports 7 unwaived DRC items (5 `NBL.b` in main, 2 `NW.d` in extra). Do not alter the source to force a pass. Case-local author's settings and exact historical run identity were not archived upstream, so this is a documented reconstruction on the current toolchain, not an exact historical replay.

Legacy fixtures still referencing the removed profiles have not been migrated. They are not the entry point or validation basis for this original-asset evaluation.

<a id="geometry"></a>

### Geometry and Port Correspondence

`klayout-geometry-docker` interprets schema 1 of `constraints.json`: `bbox_max` names the functional layers that contribute to the outline and sets maximum width and height; `named_metal_ports` names each port, its drawing/pin/text layers, logical connection layer, and minimum square side that can be contacted; `functional_bbox_area` measures area using the layer set from an outline constraint. The top cell must contain exactly one label with each required name. Its center square must lie completely in the intersection of the pin, drawing, and correctly extracted network regions. Adapters extend the set of constraint kinds; the generic plan executor does not interpret process layers or geometry semantics.

LVS can export a native `klayout-lvs` database and a JSON binding. The binding records the candidate GDS, database digest, top cell, and logical-layer mapping. After validating the binding, the geometry adapter uses the native [LayoutVsSchematic](https://www.klayout.de/doc/code/class_LayoutVsSchematic.html), [NetlistCrossReference](https://www.klayout.de/doc/code/class_NetlistCrossReference.html), and [LayoutToNetlist](https://www.klayout.de/doc/code/class_LayoutToNetlist.html) APIs for network correspondence and geometry. Process support bundles declare deck-layer variables; the adapter reads the names actually registered by the run instead of fixing runtime indices such as `l10`, and it does not modify upstream rules.

Magic's SPICE export drops the `!` from `!CONTROL`, causing a collision with `CONTROL`. The extraction adapter first uses KLayout on an isolated GDS copy to give unsafe interface names unique aliases, preserves the original candidate and mapping evidence, and then uses the native SPICE reader to check the count, names, and order of exported ports. It does not rewrite the original task netlist; simulation connects through the declared port order. For pre-layout simulation, the PDK's native reader and the KLayout writer generate model calls from the authoritative netlist; no additional SPICE/CDL parser is introduced.

### Qucs-S and Qucsator

The unified image installs Qucs-S 26.1.1 from the pinned Ubuntu 24.04 amd64 OBS package and builds the official Qucsator 0.0.20 core from commit `e995f9acc71a8c7319286944e4a1692318b9dd80`. The image therefore provides `qucs-s`, `qucsator`, `qucsator_rf`, and `qucsconv` alongside Ngspice. Qucs-S is used headlessly as the `.sch` parser/netlister (`QT_QPA_PLATFORM=offscreen`); the simulator remains an explicit backend.

Xyce is not silently substituted by Qucsator. The upstream project does not publish an Ubuntu-compatible open-source binary; a reproducible Xyce backend needs its own source build (including Trilinos) and is outside this image until that build is pinned and validated. Current IHP MPA schematics that declare Xyce analyses must consequently report the backend as unavailable rather than claiming a completed simulation.

<a id="manual-tools"></a>

## Unified tool image

The repository publishes and tests one image: `layout-bench-tools:local`. It contains the complete EDA runtime used by preparation, simulation, extraction, and judging, including Qucs-S, Qucsator/QucsatorRF, Ngspice, Xschem, Magic, OpenVAF, and KLayout. Harnesses remain an external seam and are not baked into the image. Each operation still runs in an isolated container invocation, but all EDA invocations resolve the same frozen image ID.

Build and check that image directly:

```bash
uv run --locked python scripts/public_preview.py build --image layout-bench-tools:local
bash tests/integration/test_toolchain.sh
```

Role-specific image tags are not part of the supported workflow. This keeps tool versions and backend availability consistent across preparation, solving, and evaluation. Prepare the shared support paths with the commands below:

```bash
uv run --locked python -m benchmarking.environment third_party/IHP-Open-PDK build/support/pdk-view
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK technology/sg13g2/magic.json build/support/sg13g2-magic
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK technology/sg13g2/mos-models.json build/support/sg13g2-mos-models
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK technology/sg13g2/klayout.json build/support/sg13g2-klayout
```

Resolve relative `settings.support` paths from the backend's launch working directory, while paths in a plan are relative to the plan file; keep these namespaces distinct. New configurations may use absolute support paths. The [integration tests](../tests/integration) maintain complete fixture invocations; see [CONTRIBUTING](../CONTRIBUTING.md#verification) for how to select and run them.
