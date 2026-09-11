# Tool Environments, Resource Preparation, and EDA Adapters

For the first run, use `quickstart` from the root [README](../README.md#quick-start-no-model-key-required); it builds only one `layout-bench-tools:local` image. This page covers stepwise preparation, troubleshooting, and changes to the tool environment. Run every command from the repository root and use a new output directory. Repository-local generated outputs use `build/`: benchmark runs go under `build/runs/`, independently prepared support bundles under `build/support/`, and Python distributions under `build/dist/`.

## Stepwise Preparation and Reuse

The host uses Linux x86-64, Git, uv, Python 3.12+, and accessible Docker/BuildKit. Versions are maintained by the [Dockerfile](../Dockerfile), [pyproject.toml](../pyproject.toml), and [uv.lock](../uv.lock); framework development needs only `uv sync --locked`.

| `scripts/public_preview.py` subcommand | When to use it |
|---|---|
| `doctor` | Check the host and Docker before downloading; does not call a model |
| `build` | Build only the unified image; accepts `--image`, defaulting to `layout-bench-tools:local` |
| `prepare --output <new-directory>` | Prepare the selected case, Magic, simulation models, KLayout rules, and solver resource bundle from the pinned PDK; bind tools to the actual image ID |
| `run --prepared <prepared-directory> --output <new-directory>` | Evaluate the prepared case witness through its complete declared plan and save raw evidence |

`quickstart` chains host checks, image build, PDK initialization, preparation, and reference evaluation, and writes `prepared/` and `run/`. It defaults to comparator; `quickstart` and `prepare` accept `--case full_OTA` to select the OTA. The script uses each case's `[toolchain]`, constraints, evaluation plan, and published witness. Preparation changes only the image and resource paths in a host-side copy at `prepared/case/case.toml`. The solver loader still materializes only declared inputs, excluding the copied reference and source README. Comparator uses the MOS model bundle; full_OTA uses the analog model bundle for its MOS, MIM capacitor, and tap models.

`--skip-build` reuses the existing image and still binds its actual ID. Existing PDK files are reused and checked against reviewed digests; output directories must be new. Quick start makes no model calls and does not establish new qualification conditions. Case-specific tests cover calibration and rejection behavior; see [CONTRIBUTING](../CONTRIBUTING.md#verification).

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
| A `build/...` support bundle is missing | Complete `prepare` first. Use the resulting `prepared/case/case.toml`, whose embedded bindings point to the prepared bundles |
| Output directory already exists | Choose a new `--output` path; logs produced by failed steps remain in the old directory for diagnosis |
| Build download fails | Check connectivity to Ubuntu, the Python package index, and tool release sites; downloads require matching digests. With a host loopback proxy, add `--network host` to `quickstart` or `build` and preserve `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`; see [stepwise preparation and reuse](#stepwise-preparation-and-reuse) for other network setup |
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

After moving the PDK pin, regenerate the support profile digests from the clean checkout and review the resulting diff before rebuilding bundles:

```bash
uv run --locked python -m benchmarking.refresh_support third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml
```

The same command refreshes a circuit case after moving its source-collection pin, rewriting `origin.commit` and the digests of `sources`, `upstream_assets`, and case-owned `source_export` files in place (PDK-owned files stay with the referenced `pdk.toml` profile):

```bash
uv run --locked python -m benchmarking.refresh_support third_party/IHP-AnalogAcademy \
  tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/comparator/case.toml
```

The refresh refuses a checkout with uncommitted tracked changes and fails on any listed file missing upstream, so a stale or renamed selection surfaces at refresh time rather than during evaluation.

| Resource | Preparation and validation |
|---|---|
| PDK view | `benchmarking.environment` prepares primitives, callbacks, layer tables, rules, and licenses using the per-file digests in [sg13g2_view.json](../benchmarking/sg13g2_view.json); `--bundle` generates the Agent resource bundle |
| Tool support bundle | `benchmarking.prepare_support` follows the profiles in the [tasks/ihp-sg13g2/pdk.toml](../tasks/ihp-sg13g2/pdk.toml) manifest to prepare Magic, MOS models, and KLayout rules; compile models in a separate container |
| Frozen bundle | `manifest.json` binds files, sources, and the actual build environment; loading rejects modifications, missing or extra files, and symlinks, while backends consume byte snapshots. A reviewed PDK bundle is auto-detected by sessions; `/protocol/resources.json` publishes its container-local import paths and a preflight import command without adding task or reference files |

Keep originals byte-for-byte as supplied upstream and register framework-generated startup settings separately in the manifest. Preserve the license notices for components such as PSP models, PyCell, and pypreprocessor. The PDK view currently validates only basic MOS/tap primitives; importing a tool or device does not qualify every parameter or process rule.

<a id="source-preparation"></a>

### Prepare a Netlist from a Schematic

`benchmarking.prepare` gives a network-isolated preparation container only the files explicitly listed by a case TOML's `[source_export]` section, invokes Xschem to export the raw LVS netlist, and saves source digests and diagnostic logs. The case lists its own files in `[source_export.files]`; reviewed PDK symbols come from the `pdk_profile` reference (for example `../../../pdk.toml#xschem-symbols`), so the PDK manifest remains their single digest declaration. Arguments include the case configuration, output directory, and `--checkout NAME=PATH` for each source. Use the unified image with `--image layout-bench-tools:local`. Any source export is preparation evidence, not a substitute for an upstream layout. See the [task guide](tasks.md) for source and input-semantics checks.

The Dockerfile builds a pinned Xschem release from checksum-verified source.
Ubuntu's older Xschem package lacks the native `ev7` expression helper used by
the current SG13G2 tap symbols and can silently export a tap as `?`. The image
upgrade supplies that helper without changing PDK symbols or adding an exporter
shim. The [input-pair source regression](../tests/integration/test_input_pair_source.py)
exports the original schematic and checks its MOS connectivity and tap geometry
against the schematic dimensions. Rebuild the tools image before using this
export path; a process exit code of zero alone does not establish netlist validity.

## EDA Backend Contract

The backend extension interface is described in [architecture](architecture.md#extension-layers). `main.py characterize` performs an independent measurement and `main.py evaluate` re-evaluates a GDS. Tool bindings may be embedded in a schema-2 case as `[toolchain]`, following the [task configuration guide](tasks.md#evaluation-plan). `evaluate` and `run` use these bindings when `--toolchain` is omitted; `characterize` still requires an explicit toolchain configuration. A plan returns 0 when it passes, 1 when a check or specification fails, and 2 for a configuration or execution error. Output includes `report.json` and artifacts saved by digest. Characterization fixtures are not formal layout tasks.

### ngspice and Magic

ngspice writes an input role as `<role>.spice` and uses `deck.spice` as its entry point. The testbench declares analyses and measurements; `parameters.values` generates `parameters.spice`, `parameters.measurements` specifies names and units, and `parameters.exports` names declared artifacts. Exit 0 still requires a complete set of finite measurements. See the [RC](../tests/fixtures/characterization/rc.toml), [divider](../tests/fixtures/characterization/divider.toml), and [MOS post-layout](../tests/fixtures/sg13g2/switch.toml) characterization fixtures.

Magic takes the top cell and ordered `ports` from trusted configuration; check the port list against the authoritative netlist. Later jobs must consume the exported netlist as-is. `magic-capacitance-docker` retains its capacitance-only behavior and records `wire_resistance=false`. `magic-rc-docker` adds distributed resistance and capacitance, and can be bound to `layout.extract_rc`.

The RC adapter requires Magic 8.3.653 or newer. It uses a geometrically checked,
flattened extraction copy, keeps devices separate, and sets resistance selection,
minimum resistance, and delay thresholds to zero with network simplification
disabled. `capacitance_threshold_ff` controls capacitance omission; the comparator
uses zero. These are the explicit controls documented by the
[Magic extresist reference](https://opencircuitdesign.com/magic/commandref/extresist.html).
The archived upstream `extresist tolerance 1` setting is deprecated in the
installed Magic and is not used by this backend. Raw extraction, resistance,
topology, feedback, and port/geometry checks are retained with the result.

The shared image builds Magic 8.3.678 with one driver-selection correction in
`ResProcessNode`: the W/L accumulator and maximum use floating point, matching
the device reader. Integer truncation otherwise skips unlabelled internal nets
whose MOS drivers all have W/L below one, even with zero extraction thresholds.
The [Dockerfile](../Dockerfile) applies the correction to the pinned source;
the [RC regression](../tests/integration/test_magic_rc.py) checks the analytical
resistance increment of a wire between two such devices. This changes tool
arithmetic, not PDK extraction rules.

The supported RC interface has one declared port per conductor. A native
topology check rejects multiple ports on one conductor: the installed Magic
can otherwise duplicate the resistance network or bypass it with an alias
resistor. This limitation produces an evaluation error. The
[RC integration checks](../tests/integration/test_magic_rc.py) validate a known
wire-resistance increment, its effect on transistor delay, a fixture threshold
rejection, and invalid/unsupported inputs. Case-specific extraction warnings,
models, and calibration still require review; the comparator's current status
and commands are in its [case README](../tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/comparator/README.md).

### KLayout Physical Checks

`klayout-docker` implements the same Backend interface, with `check` selecting `artifact`, `drc`, or `lvs`. A task job supplies only `layout` and `task`; LVS additionally supplies the authoritative `netlist`. For standalone debugging, use `parameters.top_cell`, `max_bytes`, and the LVS `subcircuit`; when `task` is supplied, these must not conflict with it. Checks do not publish an extracted netlist for post-layout simulation. The LVS extraction result is diagnostic evidence; a separate PEX job re-extracts from the same GDS for post-layout simulation.

The artifact check uses KLayout's native reader to validate the GDSII stream, the published file-size limit, the specified top cell, non-empty geometry, and unresolved hierarchy references. DRC/LVS configuration is a JSON file in the frozen support bundle that specifies `deck`, fixed `variables`, and explanatory `scope`; DRC also declares `required_categories`. The optional DRC `additional_decks` list contains `{deck, required_categories}` entries sharing the same variables. Every deck runs in its own KLayout process and must complete and produce its required categories. The gate sums their counts and fails if any deck fails; an execution or report error takes precedence. `report.db` and `report-1.db` (and corresponding logs/completion markers) remain separate native evidence, with per-deck results in `result.json`. Required categories guard against skipping rule groups but are not a complete rule list. Exact case-local `parameters.waivers` remain available to other reviewed tasks, but the AnalogAcademy upstream reproduction path supplies none. For LVS, native cross-reference data must confirm that comparison occurred, the reference circuit is non-empty, and the requested circuit participated. The `ignore_top_ports_mismatch` variable controls whether the upstream runset and adapter add named-port checks after comparison. The reader follows KLayout's [LVS database](https://www.klayout.de/doc/code/class_LayoutVsSchematic.html) and [comparison result](https://www.klayout.de/doc/code/class_NetlistCrossReference.html) documentation. A missing report, skipped run, crash, or timeout is `error`; a completed check with unwaived violations is `failed`.

<a id="original-asset-evaluation"></a>

### Original-asset evaluation

Prepare support from the `klayout` profile in `tasks/ihp-sg13g2/pdk.toml`. Frozen bundles are not
updated in place; prepare a new bundle when the manifest changes. The profiles
declare their upstream scope explicitly:

| Profile | Mapping and provenance |
|---|---|
| `drc-upstream.json` | Current pinned PDK GUI defaults (`tech/macros/sg13g2_drc.lym` → `drc/run_drc.py`): main plus extra `sg13g2_maximal.drc`, deep mode, density and antenna off. This is not the historical minimal deck. |
| `lvs-upstream.json` | Current pinned PDK GUI defaults (`tech/macros/sg13g2_lvs.lym`): explicit taps, native simplification, strict named ports. |
| `lvs-analogacademy.json` | Course-era defaults mapped to the current PDK: explicit taps, native simplification, and comparison without the additional `flag_missing_ports` check. The historical [GUI options](https://github.com/IHP-GmbH/IHP-Open-PDK/blob/eb1b540c58346cf6259285a38d09b2a04feb344a/ihp-sg13g2/libs.tech/klayout/tech/macros/lvs_options.yml) and [LVS runset](https://github.com/IHP-GmbH/IHP-Open-PDK/blob/eb1b540c58346cf6259285a38d09b2a04feb344a/ihp-sg13g2/libs.tech/klayout/tech/lvs/sg13g2.lvs) establish these defaults, not the author's actual saved options. |

`python -m benchmarking.upstream` evaluates cataloged cases through one API, one case per invocation. Each case's `[upstream_evaluation]` declares the original layout/netlist asset IDs, separate layout and reference circuit names, profile names, and selection basis. The entry point checks the upstream commit and selected asset hashes, invokes the existing evaluation API, and archives the exact case TOML alongside the report. It does not export or rewrite netlists, remove taps, tie bulk nodes, change device parameters, or supply waivers. Native runset simplification is part of upstream evaluation, not input preprocessing. The comparator task instead delivers the untouched Xschem export of its matched derivative schematic as the task netlist (see the case README). `tasks/ihp-sg13g2/IHP-AnalogAcademy/evaluate.py` is a thin compatibility entry point. The standalone file-size limit is 64 MiB and the per-job timeout defaults to 600 seconds (`--timeout-seconds`); these do not change executable task limits.

```bash
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml#klayout build/support/upstream-all
uv run --locked python -m benchmarking.upstream \
  tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/input_pair/case.toml \
  --support build/support/upstream-all \
  --output build/runs/upstream-input-pair
```

Run the same command with any case listed in a `tasks/*/*/catalog.toml`,
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

With PDK commit `5e6d592e4002946a4616f798c357f0f3c06cf3b6` and KLayout
0.30.11, the original assets produce the following native results without
waivers. Reproduce each row with the command above and its catalog case:

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

All four TO source LVS netlists use legacy two-terminal poly-resistor cards:
`rhigh` in the 160 GHz LNA, and `rppd` (also `rhigh` in the 97 GHz case)
in the TIAs. The current
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

These results establish physical status under the declared profiles, not task
qualification. The input pair's LVS mismatch concerns tap parameters; its
combined MOS devices and ports match. The comparator's seven DRC findings and
their disposition are explained in its
[case README](../tasks/ihp-sg13g2/IHP-AnalogAcademy/cases/comparator/README.md#original-issues-and-modifications).
The author's settings and exact historical run identity were not archived
upstream, so the checks reconstruct documented defaults on the current
toolchain. Keep the original source bytes when reproducing them.

<a id="geometry"></a>

### Geometry and Port Correspondence

`klayout-geometry-docker` interprets schema 1 of the geometry constraints, supplied as a JSON snapshot from either `[task.constraints]` or a declared constraints file: `bbox_max` names the functional layers that contribute to the outline and sets maximum width and height; `named_metal_ports` names each port, its drawing/pin/text layers, logical connection layer, and minimum square side that can be contacted; `functional_bbox_area` measures area using the layer set from an outline constraint. The top cell must contain exactly one label with each required name. Its center square must lie completely in the intersection of the pin, drawing, and correctly extracted network regions. Adapters extend the set of constraint kinds; the generic plan executor does not interpret process layers or geometry semantics.

LVS can export a native `klayout-lvs` database and a JSON binding. The binding records the candidate GDS, database digest, top cell, and logical-layer mapping. After validating the binding, the geometry adapter uses the native [LayoutVsSchematic](https://www.klayout.de/doc/code/class_LayoutVsSchematic.html), [NetlistCrossReference](https://www.klayout.de/doc/code/class_NetlistCrossReference.html), and [LayoutToNetlist](https://www.klayout.de/doc/code/class_LayoutToNetlist.html) APIs for network correspondence and geometry. Process support bundles declare deck-layer variables; the adapter reads the names actually registered by the run instead of fixing runtime indices such as `l10`, and it does not modify upstream rules.

Magic's SPICE export drops the `!` from `!CONTROL`, causing a collision with `CONTROL`. The extraction adapter first uses KLayout on an isolated GDS copy to give unsafe interface names unique aliases, preserves the original candidate and mapping evidence, and then uses the native SPICE reader to check the count, names, and order of exported ports. It does not rewrite the original task netlist; simulation connects through the declared port order.

The AnalogAcademy LVS profile also accepts ngspice model calls for
`sg13_lv_nmos`, `sg13_lv_pmos`, `cap_cmim`, `ntap1` and `ptap1`. Its
`sg13g2-model-calls.lvs` entry point is generated from the KLayout support
manifest and includes the unchanged upstream runset. A KLayout
[reader delegate](https://www.klayout.de/doc-qt5/code/class_NetlistSpiceReaderDelegate.html)
maps these `X` calls to the native PDK device handlers, preserving their terminal
mapping, parameter units, simplification and comparison rules. Other `X` calls
retain normal hierarchy handling, and legacy CDL primitive cards retain their
native interpretation. Use circuit-local `.param` definitions and compact
expressions on model calls; expression parsing and parameter scoping remain
those of the pinned native reader. This is an input adapter, with no rule
waivers or new device models. The full OTA uses one authoritative circuit for LVS and direct
pre-layout simulation: tap `a`/`p` geometry and derived `r` share the same
parameter definitions, and MOS finger/multiplicity parameters reach ngspice
without LVS simplification. Candidate scoring still simulates only GDS-derived
PEX. Other source dialects require an explicitly validated adaptation.

### HBT core simulation support

[The HBT model profile](../tasks/ihp-sg13g2/pdk.toml) prepares the pinned
HBT, resistor and capacitor include closure, using native ngspice VBIC and
OpenVAF-compiled R3_CMC and MoM models. It retains the R3_CMC license and
NOTICE with the IHP adaptation. No compact-model source is patched.
The [design 1 regression](../tests/integration/test_to_apr2025_schematic.py)
checks nominal DC operation of the schematic-derived two-stage TIA core.
This does not validate RF/EM extraction, PEX, noise or statistical corners;
see the [case scope](../tasks/ihp-sg13g2/TO_Apr2025/cases/DC_to_130_GHz_TIA.design_1/README.md#core-operating-point-check).

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
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml#magic build/support/sg13g2-magic
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml#mos-models build/support/sg13g2-mos-models
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK tasks/ihp-sg13g2/pdk.toml#klayout build/support/sg13g2-klayout
```

Resolve relative `settings.support` paths from the backend's launch working directory, while paths in a plan are relative to the plan file; keep these namespaces distinct. New configurations may use absolute support paths. The [integration tests](../tests/integration) maintain complete fixture invocations; see [CONTRIBUTING](../CONTRIBUTING.md#verification) for how to select and run them.
