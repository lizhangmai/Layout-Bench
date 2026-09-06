# Optional Admission and Restricted Report Export

This page is for maintainers assembling a controlled evaluation. Ordinary public-development `run` and `batch` commands need no configuration from this page. It documents the implemented local policy interface; identity authentication, hosted submission, cross-plan quotas, and task retirement are not implemented, and hidden-task instances are not developed. See the [task guide](tasks.md#asset-rights) for source and visibility requirements.

<a id="local-admission"></a>

## Preconditions and Approved Execution

`benchmarking/admission.py` provides locally verifiable admission. The evaluator assembles the specific qualification materials, authorization, deployment paths, and disclosure configuration. `batch --policy ... --policy-sha256 ...` requires an independently supplied policy digest approved by the evaluator; a participant cannot gain approval by changing the plan, the `qualified` label, or attaching a policy with the Agent submission. **The trust boundary is the evaluator-controlled entry point, digest, ledger, and host**, not a signature system for local files. If a participant controls the host or can rewrite the digest and ledger arbitrarily, this mechanism provides no hosted-security guarantee.

Preparation, execution, and export use three separate entry points. The paths below are configurations and new run directories prepared by the evaluator:

```bash
uv run --locked python main.py batch /approved/plan.toml --prepare-only --output /runs/review
uv run --locked python main.py batch /approved/plan.toml --policy /approved/policy.json --policy-sha256 "$BENCH_POLICY_SHA256" --output /runs/measured
uv run --locked python main.py export /runs/measured --policy-sha256 "$BENCH_POLICY_SHA256"
```

`--prepare-only` resolves all inputs, actual images, and backend identities and archives `execution.json`, producing `conditions_sha256` without creating solve sessions, sending inference requests, or consuming authorization. When inference is configured, it still checks that the relevant credential environment variable exists. After reviewing actual conditions and qualification materials, the evaluator writes and fixes the policy. Execution resolves the actual environment again and matches every item; an old preparation directory cannot simply be treated as still valid. A `run` or `batch` without a policy remains a local development entry point. Do not combine `--prepare-only` with `--policy`.

## Policy and Qualification Records

The policy is strict JSON schema 1 and rejects unknown fields. Hashes are lowercase SHA-256. The policy-file digest binds the original bytes, while the structured condition digest uses `provenance.json_asset(value).sha256` (sorted keys, compact JSON, trailing newline). The fields are:

| Field | Content and validation |
|---|---|
| `schema_version`, `id` | `1` and a disclosure-reviewed release identifier of at most 64 characters |
| `conditions_sha256` | Digest of `admission.conditions(execution_manifest)`, binding the plan, every task/input/backend, every Agent configuration/file/resource, budgets, models/endpoints, repetitions/retries/order, statistics rules, host conditions, and the complete framework-source digest. Git-status text is excluded from this digest, but the actual Git status is still archived |
| `valid_until` | ISO time with an explicit time zone; checked during preparation, authorization reservation, and the start of every attempt. A started session ends according to its frozen budget |
| `ledger` | An evaluator-created absolute directory owned and accessible only by the evaluator, with no symlinks; it is in controlled storage and outside Git and participant bundles |
| `dataset` | `public`, `hidden`, or `synthetic_hidden`, matching only a plan with `public_development`, `hidden_development`, or `synthetic`, respectively. Synthetic verification cannot be relabeled as a real hidden score |
| `exposure_mode` | `offline` or `external_api`; every configuration in the batch must use the same task-pool exposure mode, with no offline/external mix within one hidden task set |
| `tasks.<task_id>` | Covers the complete task set and contains `source_kind`, `qualification`, a non-empty `materials` list, and `authorization` |
| `agents.<configuration_id>` | Covers the complete configuration set and contains `conditions_sha256` for the complete Agent object in the manifest, `resource_review`, and `endpoint`. Image ID, command, public environment variables, all files and bundles, budget, and inference configuration cannot be replaced after review |
| `export` | Predeclared summary fields, group labels, minimum distinct task/family/trial counts, and precision; allowed values are defined below |

For public data, `source_kind` can only be `public`. Hidden data must use `independent_unpublished` or `authorized_unpublished`; synthetic hidden tests must use `synthetic`. This is an evaluator declaration bound to specific source-authorization materials; code cannot determine automatically whether a circuit with the same origin is already online. `authorization` records permission to use and transmit design, process, and tool assets, while `resource_review` records review of run bundles and materials. The corresponding rights and qualification processes own their contents, and these records cannot be empty files.

Every `qualification`, `materials[]`, `authorization`, `resource_review`, and endpoint-authorization reference has the form `{"path": "path relative to the policy file", "sha256": "file digest"}`. Accept ordinary non-link files only, validate their original contents, archive them privately, and never reread mutable originals later. Reference paths must stay inside the policy directory; organize the policy and materials in a private repository or approved storage.

`qualification` points to an independent JSON record. Required fields are `schema_version=1`, `task_sha256`, `backends_sha256` (the normalized digest of actual backend identity objects), `framework_sha256`, a non-empty review description `review`, and `checks`. `checks` must be complete and every value must be JSON `true`: `witness`, `invalid_physical`, `invalid_geometry`, `invalid_performance`, `calibration`, `repeated_stability`, and `input_semantics`, corresponding to the [task and judge qualification requirements](tasks.md#qualification). The loader validates coverage and identity in the trusted record; **a boolean declaration or synthetic test does not count as rerunning the qualification matrix**. Verify real witnesses and counterexamples in the corresponding tool environments first, then have the evaluator review the archived materials and fix the record. The current conservative binding covers the complete framework source; review again and fix the qualification scope after a framework change.

`endpoint=null` is allowed only for a run with no inference endpoint. With inference configured, provide `provider`, the exact `base_url`, `model`, `no_training=true`, `zero_data_retention=true`, and an `authorization` reference. The reference must record the applicable endpoint, model-processing scope, and data arrangements and agree with task and resource authorization. Code checks the binding between trusted review records and actual configuration; it cannot prove provider compliance, and legal authorization or zero retention cannot be inferred from `store=false`. Generation and standalone compaction parameter handling follow the semantics of the [Codex adapter and fixed inference endpoint](running.md#model-inference); do not inject an unsupported `store` field into compaction. A deterministic test transport cannot be used for a real `hidden` dataset.

## Single Authorization and Interruption

Before the first solve input, the executor freezes the policy and all review materials. It then exclusively creates a ledger record named by the policy digest, writes the actual execution-manifest digest and time, and `fsync`s the file and directory; only after success does it start an attempt. Concurrent use and reuse of the same authorization are rejected. A host interruption, startup failure, or expiry does not automatically return authorization; permitted infrastructure replacements must already be included in the fixed plan. Batch records retain the same reservation credential and internally recompute the policy, material, and execution bindings. The ledger records the maximum total exposure for the plan; batch and single-run events identify the slots and requests actually attempted. Participant quotas across policies, task-exposure history across plans, task retirement, and distributed scheduling require an outer service and cannot be claimed as complete access governance from this ledger alone.

## Summary Export

The `export` rule permits only the following fields:

| Field | Allowed values and behavior |
|---|---|
| `fields` | A non-empty, duplicate-free list containing only `success_rate`, `physical_valid_rate`, and `infrastructure_error_rate` |
| `min_tasks`, `min_families`, `min_trials` | Integers of at least 2, constraining distinct task count, distinct family count, and completed measurement count, respectively. Repetitions cannot make up for task or family diversity; a deployment may require higher thresholds |
| `decimals` | An integer from 0 through 3; round every approved rate to this fixed precision |
| `groups[]` | A planned list of `{configuration_id, environment_group, label}` objects. Groups and public labels are unique and must come from the actual manifest. Public labels undergo disclosure review and cannot encode task information |

`export` recomputes from raw durable evidence, accepts only completed batches with complete samples, and validates the policy frozen before the run and the caller-supplied original digest. The statistics and export implementation must match the approved source; changing fields, thresholds, groups, or precision afterward cannot change an old batch. The output is a newly constructed JSON object containing only the schema, development-export type, approved release identifier/data category/exposure mode, fixed weighting description, currently unimplemented summary intervals as `null`, and groups that meet the thresholds. Each group contains only its approved label, original run kind, task/family/measurement counts, and approved rates. Suppress a small group in its entirety: return none of its label, counts, or per-task hashes. Return `groups=[]` when no group is publishable. Repeated exports of the same frozen batch produce the same artifact; arbitrary slice queries are unavailable.

Success and physical-validity rates use equal family weights and equal task weights within each family. Infrastructure-error rate uses ended attempts as its denominator and includes approved replacements. Conservative export currently provides no per-task intervals, metrics, success/failure breakdown, raw resource distributions, or log/path/artifact references. `summarize` remains the evaluator's complete internal statistics entry point; it is not a participant query or download interface. A policy-bound `batch` prints only the internal record location and completion status, not internal summaries. `export` errors return only a generic rejection message; the evaluator checks detailed evidence internally. Export results remain labeled `policy_checked_development_export`, protocol tests retain `model_protocol_test`, and probes that call no model retain `offline_cli_development`. None of these commands is a hosted-submission, identity-authentication, file-download, or official-leaderboard service.
