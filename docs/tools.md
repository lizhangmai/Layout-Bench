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

`quickstart` chains host checks, image build, PDK initialization, preparation, and smoke validation, and writes `prepared/` and `run/`. It reuses build caches and the pinned upstream checkout, but prepares derived resources and fresh run artifacts again. `--skip-build` reuses an existing image and still binds its actual ID; it does not download an unpublished prebuilt image or overwrite existing output. The smoke run evaluates the reference, the original offline protocol probe, and the provider-neutral canonical probe; the latter is a deterministic harness control, not a model baseline. The prepared directory contains both probe configurations. The script assembles only public examples; use `main.py` and your own tool configuration for custom tasks.

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

ngspice writes an input role as `<role>.spice` and uses `deck.spice` as its entry point. The testbench declares analyses and measurements; `parameters.values` generates `parameters.spice`, `parameters.measurements` specifies names and units, and `parameters.exports` names declared artifacts. Exit 0 still requires a complete set of finite measurements. See the [RC](../examples/characterization/rc.toml), [divider](../examples/characterization/divider.toml), and [MOS post-layout](../examples/sg13g2/switch.toml) plan examples.

Magic's `layout.extract_capacitance` takes the top cell and ordered `ports` from trusted configuration; check the port list against the authoritative netlist. Later jobs must reference the extracted netlist exported as-is rather than replacing it with string substitutions or a hand-written netlist. The current flow extracts devices and parasitic capacitance only and records `wire_resistance=false`; it cannot claim complete RC extraction. A case-specific qualification record must document the exact conditions and calibration scope.

### KLayout Physical Checks

`klayout-docker` implements the same Backend interface, with `check` selecting `artifact`, `drc`, or `lvs`. A task job supplies only `layout` and `task`; LVS additionally supplies the authoritative `netlist`. For standalone debugging, use `parameters.top_cell`, `max_bytes`, and the LVS `subcircuit`; when `task` is supplied, these must not conflict with it. Checks do not publish an extracted netlist for post-layout simulation. The LVS extraction result is diagnostic evidence; a separate PEX job re-extracts from the same GDS for post-layout simulation.

The artifact check uses KLayout's native reader to validate the GDSII stream, the published file-size limit, the specified top cell, non-empty geometry, and unresolved hierarchy references. DRC/LVS configuration is a JSON file in the frozen support bundle that specifies `deck`, fixed `variables`, and explanatory `scope`; DRC also declares `required_categories`. Required categories guard against skipping rule groups but are not a complete rule list. A DRC job may additionally declare case-local `parameters.waivers`; each waiver names an exact report category, cell, marker text, and human-readable reason. Only matching marker items are waived. Archive the native report and raw category counts together with waived and unwaived counts; every unwaived violation remains a failure. Waivers do not modify the shared deck or its rule thresholds. The backend requires the deck to reach its end marker, the process to complete normally, and the database to be readable. For LVS, use native cross-reference data to confirm that comparison occurred, the specified reference circuit is non-empty, and the target circuit corresponds. A profile with `ignore_top_ports_mismatch = "false"` additionally requires matching top-level port labels; a profile that sets it to `"true"` follows the upstream runset's port-mismatch policy while still requiring circuit/device/connectivity comparison. The reader follows KLayout's [LVS database](https://www.klayout.de/doc/code/class_LayoutVsSchematic.html) and [comparison result](https://www.klayout.de/doc/code/class_NetlistCrossReference.html) documentation. A missing report, skipped run, crash, or timeout is `error`; a completed check with unwaived violations is `failed`.

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
uv run --locked python -m benchmarking.prepare_support third_party/IHP-Open-PDK technology/sg13g2/klayout.json build/support/sg13g2-klayout-ports
```

Resolve relative `settings.support` paths from the backend's launch working directory, while paths in a plan are relative to the plan file; keep these namespaces distinct. New configurations may use absolute support paths. The [integration tests](../tests/integration) maintain complete fixture invocations; see [CONTRIBUTING](../CONTRIBUTING.md#verification) for how to select and run them.
