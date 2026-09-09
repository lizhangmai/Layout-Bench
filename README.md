<p align="center">
<strong>Layout-Bench</strong><br/>
<sub>A reproducible benchmark for AI agents that generate integrated-circuit layouts.</sub>
</p>

<p align="center">
Measure whether an agent can turn a circuit netlist, physical constraints, and process resources into a valid GDS layout.
</p>

<p align="center">
<a href="README_CN.md">Simplified Chinese</a> •
<a href="#quick-start">Quick Start</a> •
<a href="docs/architecture.md">Architecture</a> •
<a href="CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
<a href="https://github.com/lizhangmai/Layout-Bench/actions/workflows/checks.yml"><img src="https://github.com/lizhangmai/Layout-Bench/actions/workflows/checks.yml/badge.svg?branch=main" alt="Framework checks"></a>
<a href="https://github.com/lizhangmai/Layout-Bench/actions/workflows/cd.yml"><img src="https://github.com/lizhangmai/Layout-Bench/actions/workflows/cd.yml/badge.svg" alt="Release workflow"></a>
<a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12%2B-3776AB.svg?logo=python&logoColor=white" alt="Python 3.12+"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f.svg" alt="MIT license"></a>
</p>

Layout-Bench runs an Agent in an isolated container, records an explicit GDS submission, and evaluates the frozen candidate with independent EDA tools. DRC/LVS establish physical validity; a complete task also checks the declared geometry and post-layout performance limits.

> **Public preview.** Quick start evaluates the published [comparator](tasks/IHP-AnalogAcademy/cases/comparator/README.md) witness, with [full_OTA](tasks/IHP-AnalogAcademy/cases/full_OTA/README.md) also available. Other public circuits are indexed in [IHP AnalogAcademy](tasks/IHP-AnalogAcademy/catalog.toml) and [TO_Apr2025](tasks/TO_Apr2025/catalog.toml); consult each case's status and README for evaluation readiness and qualification scope.

## Why Layout-Bench?

| Capability | What it provides |
| --- | --- |
| **End-to-end layout tasks** | A frozen netlist, constraints, process resources, and evaluation plan, ending in a GDS artifact. |
| **Reproducible conditions** | Pinned inputs, configuration digests, image IDs, budgets, event logs, and durable submissions. |
| **Independent judgment** | A trusted evaluator rechecks the candidate after the Agent stops; self-reported checks do not decide the score. |
| **Open integration surface** | Any executable harness and configurable EDA backend can use the same frozen session and evaluation contracts. |
| **Qualification-first evaluation** | Reference witnesses, counterexamples, extraction checks, and schematic/post-layout calibration expose judge failures before release. |

## Prerequisites:

- **Linux x86-64**, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
- **Docker with BuildKit**, accessible to your user. Tool images use Ubuntu 24.04; native macOS, Windows, and ARM execution are not validated.
- **Network access and storage** for the initial tool/image/PDK downloads and several GB of free space. Evaluation containers run without external network access.

Use a source checkout and run commands from its root. The quick-start command supplies Python 3.12 through uv. No private checkout, PyPI installation, or prebuilt image release is required.

<a id="quick-start-no-model-key-required"></a>

## Quick Start

Clone the public repository, then run:

```bash
git clone https://github.com/lizhangmai/Layout-Bench.git
cd Layout-Bench
uv run --python 3.12 --locked python scripts/public_preview.py quickstart --output build/runs/preview
```

This builds one `layout-bench-tools:local` image, fetches the pinned PDK, prepares reviewed resources, and evaluates the comparator reference GDS through its complete case plan. KLayout, ngspice, Qucs-S/Qucsator, Magic, OpenVAF, Xschem, and Python are in that image; harness runtimes are supplied by each harness through the common session contract, so no role-specific EDA image is needed. The quick start never calls a model account.

If your host proxy listens only on `127.0.0.1` or `localhost`, add `--network host` to the quick-start command so the image build can reach it. This applies only to image construction; evaluation containers still run with networking disabled.

The first run downloads tools and the PDK and may take several minutes. Later runs reuse Docker layers and the PDK checkout while preparing fresh, verified resources and workspaces. Choose a new `--output` directory for each run; existing evidence is never overwritten. Use `--skip-build` to reuse an already built image. Quick start initializes the PDK and only the two nested KLayout Python dependencies required by the reviewed view; digital, openEMS, and Palace submodules remain optional. If those required directories already contain complete files without Git metadata, quick start reuses them and the preparation hash checks still verify every file.

Repository-local generated files use one top-level directory: benchmark runs are under `build/runs/`, prepared PDK and EDA bundles under `build/support/`, and Python distributions under `build/dist/`. The `build/lib/` and `build/bdist.*` directories are temporary setuptools staging files. The directory is ignored by Git and can be removed at any time when you do not need its local reports or prepared resources.

A successful run ends with `PASS` and creates:

| File | Content |
| --- | --- |
| `build/runs/preview/run/preview.json` | Case ID, reference evaluation result, and confirmation that no model was called. |
| `build/runs/preview/run/reference/report.json` | Complete artifact, DRC, LVS, geometry, RC extraction, and post-layout performance results. |
| `build/runs/preview/prepared/case/case.toml` | Case configuration bound to the actual image ID and resource paths; usable with `main.py run` or `evaluate`. |

The wrapper returns **0** only when the witness passes the complete evaluation. This demonstrates feasibility under the declared conditions; it is not a model score, an optimum, or signoff across all operating conditions.

To verify full_OTA using the existing image:

```bash
uv run --locked python scripts/public_preview.py quickstart --case full_OTA \
  --skip-build --output build/runs/ota-preview
```

IHP and TO_Apr2025 reference and qualification assets are published only for cases that pass the upstream-complete screening gate. Standard Agent runs receive only the declared task inputs and never a reference solution.

<a id="run-your-agent"></a>

## How to Use

The workflow is simple:

1. **Choose a task** — start with a case that has a complete evaluation and a passing witness, such as comparator or full_OTA.
2. **Configure a harness** — provide any executable command, reviewed files, resources, and budgets; an optional harness profile records its protocol and execution semantics.
3. **Submit a candidate** — work in `/workspace`, then run `python -I /protocol/submit.py` to submit the configured GDS explicitly.
4. **Evaluate and compare** — use the independent evaluator for one candidate, or a frozen batch plan for task × configuration × repetition measurements.

The configured harness receives `/protocol/prompt.txt`, `/protocol/task.json`, `/protocol/harness.json`, `/protocol/resources.json`, and read-only `/task` inputs. It does not receive the public reference solution during a standard run. The harness is opaque to the runner: it only needs to produce the session's explicit submission. When a reviewed PDK bundle is mounted, the runner automatically exposes its container-local `KLAYOUT`/`PYTHONPATH` settings and publishes the import preflight in `/protocol/resources.json`.

To connect a model through the host-owned gateway, create the schema 1 inference profile described in the [running guide](docs/running.md#model-inference), fill in your endpoint, model, and host key-variable name, and run your harness configuration:

```bash
uv run --locked python main.py run build/runs/preview/prepared/case/case.toml \
  --agent path/to/agent.toml \
  --resources build/runs/preview/prepared/agent-resources \
  --inference build/runs/inference.toml \
  --output build/runs/my-first-model-run
```

Before spending a request, validate the profile, optional harness wire declaration, and host credential without contacting the provider:

```bash
uv run --locked python main.py inference-check build/runs/inference.toml --agent path/to/agent.toml
```

Once the harness forwards a request, this command calls your configured model; quick start itself never does. A configured profile with no forwarded requests is explicitly labeled offline in the report. Credentials stay on the host. The gateway selects the declared wire family through a provider-neutral adapter registry; the optional Responses adapter is one choice, while the harness owns any bridge needed by its model client. A harness may opt into same-semantic in-session checks by declaring `process-feedback.v1`; each check uses a frozen candidate snapshot and is reported separately from the final independent score.

## How It Works

Layout-Bench runs a four-phase loop:

1. **Define** — a case TOML freezes the circuit sources, task inputs, output contract, constraints, and optional evaluation plan in one file.
2. **Run** — the Runner freezes the Agent configuration, resources, budgets, toolchain, and execution identity, then starts an isolated session.
3. **Judge** — after an explicit submission, the evaluator checks the frozen GDS with the declared artifact, DRC, LVS, geometry, extraction, and performance jobs.
4. **Report** — durable events and artifacts support independent re-evaluation, batch statistics, and reproducibility checks.

DRC/LVS are physical-validity gates. Task success additionally requires every hard constraint, required post-layout job, and declared performance limit to pass.

<a id="documentation"></a>

## Resources

| Need | Link |
| --- | --- |
| Reproduce the no-key public preview | [Quick Start](#quick-start) |
| Connect a custom harness | [Running guide](docs/running.md#offline-cli) |
| Add a task and qualify its judge | [Tasks and evaluation](docs/tasks.md) |
| Understand run plans, inference limits, and scoring | [Running](docs/running.md) |
| Prepare PDK/EDA resources or troubleshoot tools | [Tools](docs/tools.md) |
| Apply operator admission and restricted export | [Admission](docs/admission.md) |
| Understand CI/CD and release triggers | [Contributing](CONTRIBUTING.md#ci-cd) |
| Contribute or report a problem | [CONTRIBUTING.md](CONTRIBUTING.md) |

Framework checks need no Docker images, PDK, or model credentials. CI runs lint, unit tests, and local documentation-link checks. The manual [Public EDA preview](.github/workflows/public-eda.yml) workflow evaluates public case witnesses and runs their EDA regressions in real containers.

## FAQ

<details>
<summary><strong>Do I need a model key to run the benchmark?</strong></summary>

No. The public quick start evaluates the reference GDS of a published case. A model key is needed only when you configure a real inference endpoint for your own Agent run.

</details>

<details>
<summary><strong>Does passing DRC/LVS mean the task passed?</strong></summary>

No. DRC/LVS establish physical validity under the selected rules. Task success also requires the task's geometry constraints and post-layout performance limits.

</details>

<details>
<summary><strong>Can I use a different harness?</strong></summary>

Yes. Any executable that follows the session protocol can be configured with its command, reviewed files, resources, and budget. The runner does not require or install a particular Agent framework.

</details>

<details>
<summary><strong>Does a standard Agent receive the reference solution?</strong></summary>

No. Reference GDS and qualification evidence are public for debugging when a task has passed admission, but standard runs materialize only the task inputs declared by the case TOML's `[task]` section.

</details>

<details>
<summary><strong>Is there a hosted service or official leaderboard?</strong></summary>

No. This is a local preview package. Hosted evaluation, identity authentication, and an official leaderboard are outside its scope.

</details>

<details>
<summary><strong>Which circuit does quick start evaluate?</strong></summary>

The default is comparator; select `--case full_OTA` for the OTA. Both use the rules, constraints, and performance limits declared in their own `case.toml`.

</details>

## Scope

This package includes the common executable-harness session protocol, a provider-neutral canonical harness example, a host-owned model gateway, configurable EDA backends, public circuit cases, and local batch statistics. It does not include hosted evaluation, identity authentication, or an official leaderboard.

The framework is licensed under [MIT](LICENSE). IHP AnalogAcademy and TO_Apr2025 source records retain their upstream licenses and per-file notices; any later derived task assets must retain the corresponding upstream notices. Submodules, tools, and dependencies retain their own licenses and notices; source and resource preparation are described in the [tool guide](docs/tools.md#external-sources).

<p align="center">
<a href="README_CN.md">Read in Chinese →</a>
</p>
