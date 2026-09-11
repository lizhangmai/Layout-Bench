# Contributing

This developer preview focuses on reproducible public layout tasks and a usable local runner. Small fixes, reproduction reports and improvements to task/harness onboarding are welcome. Issues and pull requests may be written in English or Chinese.

## Set up and verify

Clone the public repository and follow the [README](README.md). No private checkout is required. Framework-only work needs `uv sync --locked`; it does not need a PDK, Docker image or model account.

Before a pull request, run:

```bash
uv run --locked ruff check .
uv run --locked python scripts/check_docs.py
uv run --locked pytest -m unit
uv build --out-dir build/dist
git diff --check
```

The repeatable black-box acceptance suites are split by runtime cost.  The
fast suite uses deterministic transports and fixtures only and is part of the
pull-request checks:

```bash
uv run --locked python scripts/acceptance.py fast
```

With the prepared tools image, the container suite exercises isolated
sessions, durable submissions, recovery, and batch CLI behavior without
contacting a model or running EDA:

```bash
uv run --locked python scripts/acceptance.py container --image layout-bench-tools:local
```

The preview and EDA suites are manual/nightly checks.  They write evidence to
a temporary directory unless `--output` is supplied, and never add
`build/runs/` artifacts to the repository:

```bash
uv run --locked python scripts/acceptance.py preview --image layout-bench-tools:local
uv run --locked python scripts/acceptance.py eda --image layout-bench-tools:local
```

`preview` runs the no-key quick start; add `--skip-build` to exercise image
reuse.  The acceptance wrapper uses Docker's host build network by default so
local build proxies are reachable; pass `--network default` to exercise the
diagnostic path explicitly.  `all` runs every suite, including both preview
modes.  None of these commands calls a real model service.

Keep repository-local generated files under `build/`: use `build/runs/` for benchmark evidence, `build/support/` for manually prepared bundles, and `build/dist/` for Python distributions. `build/lib/` and `build/bdist.*` are setuptools staging directories. Do not commit generated output.

<a id="verification"></a>

### Choose the affected checks

| Change | Validation |
|---|---|
| Documentation only | Local link checker, `git diff --check`, and verify paths/commands against their consumers |
| Framework logic | Ruff, unit tests and affected integration checks |
| Images, sessions, harnesses or wire adapters | Build-context/tool checks and affected container regressions below |
| Tasks, rules or evaluators | Real EDA positive/negative cases, task qualification and schematic/post-layout calibration |

After the README quick start with `--output build/runs/preview`, choose the applicable commands:

```bash
bash tests/integration/test_build_context.sh
bash tests/integration/test_toolchain.sh tools
uv run --locked python scripts/acceptance.py eda --image layout-bench-tools:local
LAYOUT_BENCH_TEST_IMAGE=layout-bench-tools:local uv run --locked pytest \
  tests/integration/test_batch.py tests/integration/test_admission_cli.py \
  tests/integration/test_session.py
uv run --locked pytest tests/integration/test_inference_https.py
```

Use new output directories. The HTTPS test requires host `openssl` and uses local certificates. Harness-specific integration tests require the runtime declared by that harness; the generic session checks above do not invoke a paid model or establish a model score.

The remaining low-level EDA regressions use the [unified tool image](docs/tools.md#manual-tools), not the generated preview configuration. Build that image before running:

```bash
uv run --locked python scripts/public_preview.py build --image layout-bench-tools:local
bash tests/integration/test_pdk_view.sh
bash tests/integration/test_task_preparation.sh
uv run --locked pytest tests/integration/test_characterization.py \
  tests/integration/test_sg13g2.py \
  tests/integration/test_magic_rc.py tests/integration/test_comparator.py \
  tests/integration/test_full_ota.py tests/integration/test_matched_schematic_exports.py \
  tests/integration/test_sg13g2_model_calls.py \
  tests/integration/test_input_pair_source.py tests/integration/test_input_pair_postlayout.py
```

The EDA acceptance suite uses the published comparator and full_OTA witnesses, OTA pre/post calibration, geometry rejection, and tool-error checks. It needs the PDK and tools image but no course checkout. The original-asset regression tests additionally need the optional IHP-AnalogAcademy source submodule. Evaluator changes must satisfy the [qualification requirements](docs/tasks.md#qualification); protocol tests and synthetic hidden fixtures do not replace real circuit evidence. Public CI uses public or synthetic inputs; hidden qualification materials stay in the authorized environment. Run upstream PDK regressions in that submodule, separately from framework checks.

When changing public catalog source records, run `uv run --locked pytest tests/integration/test_catalog_assets.py` with the corresponding source submodules initialized. These checks compare pinned commits and original asset digests; they do not run EDA and are separate from the offline unit suite.

For TO_Apr2025 design 1 source/physical diagnostics, run
`uv run --locked pytest tests/integration/test_to_apr2025_source.py tests/integration/test_to_apr2025_schematic.py` with the
TO/PDK checkouts and tools image. This verifies original-asset rejection,
independent extraction discrepancies, Qucs export compatibility, derivative
schematic exports and nominal HBT-model operation; it does
not establish performance qualification.

Report the checks actually run and their limits. Documentation-only changes do not require rebuilding tools or rerunning EDA.

<a id="ci-cd"></a>

## CI/CD

The `checks.yml` workflow runs on pushes, pull requests, and manual dispatch. It checks Python 3.12 and 3.13, validates repository links, runs unit tests, and builds a wheel and source distribution with an install smoke test. The distributions are retained as a workflow artifact for 14 days.

The `cd.yml` workflow is the release path. A tag matching `v*.*.*` must equal the version in `pyproject.toml`; a valid tag builds the Python distributions, publishes the `tools` Docker image to `ghcr.io`, and creates a GitHub Release with the distributions attached. The image receives the source tag, commit, and `latest` tags; PEP 440 tags also receive normalized version tags. Manual dispatch of `cd.yml` only builds and uploads the distributions, so it is safe for a dry run. The `public-eda.yml` workflow runs the long-running EDA acceptance suite on manual dispatch and nightly schedule; it is deliberately not part of every pull request.

Before the first tagged release, allow GitHub Actions to write packages in the repository settings and choose the desired visibility for the GHCR image. The workflow authenticates with the repository `GITHUB_TOKEN`; no personal registry token is required.

## Where a change belongs

| Contribution | Start here | Evidence to include |
|---|---|---|
| Public task | [Task design](docs/tasks.md#task-design), `tasks/ihp-sg13g2/IHP-AnalogAcademy/` | Source and license, explicit input list, executable constraints/metrics, passing witness and rejected counterexamples |
| Harness or wire adapter | [Running guide](docs/running.md#offline-cli), `benchmarking/model_config.py`, `benchmarking/inference.py` | Frozen command/files, budgets, protocol metadata, and clear result labels |
| EDA backend | [Architecture](docs/architecture.md#architecture), `benchmarking/toolchains.py` | Tool identity, isolated inputs, structured evidence and tests of passing/failing/error cases |
| Runner or statistics | `benchmarking/session.py`, `swarm.py`, `report.py` | Relevant lifecycle, evidence-integrity or measurement tests |
| Documentation or preparation UX | `README.md`, `scripts/public_preview.py` | Commands that work from a clean checkout and repository-local links |

Keep general mechanisms in `benchmarking/`; task-specific preparation and qualification belong with their public task or test fixture. `third_party/` contains independent upstream submodules. Search and test the framework separately; upstream changes follow that project's contribution rules and must be recorded by commit.

Task success is defined by that task's declared requirements. A DRC/LVS pass alone is not a successful layout, and a deterministic endpoint test is not a model score. Public reference and qualification materials remain available for debugging but outside standard solver inputs.

Architecture changes update [docs/architecture.md](docs/architecture.md). Update configuration, protocol and operating rules in their owning topic from the [README guide table](README.md#resources); each contract has one authoritative location. Keep README onboarding short and task-specific qualification evidence with its task. Private task data and deployment configuration are not developed in this repository.

Write public documentation for readers of a clean checkout. Describe the current
behavior, source and modification rationale, validation conditions, results, and
limits. Provide reproduction commands or links to distributed artifacts; local
run directories and unpublished image IDs are not accessible evidence. Keep
experiment chronology, discarded results, approval discussions, and transient
test summaries out of public READMEs. Paths such as `build/runs/example` are
appropriate when the documented commands create them for the reader.

## Reporting a problem

Include the framework commit, host OS/architecture, Python and Docker versions, relevant image IDs, the exact command and expected versus observed behavior. For a public task, attach the smallest useful report and reproduction steps. Review logs before posting: model prompts, credentials, endpoint details and proprietary inputs may require removal.

If you find a suspected security issue, avoid publishing credentials, nonpublic designs or a working exploit in a public issue. Use GitHub's private vulnerability reporting if enabled for this repository; otherwise request a private reporting channel without including sensitive details.

Keep pull requests focused. Describe the behavior change, why it is needed and validation results. Do not include generated caches, virtual environments, API keys or complete run directories; small, deliberately public fixtures and qualified reference assets belong with their tests or tasks.

When adding or cleaning up tests, follow the [test conventions](tests/AGENTS.md) for independent expectations, behavioral assertions, fixtures, and test scope.
