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
uv run --locked python scripts/public_preview.py qualify \
  --prepared build/runs/preview/prepared --output build/runs/preview-qualification
LAYOUT_BENCH_TEST_IMAGE=layout-bench-tools:local uv run --locked pytest \
  tests/integration/test_batch.py tests/integration/test_admission_cli.py \
  tests/integration/test_session.py tests/integration/test_codex.py
uv run --locked pytest tests/integration/test_inference_https.py
```

Use new output directories. The HTTPS test requires host `openssl` and uses local certificates. The native-harness integration test uses a deterministic endpoint; neither invokes a paid model or establishes a model score.

The remaining low-level EDA regressions use the [manual tool profiles](docs/tools.md#manual-tools), not the generated preview configuration. Prepare the targets they use before running:

```bash
bash tests/integration/test_pdk_view.sh
bash tests/integration/test_task_preparation.sh
uv run --locked pytest tests/integration/test_characterization.py \
  tests/integration/test_sg13g2.py tests/integration/test_physical_checks.py \
  tests/integration/test_tgate.py -m integration
```

Task preparation also needs the optional source submodule. Evaluator changes must satisfy the [qualification requirements](docs/tasks.md#qualification); protocol tests and synthetic hidden fixtures do not replace real circuit evidence. Public CI uses public or synthetic inputs; hidden qualification materials stay in the authorized environment. Run upstream PDK regressions in that submodule, separately from framework checks.

Report the checks actually run and their limits. Documentation-only changes do not require rebuilding tools or rerunning EDA.

<a id="ci-cd"></a>

## CI/CD

The `checks.yml` workflow runs on pushes, pull requests, and manual dispatch. It checks Python 3.12 and 3.13, validates repository links, runs unit tests, and builds a wheel and source distribution with an install smoke test. The distributions are retained as a workflow artifact for 14 days.

The `cd.yml` workflow is the release path. A tag matching `v*.*.*` must equal the version in `pyproject.toml`; a valid tag builds the Python distributions, publishes the `tools` Docker image to `ghcr.io`, and creates a GitHub Release with the distributions attached. The image receives the source tag, commit, and `latest` tags; PEP 440 tags also receive normalized version tags. Manual dispatch of `cd.yml` only builds and uploads the distributions, so it is safe for a dry run. The `public-eda.yml` workflow remains a manual, long-running EDA preview and is not part of every pull request.

Before the first tagged release, allow GitHub Actions to write packages in the repository settings and choose the desired visibility for the GHCR image. The workflow authenticates with the repository `GITHUB_TOKEN`; no personal registry token is required.

## Where a change belongs

| Contribution | Start here | Evidence to include |
|---|---|---|
| Public task | [Task design](docs/tasks.md#task-design), `tasks/academy-tgate/` | Source and license, explicit input list, executable constraints/metrics, passing witness and rejected counterexamples |
| Harness or wire adapter | [Harness examples](examples/agents/README.md), `benchmarking/model_config.py`, `benchmarking/inference.py` | Frozen command/files, budgets, protocol metadata, and clear result labels |
| EDA backend | [Architecture](docs/architecture.md#architecture), `benchmarking/toolchains.py` | Tool identity, isolated inputs, structured evidence and tests of passing/failing/error cases |
| Runner or statistics | `benchmarking/session.py`, `swarm.py`, `report.py` | Relevant lifecycle, evidence-integrity or measurement tests |
| Documentation or preparation UX | `README.md`, `scripts/public_preview.py` | Commands that work from a clean checkout and repository-local links |

Keep general mechanisms in `benchmarking/`; task-specific preparation and qualification belong with their public task or example. `third_party/` contains independent upstream submodules. Search and test the framework separately; upstream changes follow that project's contribution rules and must be recorded by commit.

Task success is defined by that task's declared requirements. A DRC/LVS pass alone is not a successful layout, and a deterministic endpoint test is not a model score. Public reference and qualification materials remain available for debugging but outside standard solver inputs.

Architecture changes update [docs/architecture.md](docs/architecture.md). Update configuration, protocol and operating rules in their owning topic from the [README guide table](README.md#documentation-and-development); each contract has one authoritative location. Keep README onboarding short and task-specific qualification evidence with its task. Private task data and deployment configuration are not developed in this repository.

## Reporting a problem

Include the framework commit, host OS/architecture, Python and Docker versions, relevant image IDs, the exact command and expected versus observed behavior. For a public task, attach the smallest useful report and reproduction steps. Review logs before posting: model prompts, credentials, endpoint details and proprietary inputs may require removal.

If you find a suspected security issue, avoid publishing credentials, nonpublic designs or a working exploit in a public issue. Use GitHub's private vulnerability reporting if enabled for this repository; otherwise request a private reporting channel without including sensitive details.

Keep pull requests focused. Describe the behavior change, why it is needed and validation results. Do not include generated caches, virtual environments, API keys or complete run directories; small, deliberately public fixtures and qualified reference assets belong with their tests or tasks.
