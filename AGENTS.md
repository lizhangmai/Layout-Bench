# Layout-Bench Repository Conventions

This file applies to a standalone checkout. The common framework, public tasks, reference solutions, and qualification materials belong in this repository; hidden tasks and internal assembly belong in the separate Private repository, with a one-way dependency from Private → Public.

Write all repository-owned Markdown in English, except `README_CN.md`.

## Starting Work

At the repository root, run `git status --short --branch` and preserve unrelated changes. For the public development preview, prioritize reproducible tasks, tool preparation, and user entry points. Use the [README](README.md) as the entry point and [CONTRIBUTING](CONTRIBUTING.md) for contribution and verification rules. Read the following guides according to the scope of the change:

| Work | Read first |
|---|---|
| Module boundaries and extension interfaces | [Architecture](docs/architecture.md) |
| Tasks, inputs, sources, constraints, metrics, or judges | [Tasks and qualification](docs/tasks.md), especially the [exclusion checklist](docs/tasks.md#input-isolation) for source surveys |
| Agents, inference, submissions, events, batches, or statistics | [Running guide](docs/running.md) |
| Images, dependencies, PDKs, EDA backends, or support bundles | [Tools guide](docs/tools.md); dependencies are declared in `pyproject.toml` and synchronized in `uv.lock` |
| Qualification admission, resource or endpoint approval, or report export | [Admission and export](docs/admission.md) |

`third_party/` contains independent upstream submodules. Exclude it from framework searches, format checks, and tests; follow its own conventions for targeted changes. PDK implementation and signoff rules belong to the PDK repository; this framework manages integration and Git references.

## Execution and Completion

- Keep common mechanisms in `benchmarking/`; put task-specific preparation, reference solutions, and qualification evidence in the corresponding task directory. Public installation and CI must not depend on Private.
- A standard solve materializes only declared inputs and reviewed resource bundles. Public reference solutions may be downloaded for debugging, but are never mounted for a standard solver Agent. Follow the [task guide](docs/tasks.md#asset-rights) for sources and distribution.
- Evaluate frozen candidates independently with trusted materials, without Agent credentials or writable directories. DRC/LVS establishes physical validity; task success also requires the declared geometry and post-layout metrics.
- Requalify affected witnesses, counterexamples, and calibration whenever the judge, rules, or task changes. Deterministic protocol tests are not model scores.
- Update the owning guide as the single source of truth when behavior changes. Keep onboarding in the README and contribution and verification guidance in CONTRIBUTING; do not create `CONTEXT.md` or duplicate protocol documents.

When complete, use the [verification matrix](CONTRIBUTING.md#verification), check documentation links against the commands they describe, and report the actual test scope and Git status. Verify and commit cross-repository changes separately; retain reviewable evidence for architecture and upstream-reference changes.
